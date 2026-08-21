#!/usr/bin/env python3
"""Proposal-only replay for the external normalized PNG queue.

This intentionally does not call the production candidate writer and does not
read old TXT, accepted transcripts, or historical attempts.  It runs the
current offline proposal adapters against the live normalized PNG queue and
writes a compact review page plus hash-bound receipt.
"""

from __future__ import annotations

import argparse
import base64
import html
import json
import signal
import shutil
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from PIL import Image

from lateletter.transcription import (
    EmojiAtlasAdapter,
    FixedLatticeStructuralAdapter,
    IndependentOfflineAdapter,
    PaddleOCROfflineAdapter,
    StructuralUnicodeRowAdapter,
    TesseractOfflineAdapter,
    UnicodeTemplateRunAdapter,
    benchmark_offline_ensemble,
    build_environment_lock,
)
from lateletter.transcription.geometry import (
    build_recognition_hypothesis_inputs,
    build_recognition_inputs,
    route_raster_geometry,
)
from lateletter.transcription.hashing import sha256_bytes, sha256_file
from lateletter.transcription.recognition import (
    _compose_run_texts,
    _proposal_texts,
    _tesseract_profile_runs,
)
from lateletter.transcription.schema import canonical_bytes


DEFAULT_ADAPTER_BUDGETS_SECONDS = {
    "tesseract-offline": 12.0,
    "fixed-lattice-structural": 5.0,
    "structural-unicode-row": 90.0,
    "unicode-template-latin": 30.0,
    "unicode-template-combining": 30.0,
    "unicode-template-kana": 30.0,
    "paddleocr-offline": 15.0,
    "independent-offline-easyocr": 15.0,
    "independent-offline-surya": 15.0,
    "emoji-grapheme-atlas": 30.0,
}


REVIEW_ADAPTER_BUDGETS_SECONDS = {
    "tesseract-offline": 5.0,
    "fixed-lattice-structural": 3.0,
    "structural-unicode-row": 8.0,
    "unicode-template-latin": 4.0,
    "unicode-template-combining": 4.0,
    "unicode-template-kana": 4.0,
    "paddleocr-offline": 1.0,
    "independent-offline-easyocr": 1.0,
    "independent-offline-surya": 1.0,
    "emoji-grapheme-atlas": 4.0,
}


class _BudgetExceeded(BaseException):
    """Hard wall-clock budget for one source/adapter diagnostic worker."""


def _run_with_budget(callback, budget_seconds: float):
    def _alarm(_signum, _frame):
        raise _BudgetExceeded(f"adapter exceeded {budget_seconds:.3f}s diagnostic budget")

    previous_handler = signal.getsignal(signal.SIGALRM)
    signal.signal(signal.SIGALRM, _alarm)
    signal.setitimer(signal.ITIMER_REAL, float(budget_seconds))
    started = time.perf_counter()
    try:
        return callback(), round((time.perf_counter() - started) * 1000.0, 3)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0.0)
        signal.signal(signal.SIGALRM, previous_handler)


def _slug(path: Path) -> str:
    allowed = []
    for char in path.stem.lower():
        if char.isalnum():
            allowed.append(char)
        elif char in {"-", "_", ".", " "}:
            allowed.append("-")
    slug = "".join(allowed).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug[:72] or "source"


def _git_state() -> dict[str, Any]:
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    status = subprocess.check_output(["git", "status", "--short"], text=True)
    return {
        "commit": commit,
        "dirty": bool(status.strip()),
        "status_short": status.splitlines(),
    }


