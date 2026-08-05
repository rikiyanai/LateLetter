"""The single production owner for PNG transcription attempts.

This module deliberately stops at the first unavailable authority.  Diagnostic
recognizers may propose evidence elsewhere, but they cannot write a candidate
or promote an accepted transcript.  ``accept`` is the only function that can
copy candidate bytes to ``accepted.txt``.
"""

from __future__ import annotations

import json
import signal
import shutil
import time
from pathlib import Path
from typing import Any, Mapping

import numpy as np
from PIL import Image

from .attempts import AttemptError, create_attempt, read_record, verify_candidate_bundle, write_candidate_bundle, write_record
from .geometry import route_raster_geometry
from .hashing import resolve_under, sha256_bytes, sha256_file
from .model import (
    CandidateBundle,
    GateReport,
    GeometryDecision,
    NormalizationReceipt,
    OperatorReviewReceipt,
    SourceReceipt,
)
from .schema import canonical_bytes


_REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
_ADAPTER_BUDGETS_SECONDS: Mapping[str, float] = {
    "emoji-grapheme-atlas": 30.0,
    "fixed-lattice-structural": 5.0,
    "independent-offline-easyocr": 15.0,
    "independent-offline-surya": 15.0,
    "paddleocr-offline": 15.0,
    "structural-unicode-row": 90.0,
    "tesseract-offline": 12.0,
    "unicode-template-arabic": 30.0,
    "unicode-template-cjk": 30.0,
    "unicode-template-combining": 30.0,
    "unicode-template-kana": 30.0,
    "unicode-template-latin": 30.0,
}
_RECOGNIZER_TOTAL_BUDGET_SECONDS = 120.0


class _RecognizerBudgetExceeded(BaseException):
    """Raised when production recognition exceeds the attempt-level ceiling."""


def _run_with_recognizer_budget(callback):
    def _alarm(_signum, _frame):
        raise _RecognizerBudgetExceeded(
            f"recognizer replay exceeded {_RECOGNIZER_TOTAL_BUDGET_SECONDS:.3f}s production ceiling"
        )

    previous_handler = signal.getsignal(signal.SIGALRM)
    signal.signal(signal.SIGALRM, _alarm)
    signal.setitimer(signal.ITIMER_REAL, _RECOGNIZER_TOTAL_BUDGET_SECONDS)
    started = time.perf_counter()
    try:
        return callback(), round((time.perf_counter() - started) * 1000.0, 3)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0.0)
        signal.signal(signal.SIGALRM, previous_handler)


