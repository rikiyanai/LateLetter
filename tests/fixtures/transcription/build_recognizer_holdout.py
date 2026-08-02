"""Build the untouched Slice 6 holdout variations.

The holdout manifest is scored after proposals are produced.  Its expected TXT
is never included in the source mapping handed to an adapter.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageFilter


ROOT = Path(__file__).resolve().parent
FONT = Path("/Library/Fonts/DejaVuSansMono.ttf")
PROPORTIONAL = Path("/Library/Fonts/DejaVuSans.ttf")
if not FONT.exists():
    FONT = Path("/System/Library/Fonts/Menlo.ttc")
if not PROPORTIONAL.exists():
    PROPORTIONAL = FONT


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def render(item: dict) -> dict:
    text = item["text"]
    font_path = Path(item["font"])
    font = ImageFont.truetype(str(font_path), item["size_px"])
    rows = text.split("\n")
    probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    width = max(220, int(max(probe.textlength(row, font=font) for row in rows)) + 32)
    height = max(56, len(rows) * (item["size_px"] + 10) + 24)
    image = Image.new("RGB", (width, height), tuple(item["background"]))
    draw = ImageDraw.Draw(image)
    for row, value in enumerate(rows):
        draw.text((16, 12 + row * (item["size_px"] + 10)), value, font=font, fill=tuple(item["foreground"]))
    if item.get("rescale"):
        factor = item["rescale"]
        image = image.resize((int(width * factor), int(height * factor)), Image.Resampling.LANCZOS)
    if item.get("blur"):
        image = image.filter(ImageFilter.GaussianBlur(item["blur"]))
    folder = ROOT / "holdout" / item["id"]
    folder.mkdir(parents=True, exist_ok=True)
    source = folder / "source.png"
    image.save(source, format="PNG", optimize=False)
    transcript = folder / "transcript.txt"
    transcript.write_text(text + "\n", encoding="utf-8")
    item = {
        **item,
        "source_png": str(source.relative_to(ROOT)),
        "source_sha256": digest(source),
        "transcript": str(transcript.relative_to(ROOT)),
        "transcript_sha256": digest(transcript),
        "font_sha256": digest(font_path),
        "provenance": {"origin": "generated-in-repo", "license": "CC0 test fixture", "source": "build_recognizer_holdout.py"},
    }
    return item


def main() -> None:
    specs = [
        {"id": "holdout-fixed-small-light", "family": "fixed_ascii", "text": "/\\_ |\n(=)", "font": str(FONT), "size_px": 18, "foreground": [34, 37, 41], "background": [255, 255, 255], "rescale": 1.0},
        {"id": "holdout-fixed-large-dark", "family": "fixed_ascii", "text": "--__\\/\n|()|", "font": str(FONT), "size_px": 26, "foreground": [235, 235, 235], "background": [26, 28, 31], "rescale": 1.0},
        {"id": "holdout-fixed-gray-rescaled", "family": "fixed_ascii", "text": "  /\\\n--__", "font": str(FONT), "size_px": 22, "foreground": [80, 80, 80], "background": [220, 220, 220], "rescale": 0.75, "blur": 0.15},
        {"id": "holdout-latin-proportional", "family": "proportional_latin", "text": "Late Letter\nkindness", "font": str(PROPORTIONAL), "size_px": 24, "foreground": [34, 37, 41], "background": [255, 255, 255], "rescale": 1.0},
        {"id": "holdout-kana-latin", "family": "kana_latin", "text": "かな ABC", "font": str(PROPORTIONAL), "size_px": 24, "foreground": [34, 37, 41], "background": [255, 255, 255], "rescale": 1.0},
        {"id": "holdout-kanji-halfwidth", "family": "cjk_width", "text": "春 花 ｶﾅ", "font": str(PROPORTIONAL), "size_px": 24, "foreground": [34, 37, 41], "background": [255, 255, 255], "rescale": 1.0},
        {"id": "holdout-arabic-latin", "family": "arabic_latin", "text": "سلام A", "font": str(PROPORTIONAL), "size_px": 24, "foreground": [34, 37, 41], "background": [255, 255, 255], "rescale": 1.0},
        {"id": "holdout-combining", "family": "combining", "text": "café e\u0301", "font": str(PROPORTIONAL), "size_px": 24, "foreground": [34, 37, 41], "background": [245, 248, 250], "rescale": 1.0},
        {"id": "holdout-emoji-color", "family": "emoji_zwj", "text": "👩‍🌾 ❤️", "font": str(PROPORTIONAL), "size_px": 24, "foreground": [34, 37, 41], "background": [255, 255, 255], "rescale": 1.0},
        {"id": "holdout-mixed-rescaled", "family": "mixed_script", "text": "A漢 سلام", "font": str(PROPORTIONAL), "size_px": 22, "foreground": [34, 37, 41], "background": [255, 255, 255], "rescale": 1.5},
    ]
    fixtures = [render(item) for item in specs]
    (ROOT / "recognizer-holdout.json").write_text(
        json.dumps({"schema_version": "lateletter-transcription-holdout-1", "fixtures": fixtures}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
