#!/usr/bin/env python3
"""Recover a fail-closed, fixed-grid ASCII candidate from a raster reference.

This is deliberately not a general-purpose OCR wrapper. It measures the raster lattice, records
Tesseract's character boxes, maps only unambiguous single-cell punctuation into the grid, and
writes ``?`` for conflicts or unsupported recognitions. That preserves spaces and makes every
unrecovered cell explicit instead of inventing text.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image


SAFE_GLYPHS = set("()[]/\\|_.:-=")
PIPE_ALIASES = {"I", "l", "L"}


def dominant_background(image: np.ndarray) -> tuple[int, int, int]:
    colours, counts = np.unique(image[:, :, :3].reshape(-1, 3), axis=0, return_counts=True)
    return tuple(int(value) for value in colours[np.argmax(counts)])


def ink_mask(image: np.ndarray, background: tuple[int, int, int]) -> np.ndarray:
    mask = np.max(np.abs(image[:, :, :3].astype(int) - np.asarray(background)), axis=2) > 25
    # Screenshot guide rails are much taller than source glyph strokes and otherwise dominate
    # horizontal-period detection.
    for column in np.where(mask.sum(axis=0) > image.shape[0] * 0.30)[0]:
        mask[:, max(0, column - 1) : column + 2] = False
    return mask


def dominant_period(signal: np.ndarray, low: int, high: int) -> int:
    centred = signal.astype(float) - signal.mean()
    scores = {
        lag: float(np.dot(centred[:-lag], centred[lag:]))
        for lag in range(low, min(high, len(centred) - 1) + 1)
    }
    return max(scores, key=scores.__getitem__)


def tesseract_boxes(source: Path) -> list[dict[str, int | str]]:
    result = subprocess.run(
        ["tesseract", str(source), "stdout", "--psm", "6", "makebox"],
        check=True,
        capture_output=True,
        text=True,
    )
    boxes: list[dict[str, int | str]] = []
    for raw in result.stdout.splitlines():
        fields = raw.split()
        if len(fields) != 6:
            continue
        glyph, left, bottom, right, top, page = fields
        boxes.append(
            {
                "glyph": glyph,
                "left": int(left),
                "bottom": int(bottom),
                "right": int(right),
                "top": int(top),
                "page": int(page),
            }
        )
    return boxes


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--calibration", type=Path, required=True)
    args = parser.parse_args()

    calibration = json.loads(args.calibration.resolve().read_text(encoding="utf-8"))
    calibrated_grid = calibration["grid"]
    columns = int(calibrated_grid["columns"])
    rows = int(calibrated_grid["rows"])
    origin_x = float(calibrated_grid["origin_x_px"])
    first_baseline_y = float(calibrated_grid["first_baseline_y_px"])
    advance_x = float(calibrated_grid["cell_advance_x_px"])
    advance_y = float(calibrated_grid["line_height_px"])

    image = np.asarray(Image.open(args.source).convert("RGB"))
    background = dominant_background(image)
    mask = ink_mask(image, background)
    measured_x = dominant_period(mask.sum(axis=0), 4, 40)
    measured_y = dominant_period(mask.sum(axis=1), 8, 50)

    args.output.mkdir(parents=True, exist_ok=False)
    boxes = tesseract_boxes(args.source)
    grid = [[" " for _ in range(columns)] for _ in range(rows)]
    evidence: list[dict[str, int | str]] = []
    height = image.shape[0]

    for box in boxes:
        centre_x = (int(box["left"]) + int(box["right"])) / 2
        centre_y = height - (int(box["bottom"]) + int(box["top"])) / 2
        row = round((centre_y - first_baseline_y) / advance_y)
        column = round((centre_x - origin_x) / advance_x)
        glyph = str(box["glyph"])
        width_cells = max(1, round((int(box["right"]) - int(box["left"])) / advance_x))
        record: dict[str, int | str] = dict(box)
        record.update({"row": row, "column": column, "width_cells": width_cells})
        evidence.append(record)
        if not (0 <= row < rows and 0 <= column < columns):
            continue
        if glyph in PIPE_ALIASES:
            glyph = "|"
        if glyph not in SAFE_GLYPHS or width_cells != 1 or grid[row][column] != " ":
            grid[row][column] = "?"
        else:
            grid[row][column] = glyph

    (args.output / "machine-ocr.txt").write_text(
        # Do not strip trailing cells: they are literal positions in the recovered lattice.
        "\n".join("".join(row) for row in grid) + "\n", encoding="utf-8"
    )
    (args.output / "tesseract-boxes.json").write_text(
        json.dumps(evidence, indent=2) + "\n", encoding="utf-8"
    )
    (args.output / "calibration.json").write_text(
        json.dumps(
            {
                "source": str(args.source),
                "pixel_size": {"width": int(image.shape[1]), "height": int(image.shape[0])},
                "background_rgb": background,
                "measured_period_px": {"x": measured_x, "y": measured_y},
                "declared_grid_px": {"x": advance_x, "y": advance_y},
                "origin_x": origin_x,
                "first_baseline_y": first_baseline_y,
                "calibration": str(args.calibration),
                "status": "machine_candidate_only",
                "note": "Question marks are unresolved cells, not glyph guesses.",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