def _write_json_once(path: Path, payload: Mapping[str, Any]) -> str:
    """Write one immutable diagnostic JSON artifact."""

    if path.exists():
        raise AttemptError(f"immutable artifact already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    data = canonical_bytes(payload) + b"\n"
    path.write_bytes(data)
    return sha256_bytes(data)


def _record_path(attempt: Path, name: str) -> Path:
    return resolve_under(attempt, name)


def _connected_components(mask: np.ndarray) -> list[tuple[int, int, int, int, int, np.ndarray]]:
    seen = np.zeros(mask.shape, dtype=bool)
    result: list[tuple[int, int, int, int, int, np.ndarray]] = []
    height, width = mask.shape
    for start_y, start_x in zip(*np.where(mask)):
        if seen[start_y, start_x]:
            continue
        stack = [(int(start_y), int(start_x))]
        seen[start_y, start_x] = True
        points: list[tuple[int, int]] = []
        while stack:
            y, x = stack.pop()
            points.append((y, x))
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    if dx == 0 and dy == 0:
                        continue
                    ny = y + dy
                    nx = x + dx
                    if 0 <= ny < height and 0 <= nx < width and mask[ny, nx] and not seen[ny, nx]:
                        seen[ny, nx] = True
                        stack.append((ny, nx))
        if len(points) < 8:
            continue
        ys = [point[0] for point in points]
        xs = [point[1] for point in points]
        y0, y1 = min(ys), max(ys)
        x0, x1 = min(xs), max(xs)
        result.append((x0, y0, x1, y1, len(points), mask[y0 : y1 + 1, x0 : x1 + 1]))
    return result


def _missing_glyph_box_evidence(source_png: Path) -> list[dict[str, Any]]:
    """Detect source-rendered tofu boxes from pixels, not transcript metadata."""

    with Image.open(source_png) as opened:
        pixels = np.asarray(opened.convert("RGB"))
    corners = np.asarray((pixels[0, 0], pixels[0, -1], pixels[-1, 0], pixels[-1, -1]), dtype=float)
    background = np.median(corners, axis=0)
    distance = np.sqrt(((pixels.astype(float) - background) ** 2).sum(axis=2))
    mask = distance > 25.0
    evidence: list[dict[str, Any]] = []
    for x0, y0, x1, y1, area, crop in _connected_components(mask):
        box_height, box_width = crop.shape
        if box_width < 8 or box_height < 12:
            continue
        top = float(crop[0, :].mean())
        bottom = float(crop[-1, :].mean())
        left = float(crop[:, 0].mean())
        right = float(crop[:, -1].mean())
        edge_density = (top + bottom + left + right) / 4.0
        inner_density = float(crop[2:-2, 2:-2].mean()) if box_width > 4 and box_height > 4 else 1.0
        fill_density = float(area / max(1, box_width * box_height))
        outline_score = edge_density - inner_density
        if (
            outline_score >= 0.70
            and edge_density >= 0.90
            and inner_density <= 0.20
            and 0.30 <= fill_density <= 0.60
        ):
            evidence.append(
                {
                    "bounds": [int(x0), int(y0), int(x1), int(y1)],
                    "width": int(box_width),
                    "height": int(box_height),
                    "ink_pixels": int(area),
                    "edge_density": edge_density,
                    "inner_density": inner_density,
                    "fill_density": fill_density,
                    "outline_score": outline_score,
                }
            )
    return evidence


def _candidate_visible_count(text: str) -> int:
    return sum(1 for char in text if not char.isspace())


def _arabic_letter_count(text: str) -> int:
    return sum(1 for char in text if ("\u0621" <= char <= "\u064a") or ("\u0671" <= char <= "\u06d3"))


def _contains_arabic_letters(text: str) -> bool:
    return _arabic_letter_count(text) > 0


def _contains_cjk_or_kana_width(text: str) -> bool:
    return any(
        ("\u3040" <= char <= "\u30ff")
        or ("\u3400" <= char <= "\u9fff")
        or ("\uff00" <= char <= "\uffef")
        for char in text
    )


def _contains_ascii_structural(text: str) -> bool:
    structural = set("()[]{}<>/\\|_.:-=~^',`+*#")
    return any(char in structural for char in text)


def _contains_emoji(text: str) -> bool:
    return any(ord(char) >= 0x1F000 for char in text)


def _mostly_structural_ascii(text: str) -> bool:
    visible = [char for char in text if not char.isspace()]
    if len(visible) < 3:
        return False
    structural = set("()[]{}<>/\\|_.:-=~^',`+*#")
    return all(ord(char) < 128 and char in structural for char in visible)


def _source_has_strong_color(source_png: Path) -> bool:
    with Image.open(source_png) as opened:
        rgba = np.asarray(opened.convert("RGBA"))
    alpha = rgba[:, :, 3] > 0
    if not bool(alpha.any()):
        return False
    rgb = rgba[:, :, :3].astype(int)
    non_gray = (np.max(rgb, axis=2) - np.min(rgb, axis=2)) > 20
    return int(np.count_nonzero(non_gray & alpha)) >= 25


def _source_ink_summary(source_png: Path) -> dict[str, int]:
    with Image.open(source_png) as opened:
        pixels = np.asarray(opened.convert("RGB"))
    corners = np.asarray((pixels[0, 0], pixels[0, -1], pixels[-1, 0], pixels[-1, -1]), dtype=float)
    background = np.median(corners, axis=0)
    distance = np.sqrt(((pixels.astype(float) - background) ** 2).sum(axis=2))
    mask = distance > 25.0
    if not bool(mask.any()):
        return {"ink_pixels": 0, "component_count": 0}
    return {"ink_pixels": int(mask.sum()), "component_count": len(_connected_components(mask))}


# The script-membership whitelist below was validated only against the ten
# tiny release fixtures (a handful of ink components each).  On live
# screenshots with hundreds of components it selects structurally plausible
# garbage (horse smoke, 2026-08-05: connected-component dashes/backslashes
# written as a candidate).  Above this component count, only screenshot-local
# row-joint evidence may author a candidate; everything else stays proposal
# evidence and the attempt is a typed refusal.
_WHITELIST_COMPONENT_LIMIT = 64


def _best_effort_candidate_from_report(
    report: Mapping[str, Any],
    *,
    source_png: Path,
    geometry_mode: str | None = None,
    source_component_count: int = 0,
    source_row_count: int = 0,
    row_joint_available: bool = False,
) -> dict[str, Any] | None:
    results = report.get("results")
    if not isinstance(results, list) or len(results) != 1:
        return None
    result = results[0]
    adapters = result.get("adapters")
    if not isinstance(adapters, list):
        return None
    strong_color = _source_has_strong_color(source_png)
    candidates: list[dict[str, Any]] = []
    for adapter in adapters:
        adapter_name = str(adapter.get("adapter", ""))
        if adapter.get("budget_exceeded") or adapter.get("deterministic") is False:
            continue
        # The router's lattice-vs-shaped mode may NOT be used to exclude
        # adapters here.  The mode assignment is itself unproven evidence:
        # the router currently routes the canonical positive-fixed-ascii
        # fixture (a lattice source by construction) as shaped_runs, and a
        # mode-based exclusion turned that misrouting into a written wrong
        # candidate ("L" instead of "/\_|", 2026-08-05 FL entry).  Until the
        # mode assignment carries its own proof, candidates from every
        # deterministic in-budget adapter compete and source-fit evidence
        # must decide, not the mode label.
        unsupported = tuple(str(item) for item in adapter.get("unsupported_status", ()))
        if any("collision" in item for item in unsupported):
            continue
        for rank, text in enumerate(adapter.get("top_k_logical_sequences", ()), start=1):
            normalized = str(text)
            if not normalized.strip():
                continue
            visible_count = _candidate_visible_count(normalized)
            minimum_visible = max(4, int(round(source_component_count * 0.40))) if source_component_count else 1
            if visible_count < minimum_visible:
                continue
            line_count = len(normalized.rstrip("\n").splitlines()) if normalized.strip() else 0
            minimum_lines = max(1, int(round(source_row_count * 0.80))) if source_row_count else 1
            if line_count < minimum_lines:
                continue
            priority = 90
            reason = "untrusted_adapter"
            if adapter_name != "row-joint-lattice" and row_joint_available:
                # Screenshot-local row-joint evidence exists for this
                # source.  Weaker evidence classes may not author the
                # candidate while stronger evidence is present — if the
                # row-joint text still carries ``?`` the correct outcome
                # is a typed refusal, not a fallback to a guess.
                continue
            if adapter_name != "row-joint-lattice" and source_component_count > _WHITELIST_COMPONENT_LIMIT:
                # Whitelist rules are fixture-scoped evidence; at live
                # scale they select plausible garbage, so they may not
                # author candidates for large sources.
                continue
            if adapter_name == "row-joint-lattice" and "?" in normalized:
                # Unknown cells are honest refusals from the row-joint
                # decoder; a text still carrying ``?`` is evidence, never
                # a candidate.
                continue
            if adapter_name == "row-joint-lattice":
                # Screenshot-local leave-one-out templates with an
                # unexplained-ink cost are the strongest source-fit
                # evidence any adapter currently records, so an
                # unknown-free row-joint decode outranks every
                # script-membership heuristic below.
                priority = 3
                reason = "row_joint_screenshot_local_template_fit"
            elif strong_color and adapter_name == "emoji-grapheme-atlas" and _contains_emoji(normalized):
                priority = 0
                reason = "source_color_emoji_atlas"
            elif adapter_name == "tesseract-profile-fusion" and _contains_arabic_letters(normalized) and _contains_cjk_or_kana_width(normalized):
                priority = 5
                reason = "mixed_script_profile_fusion"
            elif (
                adapter_name == "psm7-ara"
                and _arabic_letter_count(normalized) >= 2
                and not _contains_ascii_structural(normalized)
                and not _contains_cjk_or_kana_width(normalized)
            ):
                priority = 10
                reason = "arabic_profile_script_match"
            elif adapter_name == "psm7-jpn-cjk" and _contains_cjk_or_kana_width(normalized) and not _contains_ascii_structural(normalized):
                priority = 20
                reason = "japanese_cjk_profile_script_match"
            elif adapter_name == "fixed-lattice-structural" and _mostly_structural_ascii(normalized):
                priority = 30
                reason = "fixed_structural_ascii_source_fit"
            elif adapter_name in {"psm7-eng", "psm13-eng"} and not _contains_arabic_letters(normalized) and not _contains_cjk_or_kana_width(normalized):
                priority = 40 if adapter_name == "psm7-eng" else 45
                reason = "latin_profile_script_match"
            if priority >= 90:
                continue
            candidates.append(
                {
                    "adapter": adapter_name,
                    "rank": rank,
                    "text": normalized,
                    "priority": priority,
                    "reason": reason,
                    "visible_count": visible_count,
                    "minimum_visible_count": minimum_visible,
                    "line_count": line_count,
                    "minimum_line_count": minimum_lines,
                }
            )
    if not candidates:
        return None
    def selector_score(item: Mapping[str, Any]) -> int:
        return int(item["priority"]) * 100 + int(item["rank"])

    candidates.sort(key=lambda item: (selector_score(item), -int(item["visible_count"]), str(item["text"])))
    best = candidates[0]
    runner = candidates[1] if len(candidates) > 1 else None
    best["selector_score"] = selector_score(best)
    best["runner_up"] = runner
    best["selector_margin"] = (
        float(selector_score(runner) - selector_score(best))
        if runner is not None
        else 100.0
    )
    return best


def _recognizer_environment() -> tuple[tuple[Any, ...], Any]:
    from .recognition import (
        EmojiAtlasAdapter,
        FixedLatticeStructuralAdapter,
        StructuralUnicodeRowAdapter,
        TesseractOfflineAdapter,
        UnicodeTemplateRunAdapter,
        build_environment_lock,
    )

    model_cache = _REPOSITORY_ROOT / "tracked/LateLetterResearch/transcription-model-cache"
    tessdata = model_cache / "tesseract_best"
    model_paths = {path.stem: str(path) for path in tessdata.glob("*.traineddata")}
    template_font = model_cache / "fonts/NotoSansMono-Variable.ttf"
    if template_font.exists():
        for name in (
            "unicode-template-latin.font",
            "unicode-template-combining.font",
            "unicode-template-kana.font",
            "unicode-template-arabic.font",
            "unicode-template-cjk.font",
        ):
            model_paths[name] = str(template_font)
    emoji = EmojiAtlasAdapter.from_cache(model_cache / "emoji")
    adapters = (
        TesseractOfflineAdapter(cache_dir=str(tessdata), languages=("eng", "ara", "jpn", "jpn_vert", "chi_sim", "chi_tra")),
        FixedLatticeStructuralAdapter(),
        StructuralUnicodeRowAdapter(),
        UnicodeTemplateRunAdapter(repertoire_name="latin", name="unicode-template-latin"),
        UnicodeTemplateRunAdapter(repertoire_name="combining", name="unicode-template-combining"),
        UnicodeTemplateRunAdapter(repertoire_name="kana", name="unicode-template-kana"),
        UnicodeTemplateRunAdapter(repertoire_name="arabic", name="unicode-template-arabic"),
        UnicodeTemplateRunAdapter(repertoire_name="cjk", name="unicode-template-cjk"),
        EmojiAtlasAdapter(
            sequence_data_path=emoji.sequence_data_path,
            font_path=emoji.font_path,
            font_hashes=emoji.font_hashes,
            max_sequences=10000,
        ),
    )
    lock = build_environment_lock(
        model_paths=model_paths,
        script_packs=tuple(sorted(model_paths)),
        preprocessing={"network": "disabled", "ground_truth_to_adapter": False},
    )
    return adapters, lock


def _candidate_layout_payload(text: str, selector: Mapping[str, Any]) -> dict[str, Any]:
    rows = text.rstrip("\n").splitlines() or [""]
    return {
        "schema": "lateletter-visual-layout-1",
        "authority": "pipeline.phase6.source_fit_collision_gate",
        "rows": [{"row_index": index, "logical_text": row} for index, row in enumerate(rows)],
        "selector": {
            "adapter": selector.get("adapter"),
            "rank": selector.get("rank"),
            "reason": selector.get("reason"),
            "selector_margin": selector.get("selector_margin"),
        },
    }


def transcribe(
    source_png: str | Path,
    attempt_root: str | Path,
    attempt_id: str,
    *,
    geometry_configuration: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the canonical source-to-review pipeline until its first failed gate.

    Geometry, recognition, source collision evidence, and candidate authority
    must all pass before a machine candidate is written.  Rejected branches
    leave no TXT bytes behind.
    """

    source = Path(source_png).resolve()
    if not source.exists() or not source.is_file():
        raise AttemptError(f"source PNG does not exist: {source}")
    if source.suffix.lower() != ".png":
        raise AttemptError("transcribe requires a PNG source")
    root = Path(attempt_root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    attempt = create_attempt(root, attempt_id)

    source_bytes = source.read_bytes()
    source_hash = sha256_bytes(source_bytes)
    with Image.open(source) as image:
        width, height = image.size
        if width <= 0 or height <= 0:
            raise AttemptError("source PNG has invalid dimensions")

    source_copy = attempt / "source.png"
    source_copy.write_bytes(source_bytes)
    source_receipt = SourceReceipt(
        source_path="source.png",
        source_sha256=source_hash,
        width=width,
        height=height,
        input_hashes={"source": source_hash},
        provenance={"authority": "pipeline.transcribe", "source_copy": True},
        status="verified",
    )
    source_receipt_hash = write_record(attempt / "source-receipt.json", source_receipt)

    normalized_copy = attempt / "normalized.png"
    normalized_copy.write_bytes(source_bytes)
    normalized_hash = sha256_file(normalized_copy)
    normalization = NormalizationReceipt(
        source_sha256=source_hash,
        normalized_sha256=normalized_hash,
        method="identity",
        guide_removal="none",
        operations=("identity_copy",),
        input_hashes={"source": source_hash},
        provenance={"authority": "pipeline.transcribe", "source_specific_guides": False},
        status="verified",
    )
    normalization_hash = write_record(attempt / "normalization.json", normalization)

    bundle, decision = route_raster_geometry(
        normalized_copy,
        expected_sha256=normalized_hash,
        configuration=geometry_configuration,
    )
    geometry_hash = write_record(attempt / "geometry.json", decision)
    evidence_hash = _write_json_once(
        attempt / "geometry-evidence.json",
        {**bundle.to_dict(), "artifact_sha256": bundle.output_hash},
    )
    components_hash = _write_json_once(
        attempt / "components.json",
        {
            "source_sha256": normalized_hash,
            "geometry_evidence_hash": bundle.output_hash,
            "component_evidence": dict(bundle.component_evidence),
            "artifact_sha256": str(bundle.component_evidence.get("component_hash", "")),
        },
    )

    checks: dict[str, bool] = {
        "source_verified": source_receipt_hash == sha256_file(attempt / "source-receipt.json"),
        "normalization_verified": normalization_hash == sha256_file(attempt / "normalization.json"),
        "geometry_proved": decision.status == "proved" and decision.mode != "unresolved",
    }
    rejection_codes = list(decision.rejection_reasons)
    provenance: dict[str, Any] = {
        "geometry_decision_hash": geometry_hash,
        "geometry_evidence_hash": evidence_hash,
        "components_hash": components_hash,
    }
    proposals_hash: str | None = None
    environment_hash: str | None = None
    selector: dict[str, Any] | None = None
    candidate_path: Path | None = None
    visual_layout_hash: str | None = None
    ownership_hash: str | None = None
    candidate_bundle_hash: str | None = None

    if checks["geometry_proved"]:
        selected_geometry = decision.provenance.get("selected_geometry") if isinstance(decision.provenance, Mapping) else {}
        source_ink_summary = _source_ink_summary(normalized_copy)
        source_row_count = 0
        if isinstance(selected_geometry, Mapping):
            row_bands = selected_geometry.get("row_bands")
            if isinstance(row_bands, (list, tuple)):
                source_row_count = len(row_bands)
        missing_box_evidence = _missing_glyph_box_evidence(normalized_copy)
        source_collision_hash = _write_json_once(
            attempt / "source-collision.json",
            {
                "schema": "lateletter-source-collision-1",
                "source_sha256": normalized_hash,
                "missing_glyph_boxes": missing_box_evidence,
                "missing_glyph_box_count": len(missing_box_evidence),
                "status": "rejected" if missing_box_evidence else "passed",
            },
        )
        provenance["source_collision_hash"] = source_collision_hash
        checks["source_missing_glyph_boxes_absent"] = not missing_box_evidence
        if missing_box_evidence:
            rejection_codes.append("source_missing_glyph_box_collision")
        else:
            try:
                from .recognition import benchmark_offline_ensemble

                adapters, environment_lock = _recognizer_environment()
                environment_hash = _write_json_once(attempt / "environment-lock.json", environment_lock.to_dict())
                report, recognizer_runtime_ms = _run_with_recognizer_budget(
                    lambda: benchmark_offline_ensemble(
                        (
                            {
                                "id": attempt_id,
                                "source_png": str(normalized_copy),
                                "source_sha256": normalized_hash,
                                "expected_outcome": "candidate",
                            },
                        ),
                        adapters,
                        environment_lock,
                        top_k=8,
                        deterministic_replay=True,
                        adapter_budgets_seconds=_ADAPTER_BUDGETS_SECONDS,
                    )
                )
                report["production_recognizer_runtime_ms"] = recognizer_runtime_ms
                report["production_recognizer_budget_seconds"] = _RECOGNIZER_TOTAL_BUDGET_SECONDS
                # Row-joint lattice evidence: when a tracked hash-bound
                # calibration exists for this exact source, the legacy
                # screenshot-local decoder joins the report as one more
                # deterministic proposal owner.  Its ``?`` cells survive
                # into the text; the selector refuses any ``?``-bearing
                # candidate, so unknown cells can never reach candidate
                # TXT.  Absence of a calibration is a typed unavailability
                # and adds nothing to the report.
                try:
                    from . import row_joint

                    row_joint_result = row_joint.decode_for_source(normalized_copy)
                except Exception as exc:  # decoder or calibration failure stays evidence-only
                    row_joint_result = None
                    provenance["row_joint_error"] = f"{type(exc).__name__}: {exc}"
                if row_joint_result is not None:
                    results_list = report.get("results")
                    if isinstance(results_list, list) and len(results_list) == 1:
                        adapters_list = results_list[0].get("adapters")
                        if isinstance(adapters_list, list):
                            adapters_list.append(
                                {
                                    "adapter": row_joint.ADAPTER_NAME,
                                    "adapter_version": row_joint_result["decoder_version"],
                                    "deterministic": True,
                                    "budget_exceeded": False,
                                    "unsupported_status": [],
                                    "top_k_logical_sequences": [row_joint_result["text"]],
                                    "row_joint": {
                                        key: row_joint_result[key]
                                        for key in (
                                            "unknown_cells",
                                            "cell_count",
                                            "row_count",
                                            "columns",
                                            "calibration_path",
                                            "calibration_sha256",
                                            "template_glyphs",
                                        )
                                        if key in row_joint_result
                                    },
                                }
                            )
                proposals_hash = _write_json_once(attempt / "proposals.json", report)
                provenance["environment_lock_hash"] = environment_hash
                provenance["proposals_hash"] = proposals_hash
                selector = _best_effort_candidate_from_report(
                    report,
                    source_png=normalized_copy,
                    geometry_mode=decision.mode,
                    source_component_count=int(source_ink_summary.get("component_count", 0)),
                    source_row_count=source_row_count,
                    row_joint_available=row_joint_result is not None,
                )
                checks["recognizer_open_repertoire_available"] = bool(selector)
                checks["recognizer_budget_passed"] = not report.get("budget_failures")
                checks["recognizer_deterministic"] = not report.get("nondeterministic_adapters")
                checks["candidate_selector_unique"] = bool(selector and float(selector.get("selector_margin", 0.0)) > 0.0)
                if not checks["recognizer_open_repertoire_available"]:
                    rejection_codes.append("recognizer_open_repertoire_unavailable")
                if not checks["recognizer_budget_passed"]:
                    rejection_codes.append("recognizer_budget_failure")
                if not checks["recognizer_deterministic"]:
                    rejection_codes.append("recognizer_nondeterministic")
                if not checks["candidate_selector_unique"]:
                    rejection_codes.append("candidate_selector_not_unique")
            except _RecognizerBudgetExceeded as exc:
                environment_error_hash = _write_json_once(
                    attempt / "recognizer-error.json",
                    {
                        "schema": "lateletter-recognizer-error-1",
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                        "budget_seconds": _RECOGNIZER_TOTAL_BUDGET_SECONDS,
                        "status": "rejected",
                    },
                )
                provenance["recognizer_error_hash"] = environment_error_hash
                checks["recognizer_open_repertoire_available"] = False
                checks["recognizer_budget_passed"] = False
                checks["recognizer_deterministic"] = False
                checks["candidate_selector_unique"] = False
                rejection_codes.append("recognizer_budget_failure")
                rejection_codes.append("recognizer_attempt_timeout")
            except Exception as exc:
                environment_error_hash = _write_json_once(
                    attempt / "recognizer-error.json",
                    {
                        "schema": "lateletter-recognizer-error-1",
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                        "status": "rejected",
                    },
                )
                provenance["recognizer_error_hash"] = environment_error_hash
                checks["recognizer_open_repertoire_available"] = False
                checks["recognizer_budget_passed"] = False
                checks["recognizer_deterministic"] = False
                checks["candidate_selector_unique"] = False
                rejection_codes.append(f"recognizer_environment_unavailable:{type(exc).__name__}")
    checks["candidate_authority_passed"] = all(checks.values())
    gate = GateReport(
        input_hashes={"source": normalized_hash, "geometry": decision.geometry_hash or bundle.output_hash},
        configuration={"pipeline": "transcribe-v1"},
        provenance=provenance,
        status="proved" if checks["candidate_authority_passed"] else "rejected",
        passed=checks["candidate_authority_passed"],
        checks=checks,
        counts={"blocking_failures": sum(1 for value in checks.values() if not value)},
        rejection_reasons=tuple(() if checks["candidate_authority_passed"] else dict.fromkeys(rejection_codes or ["geometry_unresolved"])),
    )
    gate_hash = write_record(attempt / "gate-report.json", gate)

    if checks["candidate_authority_passed"]:
        assert selector is not None
        assert proposals_hash is not None
        assert environment_hash is not None
        candidate_text = str(selector["text"]).rstrip("\n") + "\n"
        candidate_path = attempt / "candidate.txt"
        candidate_path.write_text(candidate_text, encoding="utf-8")
        visual_layout_hash = _write_json_once(attempt / "visual-layout.json", _candidate_layout_payload(candidate_text, selector))
        ownership_hash = _write_json_once(
            attempt / "ownership.json",
            {
                "schema": "lateletter-candidate-ownership-1",
                "source_sha256": normalized_hash,
                "geometry_hash": geometry_hash,
                "component_hash": components_hash,
                "proposal_hash": proposals_hash,
                "selector": selector,
                "component_evidence": dict(bundle.component_evidence),
                "source_collision": {"missing_glyph_box_count": 0},
                "status": "candidate",
            },
        )
        candidate_bundle = CandidateBundle(
            source_hash=sha256_file(attempt / "source.png"),
            normalized_source_hash=normalized_hash,
            geometry_hash=geometry_hash,
            component_hash=components_hash,
            proposal_hash=proposals_hash,
            logical_txt_hash=sha256_file(candidate_path),
            visual_layout_hash=visual_layout_hash,
            ownership_hash=ownership_hash,
            environment_lock_hash=environment_hash,
            gate_report_hash=gate_hash,
            candidate_txt_path="candidate.txt",
            visual_layout_path="visual-layout.json",
            input_hashes={
                "source": source_hash,
                "normalized": normalized_hash,
                "geometry": geometry_hash,
                "components": components_hash,
                "proposals": proposals_hash,
                "gate": gate_hash,
            },
            provenance={"authority": "pipeline.phase6.source_fit_collision_gate", "selector": selector},
            status="candidate",
        )
        candidate_bundle_hash = write_candidate_bundle(attempt / "candidate-bundle.json", candidate_bundle)

    status = (
        "machine_candidate_pending_operator_review"
        if checks["candidate_authority_passed"]
        else "rejected_geometry"
        if not checks["geometry_proved"]
        else "rejected_candidate_authority"
    )
    manifest = {
        "schema": "lateletter-transcribe-attempt-1",
        "attempt_id": attempt_id,
        "status": status,
        "candidate_written": checks["candidate_authority_passed"],
        "source": {"path": "source.png", "sha256": source_hash, "receipt_hash": source_receipt_hash},
        "normalized": {"path": "normalized.png", "sha256": normalized_hash, "receipt_hash": normalization_hash},
        "geometry": {"path": "geometry.json", "record_hash": geometry_hash, "evidence_hash": evidence_hash, "mode": decision.mode},
        "gate": {"path": "gate-report.json", "record_hash": gate_hash, "passed": checks["candidate_authority_passed"]},
        "recognition": {"path": "proposals.json" if proposals_hash else None, "record_hash": proposals_hash},
        "candidate": {
            "path": "candidate.txt" if candidate_path else None,
            "bundle_path": "candidate-bundle.json" if candidate_bundle_hash else None,
            "bundle_hash": candidate_bundle_hash,
            "visual_layout_hash": visual_layout_hash,
            "ownership_hash": ownership_hash,
            "selector": selector,
        },
        "rejection_reasons": list(gate.rejection_reasons),
    }
    _write_json_once(attempt / "manifest.json", manifest)
    return {
        "attempt_dir": str(attempt),
        "status": status,
        "candidate_written": checks["candidate_authority_passed"],
        "gate_report": gate.to_dict(),
        "manifest": manifest,
    }


def accept(
    attempt_dir: str | Path,
    operator_review_receipt: str | Path,
) -> dict[str, Any]:
    """Promote one machine candidate after an approved hash-bound review."""

    attempt = Path(attempt_dir).resolve()
    bundle_path = attempt / "candidate-bundle.json"
    if not bundle_path.exists():
        raise AttemptError("attempt has no candidate bundle")
    bundle = read_record(bundle_path, CandidateBundle)
    review_path = Path(operator_review_receipt).resolve()
    review = read_record(review_path, OperatorReviewReceipt)
    if review.operator_verdict != "approved":
        raise AttemptError("operator review is not approved")
    if review.candidate_bundle_hash != bundle.output_hash:
        raise AttemptError("operator review candidate bundle hash mismatch")
    candidate_path = resolve_under(attempt, bundle.candidate_txt_path)
    if sha256_file(candidate_path) != bundle.logical_txt_hash:
        raise AttemptError("candidate TXT hash mismatch")
    artifact_paths = {
        "source_hash": "source.png",
        "normalized_source_hash": "normalized.png",
        "geometry_hash": "geometry.json",
        "component_hash": "components.json",
        "proposal_hash": "proposals.json",
        "logical_txt_hash": bundle.candidate_txt_path,
        "visual_layout_hash": bundle.visual_layout_path,
        "ownership_hash": "ownership.json",
        "environment_lock_hash": "environment-lock.json",
        "gate_report_hash": "gate-report.json",
    }
    verify_candidate_bundle(bundle, attempt, artifact_paths)
    accepted = attempt / "accepted.txt"
    if accepted.exists():
        raise AttemptError("accepted.txt already exists")
    accepted.write_bytes(candidate_path.read_bytes())
    receipt = {
        "schema": "lateletter-acceptance-receipt-1",
        "candidate_bundle_hash": bundle.output_hash,
        "operator_review_hash": review.output_hash,
        "candidate_sha256": sha256_file(candidate_path),
        "accepted_sha256": sha256_file(accepted),
        "status": "accepted",
    }
    receipt_hash = _write_json_once(attempt / "acceptance-receipt.json", receipt)
    return {"status": "accepted", "accepted_path": str(accepted), "receipt_hash": receipt_hash}
