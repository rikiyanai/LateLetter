#!/usr/bin/env python3
"""Derive a fixed-lattice calibration artifact from a raster reference.

This is deliberately a calibration step, not a transcription step.  The pixel periods and
grid phases are measured from the source ink; the OCR stage consumes this artifact rather than
accepting origin/baseline guesses on its command line.  A source-sized overlay is emitted so a
reviewer can see exactly which lattice was used.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont


CALIBRATOR_VERSION = "grid-calibrator-5-parameterized-bounds"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def dominant_background(image: np.ndarray) -> tuple[int, int, int]:
    values, counts = np.unique(image.reshape(-1, 3), axis=0, return_counts=True)
    return tuple(int(value) for value in values[np.argmax(counts)])


def dominant_foreground(image: np.ndarray, background: tuple[int, int, int]) -> tuple[int, int, int]:
    """Return the most common non-background ink colour.

    The source raster's solid ink is a better comparison foreground than a hard-coded
    presentation colour.  Anti-aliased shades remain part of segmentation, but the dominant
    solid colour gives the parity renderer a readable, source-derived foreground.
    """
    values, counts = np.unique(image.reshape(-1, 3), axis=0, return_counts=True)
    background_array = np.asarray(background)
    candidates: list[tuple[int, int, tuple[int, int, int]]] = []
    for value, count in zip(values, counts):
        colour = tuple(int(item) for item in value)
        if colour == background:
            continue
        distance = int(np.abs(value.astype(int) - background_array.astype(int)).sum())
        candidates.append((int(count), distance, colour))
    if not candidates:
        return background
    # Prefer the colour farthest from the background first.  Near-background anti-aliased
    # pixels are often more numerous than the solid ink; choosing by frequency first can make
    # a white-on-white diagnostic foreground (as happened on the queued black-on-white source).
    # Frequency is only a tie-break among equally distant colours.
    return max(candidates, key=lambda item: (item[1], item[0], tuple(-channel for channel in item[2])))[2]


def dominant_period(profile: np.ndarray, minimum: int, maximum: int) -> tuple[int, dict[int, float]]:
    """Choose the strongest non-zero autocorrelation period, with deterministic tie breaks."""
    values = profile.astype(float)
    values -= values.mean()
    scores: dict[int, float] = {}
    denominator = float(np.dot(values, values)) or 1.0
    for period in range(minimum, maximum + 1):
        scores[period] = float(np.dot(values[:-period], values[period:]) / denominator)
    best = max(scores, key=lambda value: (scores[value], -value))
    return best, scores


def guide_columns(mask: np.ndarray, spacing: int = 36) -> list[int]:
    """Find the repeated screenshot rails without treating one art stem as a rail set."""
    counts = mask.sum(axis=0)
    best: tuple[int, int] | None = None
    for start in range(max(0, mask.shape[1] - spacing * 2)):
        score = min(
            int(counts[start]),
            int(counts[start + spacing]),
            int(counts[start + spacing * 2]),
        )
        if best is None or score > best[0]:
            best = (score, start)
    if best is None or best[0] < mask.shape[0] * 0.15:
        return []
    columns = [best[1], best[1] + spacing, best[1] + spacing * 2]
    # A fourth rail can be partially covered by the artwork.  Extend the observed sequence
    # only while its column still has the sparse dotted-rail signature.
    next_column = columns[-1] + spacing
    counts = mask.sum(axis=0)

    def railness(column: int) -> tuple[float, int]:
        values = mask[:, column]
        isolated = values.copy()
        isolated[:-1] &= ~values[1:]
        isolated[1:] &= ~values[:-1]
        total = int(values.sum())
        return (float(isolated.sum()) / max(total, 1), total)

    while next_column < mask.shape[1]:
        candidates = range(max(0, next_column - 2), min(mask.shape[1], next_column + 3))
        column = max(candidates, key=lambda value: railness(value))
        ratio, total = railness(column)
        if total < mask.shape[0] * 0.04 or ratio < 0.7:
            break
        columns.append(column)
        next_column += spacing
    return columns


def remove_guides(mask: np.ndarray, columns: list[int]) -> np.ndarray:
    result = mask.copy()
    for column in columns:
        # Rails are one-pixel dotted columns in this capture.  Remove the measured column only;
        # a broad erase band would delete a neighbouring real stem.
        if 0 <= column < result.shape[1]:
            result[:, column] = False
    return result


def phase_x(mask: np.ndarray, period: int) -> tuple[int, dict[int, float]]:
    """Select the cell phase that minimises ink on vertical cell boundaries."""
    scores: dict[int, float] = {}
    height, width = mask.shape
    for phase in range(period):
        origin = phase - math.ceil(phase / period) * period
        columns = math.ceil((width - origin) / period)
        boundary_ink = 0
        for column in range(columns + 1):
            x = round(origin + column * period)
            if 0 <= x < width:
                boundary_ink += int(mask[:, x].sum())
        scores[phase] = float(boundary_ink)
    return min(scores, key=lambda value: (scores[value], value)), scores


def integer_x_grid(mask: np.ndarray, period: int) -> dict[str, object]:
    """Return the cleanest integer-phase grid for a contact-sheet comparison."""
    phase, scores = phase_x(mask, period)
    origin = phase - math.ceil(phase / period) * period
    positions = [
        round(origin + column * period)
        for column in range(math.ceil((mask.shape[1] - origin) / period) + 1)
        if 0 <= round(origin + column * period) < mask.shape[1]
    ]
    values = [int(mask[:, column].sum()) for column in positions]
    return {
        "period_px": period,
        "phase_px_mod_period": phase,
        "origin_px": origin,
        "boundary_columns_px": positions,
        "boundary_ink_total": int(sum(values)),
        "boundary_ink_max": int(max(values)) if values else 0,
        "boundary_columns_with_ink": int(sum(value > 0 for value in values)),
        "phase_scores": scores,
    }


def horizontal_join_mask(mask: np.ndarray, minimum_run: int = 8, maximum_vertical_run: int = 4) -> np.ndarray:
    """Mark ink pixels that are plausibly a join between adjacent horizontal glyphs.

    This is computed once per source, rather than inside every pitch/phase candidate.  The
    resulting mask both keeps the search tractable for wide pitch ranges and makes the
    horizontal-join exemption auditable in the calibration artifact.
    """
    horizontal = np.zeros_like(mask, dtype=bool)
    for row in range(mask.shape[0]):
        xs = np.flatnonzero(mask[row])
        if not len(xs):
            continue
        starts = np.r_[0, np.flatnonzero(np.diff(xs) > 1) + 1]
        ends = np.r_[starts[1:] - 1, len(xs) - 1]
        for start, end in zip(starts, ends):
            if int(xs[end] - xs[start] + 1) >= minimum_run:
                horizontal[row, xs[start] : xs[end] + 1] = True

    vertical_short = np.zeros_like(mask, dtype=bool)
    for column in range(mask.shape[1]):
        ys = np.flatnonzero(mask[:, column])
        if not len(ys):
            continue
        starts = np.r_[0, np.flatnonzero(np.diff(ys) > 1) + 1]
        ends = np.r_[starts[1:] - 1, len(ys) - 1]
        for start, end in zip(starts, ends):
            if int(ys[end] - ys[start] + 1) <= maximum_vertical_run:
                vertical_short[ys[start] : ys[end] + 1, column] = True
    return mask & horizontal & vertical_short


def continuous_x_grid(mask: np.ndarray, minimum: float = 9.0, maximum: float = 14.0) -> dict[str, object]:
    """Search subpixel pitch/phase by minimizing ink on rounded cell boundaries.

    The source is a rasterized monospace surface that may have been scaled after rendering.
    Integer autocorrelation lags can therefore be near-ties while still putting boundaries
    through glyphs.  A fine pitch/phase search recovers the gutter lattice without using any
    candidate transcript as input.
    """
    best: tuple[tuple[float, float, int, float, float], dict[str, object]] | None = None
    horizontal_joins = horizontal_join_mask(mask)
    nonhorizontal_mask = mask & ~horizontal_joins
    for period_index in range(int(round(minimum * 20)), int(round(maximum * 20)) + 1):
        period = period_index / 20.0
        for phase_index in range(0, int(round(period * 20))):
            phase = phase_index / 20.0
            origin = phase - math.ceil(phase / period) * period
            positions: list[int] = []
            position = origin
            while position < mask.shape[1] + period:
                rounded = round(position)
                if 0 <= rounded < mask.shape[1] and (not positions or rounded != positions[-1]):
                    positions.append(rounded)
                position += period
            values = [int(mask[:, column].sum()) for column in positions]
            nonhorizontal_values = [int(nonhorizontal_mask[:, column].sum()) for column in positions]
            total = int(sum(values))
            maximum_boundary = int(max(values)) if values else 0
            nonzero = int(sum(value > 0 for value in values))
            maximum_nonhorizontal = int(max(nonhorizontal_values)) if nonhorizontal_values else 0
            nonhorizontal_total = int(sum(nonhorizontal_values))
            nonzero_nonhorizontal = int(sum(value > 0 for value in nonhorizontal_values))
            # Prefer a lattice that avoids substantive cuts.  Raw boundary ink remains recorded
            # for diagnostics, and period distance is only a final deterministic tie-break.
            key = (
                nonhorizontal_total,
                maximum_nonhorizontal,
                nonzero_nonhorizontal,
                float(total),
                float(maximum_boundary),
                nonzero,
                abs(period - 11.0),
                period,
            )
            candidate = {
                "period_px": period,
                "phase_px_mod_period": phase,
                "origin_px": origin,
                "boundary_columns_px": positions,
                "boundary_ink_total": total,
                "boundary_ink_max": maximum_boundary,
                "boundary_columns_with_ink": nonzero,
                "boundary_ink_nonhorizontal_total": nonhorizontal_total,
                "boundary_ink_nonhorizontal_max": maximum_nonhorizontal,
                "boundary_columns_with_nonhorizontal_ink": nonzero_nonhorizontal,
                "boundary_ink_horizontal_join_total": total - nonhorizontal_total,
            }
            if best is None or key < best[0]:
                best = (key, candidate)
    if best is None:
        raise ValueError("unable to derive a continuous horizontal lattice")
    return best[1]


def validate_x_grid(search: dict[str, object]) -> dict[str, object]:
    """Reject a candidate lattice whose boundaries still traverse substantive ink."""
    total = int(search["boundary_ink_total"])
    maximum = int(search["boundary_ink_max"])
    nonzero = int(search["boundary_columns_with_ink"])
    nonhorizontal_total = int(search.get("boundary_ink_nonhorizontal_total", total))
    nonhorizontal_maximum = int(search.get("boundary_ink_nonhorizontal_max", maximum))
    nonhorizontal_nonzero = int(search.get("boundary_columns_with_nonhorizontal_ink", nonzero))
    accepted = nonhorizontal_total <= 8 and nonhorizontal_maximum <= 3 and nonhorizontal_nonzero <= 4
    return {
        "verdict": "machine_legal" if accepted else "rejected_boundary_crossings",
        "boundary_ink_total": total,
        "boundary_ink_max": maximum,
        "boundary_columns_with_ink": nonzero,
        "boundary_ink_nonhorizontal_total": nonhorizontal_total,
        "boundary_ink_nonhorizontal_max": nonhorizontal_maximum,
        "boundary_columns_with_nonhorizontal_ink": nonhorizontal_nonzero,
        "horizontal_join_pixels_exempt": total - nonhorizontal_total,
        "rule": "nonhorizontal_total<=8, nonhorizontal_max<=3, nonhorizontal_columns<=4; horizontal joins are diagnostic",
    }


def draw_grid_panel(
    image: Image.Image,
    origin: float,
    period: float,
    first_baseline: int,
    line_height: int,
    rows: int,
    label: str,
) -> Image.Image:
    """Render one labelled source-sized grid panel for operator calibration review."""
    header_height = 28
    panel = Image.new("RGBA", (image.width, image.height + header_height), (255, 255, 255, 255))
    panel.paste(image.convert("RGBA"), (0, header_height))
    draw = ImageDraw.Draw(panel, "RGBA")
    draw.rectangle((0, 0, image.width - 1, header_height - 1), fill=(245, 245, 245, 255))
    draw.text((6, 7), label, fill=(15, 15, 15, 255))
    for column in range(math.ceil((image.width - origin) / period) + 1):
        x = round(origin + column * period)
        if 0 <= x < image.width:
            draw.line((x, header_height, x, panel.height - 1), fill=(40, 120, 240, 180), width=1)
    for row in range(rows):
        baseline = round(first_baseline + row * line_height) + header_height
        if 0 <= baseline < panel.height:
            draw.line((0, baseline, image.width - 1, baseline), fill=(235, 145, 30, 170), width=1)
    return panel


def write_candidate_contact_sheet(
    image: Image.Image,
    output: Path,
    candidates: list[tuple[str, dict[str, object]]],
    first_baseline: int,
    line_height: int,
    rows: int,
) -> None:
    """Write the required labelled comparison of plausible horizontal lattices."""
    panels = [
        draw_grid_panel(
            image,
            float(candidate["origin_px"]),
            float(candidate["period_px"]),
            first_baseline,
            line_height,
            rows,
            f"{label}: p={float(candidate['period_px']):.2f}px, boundary ink={candidate['boundary_ink_total']}",
        )
        for label, candidate in candidates
    ]
    sheet = Image.new("RGBA", (sum(panel.width for panel in panels), panels[0].height), (255, 255, 255, 255))
    offset = 0
    for panel in panels:
        sheet.paste(panel, (offset, 0))
        offset += panel.width
    sheet.save(output / "calibration-candidates.png")


def phase_y(mask: np.ndarray, period: int) -> tuple[int, dict[int, float]]:
    """Select the baseline phase with the strongest short horizontal strokes near baselines."""
    scores: dict[int, float] = {}
    height = mask.shape[0]
    horizontal = mask[:, :-1] & mask[:, 1:]
    for phase in range(period):
        score = 0
        for baseline in range(phase, height + period, period):
            score += int(horizontal[max(0, baseline - 5) : min(height, baseline + 3)].sum())
        scores[phase] = float(score)
    return max(scores, key=lambda value: (scores[value], -value)), scores


def derive_row_crop_offsets(mask: np.ndarray, first_baseline: int, period: int) -> dict[str, int | float]:
    """Derive a tiled, non-overlapping vertical crop from source row gutters.

    The horizontal grid is a measured period, so the row cells must tile that period too.
    For each possible top boundary, score the ink crossing all repeated boundaries and choose
    the cleanest one.  This uses the source's actual gutters rather than a surrogate font bbox;
    adjacent cells therefore cannot contain two baselines' strokes.
    """
    height = mask.shape[0]
    candidates: list[tuple[float, int, int, int]] = []
    for top in range(-period, 1):
        boundary_ink = 0
        samples = 0
        for row in range((height // period) + 2):
            y = first_baseline + row * period + top
            if 0 <= y < height:
                boundary_ink += int(mask[y].sum())
                samples += 1
        if samples:
            candidates.append((boundary_ink / samples, boundary_ink, -samples, top))
    if not candidates:
        top = -period // 2
        return {"top": top, "bottom": top + period, "boundary_ink": 0, "boundary_samples": 0}
    score, raw_score, neg_samples, top = min(candidates)
    return {
        "top": int(top),
        "bottom": int(top + period),
        "boundary_ink": int(raw_score),
        "boundary_ink_mean": float(score),
        "boundary_samples": int(-neg_samples),
        "inter_row_clearance_px": 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--font-path", default="/System/Library/Fonts/Menlo.ttc")
    parser.add_argument("--font-size", type=int, default=15)
    parser.add_argument(
        "--x-min",
        type=float,
        default=6.0,
        help="inclusive minimum horizontal pitch searched in pixels (default: 6)",
    )
    parser.add_argument(
        "--x-max",
        type=float,
        default=14.0,
        help="inclusive maximum horizontal pitch searched in pixels (default: 14)",
    )
    parser.add_argument(
        "--y-min",
        type=int,
        default=14,
        help="inclusive minimum vertical pitch searched in pixels (default: 14)",
    )
    parser.add_argument(
        "--y-max",
        type=int,
        default=24,
        help="inclusive maximum vertical pitch searched in pixels (default: 24)",
    )
    args = parser.parse_args()

    if args.x_min <= 0 or args.x_max < args.x_min:
        parser.error("--x-min and --x-max must be positive and x-min <= x-max")
    if args.y_min <= 0 or args.y_max < args.y_min:
        parser.error("--y-min and --y-max must be positive and y-min <= y-max")

    source = args.source.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    with Image.open(source) as opened:
        rgb_image = opened.convert("RGB")
        rgba_image = opened.convert("RGBA")
    pixels = np.asarray(rgb_image)
    background = dominant_background(pixels)
    foreground = dominant_foreground(pixels, background)
    raw_mask = np.max(np.abs(pixels.astype(int) - np.asarray(background)), axis=2) > 25
    rails = guide_columns(raw_mask)
    mask = remove_guides(raw_mask, rails)
    integer_period_x, x_scores = dominant_period(
        mask.sum(axis=0), max(1, math.ceil(args.x_min)), math.floor(args.x_max)
    )
    period_y, y_scores = dominant_period(mask.sum(axis=1), args.y_min, args.y_max)
    x_phase, x_phase_scores = phase_x(mask, integer_period_x)
    integer_11 = integer_x_grid(mask, 11)
    integer_12 = integer_x_grid(mask, 12)
    continuous_grid = continuous_x_grid(mask, args.x_min, args.x_max)
    x_legality = validate_x_grid(continuous_grid)
    y_phase, y_phase_scores = phase_y(mask, period_y)

    ys, _ = np.where(mask)
    ink_min_y = int(ys.min()) if len(ys) else 0
    font = ImageFont.truetype(args.font_path, args.font_size)
    ascent, descent = font.getbbox("|", anchor="ls")[1], font.getbbox("|", anchor="ls")[3]
    # Select the earliest phase-aligned baseline whose glyph box reaches the first measured ink.
    # Ceil skipped a visible top row whenever the source began on the preceding phase cell.
    first_baseline = y_phase + math.floor((ink_min_y - y_phase + -ascent) / period_y) * period_y
    if first_baseline <= 0:
        first_baseline += period_y
    origin_x = float(continuous_grid["origin_px"])
    period_x = float(continuous_grid["period_px"])
    width, height = rgb_image.size
    columns = math.ceil((width - origin_x) / period_x)
    top_of_first_row = first_baseline + ascent
    rows = math.ceil((height - top_of_first_row) / period_y)
    rows = max(1, rows)
    row_crop = derive_row_crop_offsets(mask, int(first_baseline), period_y)
    candidate_comparison = [
        {"label": "integer-11", **integer_11},
        {"label": "integer-12", **integer_12},
        {"label": "subpixel-selected", **continuous_grid},
    ]

    calibration = {
        "calibrator": {"name": "LateLetter monospace grid calibrator", "version": CALIBRATOR_VERSION},
        "source_png": str(source),
        "source_sha256": sha256(source),
        "canvas": {"width_px": width, "height_px": height, "background_rgb": list(background)},
        "normalization": {
            "colour_space": "RGB",
            "ink_threshold_l1": 25,
            "background_method": "dominant_exact_rgb",
            "guide_removal": (
                "measured sparse dotted columns at 36px repetition; exact-column erase"
                if rails
                else "none"
            ),
            "foreground_rgb": list(foreground),
        },
        "guide_columns_px": rails,
        "grid": {
            "columns": columns,
            "rows": rows,
            "origin_x_px": float(origin_x),
            "first_baseline_y_px": float(first_baseline),
            "cell_advance_x_px": float(period_x),
            "line_height_px": float(period_y),
            "x_phase_px_mod_period": x_phase,
            "y_phase_px_mod_period": y_phase,
            "cell_crop_top_offset_px": row_crop["top"],
            "cell_crop_bottom_offset_px": row_crop["bottom"],
            "row_crop_measurement": row_crop,
        },
        "font_model": {"path": args.font_path, "size_px": args.font_size, "bbox_anchor": "ls"},
        "search_bounds": {
            "x_min_px": float(args.x_min),
            "x_max_px": float(args.x_max),
            "y_min_px": int(args.y_min),
            "y_max_px": int(args.y_max),
        },
        "measurement": {
            "x_autocorrelation": x_scores,
            "x_continuous_search": continuous_grid,
            "x_candidate_comparison": candidate_comparison,
            "y_autocorrelation": y_scores,
            "x_phase_boundary_ink": x_phase_scores,
            "y_phase_horizontal_ink": y_phase_scores,
            "ink_bbox_without_guides": {
                "left_px": int(np.where(mask.any(axis=0))[0].min()) if mask.any() else None,
                "top_px": ink_min_y if mask.any() else None,
                "right_px": int(np.where(mask.any(axis=0))[0].max()) if mask.any() else None,
                "bottom_px": int(np.where(mask.any(axis=0))[0].max()) if mask.any() else None,
            },
        },
        "status": "calibration_candidate" if x_legality["verdict"] == "machine_legal" else "calibration_rejected",
        "grid_legality": {"x": x_legality, "status": x_legality["verdict"]},
        "review": {
            "calibration_overlay": "pending_operator_review",
            "contact_sheet": "calibration-candidates.png",
            "required_checks": [
                "vertical boundaries lie in real gutters",
                "no substantive glyph strokes are divided",
                "every visible row and column is covered",
                "horizontal baselines and crops are correct",
            ],
        },
    }
    # Correct the y extent field without introducing a second image scan in the JSON literal.
    if mask.any():
        y_indices = np.where(mask.any(axis=1))[0]
        calibration["measurement"]["ink_bbox_without_guides"]["bottom_px"] = int(y_indices.max())

    (output / "calibration.json").write_text(json.dumps(calibration, indent=2) + "\n", encoding="utf-8")

    write_candidate_contact_sheet(
        rgba_image,
        output,
        [(item["label"], item) for item in candidate_comparison],
        int(first_baseline),
        period_y,
        rows,
    )

    overlay = rgba_image.copy()
    draw = ImageDraw.Draw(overlay, "RGBA")
    for column in range(columns + 1):
        x = round(origin_x + column * period_x)
        if 0 <= x < width:
            draw.line((x, 0, x, height - 1), fill=(80, 160, 255, 130), width=1)
    for row in range(rows):
        baseline = round(first_baseline + row * period_y)
        if 0 <= baseline < height:
            draw.line((0, baseline, width - 1, baseline), fill=(255, 180, 60, 150), width=1)
    for column in rails:
        draw.line((column, 0, column, height - 1), fill=(255, 70, 70, 190), width=1)
    overlay.save(output / "calibration.png")


if __name__ == "__main__":
    main()
