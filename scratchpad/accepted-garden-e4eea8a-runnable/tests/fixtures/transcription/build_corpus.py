"""Generate the small, tracked raster corpus used by the IR validator.

The fixtures are intentionally generated from pinned local fonts and retain a
renderer receipt.  This script is a corpus builder, not a recognizer and never
changes an attempt or accepted transcript.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont


ROOT = Path(__file__).resolve().parent
FONT = Path("/Library/Fonts/DejaVuSansMono.ttf")
PROPORTIONAL_FONT = Path("/Library/Fonts/DejaVuSans.ttf")
if not PROPORTIONAL_FONT.exists():
    PROPORTIONAL_FONT = FONT


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def render_fixture(fixture_id: str, text: str, *, mode: str, degraded: bool = False) -> dict[str, str]:
    folder = ROOT / ("positive" if fixture_id.startswith("positive-") else "fail_closed" if fixture_id.startswith("negative-") else "mutations") / fixture_id
    folder.mkdir(parents=True, exist_ok=True)
    font_path = FONT if mode == "fixed_lattice" else PROPORTIONAL_FONT
    font = ImageFont.truetype(str(font_path), 22)
    rows = text.split("\n")
    widths = [ImageDraw.Draw(Image.new("RGB", (1, 1))).textlength(row, font=font) for row in rows]
    width = max(180, int(max(widths, default=0)) + 28)
    height = max(44, 30 * len(rows) + 18)
    image = Image.new("RGB", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    for row, value in enumerate(rows):
        draw.text((12, 12 + row * 30), value, font=font, fill=(34, 37, 41))
    if degraded:
        image = image.resize((max(1, width // 2), max(1, height // 2)), Image.Resampling.LANCZOS)
        image = image.resize((width, height), Image.Resampling.BICUBIC).filter(ImageFilter.GaussianBlur(0.25))
    source = folder / "source.png"
    image.save(source, format="PNG", optimize=False)
    transcript = folder / "transcript.txt"
    transcript.write_text(text + "\n", encoding="utf-8")
    layout = folder / "visual-layout.json"
    write_json(
        layout,
        {
            "fixture_id": fixture_id,
            "logical_rows": len(rows),
            "direction": "rtl" if any("سلام" in row for row in rows) else "ltr",
            "mode": mode,
            "anchors": [{"row": index, "x": 12, "baseline": 29 + index * 30} for index in range(len(rows))],
        },
    )
    receipt = folder / "source-renderer-receipt.json"
    write_json(
        receipt,
        {
            "fixture_id": fixture_id,
            "renderer": "Pillow",
            "pillow_version": __import__("PIL").__version__,
            "font_path": str(font_path),
            "font_sha256": digest(font_path),
            "font_size_px": 22,
            "foreground_rgb": [34, 37, 41],
            "background_rgb": [255, 255, 255],
            "degraded": degraded,
            "generator": "tests/fixtures/transcription/build_corpus.py",
        },
    )
    return {
        "source_png": str(source.relative_to(ROOT)),
        "source_sha256": digest(source),
        "transcript": str(transcript.relative_to(ROOT)),
        "transcript_sha256": digest(transcript),
        "visual_layout": str(layout.relative_to(ROOT)),
        "visual_layout_sha256": digest(layout),
        "source_renderer_receipt": str(receipt.relative_to(ROOT)),
        "source_renderer_receipt_sha256": digest(receipt),
    }


def main() -> None:
    positive = [
        ("positive-fixed-ascii", "/\\_|\n(=)\n", "fixed_lattice", False),
        ("positive-proportional-latin", "Late letter\nkindness", "shaped_runs", False),
        ("positive-kana", "かな カナ", "shaped_runs", False),
        ("positive-kanji", "春 花", "shaped_runs", False),
        ("positive-arabic", "سلام", "shaped_runs", False),
        ("positive-combining", "café e\u0301", "shaped_runs", False),
        ("positive-width-mixture", "ＡB ｶﾅ", "shaped_runs", False),
        ("positive-emoji-zwj", "👩‍🌾 ❤️", "shaped_runs", False),
        ("positive-mixed-script", "A漢 سلام", "shaped_runs", False),
        ("positive-degraded-fixed", "  /\\\n--__", "fixed_lattice", True),
    ]
    negative = [
        ("negative-uncertain-pitch", "--  --", "unresolved", "geometry_unresolved"),
        ("negative-ambiguous-width", "·", "shaped_runs", "width_profile_missing"),
        ("negative-partial-kanji", "木", "shaped_runs", "component_unowned"),
        ("negative-disconnected-combining", "e\u0301", "shaped_runs", "component_unowned"),
        ("negative-visual-collision", "é e\u0301", "shaped_runs", "unicode_visual_collision"),
        ("negative-bidi-control", "A\u202eB", "shaped_runs", "logical_visual_contradiction"),
        ("negative-unknown-font", "سلام", "shaped_runs", "shaping_profile_missing"),
        ("negative-ui-contamination", "MENU  /\\", "fixed_lattice", "source_contamination"),
        ("negative-cross-row-spill", "|\n/", "fixed_lattice", "component_multiply_owned"),
        ("negative-joined-boundary", "漢字", "shaped_runs", "component_multiply_owned"),
    ]
    fixtures: list[dict] = []
    for fixture_id, text, mode, degraded in positive:
        paths = render_fixture(fixture_id, text, mode=mode, degraded=degraded)
        fixtures.append(
            {
                "id": fixture_id,
                "split": "release_gate",
                "class": "positive",
                **paths,
                "provenance": {"origin": "generated-in-repo", "license": "CC0 test fixture", "source": "LateLetter corpus builder"},
                "expected_geometry_mode": mode,
                "expected_outcome": "positive",
                "expected_rejection_codes": [],
            }
        )
    for fixture_id, text, mode, rejection in negative:
        paths = render_fixture(fixture_id, text, mode=mode)
        fixtures.append(
            {
                "id": fixture_id,
                "split": "development",
                "class": "fail_closed",
                **paths,
                "provenance": {"origin": "generated-in-repo", "license": "CC0 test fixture", "source": "LateLetter corpus builder"},
                "expected_geometry_mode": mode,
                "expected_outcome": "rejected",
                "expected_rejection_codes": [rejection],
            }
        )
    mutation_specs = [
        ("mutation-fixed-crop", "positive-fixed-ascii", "fixed_lattice", "geometry_unresolved"),
        ("mutation-rescaled-kana", "positive-kana", "shaped_runs", "geometry_unresolved"),
        ("mutation-ui-overlay", "positive-mixed-script", "unresolved", "source_contamination"),
    ]
    for fixture_id, parent, mode, rejection in mutation_specs:
        paths = render_fixture(fixture_id, "MUTATION", mode=mode, degraded=True)
        fixtures.append(
            {
                "id": fixture_id,
                "split": "development",
                "class": "mutation",
                "parent_fixture_id": parent,
                "mutation": "deterministic synthetic mutation",
                **paths,
                "provenance": {"origin": "generated-in-repo", "license": "CC0 test fixture", "source": "LateLetter corpus builder"},
                "expected_geometry_mode": mode,
                "expected_outcome": "rejected",
                "expected_rejection_codes": [rejection],
            }
        )
    corpus = {
        "schema_version": "lateletter-transcription-corpus-1",
        "generator": "tests/fixtures/transcription/build_corpus.py",
        "development": [item["id"] for item in fixtures if item["split"] == "development"],
        "release_gate": [item["id"] for item in fixtures if item["split"] == "release_gate"],
        "fixtures": fixtures,
    }
    write_json(ROOT / "corpus.json", corpus)


if __name__ == "__main__":
    main()
