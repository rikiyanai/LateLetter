#!/usr/bin/env python3
"""Render a review-only source-cell contact sheet for one immutable OCR attempt.

The sheet displays the source pixels in every calibration cell together with the emitted
machine character and its row/column identity.  It never edits the transcript, rerenders a
candidate, or uses the candidate renderer.  A second sheet contains only nonblank emitted
cells so character identity can be inspected without a wall of empty cells.
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
    args = parser.parse_args()

    source = args.source.resolve()
    attempt = args.attempt.resolve()
    manifest_path = attempt / "manifest.json"
    calibration_path = (attempt / json.loads(manifest_path.read_text(encoding="utf-8"))["calibration"]["path"]).resolve()
    transcript_path = attempt / json.loads(manifest_path.read_text(encoding="utf-8"))["transcript"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    calibration = json.loads(calibration_path.read_text(encoding="utf-8"))
    if sha256(source) != manifest["source_sha256"]:
        raise SystemExit("source hash differs from attempt manifest")
    if sha256(calibration_path) != manifest["calibration"]["sha256"]:
        raise SystemExit("calibration hash differs from attempt manifest")
    transcript = transcript_path.read_text(encoding="utf-8").splitlines()
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
    tile_width, tile_height = 140, 132
    image_scale = 5
    cell_records: list[dict[str, object]] = []

    def cell_box(row: int, column: int) -> tuple[int, int, int, int]:
        x0 = round(origin_x + column * advance_x)
        x1 = round(origin_x + (column + 1) * advance_x)
        baseline = first_baseline + row * advance_y
        y0, y1 = round(baseline + crop_top), round(baseline + crop_bottom)
        return max(0, x0), max(0, y0), min(source_image.width, x1), min(source_image.height, y1)

    for row in range(rows):
        line = transcript[row] if row < len(transcript) else ""
        for column in range(columns):
            glyph = line[column] if column < len(line) else " "
            box = cell_box(row, column)
            cell_records.append(
                {"row": row, "column": column, "glyph": glyph, "box": list(box), "nonblank": glyph not in (" ", "\t")}
            )

    def draw_sheet(path: Path, records: list[dict[str, object]], title: str, columns_per_row: int) -> None:
        sheet_rows = (len(records) + columns_per_row - 1) // columns_per_row
        canvas = Image.new("RGBA", (columns_per_row * tile_width, sheet_rows * tile_height), (242, 242, 242, 255))
        draw = ImageDraw.Draw(canvas)
        for index, record in enumerate(records):
            tile_x = (index % columns_per_row) * tile_width
            tile_y = (index // columns_per_row) * tile_height
            draw.rectangle((tile_x, tile_y, tile_x + tile_width - 1, tile_y + tile_height - 1), outline=(160, 160, 160, 255))
            x0, y0, x1, y1 = record["box"]
            crop = source_image.crop((x0, y0, max(x0 + 1, x1), max(y0 + 1, y1)))
            crop = crop.resize((crop.width * image_scale, crop.height * image_scale), Image.Resampling.NEAREST)
            max_width, max_height = tile_width - 12, tile_height - 38
            crop.thumbnail((max_width, max_height), Image.Resampling.NEAREST)
            crop_x = tile_x + (tile_width - crop.width) // 2
            crop_y = tile_y + 28 + (max_height - crop.height) // 2
            canvas.alpha_composite(crop, (crop_x, crop_y))
            glyph = record["glyph"]
            shown = "blank" if glyph == " " else repr(glyph)
            label = f"r{int(record['row']):02d} c{int(record['column']):02d} {shown}"
            draw.text((tile_x + 5, tile_y + 5), label, fill=(0, 0, 0, 255), font=label_font)
        canvas.save(path)

    all_path = attempt / "cell-contact-sheet.png"
    nonblank_path = attempt / "nonblank-contact-sheet.png"
    if all_path.exists() or nonblank_path.exists():
        raise SystemExit("refusing to overwrite existing contact-sheet artifacts")
    draw_sheet(all_path, cell_records, "all calibrated cells", 8)
    nonblank = [record for record in cell_records if record["nonblank"]]
    draw_sheet(nonblank_path, nonblank, "nonblank emitted cells", 6)
    receipt = {
        "format": "lateletter-cell-contact-sheet-v1",
        "source": os.path.relpath(source, attempt),
        "source_sha256": sha256(source),
        "calibration": "calibration.json",
        "calibration_sha256": sha256(calibration_path),
        "transcript": transcript_path.name,
        "transcript_sha256": sha256(transcript_path),
        "grid": {"columns": columns, "rows": rows, "origin_x_px": origin_x, "first_baseline_y_px": first_baseline, "advance_x_px": advance_x, "advance_y_px": advance_y, "crop_top_offset_px": crop_top, "crop_bottom_offset_px": crop_bottom},
        "cells_shown": len(cell_records),
        "nonblank_cells_shown": len(nonblank),
        "artifacts": {"all_cells": all_path.name, "nonblank_cells": nonblank_path.name},
        "review_only": True,
        "note": "This contact sheet is source-cell evidence; it is not a rendered parity result or operator acceptance.",
    }
    (attempt / "cell-contact-sheet.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"all_cells": len(cell_records), "nonblank_cells": len(nonblank), "all_artifact": str(all_path), "nonblank_artifact": str(nonblank_path)}))


if __name__ == "__main__":
    main()
