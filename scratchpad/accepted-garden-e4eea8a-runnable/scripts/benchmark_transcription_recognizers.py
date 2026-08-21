#!/usr/bin/env python3
"""Run the Slice 6 proposal-coverage benchmark against the release corpus."""

from __future__ import annotations

import argparse
import cProfile
import json
import os
import pstats
import resource
import signal
import subprocess
import sys
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


COST_ATTRIBUTION_PAIRS = (
    {
        "owner": "tesseract-degraded",
        "adapter": "tesseract-offline",
        "fixture": "positive-degraded-fixed",
        "control_fixture": "positive-fixed-ascii",
        "budget_seconds": 12.0,
    },
    {
        "owner": "structural-degraded",
        "adapter": "structural-unicode-row",
        "fixture": "positive-degraded-fixed",
        "control_fixture": "positive-fixed-ascii",
        "budget_seconds": 90.0,
    },
    {
        "owner": "structural-emoji-shaped",
        "adapter": "structural-unicode-row",
        "fixture": "positive-emoji-zwj",
        "control_fixture": "positive-kana",
        "budget_seconds": 90.0,
    },
    {
        "owner": "emoji-atlas-zwj",
        "adapter": "emoji-grapheme-atlas",
        "fixture": "positive-emoji-zwj",
        "control_fixture": "positive-kana",
        "budget_seconds": 30.0,
    },
)


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


def _stage_bucket(filename: str, function: str) -> str:
    lower_file = filename.lower()
    lower_func = function.lower()
    if "/geometry/" in lower_file or lower_func in {
        "route_raster_geometry",
        "build_recognition_inputs",
        "build_recognition_hypothesis_inputs",
    }:
        return "geometry"
    if "subprocess.py" in lower_file or "popen" in lower_func or "communicate" in lower_func:
        return "tesseract_subprocess"
    if "emoji" in lower_func or "atlas" in lower_func or "_rgba_residual" in lower_func:
        return "emoji_atlas"
    if (
        "topology" in lower_func
        or "variant" in lower_func
        or "structuralunicode" in lower_func
        or lower_func
        in {
            "_run_level_variants",
            "_unicode_run_sequences",
            "_advance_options",
            "_candidate_units",
            "_next_substantive_unit",
            "_structural_template",
        }
    ):
        return "structural_span_lattice"
    if "residual" in lower_func or "raster" in lower_func or "mask" in lower_func or "resize" in lower_func:
        return "raster_comparison"
    if lower_func in {"_coverage_rank_matrix", "_proposal_texts", "_compose_run_texts"}:
        return "coverage_matrix"
    if "benchmark_transcription_recognizers.py" in lower_file or lower_func == "benchmark_offline_ensemble":
        return "benchmark_harness"
    return "other_python"


def _profile_stage_table(profiler: cProfile.Profile) -> list[dict[str, object]]:
    stats = pstats.Stats(profiler)
    buckets: dict[str, dict[str, float | int]] = {}
    for (filename, _line, function), values in stats.stats.items():
        primitive_calls, total_calls, total_time, cumulative_time, _callers = values
        bucket = buckets.setdefault(
            _stage_bucket(filename, function),
            {"primitive_calls": 0, "total_calls": 0, "total_time_ms": 0.0, "cumulative_time_ms": 0.0},
        )
        bucket["primitive_calls"] = int(bucket["primitive_calls"]) + int(primitive_calls)
        bucket["total_calls"] = int(bucket["total_calls"]) + int(total_calls)
        bucket["total_time_ms"] = float(bucket["total_time_ms"]) + float(total_time) * 1000.0
        bucket["cumulative_time_ms"] = float(bucket["cumulative_time_ms"]) + float(cumulative_time) * 1000.0
    return [
        {
            "owner": owner,
            "primitive_calls": int(values["primitive_calls"]),
            "total_calls": int(values["total_calls"]),
            "total_time_ms": round(float(values["total_time_ms"]), 3),
            "cumulative_time_ms": round(float(values["cumulative_time_ms"]), 3),
        }
        for owner, values in sorted(
            buckets.items(),
            key=lambda item: (-float(item[1]["cumulative_time_ms"]), item[0]),
        )
    ]


def _profile_top_functions(profiler: cProfile.Profile, *, limit: int = 30) -> list[dict[str, object]]:
    stats = pstats.Stats(profiler)
    rows = []
    for (filename, line, function), values in stats.stats.items():
        primitive_calls, total_calls, total_time, cumulative_time, _callers = values
        rows.append(
            {
                "file": filename,
                "line": int(line),
                "function": function,
                "owner": _stage_bucket(filename, function),
                "primitive_calls": int(primitive_calls),
                "total_calls": int(total_calls),
                "self_time_ms": round(float(total_time) * 1000.0, 3),
                "cumulative_time_ms": round(float(cumulative_time) * 1000.0, 3),
            }
        )
    rows.sort(key=lambda item: (-float(item["self_time_ms"]), -float(item["cumulative_time_ms"]), str(item["function"])))
    return rows[: max(1, int(limit))]


