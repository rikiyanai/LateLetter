#!/usr/bin/env python3
"""Run the Slice 6 proposal-coverage benchmark against the release corpus."""

from __future__ import annotations

import argparse
import json
import signal
import time
from pathlib import Path

from lateletter.transcription import (
    EmojiAtlasAdapter,
    FixedLatticeStructuralAdapter,
    StructuralUnicodeRowAdapter,
    IndependentOfflineAdapter,
    PaddleOCROfflineAdapter,
    TesseractOfflineAdapter,
    UnicodeTemplateRunAdapter,
    benchmark_offline_ensemble,
    build_environment_lock,
)
from lateletter.transcription.hashing import sha256_file


DEFAULT_ADAPTER_BUDGETS_SECONDS = {
    # These ceilings are deliberately per fixture.  They are not a beam or
    # report cap: a completed proposal surface is retained in full, while a
    # worker that exceeds its measured ceiling is rejected as evidence.
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


class _AdapterBudgetExceeded(BaseException):
    """Raised only around one adapter/fixture worker.

    This intentionally is not an ``Exception``: the benchmark catches
    ordinary adapter failures, but a budget signal must cross that boundary
    and terminate this worker.
    """


def _run_with_budget(callback, budget_seconds: float):
    """Run one proposal worker with a deterministic wall-clock ceiling.

    The benchmark is a foreground CLI, so SIGALRM is available on the pinned
    offline runtime.  The timeout is outside the adapter: no partial proposal
    is promoted, and all already-completed fixture evidence remains persisted.
    """

    def _alarm(_signum, _frame):
        raise _AdapterBudgetExceeded(f"adapter fixture exceeded {budget_seconds:.3f}s budget")

    previous_handler = signal.getsignal(signal.SIGALRM)
    previous_timer = signal.setitimer(signal.ITIMER_REAL, float(budget_seconds))
    signal.signal(signal.SIGALRM, _alarm)
    started = time.perf_counter()
    try:
        return callback(), (time.perf_counter() - started) * 1000.0
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0.0)
        signal.signal(signal.SIGALRM, previous_handler)
        # Do not inherit an earlier timer if a caller had one installed.
        if previous_timer[0] > 0:
            signal.setitimer(signal.ITIMER_REAL, previous_timer[0], previous_timer[1])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("corpus", type=Path)
    parser.add_argument("cache", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--emoji-max-sequences",
        type=int,
        default=2000,
        help="bounded atlas size for this diagnostic run; the adapter remains pinned to the full UTS data file",
    )
    parser.add_argument(
        "--profile-only",
        action="store_true",
        help="measure each adapter independently without a second determinism replay or release verdict",
    )
    parser.add_argument(
        "--adapter-budget",
        action="append",
        metavar="ADAPTER=SECONDS",
        help="override one pinned per-fixture adapter budget (repeatable)",
    )
    args = parser.parse_args()
    adapter_budgets = dict(DEFAULT_ADAPTER_BUDGETS_SECONDS)
    for raw_budget in args.adapter_budget or ():
        name, separator, value = raw_budget.partition("=")
        if not separator or not name or not value:
            parser.error(f"invalid --adapter-budget {raw_budget!r}; expected ADAPTER=SECONDS")
        try:
            parsed_budget = float(value)
        except ValueError:
            parser.error(f"invalid budget value in {raw_budget!r}")
        if parsed_budget <= 0:
            parser.error(f"budget must be positive in {raw_budget!r}")
        adapter_budgets[name] = parsed_budget
    corpus = json.loads(args.corpus.read_text(encoding="utf-8"))
    fixtures = tuple(item for item in corpus["fixtures"] if item["split"] == "release_gate")
    model_paths = {path.stem: str(path) for path in (args.cache / "tesseract_best").glob("*.traineddata")}
    mono_font = args.cache / "fonts" / "NotoSansMono-Variable.ttf"
    cjk_font = args.cache / "fonts" / "NotoSansCJKjp-Regular.otf"
    arabic_font = args.cache / "fonts" / "NotoSansArabic-Regular.ttf"
    if mono_font.exists():
        model_paths.update({
            "unicode-template-latin.font": str(mono_font),
            "unicode-template-combining.font": str(mono_font),
        })
    if cjk_font.exists():
        model_paths["unicode-template-kana.font"] = str(cjk_font)
    if arabic_font.exists():
        model_paths["unicode-template-arabic.font"] = str(arabic_font)
    script_packs = tuple(sorted(model_paths))
    preliminary = build_environment_lock(model_paths=model_paths, script_packs=script_packs, preprocessing={"network": "disabled"})
    emoji_adapter = EmojiAtlasAdapter.from_cache(args.cache / "emoji")
    emoji_adapter = EmojiAtlasAdapter(
        sequence_data_path=emoji_adapter.sequence_data_path,
        font_path=emoji_adapter.font_path,
        font_hashes=emoji_adapter.font_hashes,
        max_sequences=max(1, args.emoji_max_sequences),
    )
    adapters = (
        TesseractOfflineAdapter(cache_dir=str(args.cache / "tesseract_best"), languages=("eng", "ara", "jpn", "jpn_vert", "chi_sim", "chi_tra")),
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
    if args.profile_only:
        profile_reports = []
        def write_profile_snapshot(status: str) -> None:
            snapshot = {
                "status": status,
                "source_corpus": str(args.corpus),
                "source_corpus_sha256": sha256_file(args.corpus),
                "environment_lock": lock.to_dict(),
                "capability_profiles": [profile.to_dict() for profile in profiles],
                "ground_truth_passed_to_adapters": False,
                "determinism_replay_performed": False,
                "adapter_budgets_seconds": adapter_budgets,
                "profiles": profile_reports,
                "authority": "diagnostic_only",
            }
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        write_profile_snapshot("running")
        for adapter in adapters:
            adapter_started = time.perf_counter()
            fixture_records = []
            positive_missing = []
            adapter_budget_failures = []
            for fixture in fixtures:
                budget_seconds = float(adapter_budgets.get(adapter.name, 30.0))
                fixture_started = time.perf_counter()
                try:
                    fixture_report, _elapsed_ms = _run_with_budget(
                        lambda: benchmark_offline_ensemble(
                            (fixture,),
                            (adapter,),
                            lock,
                            root=args.corpus.parent,
                            deterministic_replay=False,
                            adapter_budgets_seconds={adapter.name: budget_seconds},
                        ),
                        budget_seconds,
                    )
                    result = fixture_report["results"][0]
                    fixture_records.append({"fixture": result["fixture"], "adapters": result["adapters"]})
                    positive_missing.extend(fixture_report["positive_missing"])
                    adapter_budget_failures.extend(fixture_report.get("budget_failures", ()))
                except _AdapterBudgetExceeded as exc:
                    elapsed_ms = round((time.perf_counter() - fixture_started) * 1000.0, 3)
                    adapter_budget_failures.append(f"{fixture['id']}:{adapter.name}")
                    fixture_records.append(
                        {
                            "fixture": fixture["id"],
                            "adapters": [
                                {
                                    "adapter": adapter.name,
                                    "version": getattr(adapter, "version", "unknown"),
                                    "status": "rejected_budget_exceeded",
                                    "budget_seconds": budget_seconds,
                                    "budget_exceeded": True,
                                    "runtime_ms": elapsed_ms,
                                    "retained_proposal_state_count": 0,
                                    "deterministic": False,
                                    "determinism_replay_performed": False,
                                    "top_k_logical_sequences": [],
                                    "proposed_logical_order": [],
                                    "unsupported_status": ["budget_exceeded"],
                                    "rejection_reason": str(exc),
                                    "source_only": True,
                                }
                            ],
                            "budget_failure": True,
                        }
                    )
                # Persist after every fixture so a slow adapter cannot erase
                # completed measurements for earlier adapters or rows.
                current = next((item for item in profile_reports if item["adapter"] == adapter.name), None)
                if current is None:
                    current = {"adapter": adapter.name, "runtime_ms": 0.0, "fixtures": [], "positive_missing": [], "budget_failures": []}
                    profile_reports.append(current)
                current["fixtures"] = list(fixture_records)
                current["runtime_ms"] = round((time.perf_counter() - adapter_started) * 1000, 3)
                current["positive_missing"] = sorted(set(positive_missing))
                current["budget_failures"] = sorted(set(adapter_budget_failures))
                current["budget_seconds"] = budget_seconds
                write_profile_snapshot("running")
            current["runtime_ms"] = round((time.perf_counter() - adapter_started) * 1000, 3)
            write_profile_snapshot("running")
        profile_status = "profile_only" if not any(item.get("budget_failures") for item in profile_reports) else "profile_only_blocked_budget"
        write_profile_snapshot(profile_status)
        print(json.dumps({"status": profile_status, "adapters": [item["adapter"] for item in profile_reports]}, indent=2))
        return 0 if profile_status == "profile_only" else 2
    report = benchmark_offline_ensemble(
        fixtures,
        adapters,
        lock,
        root=args.corpus.parent,
        adapter_budgets_seconds=adapter_budgets,
    )
    holdout_path = args.corpus.parent / "recognizer-holdout.json"
    if holdout_path.exists():
        holdout_payload = json.loads(holdout_path.read_text(encoding="utf-8"))
        report["holdout"] = benchmark_offline_ensemble(
            tuple(holdout_payload.get("fixtures", [])),
            adapters,
            lock,
            root=holdout_path.parent,
        )
        report["holdout"]["manifest_sha256"] = sha256_file(holdout_path)
    report["environment_lock"] = lock.to_dict()
    report["capability_profiles"] = [profile.to_dict() for profile in profiles]
    report["source_corpus"] = str(args.corpus)
    report["source_corpus_sha256"] = sha256_file(args.corpus)
    report["network"] = {"required": False, "disabled_during_run": True}
    report["emoji_atlas"] = {
        "sequence_data": "pinned UTS #51 emoji-test.txt",
        "font": "pinned NotoColorEmoji.ttf",
        "max_sequences_for_run": max(1, args.emoji_max_sequences),
        "full_atlas_adapter_available": True,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "positive_missing": report["positive_missing"], "false_unique": report["false_unique_negative_fixtures"]}, indent=2))
    return 0 if report["status"] == "passed" and report.get("holdout", {}).get("status", "passed") == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
