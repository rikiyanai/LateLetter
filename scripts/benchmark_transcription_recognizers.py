#!/usr/bin/env python3
"""Run the Slice 6 proposal-coverage benchmark against the release corpus."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from lateletter.transcription import (
    EmojiAtlasAdapter,
    FixedLatticeStructuralAdapter,
    IndependentOfflineAdapter,
    PaddleOCROfflineAdapter,
    TesseractOfflineAdapter,
    benchmark_offline_ensemble,
    build_environment_lock,
)
from lateletter.transcription.hashing import sha256_file


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
    args = parser.parse_args()
    corpus = json.loads(args.corpus.read_text(encoding="utf-8"))
    fixtures = tuple(item for item in corpus["fixtures"] if item["split"] == "release_gate")
    model_paths = {path.stem: str(path) for path in (args.cache / "tesseract_best").glob("*.traineddata")}
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
        PaddleOCROfflineAdapter(),
        IndependentOfflineAdapter(backend="easyocr"),
        IndependentOfflineAdapter(backend="surya"),
        emoji_adapter,
    )
    profiles = tuple(adapter.capability_profile(preliminary) for adapter in adapters if hasattr(adapter, "capability_profile"))
    lock = build_environment_lock(
        model_paths=model_paths,
        script_packs=script_packs,
        preprocessing={"network": "disabled", "ground_truth_to_adapter": False},
        capability_profiles=profiles,
    )
    report = benchmark_offline_ensemble(fixtures, adapters, lock, root=args.corpus.parent)
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
