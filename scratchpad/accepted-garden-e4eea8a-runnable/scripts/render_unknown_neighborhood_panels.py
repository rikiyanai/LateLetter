#!/usr/bin/env python3
"""Render labeled 3×3 source-cell panels around unresolved OCR cells.

This is review evidence only.  It reads an immutable attempt's recognition records and
calibration, paints each source cell separately, and highlights the unresolved center cell so
row/column spill ownership can be inspected without editing the attempt.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("attempt", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    source = args.source.resolve()
    attempt = args.attempt.resolve()
    output = args.output.resolve()
    manifest = json.loads((attempt / "manifest.json").read_text(encoding="utf-8"))
    calibration_path = (attempt / manifest["calibration"]["path"]).resolve()
    calibration = json.loads(calibration_path.read_text(encoding="utf-8"))
    evidence_name = manifest.get("artifacts", {}).get("cell_recognition_json", "cell-recognition.json")
    evidence_path = attempt / evidence_name
    if not evidence_path.exists() and (attempt / "row-decoding.json").exists():
        evidence_path = attempt / "row-decoding.json"
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    records = evidence.get("cells", evidence) if isinstance(evidence, dict) else evidence
    unknowns = [item for item in records if item.get("glyph") == "?"]
    if not unknowns:
        raise SystemExit("attempt has no unknown cells; no neighborhood review is needed")
    if output.exists():
        raise SystemExit(f"refusing to overwrite review directory: {output}")
    output.mkdir(parents=True)

    grid = calibration["grid"]
    columns, rows = int(grid["columns"]), int(grid["rows"])
    origin_x = float(grid["origin_x_px"])
    first_baseline = float(grid["first_baseline_y_px"])
    advance_x = float(grid["cell_advance_x_px"])
    advance_y = float(grid["line_height_px"])
    crop_top = float(grid["cell_crop_top_offset_px"])
    crop_bottom = float(grid["cell_crop_bottom_offset_px"])
    with Image.open(source) as opened:
        source_image = opened.convert("RGBA")
    label_font = ImageFont.load_default()
    tile_width, tile_height, scale = 122, 122, 5
    panel_gap, panel_header = 10, 30
    panel_width, panel_height = tile_width * 3, panel_header + tile_height * 3
    canvas = Image.new("RGBA", (panel_width, panel_height * len(unknowns) + panel_gap * (len(unknowns) - 1)), (238, 238, 238, 255))
    draw = ImageDraw.Draw(canvas)

    def box(row: int, column: int) -> tuple[int, int, int, int]:
        x0 = round(origin_x + column * advance_x)
        x1 = round(origin_x + (column + 1) * advance_x)
        baseline = first_baseline + row * advance_y
        y0, y1 = round(baseline + crop_top), round(baseline + crop_bottom)
        return max(0, x0), max(0, y0), min(source_image.width, x1), min(source_image.height, y1)

    for panel_index, center in enumerate(unknowns):
        row, column = int(center["row"]), int(center["column"])
        panel_y = panel_index * (panel_height + panel_gap)
        draw.text(
            (4, panel_y + 5),
            f"unknown center r{row:02d} c{column:02d} = '?'  |  3×3 calibrated neighbors",
            fill=(0, 0, 0, 255),
            font=label_font,
        )
        for panel_row, source_row in enumerate(range(max(0, row - 1), min(rows, row + 2))):
            for panel_column, source_column in enumerate(range(max(0, column - 1), min(columns, column + 2))):
                tile_x = panel_column * tile_width
                tile_y = panel_y + panel_header + panel_row * tile_height
                is_center = source_row == row and source_column == column
                draw.rectangle(
                    (tile_x, tile_y, tile_x + tile_width - 1, tile_y + tile_height - 1),
                    fill=(255, 248, 226, 255) if is_center else (255, 255, 255, 255),
                    outline=(190, 35, 35, 255) if is_center else (150, 150, 150, 255),
                    width=3 if is_center else 1,
                )
                x0, y0, x1, y1 = box(source_row, source_column)
                crop = source_image.crop((x0, y0, max(x0 + 1, x1), max(y0 + 1, y1)))
                crop = crop.resize((crop.width * scale, crop.height * scale), Image.Resampling.NEAREST)
                crop.thumbnail((tile_width - 10, tile_height - 34), Image.Resampling.NEAREST)
                canvas.alpha_composite(crop, (tile_x + (tile_width - crop.width) // 2, tile_y + 25 + (tile_height - 34 - crop.height) // 2))
                neighbor = next((item for item in records if item.get("row") == source_row and item.get("column") == source_column), None)
                glyph = neighbor.get("glyph", " ") if neighbor else " "
                shown = "blank" if glyph == " " else repr(glyph)
                draw.text((tile_x + 4, tile_y + 5), f"r{source_row:02d} c{source_column:02d} {shown}", fill=(0, 0, 0, 255), font=label_font)

    png_path = output / "unknown-neighborhoods.png"
    canvas.save(png_path)
    receipt = {
        "format": "lateletter-unknown-neighborhood-review-v1",
        "source": os.path.relpath(source, output),
        "source_sha256": sha256(source),
        "attempt": os.path.relpath(attempt, output),
        "attempt_manifest_sha256": sha256(attempt / "manifest.json"),
        "evidence": os.path.relpath(evidence_path, output),
        "evidence_sha256": sha256(evidence_path),
        "calibration_sha256": sha256(calibration_path),
        "unknown_centers": [{"row": int(item["row"]), "column": int(item["column"])} for item in unknowns],
        "panel_shape": "3x3",
        "artifact": png_path.name,
        "review_only": True,
        "note": "Panels expose neighboring cell ownership; they do not resolve or edit unknown glyphs.",
    }
    (output / "review.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"unknowns": len(unknowns), "artifact": str(png_path)}))


if __name__ == "__main__":
    main()