def _write_json(path: Path, payload: dict[str, Any]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = canonical_bytes(payload) + b"\n"
    path.write_bytes(data)
    return sha256_bytes(data)


def _rel(path: Path, base: Path) -> str:
    return path.resolve().relative_to(base.resolve()).as_posix()


def _proposal_block(values: Iterable[str], *, empty: str = "NO PROPOSALS") -> str:
    lines = [str(value) for value in values if str(value)]
    if not lines:
        return f"<div class='empty'>{html.escape(empty)}</div>"
    blocks = []
    for rank, text in enumerate(lines[:5], start=1):
        blocks.append(
            "<div class='proposal'>"
            f"<div class='rank'>rank {rank}</div>"
            f"<pre>{html.escape(text)}</pre>"
            "</div>"
        )
    return "\n".join(blocks)


def _compact_row_proposals(row_proposals: list[dict[str, Any]], *, max_hypotheses: int = 2, max_rows: int = 16) -> list[dict[str, Any]]:
    compact: list[dict[str, Any]] = []
    for hypothesis in row_proposals[:max_hypotheses]:
        rows = []
        for row in list(hypothesis.get("rows", ()))[:max_rows]:
            rows.append(
                {
                    "row_index": row.get("row_index"),
                    "run_id": row.get("run_id"),
                    "proposals": list(row.get("proposals", ()))[:5],
                    "composed_proposals": list(row.get("composed_proposals", ()))[:5],
                    "run_rejection_codes": sorted(
                        {
                            str(code)
                            for run in row.get("runs", ())
                            for code in run.get("rejection_codes", ())
                        }
                    )[:12],
                }
            )
        compact.append({"hypothesis_id": hypothesis.get("hypothesis_id"), "rows": rows})
    return compact


def _compact_adapter(record: dict[str, Any]) -> dict[str, Any]:
    unsupported = sorted(str(item) for item in record.get("unsupported_status", ()) or ())
    return {
        "adapter": record.get("adapter"),
        "version": record.get("version"),
        "status": record.get("status"),
        "runtime_ms": record.get("runtime_ms"),
        "budget_seconds": record.get("budget_seconds"),
        "budget_exceeded": bool(record.get("budget_exceeded")),
        "deterministic": bool(record.get("deterministic", True)),
        "top_k_logical_sequences": list(record.get("top_k_logical_sequences", ()))[:5],
        "unsupported_status": unsupported[:30],
        "geometry_status": record.get("geometry_status"),
        "geometry_rejection_codes": list(record.get("geometry_rejection_codes", ()))[:20],
        "recognition_input_hash": record.get("recognition_input_hash"),
        "retained_proposal_state_count": record.get("retained_proposal_state_count"),
        "row_proposals": _compact_row_proposals(list(record.get("row_proposals", ()) or ())),
        "joint_decoder": record.get("joint_decoder"),
        "error": record.get("error"),
    }


def _timeout_adapter_record(adapter: Any, fixture_id: str, budget_seconds: float, elapsed_ms: float) -> dict[str, Any]:
    return {
        "adapter": getattr(adapter, "name", type(adapter).__name__),
        "version": getattr(adapter, "version", "unknown"),
        "status": "rejected_budget_exceeded",
        "runtime_ms": elapsed_ms,
        "budget_seconds": budget_seconds,
        "budget_exceeded": True,
        "deterministic": False,
        "top_k_logical_sequences": [],
        "unsupported_status": ["budget_exceeded"],
        "geometry_status": "unknown_after_adapter_timeout",
        "geometry_rejection_codes": [],
        "recognition_input_hash": None,
        "retained_proposal_state_count": 0,
        "row_proposals": [],
        "joint_decoder": None,
        "error": f"{fixture_id}:{getattr(adapter, 'name', type(adapter).__name__)} exceeded {budget_seconds:.3f}s",
    }


def _adapter_profiles(adapter: Any) -> tuple[tuple[str, int | None, tuple[str, ...] | None], ...]:
    if isinstance(adapter, TesseractOfflineAdapter):
        return (
            ("psm7-eng", 7, ("eng",)),
            ("psm13-eng", 13, ("eng",)),
            ("psm7-jpn-cjk", 7, ("jpn", "chi_sim")),
            ("psm7-ara", 7, ("ara",)),
        )
    return ((str(getattr(adapter, "name", type(adapter).__name__)), None, None),)


def _evaluate_adapter_direct(
    *,
    adapter: Any,
    source_path: Path,
    source_sha256: str,
    geometry: dict[str, Any],
    components: dict[str, Any],
    variants: tuple[tuple[str, dict[str, Any]], ...],
    environment_lock: Any,
    top_k: int,
    geometry_status: str,
    geometry_rejection_codes: list[str],
    recognition_input_hash: str | None,
    budget_seconds: float,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for profile_name, psm, languages in _adapter_profiles(adapter):
        start = time.perf_counter()
        run_text_candidates: list[tuple[Any, ...]] = []
        run_input_hashes: list[str] = []
        row_proposal_evidence: list[dict[str, Any]] = []
        unsupported: list[str] = []
        statuses: list[str] = []
        run_spans: list[str] = []
        with tempfile.TemporaryDirectory(prefix="lateletter-queue-proposal-run-") as run_root_raw:
            run_root = Path(run_root_raw)
            for variant_id, variant_input in variants:
                variant_geometry = dict(geometry)
                variant_geometry["hypothesis_id"] = str(variant_id)
                variant_geometry["hypothesis"] = dict(variant_input.get("provenance", {}).get("hypothesis", {}))
                profile_runs = (
                    _tesseract_profile_runs(source_path, variant_input)
                    if psm is not None
                    else tuple(variant_input.get("runs", ()))
                )
                variant_rows: dict[int, tuple[str, ...]] = {}
                variant_row_proposals: dict[int, list[dict[str, Any]]] = {}
                for run_index, run_mapping in enumerate(profile_runs):
                    run = dict(run_mapping)
                    run_source = {
                        "path": str(source_path),
                        "source_sha256": source_sha256,
                        "run_id": str(run.get("run_id", f"run-{run_index:04d}")),
                    }
                    run_geometry = dict(variant_geometry)
                    if run.get("run_strip_png_base64"):
                        run_bytes = base64.b64decode(run["run_strip_png_base64"])
                        run_path = run_root / f"{profile_name}-run-{run_index:04d}.png"
                        run_path.write_bytes(run_bytes)
                        run_rgba = None
                        try:
                            run_image = Image.open(run_path).convert("RGBA")
                            run_rgba = [
                                [
                                    tuple(int(channel) for channel in run_image.getpixel((x, y)))
                                    for x in range(run_image.width)
                                ]
                                for y in range(run_image.height)
                            ]
                        except (OSError, ValueError, TypeError):
                            run_rgba = None
                        run_source.update(
                            {
                                "path": str(run_path),
                                "source_sha256": sha256_bytes(run_bytes),
                                "run_source_bounds": run.get("source_bounds"),
                                "component_ids": list(run.get("component_ids", ())),
                                "run_color_stats": dict(run.get("run_color_stats") or {}),
                                "anchor_evidence": dict(run.get("anchor_evidence") or {}),
                            }
                        )
                        run_input_hash = sha256_bytes(canonical_bytes(run))
                        run_input_hashes.append(run_input_hash)
                        run_geometry["run_mask"] = {
                            "authority": "geometry_hypothesis_run" if str(variant_id) != "authoritative" else "geometry_proven_run",
                            "grapheme_complete": True,
                            "pixels": run.get("binary_run_mask", []),
                            "run_id": run_source["run_id"],
                            "source_bounds": run.get("source_bounds"),
                            "mask_sha256": run.get("binary_run_mask_sha256"),
                            "rgba": run_rgba,
                            "component_ids": list(run.get("component_ids", ())),
                            "measured_advances": run.get("measured_advances", []),
                            "anchor_evidence": dict(run.get("anchor_evidence") or {}),
                        }
                        run_geometry["geometry_hash"] = sha256_bytes(
                            canonical_bytes({"base": variant_geometry, "run_id": run_source["run_id"]})
                        )
                        run_source["geometry_hash"] = run_geometry["geometry_hash"]
                    if psm is not None:
                        run_source["tesseract_psm"] = psm
                        run_source["tesseract_languages"] = list(languages or ())
                        run_source["tesseract_timeout_seconds"] = max(0.05, min(3.0, budget_seconds / max(1, len(profile_runs)) * 0.80))
                    if isinstance(adapter, StructuralUnicodeRowAdapter):
                        run_source["structural_run_budget_seconds"] = max(0.05, budget_seconds / max(1, len(profile_runs)) * 0.45)
                    proposal_set = adapter.propose(run_source, run_geometry, components, environment_lock)
                    proposal_limit = None if isinstance(adapter, StructuralUnicodeRowAdapter) else max(top_k, min(32, int(getattr(adapter, "beam_width", 8)) * 4))
                    run_texts = _proposal_texts(proposal_set, top_k=proposal_limit)
                    row_index = int(run.get("row_index", run_index))
                    bounds = run.get("source_bounds") if str(variant_geometry.get("mode", "")) == "shaped_runs" else None
                    run_text_candidates.append((row_index, run_texts, bounds))
                    prior = variant_rows.get(row_index, ())
                    variant_rows[row_index] = tuple(dict.fromkeys((*prior, *run_texts)))
                    variant_row_proposals.setdefault(row_index, []).append(
                        {
                            "run_id": run_source["run_id"],
                            "proposals": list(run_texts)[:32],
                            "run_input_hash": run_input_hashes[-1] if run_input_hashes else None,
                            "rejection_codes": sorted(set(proposal_set.rejection_codes)),
                        }
                    )
                    unsupported.extend(proposal_set.rejection_codes)
                    statuses.append(proposal_set.status)
                    run_spans.extend(proposal.run_id for proposal in proposal_set.proposals if proposal.run_id)
                composed = _compose_run_texts(run_text_candidates, top_k=max(top_k, 32))
                row_proposal_evidence.append(
                    {
                        "hypothesis_id": str(variant_id),
                        "rows": [
                            {
                                "row_index": int(row_index),
                                "runs": list(run_items),
                                "run_id": str(run_items[0].get("run_id", "")) if run_items else "",
                                "proposals": list(variant_rows.get(row_index, ()))[:32],
                                "composed_proposals": [],
                            }
                            for row_index, run_items in sorted(variant_row_proposals.items())
                        ],
                    }
                )
        top_sequences = _compose_run_texts(run_text_candidates, top_k=max(top_k, 5))
        elapsed_ms = round((time.perf_counter() - start) * 1000.0, 3)
        records.append(
            {
                "adapter": profile_name,
                "version": getattr(adapter, "version", "unknown"),
                "top_k_logical_sequences": list(top_sequences)[:top_k],
                "proposed_logical_order": list(top_sequences)[:top_k],
                "run_spans": sorted(set(run_spans)),
                "run_count": sum(len(item.get("runs", ())) for _variant_id, item in variants),
                "run_input_hashes": run_input_hashes,
                "repeat_run_hash": None,
                "deterministic": True,
                "runtime_ms": elapsed_ms,
                "budget_seconds": budget_seconds,
                "budget_exceeded": elapsed_ms > budget_seconds * 1000.0,
                "retained_proposal_state_count": sum(
                    len(run.get("proposals", ()))
                    for hypothesis in row_proposal_evidence
                    for row in hypothesis.get("rows", ())
                    for run in row.get("runs", ())
                ),
                "determinism_replay_performed": False,
                "unsupported_status": sorted(set(unsupported)),
                "status": "proposal_only" if any(status == "proposal_only" for status in statuses) else "rejected",
                "geometry_status": geometry_status,
                "geometry_rejection_codes": geometry_rejection_codes,
                "recognition_input_hash": recognition_input_hash,
                "row_proposals": row_proposal_evidence,
                "joint_decoder": None,
            }
        )
    return records


def _build_adapters(cache: Path, *, emoji_max_sequences: int) -> tuple[tuple[Any, ...], Any, list[dict[str, Any]]]:
    model_paths = {path.stem: str(path) for path in (cache / "tesseract_best").glob("*.traineddata")}
    mono_font = cache / "fonts" / "NotoSansMono-Variable.ttf"
    cjk_font = cache / "fonts" / "NotoSansCJKjp-Regular.otf"
    arabic_font = cache / "fonts" / "NotoSansArabic-Regular.ttf"
    if mono_font.exists():
        model_paths.update(
            {
                "unicode-template-latin.font": str(mono_font),
                "unicode-template-combining.font": str(mono_font),
            }
        )
    if cjk_font.exists():
        model_paths["unicode-template-kana.font"] = str(cjk_font)
    if arabic_font.exists():
        model_paths["unicode-template-arabic.font"] = str(arabic_font)
    script_packs = tuple(sorted(model_paths))
    preliminary = build_environment_lock(
        model_paths=model_paths,
        script_packs=script_packs,
        preprocessing={"network": "disabled"},
    )
    emoji_adapter = EmojiAtlasAdapter.from_cache(cache / "emoji")
    emoji_adapter = EmojiAtlasAdapter(
        sequence_data_path=emoji_adapter.sequence_data_path,
        font_path=emoji_adapter.font_path,
        font_hashes=emoji_adapter.font_hashes,
        max_sequences=max(1, emoji_max_sequences),
    )
    adapters = (
        TesseractOfflineAdapter(
            cache_dir=str(cache / "tesseract_best"),
            languages=("eng", "ara", "jpn", "jpn_vert", "chi_sim", "chi_tra"),
        ),
        FixedLatticeStructuralAdapter(),
        StructuralUnicodeRowAdapter(),
        UnicodeTemplateRunAdapter(
            repertoire_name="latin",
            name="unicode-template-latin",
            font_path=str(mono_font) if mono_font.exists() else None,
        ),
        UnicodeTemplateRunAdapter(
            repertoire_name="combining",
            name="unicode-template-combining",
            font_path=str(mono_font) if mono_font.exists() else None,
        ),
        UnicodeTemplateRunAdapter(
            repertoire_name="kana",
            name="unicode-template-kana",
            font_path=str(cjk_font) if cjk_font.exists() else None,
        ),
        PaddleOCROfflineAdapter(),
        IndependentOfflineAdapter(backend="easyocr", name="independent-offline-easyocr"),
        IndependentOfflineAdapter(backend="surya", name="independent-offline-surya"),
        emoji_adapter,
    )
    profiles = tuple(adapter.capability_profile(preliminary) for adapter in adapters if hasattr(adapter, "capability_profile"))
    lock = build_environment_lock(
        model_paths=model_paths,
        script_packs=script_packs,
        preprocessing={"network": "disabled", "ground_truth_to_adapter": False},
        capability_profiles=profiles,
    )
    return adapters, lock, [profile.to_dict() for profile in profiles]


def _html_review(output_root: Path, rows: list[dict[str, Any]], receipt: dict[str, Any]) -> str:
    summary_rows = "".join(
        f"<tr><td>{html.escape(str(key))}</td><td>{html.escape(str(value))}</td></tr>"
        for key, value in sorted(receipt["summary"].items())
    )
    cards = []
    for row in rows:
        adapter_cards = []
        for adapter in row["adapters"]:
            flags = []
            if adapter.get("budget_exceeded"):
                flags.append("budget exceeded")
            if not adapter.get("deterministic", True):
                flags.append("nondeterministic")
            if adapter.get("error"):
                flags.append(str(adapter["error"]))
            unsupported = ", ".join(str(item) for item in adapter.get("unsupported_status", ())[:8])
            adapter_cards.append(
                "<details class='adapter'>"
                f"<summary>{html.escape(str(adapter['adapter']))} — {html.escape(str(adapter['status']))}"
                f" · {html.escape(str(adapter.get('runtime_ms')))} ms"
                f"{' · ' + html.escape('; '.join(flags)) if flags else ''}</summary>"
                f"<div class='unsupported'>{html.escape(unsupported)}</div>"
                f"{_proposal_block(adapter.get('top_k_logical_sequences', ()), empty='no whole-source proposals')}"
                "</details>"
            )
        cards.append(
            f"""
            <section class="card">
              <h2>{html.escape(row['id'])}</h2>
              <div class="meta">
                <div><b>Authority:</b> proposal_only_diagnostic</div>
                <div><b>Geometry:</b> {html.escape(str(row['geometry_status']))}</div>
                <div><b>Any proposal:</b> {str(row['has_any_proposal']).lower()}</div>
                <div><b>SHA-256:</b> <code>{html.escape(row['source_sha256'])}</code></div>
                <div><b>Size:</b> {row['width']}×{row['height']}</div>
              </div>
              <div class="compare">
                <figure>
                  <figcaption>Current source normalized PNG</figcaption>
                  <img src="{html.escape(_rel(Path(row['copied_source']), output_root))}" />
                </figure>
                <figure>
                  <figcaption>Union/order diagnostic proposals — not candidates</figcaption>
                  {_proposal_block(row.get('proposed_logical_order', ()), empty='NO PROPOSALS FROM ANY ADAPTER')}
                </figure>
              </div>
              <details>
                <summary>Geometry rejection codes</summary>
                <pre class="codes">{html.escape(json.dumps(row.get('geometry_rejection_codes', []), ensure_ascii=False, indent=2))}</pre>
              </details>
              <div class="adapters">
                {''.join(adapter_cards)}
              </div>
            </section>
            """
        )
    return (
        "<!doctype html><meta charset='utf-8'>"
        "<title>LateLetter fresh PNG→TXT proposal review</title>"
        "<style>"
        "body{font-family:system-ui,-apple-system,sans-serif;margin:24px;background:#f6f6f6;color:#111}"
        "h1{margin-bottom:4px}.note{max-width:1050px;line-height:1.45}.summary{border-collapse:collapse;margin:16px 0;background:white}"
        ".summary td{border:1px solid #ccc;padding:6px 10px}.card{background:white;border:1px solid #ccc;border-radius:10px;margin:18px 0;padding:16px}"
        ".meta{font-size:13px;color:#333;display:grid;gap:4px;margin:8px 0 12px}"
        ".compare{display:grid;grid-template-columns:minmax(240px,0.8fr) minmax(360px,1.2fr);gap:18px;align-items:start}"
        "figure{margin:0}figcaption{font-weight:700;margin-bottom:8px}img{max-width:100%;background:white;border:1px solid #ddd}"
        ".proposal{margin:0 0 12px}.rank{font-size:12px;color:#555;font-weight:700}.proposal pre{white-space:pre;overflow:auto;background:#1f1f1f;color:#f7f7f7;padding:10px;border-radius:8px;font:16px/1.2 ui-monospace,Menlo,monospace}"
        ".empty{background:#eee;border:1px dashed #999;border-radius:8px;padding:18px;color:#555;font-weight:700}.adapter{border-top:1px solid #ddd;padding:8px 0}.adapter summary{cursor:pointer;font-weight:700}"
        ".unsupported{font:12px ui-monospace,monospace;color:#666;margin:6px 0}.codes{background:#f2f2f2;padding:8px;overflow:auto}code{font-family:ui-monospace,monospace;font-size:12px}"
        "</style>"
        "<h1>Fresh proposal-only replay: current offline recognizers over 26 PNGs</h1>"
        "<p class='note'>This is not a conversion result. It does not read old TXT, accepted TXT, historical attempts, or provisional candidates. It runs current source-only recognizer adapters and displays their proposal evidence so bad recognizer output can be inspected directly.</p>"
        f"<table class='summary'>{summary_rows}</table>"
        + "\n".join(cards)
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=Path("/Users/r/Downloads/STRUCTURAL ASCII ART EXAMPLES "),
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("tracked/LateLetterResearch/transcription-parity/queue-diagnostic-replays"),
    )
    parser.add_argument(
        "--cache",
        type=Path,
        default=Path("tracked/LateLetterResearch/transcription-model-cache"),
    )
    parser.add_argument("--run-id", default="")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--emoji-max-sequences", type=int, default=2000)
    parser.add_argument(
        "--budget-profile",
        choices=("review", "release"),
        default="review",
        help="review uses strict interactive ceilings; release uses benchmark ceilings but can take much longer",
    )
    args = parser.parse_args()

    source_dir = args.source_dir.resolve()
    sources = tuple(sorted(source_dir.glob("*.normalized.png")))
    if not sources:
        raise SystemExit(f"no *.normalized.png files found under {source_dir}")
    run_id = args.run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-current-proposals")
    run_root = (args.output_root / run_id).resolve()
    if run_root.exists():
        raise SystemExit(f"proposal replay already exists: {run_root}")
    source_copy_root = run_root / "sources"
    report_root = run_root / "source-reports"
    source_copy_root.mkdir(parents=True)
    report_root.mkdir(parents=True)

    git = _git_state()
    adapter_budgets = (
        REVIEW_ADAPTER_BUDGETS_SECONDS
        if args.budget_profile == "review"
        else DEFAULT_ADAPTER_BUDGETS_SECONDS
    )
    adapters, lock, capability_profiles = _build_adapters(args.cache.resolve(), emoji_max_sequences=args.emoji_max_sequences)
    rows: list[dict[str, Any]] = []
    budget_failures: list[str] = []
    nondeterministic: list[str] = []
    harness_errors: list[str] = []
    for index, source in enumerate(sources, start=1):
        source_hash = sha256_file(source)
        copied_source = source_copy_root / f"{index:03d}-{_slug(source)}.png"
        shutil.copy2(source, copied_source)
        with Image.open(source) as image:
            width, height = image.size
        fixture = {
            "id": source.stem,
            "split": "queue_diagnostic",
            "source_png": str(source),
            "source_sha256": source_hash,
            "expected_outcome": "diagnostic",
        }
        print(f"[{index:02d}/{len(sources):02d}] proposals {source.name}", flush=True)
        try:
            geometry_bundle, geometry_decision = route_raster_geometry(source)
            geometry_status = geometry_decision.status
            geometry_rejection_codes = list(geometry_decision.rejection_reasons)
            recognition_input_hash = None
            components = dict(geometry_bundle.component_evidence)
            if geometry_decision.mode == "unresolved":
                geometry = {
                    "mode": "fixed_lattice",
                    "geometry_proven": False,
                    "source_sha256": source_hash,
                    "geometry_evidence_hash": geometry_bundle.output_hash,
                    "mixed_width_display": dict(geometry_bundle.projection_evidence.get("mixed_width_display", {})),
                    "hypothesis_only": True,
                }
                variants = tuple(
                    (
                        str(item.get("provenance", {}).get("hypothesis", {}).get("pitch", "hypothesis"))
                        + ":"
                        + str(item.get("provenance", {}).get("hypothesis", {}).get("phase", ""))
                        + ":"
                        + str(item.get("provenance", {}).get("hypothesis", {}).get("base_advance_px", ""))
                        + ":"
                        + str(item.get("provenance", {}).get("hypothesis", {}).get("origin_px", "")),
                        dict(item),
                    )
                    for item in build_recognition_hypothesis_inputs(source, geometry_bundle, max_hypotheses=2)
                )
            else:
                geometry = dict(geometry_decision.provenance["selected_geometry"])
                recognition_inputs = build_recognition_inputs(source, geometry_bundle, mode=geometry_decision.mode)
                recognition_input_hash = str(recognition_inputs["input_hash"])
                variants = (("authoritative", dict(recognition_inputs)),)
            adapter_records: list[dict[str, Any]] = []
            proposed_logical_order: list[str] = []
            row_budget_failures: list[str] = []
            row_nondeterministic: list[str] = []
            for adapter in adapters:
                adapter_name = str(getattr(adapter, "name", type(adapter).__name__))
                budget_seconds = float(adapter_budgets.get(adapter_name, 30.0))
                adapter_started = time.perf_counter()
                try:
                    records, _elapsed_ms = _run_with_budget(
                        lambda: _evaluate_adapter_direct(
                            adapter=adapter,
                            source_path=source,
                            source_sha256=source_hash,
                            geometry=geometry,
                            components=components,
                            variants=variants,
                            environment_lock=lock,
                            top_k=max(1, args.top_k),
                            geometry_status=geometry_status,
                            geometry_rejection_codes=geometry_rejection_codes,
                            recognition_input_hash=recognition_input_hash,
                            budget_seconds=budget_seconds,
                        ),
                        budget_seconds,
                    )
                    adapter_records.extend(records)
                    for record in records:
                        proposed_logical_order.extend(str(item) for item in record.get("top_k_logical_sequences", ()) if str(item))
                        if record.get("budget_exceeded"):
                            row_budget_failures.append(f"{fixture['id']}:{record.get('adapter')}")
                except _BudgetExceeded:
                    elapsed_ms = round((time.perf_counter() - adapter_started) * 1000.0, 3)
                    failure = f"{fixture['id']}:{adapter_name}"
                    row_budget_failures.append(failure)
                    adapter_records.append(_timeout_adapter_record(adapter, str(fixture["id"]), budget_seconds, elapsed_ms))
                    print(f"  timeout {adapter_name} after {elapsed_ms:.1f}ms", flush=True)
                except Exception as exc:
                    elapsed_ms = round((time.perf_counter() - adapter_started) * 1000.0, 3)
                    adapter_records.append(
                        {
                            "adapter": adapter_name,
                            "version": getattr(adapter, "version", "unknown"),
                            "status": "rejected",
                            "runtime_ms": elapsed_ms,
                            "budget_seconds": budget_seconds,
                            "budget_exceeded": False,
                            "deterministic": True,
                            "top_k_logical_sequences": [],
                            "unsupported_status": [f"adapter_exception:{type(exc).__name__}"],
                            "geometry_status": geometry_status,
                            "geometry_rejection_codes": geometry_rejection_codes,
                            "recognition_input_hash": recognition_input_hash,
                            "retained_proposal_state_count": 0,
                            "row_proposals": [],
                            "joint_decoder": None,
                            "error": f"{type(exc).__name__}: {exc}",
                        }
                    )
                    print(f"  adapter error {adapter_name}: {type(exc).__name__}", flush=True)
            compact_adapters = [_compact_adapter(dict(item)) for item in adapter_records]
            proposed_logical_order = list(dict.fromkeys(proposed_logical_order))[: max(1, args.top_k)]
            budget_failures.extend(row_budget_failures)
            nondeterministic.extend(row_nondeterministic)
            row = {
                "id": source.name,
                "fixture": fixture["id"],
                "source_path": str(source),
                "copied_source": str(copied_source),
                "source_sha256": source_hash,
                "width": width,
                "height": height,
                "authority": "proposal_only_diagnostic",
                "candidate_written": False,
                "accepted_written": False,
                "old_txt_read": False,
                "accepted_txt_read": False,
                "historical_attempts_read": False,
                "geometry_status": geometry_status,
                "geometry_rejection_codes": geometry_rejection_codes,
                "recognition_input_hash": recognition_input_hash,
                "proposed_logical_order": proposed_logical_order,
                "has_any_proposal": any(adapter.get("top_k_logical_sequences") for adapter in compact_adapters),
                "unsupported": not bool(proposed_logical_order),
                "budget_failures": sorted(set(row_budget_failures)),
                "nondeterministic_adapters": sorted(set(row_nondeterministic)),
                "adapters": compact_adapters,
            }
        except Exception as exc:  # diagnostic replay must fail closed per source
            harness_errors.append(f"{source.name}:{type(exc).__name__}")
            row = {
                "id": source.name,
                "source_path": str(source),
                "copied_source": str(copied_source),
                "source_sha256": source_hash,
                "width": width,
                "height": height,
                "authority": "proposal_only_diagnostic",
                "candidate_written": False,
                "accepted_written": False,
                "old_txt_read": False,
                "accepted_txt_read": False,
                "historical_attempts_read": False,
                "geometry_status": "harness_error",
                "geometry_rejection_codes": [f"{type(exc).__name__}: {exc}"],
                "recognition_input_hash": None,
                "proposed_logical_order": [],
                "has_any_proposal": False,
                "unsupported": True,
                "budget_failures": [],
                "nondeterministic_adapters": [],
                "adapters": [],
            }
        rows.append(row)
        _write_json(report_root / f"{index:03d}-{_slug(source)}.json", row)

    summary: dict[str, Any] = {
        "source_count": len(rows),
        "proposal_authority": "diagnostic_only",
        "budget_profile": args.budget_profile,
        "candidate_written": sum(1 for row in rows if row["candidate_written"]),
        "accepted_written": sum(1 for row in rows if row["accepted_written"]),
        "old_txt_read": False,
        "accepted_txt_read": False,
        "historical_attempts_read": False,
        "sources_with_any_proposal": sum(1 for row in rows if row["has_any_proposal"]),
        "sources_with_no_proposal": sum(1 for row in rows if not row["has_any_proposal"]),
        "budget_failure_count": len(sorted(set(budget_failures))),
        "nondeterministic_count": len(sorted(set(nondeterministic))),
        "harness_error_count": len(harness_errors),
    }
    for row in rows:
        key = f"geometry:{row['geometry_status']}"
        summary[key] = int(summary.get(key, 0)) + 1
    inventory = {
        "schema": "lateletter-queue-proposal-inventory-1",
        "source_dir": str(source_dir),
        "git": git,
        "sources": [
            {
                "path": row["source_path"],
                "copied_source": row["copied_source"],
                "sha256": row["source_sha256"],
                "width": row["width"],
                "height": row["height"],
            }
            for row in rows
        ],
    }
    inventory_hash = _write_json(run_root / "source-inventory.json", inventory)
    replay = {
        "schema": "lateletter-queue-proposal-replay-1",
        "run_id": run_id,
        "authority": "proposal_only_diagnostic",
        "old_txt_read": False,
        "accepted_txt_read": False,
        "historical_attempts_read": False,
        "candidate_written": False,
        "accepted_written": False,
        "source_inventory_hash": inventory_hash,
        "git": git,
        "environment_lock": lock.to_dict(),
        "capability_profiles": capability_profiles,
        "adapter_budgets_seconds": adapter_budgets,
        "summary": summary,
        "budget_failures": sorted(set(budget_failures)),
        "nondeterministic_adapters": sorted(set(nondeterministic)),
        "harness_errors": sorted(set(harness_errors)),
        "rows": rows,
    }
    replay_hash = _write_json(run_root / "proposal-replay.json", replay)
    receipt = {
        "schema": "lateletter-queue-proposal-receipt-1",
        "run_id": run_id,
        "authority": "proposal_only_diagnostic",
        "budget_profile": args.budget_profile,
        "run_root": str(run_root),
        "source_inventory_sha256": inventory_hash,
        "proposal_replay_sha256": replay_hash,
        "summary": summary,
        "old_txt_read": False,
        "accepted_txt_read": False,
        "historical_attempts_read": False,
        "candidate_written": False,
        "accepted_written": False,
        "next_step": "Inspect current recognizer proposals; failures here are proposal/repertoire/ranking evidence, not accepted conversion output.",
    }
    review_path = run_root / "review.html"
    review_path.write_text(_html_review(run_root, rows, receipt), encoding="utf-8")
    receipt["review_sha256"] = sha256_file(review_path)
    receipt_hash = _write_json(run_root / "receipt.json", receipt)
    receipt["receipt_sha256"] = receipt_hash
    print(
        json.dumps(
            {
                "run_root": str(run_root),
                "review": str(review_path),
                "summary": summary,
                "receipt_sha256": receipt_hash,
            },
            ensure_ascii=False,
            indent=2,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