def _dominant_self_time_owner(stage_costs: object) -> str:
    if not isinstance(stage_costs, list) or not stage_costs:
        return "unknown"
    ranked = sorted(
        (item for item in stage_costs if isinstance(item, dict)),
        key=lambda item: (-float(item.get("total_time_ms", 0.0)), str(item.get("owner", ""))),
    )
    return str(ranked[0].get("owner", "unknown")) if ranked else "unknown"


def _select_adapter(adapters: tuple[object, ...], name: str):
    for adapter in adapters:
        if getattr(adapter, "name", "") == name:
            return adapter
    raise ValueError(f"unknown adapter for cost attribution: {name}")


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _compact_profile_adapter(record: dict[str, object]) -> dict[str, object]:
    """Persist profile counters without embedding full proposal payloads."""

    return {
        "adapter": record.get("adapter"),
        "version": record.get("version"),
        "status": record.get("status"),
        "runtime_ms": record.get("runtime_ms"),
        "budget_seconds": record.get("budget_seconds"),
        "budget_exceeded": record.get("budget_exceeded"),
        "deterministic": record.get("deterministic"),
        "determinism_replay_performed": record.get("determinism_replay_performed"),
        "run_count": record.get("run_count"),
        "proposal_hypothesis_count": record.get("proposal_hypothesis_count", 0),
        "retained_proposal_state_count": record.get("retained_proposal_state_count"),
        "top_k_count": len(record.get("top_k_logical_sequences", ()) or ()),
        "run_span_count": len(record.get("run_spans", ()) or ()),
        "run_input_hash_count": len(record.get("run_input_hashes", ()) or ()),
        "memory_max_rss": record.get("memory_max_rss"),
        "unsupported_status": record.get("unsupported_status", []),
        "geometry_status": record.get("geometry_status"),
        "geometry_rejection_codes": record.get("geometry_rejection_codes", []),
        "recognition_input_hash": record.get("recognition_input_hash"),
        "error": record.get("error"),
    }


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
    parser.add_argument(
        "--cost-attribution",
        action="store_true",
        help="diagnostic A1 mode: profile only the four blocked adapter/fixture pairs and controls",
    )
    parser.add_argument("--cost-worker-adapter", help=argparse.SUPPRESS)
    parser.add_argument("--cost-worker-fixture", help=argparse.SUPPRESS)
    parser.add_argument("--cost-worker-budget", type=float, help=argparse.SUPPRESS)
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
    if args.cost_worker_adapter and args.cost_worker_fixture:
        fixture_by_id = {str(item.get("id", "")): item for item in fixtures}
        fixture = fixture_by_id.get(args.cost_worker_fixture)
        if fixture is None:
            raise SystemExit(f"unknown fixture for cost attribution: {args.cost_worker_fixture}")
        adapter = _select_adapter(adapters, args.cost_worker_adapter)
        budget_seconds = float(args.cost_worker_budget or adapter_budgets.get(adapter.name, 30.0))
        profiler = cProfile.Profile()
        started = time.perf_counter()
        status = "completed"
        report: dict[str, object] | None = None
        error: str | None = None
        profiler.enable()
        try:
            report, _elapsed_ms = _run_with_budget(
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
        except _AdapterBudgetExceeded as exc:
            status = "rejected_budget_exceeded"
            error = str(exc)
        except Exception as exc:  # diagnostic worker must fail closed
            status = "rejected_worker_exception"
            error = f"{type(exc).__name__}: {exc}"
        finally:
            profiler.disable()
        elapsed_ms = round((time.perf_counter() - started) * 1000.0, 3)
        adapter_record: dict[str, object] = {}
        if report and report.get("results"):
            result = report["results"][0]  # type: ignore[index]
            records = result.get("adapters", ()) if isinstance(result, dict) else ()
            if records:
                adapter_record = dict(records[0])
        payload = {
            "status": status,
            "authority": "diagnostic_only",
            "fixture": args.cost_worker_fixture,
            "adapter": args.cost_worker_adapter,
            "budget_seconds": budget_seconds,
            "runtime_ms": elapsed_ms,
            "rss_max_platform_units": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            "rss_unit_note": "resource.getrusage ru_maxrss; bytes on macOS, kilobytes on Linux",
            "stage_costs": _profile_stage_table(profiler),
            "top_functions_by_self_time": _profile_top_functions(profiler),
            "adapter_counters": {
                "run_count": adapter_record.get("run_count", 0),
                "proposal_hypothesis_count": adapter_record.get("proposal_hypothesis_count", 0),
                "retained_proposal_state_count": adapter_record.get("retained_proposal_state_count", 0),
                "budget_exceeded": adapter_record.get("budget_exceeded", status == "rejected_budget_exceeded"),
                "memory_max_rss": adapter_record.get("memory_max_rss"),
                "unsupported_status": adapter_record.get("unsupported_status", []),
            },
            "benchmark_status": report.get("status") if report else None,
            "error": error,
            "ground_truth_passed_to_adapters": False,
            "source_corpus_sha256": sha256_file(args.corpus),
            "environment_lock_hash": lock.output_hash,
        }
        _write_json(args.output, payload)
        print(json.dumps({"status": status, "adapter": args.cost_worker_adapter, "fixture": args.cost_worker_fixture}, indent=2))
        return 0 if status == "completed" else 2
    if args.cost_attribution:
        records = []
        output_root = args.output.parent / f"{args.output.stem}-workers"
        for pair in COST_ATTRIBUTION_PAIRS:
            for role, fixture_id in (("blocked", pair["fixture"]), ("control", pair["control_fixture"])):
                worker_output = output_root / f"{pair['owner']}-{role}.json"
                command = [
                    sys.executable,
                    str(Path(__file__).resolve()),
                    str(args.corpus),
                    str(args.cache),
                    str(worker_output),
                    "--emoji-max-sequences",
                    str(max(1, args.emoji_max_sequences)),
                    "--cost-worker-adapter",
                    str(pair["adapter"]),
                    "--cost-worker-fixture",
                    str(fixture_id),
                    "--cost-worker-budget",
                    str(float(pair["budget_seconds"])),
                ]
                env = dict(os.environ)
                src_path = str(Path("src").resolve())
                env["PYTHONPATH"] = src_path + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
                started = time.perf_counter()
                completed = subprocess.run(command, text=True, capture_output=True, env=env, check=False)
                elapsed_ms = round((time.perf_counter() - started) * 1000.0, 3)
                if worker_output.exists():
                    worker_payload = json.loads(worker_output.read_text(encoding="utf-8"))
                else:
                    worker_payload = {
                        "status": "rejected_worker_no_output",
                        "adapter": pair["adapter"],
                        "fixture": fixture_id,
                        "runtime_ms": elapsed_ms,
                        "stage_costs": [],
                        "top_functions_by_self_time": [],
                        "adapter_counters": {},
                        "error": completed.stderr.strip() or completed.stdout.strip(),
                    }
                worker_payload["role"] = role
                worker_payload["owner"] = pair["owner"]
                worker_payload["worker_returncode"] = completed.returncode
                records.append(worker_payload)
        summary_by_owner: dict[str, dict[str, object]] = {}
        for record in records:
            owner = str(record["owner"])
            stage_costs = record.get("stage_costs", [])
            top_stage = _dominant_self_time_owner(stage_costs)
            current = summary_by_owner.setdefault(
                owner,
                {
                    "adapter": record["adapter"],
                    "blocked_fixture": None,
                    "control_fixture": None,
                    "dominant_stage": top_stage,
                    "recommended_time_budget_seconds": 0.0,
                    "recommended_rss_budget_platform_units": 0,
                },
            )
            if record.get("role") == "blocked":
                current["blocked_fixture"] = record.get("fixture")
            if record.get("role") == "control":
                current["control_fixture"] = record.get("fixture")
            runtime_seconds = float(record.get("runtime_ms", 0.0)) / 1000.0
            current["recommended_time_budget_seconds"] = max(
                float(current["recommended_time_budget_seconds"]),
                round(max(runtime_seconds * 1.25, float(record.get("budget_seconds", 0.0) or 0.0)), 3),
            )
            current["recommended_rss_budget_platform_units"] = max(
                int(current["recommended_rss_budget_platform_units"]),
                int(record.get("rss_max_platform_units", 0) or 0),
            )
        payload = {
            "status": "cost_attribution_complete",
            "authority": "diagnostic_only",
            "source_corpus": str(args.corpus),
            "source_corpus_sha256": sha256_file(args.corpus),
            "environment_lock": lock.to_dict(),
            "ground_truth_passed_to_adapters": False,
            "pairs": records,
            "cost_owner_table": list(summary_by_owner.values()),
            "worker_directory": str(output_root),
        }
        _write_json(args.output, payload)
        print(json.dumps({"status": payload["status"], "records": len(records)}, indent=2))
        return 0
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
                    fixture_records.append(
                        {
                            "fixture": result["fixture"],
                            "adapters": [_compact_profile_adapter(dict(item)) for item in result["adapters"]],
                        }
                    )
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
