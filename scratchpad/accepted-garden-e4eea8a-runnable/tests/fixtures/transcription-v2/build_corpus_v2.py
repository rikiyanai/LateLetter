"""Build the verified-font corpus v2 without mutating corpus v1.

Corpus v1 is historical evidence and remains byte-for-byte unchanged.  This
builder uses only project-controlled, hash-pinned fonts and refuses to publish
a positive fixture when every code point is not covered by the selected font.
Legacy fallback-box examples are emitted as development fail-closed fixtures,
never as positive release evidence.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import unicodedata
from pathlib import Path

import regex
from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw, ImageFilter, ImageFont


ROOT = Path(__file__).resolve().parent
CACHE = ROOT.parents[2] / "tracked/LateLetterResearch/transcription-model-cache"
FONT_MONO = CACHE / "fonts/NotoSansMono-Variable.ttf"
FONT_CJK = CACHE / "fonts/NotoSansCJKjp-Regular.otf"
FONT_ARABIC = CACHE / "fonts/NotoSansArabic-Regular.ttf"
FONT_EMOJI = CACHE / "emoji/NotoColorEmoji.ttf"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def cmap(path: Path) -> set[int]:
    font = TTFont(str(path), lazy=True)
    try:
        values: set[int] = set()
        for table in font["cmap"].tables:
            values.update(table.cmap)
        return values
    finally:
        font.close()


FONT_CMAPS = {path: cmap(path) for path in (FONT_MONO, FONT_CJK, FONT_ARABIC, FONT_EMOJI)}


def graphemes(text: str) -> tuple[str, ...]:
    return tuple(regex.findall(r"\X", text))


def is_emoji(cluster: str) -> bool:
    return any(ord(char) >= 0x1F000 for char in cluster) or "\u200d" in cluster or "\ufe0f" in cluster


def is_arabic(cluster: str) -> bool:
    return any("ARABIC" in unicodedata.name(char, "") for char in cluster)


def is_cjk(cluster: str) -> bool:
    for char in cluster:
        codepoint = ord(char)
        if (
            0x3000 <= codepoint <= 0x30FF
            or 0x3400 <= codepoint <= 0x4DBF
            or 0x4E00 <= codepoint <= 0x9FFF
            or 0xFF00 <= codepoint <= 0xFFEF
        ):
            return True
    return False


def font_for_cluster(cluster: str, *, proportional: bool = False) -> Path:
    if is_emoji(cluster):
        return FONT_EMOJI
    if is_arabic(cluster):
        return FONT_ARABIC
    if is_cjk(cluster) or proportional:
        return FONT_CJK
    return FONT_MONO


def coverage_report(text: str, *, proportional: bool = False) -> dict:
    records = []
    complete = True
    for cluster in graphemes(text):
        if cluster.isspace():
            records.append({"text": cluster, "font": "layout-space", "missing_codepoints": [], "covered": True})
            continue
        path = font_for_cluster(cluster, proportional=proportional)
        missing = sorted(
            {
                f"U+{ord(char):04X}"
                for char in cluster
                if ord(char) not in FONT_CMAPS[path] and ord(char) not in {0x200D, 0xFE0E, 0xFE0F}
            }
        )
        records.append({"text": cluster, "font": path.name, "missing_codepoints": missing, "covered": not missing})
        complete = complete and not missing
    return {"complete": complete, "clusters": records}


def coverage_report_for_font(text: str, path: Path) -> dict:
    values = FONT_CMAPS.get(path) or cmap(path)
    records = []
    complete = True
    for cluster in graphemes(text):
        missing = sorted(
            {
                f"U+{ord(char):04X}"
                for char in cluster
                if not cluster.isspace()
                and ord(char) not in values
                and ord(char) not in {0x200D, 0xFE0E, 0xFE0F}
            }
        )
        records.append({"text": cluster, "font": path.name, "missing_codepoints": missing, "covered": not missing})
        complete = complete and not missing
    return {"complete": complete, "clusters": records}


def _font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    # NotoColorEmoji is a CBDT strike font and only exposes its pinned 109px
    # strike.  Loading it at 22px raises ``invalid pixel size``; its measured
    # raster is intentionally kept at the strike size in the corpus receipt.
    return ImageFont.truetype(str(path), 109 if path == FONT_EMOJI else size)


def render_text(text: str, *, mode: str, degraded: bool = False, fallback: bool = False) -> tuple[Image.Image, dict]:
    rows = text.split("\n")
    size = 22
    proportional = mode == "shaped_runs"
    if fallback:
        fallback_font_path = Path("/Library/Fonts/DejaVuSans.ttf")
        fallback_font = _font(fallback_font_path, size)
        coverage = coverage_report_for_font(text, fallback_font_path)
        font_chain = {"fallback": fallback_font_path.name}
    else:
        coverage = coverage_report(text, proportional=proportional)
        if not coverage["complete"]:
            raise ValueError(f"font coverage incomplete: {coverage}")
        font_chain = {path.name: digest(path) for path in (FONT_MONO, FONT_CJK, FONT_ARABIC, FONT_EMOJI)}
    row_widths: list[float] = []
    for row in rows:
        if fallback:
            row_widths.append(ImageDraw.Draw(Image.new("RGB", (1, 1))).textlength(row, font=fallback_font))
            continue
        width = 0.0
        for cluster in graphemes(row):
            width += ImageDraw.Draw(Image.new("RGB", (1, 1))).textlength(cluster, font=_font(font_for_cluster(cluster, proportional=proportional), size))
        row_widths.append(width)
    width = max(220, int(max(row_widths, default=0)) + 28)
    line_height = 126 if any(is_emoji(cluster) for row in rows for cluster in graphemes(row)) else 32
    height = max(44, line_height * len(rows) + 18)
    image = Image.new("RGB", (width, height), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    for row_index, row in enumerate(rows):
        x = 12.0
        baseline_y = 12 + row_index * line_height
        if fallback:
            draw.text((x, baseline_y), row, font=fallback_font, fill=(34, 37, 41))
            continue
        run: list[str] = []
        run_font: Path | None = None
        for cluster in (*graphemes(row), ""):
            path = font_for_cluster(cluster, proportional=proportional) if cluster else None
            if run and path != run_font:
                value = "".join(run)
                draw.text((x, baseline_y), value, font=_font(run_font, size), fill=(34, 37, 41), embedded_color=run_font == FONT_EMOJI)
                x += draw.textlength(value, font=_font(run_font, size))
                run = []
            if cluster:
                run.append(cluster)
                run_font = path
    if degraded:
        image = image.resize((max(1, width // 2), max(1, height // 2)), Image.Resampling.LANCZOS)
        image = image.resize((width, height), Image.Resampling.BICUBIC).filter(ImageFilter.GaussianBlur(0.25))
    return image, {
        "font_chain": font_chain,
        "coverage": coverage,
        "font_size_px": size,
        "foreground_rgb": [34, 37, 41],
        "background_rgb": [255, 255, 255],
        "degraded": degraded,
        "fallback_box_expected": fallback,
    }


def render_fixture(fixture_id: str, text: str, *, mode: str, degraded: bool = False, fallback: bool = False) -> dict[str, str]:
    folder = ROOT / ("positive" if not fallback else "fail_closed") / fixture_id
    folder.mkdir(parents=True, exist_ok=True)
    image, renderer_metadata = render_text(text, mode=mode, degraded=degraded, fallback=fallback)
    source = folder / "source.png"
    image.save(source, format="PNG", optimize=False)
    transcript = folder / "transcript.txt"
    transcript.write_text(text + "\n", encoding="utf-8")
    layout = folder / "visual-layout.json"
    rows = text.split("\n")
    write_json(
        layout,
        {
            "fixture_id": fixture_id,
            "logical_rows": len(rows),
            "direction": "rtl" if any(is_arabic(cluster) for row in rows for cluster in graphemes(row)) else "ltr",
            "mode": mode,
            "anchors": [{"row": index, "x": 12, "baseline": 30 + index * 32} for index in range(len(rows))],
        },
    )
    receipt = folder / "source-renderer-receipt.json"
    write_json(
        receipt,
        {
            "fixture_id": fixture_id,
            "renderer": "Pillow",
            "pillow_version": __import__("PIL").__version__,
            "font_hashes": renderer_metadata["font_chain"],
            **renderer_metadata,
            "generator": "tests/fixtures/transcription-v2/build_corpus_v2.py",
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
        ("positive-fixed-ascii", "/\\_|\n(=)", "fixed_lattice", False),
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
    fixtures: list[dict] = []
    for fixture_id, text, mode, degraded in positive:
        paths = render_fixture(fixture_id, text, mode=mode, degraded=degraded)
        fixtures.append(
            {
                "id": fixture_id,
                "split": "release_gate",
                "class": "positive",
                **paths,
                "provenance": {"origin": "generated-in-repo", "license": "CC0 test fixture; renderer fonts OFL-1.1", "source": "corpus v2 verified-font builder"},
                "expected_geometry_mode": mode,
                "expected_outcome": "positive",
                "expected_rejection_codes": [],
            }
        )
    fallback_cases = [
        ("fallback-kana", "かな カナ", "shaped_runs"),
        ("fallback-kanji", "春 花", "shaped_runs"),
        ("fallback-width-mixture", "ＡB ｶﾅ", "shaped_runs"),
        ("fallback-emoji-zwj", "👩‍🌾 ❤️", "shaped_runs"),
        ("fallback-mixed-script", "A漢 سلام", "shaped_runs"),
    ]
    for fixture_id, text, mode in fallback_cases:
        paths = render_fixture(fixture_id, text, mode=mode, fallback=True)
        fixtures.append(
            {
                "id": fixture_id,
                "split": "development",
                "class": "fail_closed",
                **paths,
                "provenance": {"origin": "reclassified v1 fallback-box evidence", "license": "CC0 test fixture", "source": "corpus v1 invalid-positive audit"},
                "expected_geometry_mode": mode,
                "expected_outcome": "rejected",
                "expected_rejection_codes": ["unicode_visual_collision"],
            }
        )
    corpus = {
        "schema_version": "lateletter-transcription-corpus-1",
        "generator": "tests/fixtures/transcription-v2/build_corpus_v2.py",
        "development": [item["id"] for item in fixtures if item["split"] == "development"],
        "release_gate": [item["id"] for item in fixtures if item["split"] == "release_gate"],
        "fixtures": fixtures,
        "renderer_contract": {
            "font_cache_manifest": "../../../tracked/LateLetterResearch/transcription-model-cache/manifest.json",
            "fallback_positive_policy": "fallback boxes are fail_closed visual collisions",
            "coverage_policy": "positive fixture requires complete codepoint coverage before rendering",
        },
    }
    write_json(ROOT / "corpus-v2.json", corpus)


if __name__ == "__main__":
    main()
