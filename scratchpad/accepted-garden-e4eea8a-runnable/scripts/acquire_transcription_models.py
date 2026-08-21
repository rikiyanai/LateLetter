#!/usr/bin/env python3
"""Acquire and verify the project-local Slice 6 model cache.

The default operation is offline verification.  Downloading requires the
explicit ``--download`` flag and writes only under the supplied cache root.
Every byte is checked against the pinned SHA-256 before it becomes usable.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import urllib.request
from pathlib import Path


REPO = "https://raw.githubusercontent.com/tesseract-ocr/tessdata_best/main"
EMOJI_FONT_URL = "https://github.com/googlefonts/noto-emoji/raw/main/fonts/NotoColorEmoji.ttf"
EMOJI_DATA_URL = "https://unicode.org/Public/emoji/latest/emoji-test.txt"
ARTIFACTS = {
    "ara": ("ara.traineddata", "ab9d157d8e38ca00e7e39c7d5363a5239e053f5b0dbdb3167dde9d8124335896", 12603724),
    "chi_sim": ("chi_sim.traineddata", "4fef2d1306c8e87616d4d3e4c6c67faf5d44be3342290cf8f2f0f6e3aa7e735b", 13077423),
    "chi_tra": ("chi_tra.traineddata", "1aa60488574cafa69486d919284f079ca9b68fcc7f6ad8dc1ff1b318dfd97028", 12985735),
    "eng": ("eng.traineddata", "8280aed0782fe27257a68ea10fe7ef324ca0f8d85bd2fd145d1c2b560bcb66ba", 15400601),
    "jpn": ("jpn.traineddata", "36bdf9ac823f5911e624c30d0553e890b8abc7c31a65b3ef14da943658c40b79", 14330109),
    "jpn_vert": ("jpn_vert.traineddata", "1258be6eb2a9851f18043234ad18cca13ed32690bfff62b335c898bbea371548", 14330809),
    "osd": ("osd.traineddata", "9cf5d576fcc47564f11265841e5ca839001e7e6f38ff7f7aacf46d15a96b00ff", 10562727),
}

EMOJI_ARTIFACTS = {
    "noto_color_emoji": ("emoji/NotoColorEmoji.ttf", "72a635cb3d2f3524c51620cdde406b217204e8a6a06c6a096ff8ed4b5fd6e27b", 10673480, EMOJI_FONT_URL, "OFL-1.1"),
    "unicode_emoji_test_17": ("emoji/emoji-test.txt", "1d8a944f88d7952f7ef7c5167fef3c67995bcae24543949710231b03a201acda", 669326, EMOJI_DATA_URL, "Unicode-Terms-of-Use"),
}

def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(cache_root: Path) -> dict:
    target = cache_root / "tesseract_best"
    rows = []
    for artifact_id, (filename, expected, size) in ARTIFACTS.items():
        path = target / filename
        actual = digest(path) if path.exists() else None
        rows.append(
            {
                "artifact_id": artifact_id,
                "source_url": f"{REPO}/{filename}",
                "cache_path": f"tesseract_best/{filename}",
                "sha256": expected,
                "actual_sha256": actual,
                "license": "Apache-2.0",
                "size_bytes": size,
                "status": "verified" if actual == expected and path.stat().st_size == size else "missing_or_stale",
            }
        )
    for artifact_id, (relative, expected, size, source_url, license_name) in EMOJI_ARTIFACTS.items():
        path = cache_root / relative
        actual = digest(path) if path.exists() else None
        rows.append(
            {
                "artifact_id": artifact_id,
                "source_url": source_url,
                "cache_path": relative,
                "sha256": expected,
                "actual_sha256": actual,
                "license": license_name,
                "size_bytes": size,
                "status": "verified" if actual == expected and path.stat().st_size == size else "missing_or_stale",
            }
        )
    return {
        "schema_version": "lateletter-transcription-model-cache-1",
        "repository": "tesseract-ocr/tessdata_best",
        "repository_license": "Apache-2.0; emoji font OFL-1.1; Unicode data terms recorded per artifact",
        "offline_runtime": True,
        "artifacts": rows,
        "all_verified": bool(rows) and all(row["status"] == "verified" for row in rows),
    }


def download(cache_root: Path) -> None:
    target = cache_root / "tesseract_best"
    target.mkdir(parents=True, exist_ok=True)
    for filename, expected, _ in ARTIFACTS.values():
        path = target / filename
        with urllib.request.urlopen(f"{REPO}/{filename}", timeout=60) as response:
            payload = response.read()
        if hashlib.sha256(payload).hexdigest() != expected:
            raise SystemExit(f"hash mismatch while downloading {filename}")
        path.write_bytes(payload)
    for _, (relative, expected, _, source_url, _) in EMOJI_ARTIFACTS.items():
        path = cache_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(source_url, timeout=60) as response:
            payload = response.read()
        if hashlib.sha256(payload).hexdigest() != expected:
            raise SystemExit(f"hash mismatch while downloading {relative}")
        path.write_bytes(payload)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("cache_root", type=Path)
    parser.add_argument("--download", action="store_true", help="download missing bytes; otherwise verify offline")
    parser.add_argument("--manifest", type=Path, help="write the verification manifest here")
    args = parser.parse_args()
    if args.download:
        download(args.cache_root)
    report = verify(args.cache_root)
    output = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.manifest:
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        args.manifest.write_text(output, encoding="utf-8")
    print(output, end="")
    return 0 if report["all_verified"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
