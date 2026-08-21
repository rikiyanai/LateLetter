#!/usr/bin/env python3
"""Generate a lossless, fail-closed cell-OCR candidate from a calibration artifact.

The calibration JSON is the only source of grid origin, baselines, dimensions, and advances.
Every declared cell is emitted, including trailing blank cells and cells outside the clipped
canvas.  This script never edits an existing attempt and never turns an unresolved cell into a
guessed character.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image


SAFE = set("()[]/\\|_.:-=~^',")
PIPE_ALIASES = {"I", "l", "L"}
UNDERSCORE_ALIASES = {"-", "—", "_"}
RECOGNIZER_VERSION = "cell-ocr-5-structural-gate"
MIN_CONFIDENCE = 0.85


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def tesseract_version() -> str:
    result = subprocess.run(["tesseract", "--version"], check=True, capture_output=True, text=True)
    return result.stdout.splitlines()[0] if result.stdout else "unknown"


def normalize(raw: str, ink_y: np.ndarray, baseline: float) -> str:
    glyph = raw.strip()
    if len(glyph) != 1:
        return "?"
    if glyph in PIPE_ALIASES:
        return "|"
    if glyph in UNDERSCORE_ALIASES:
        return "_" if ink_y.mean() >= baseline else "-"
    return glyph if glyph in SAFE else "?"


def topology(mask: np.ndarray) -> dict[str, object]:
    """Return reviewable, hashable topology facts for one segmented cell."""
    ys, xs = np.where(mask)
    if len(xs) == 0:
        return {
            "bbox": None,
            "width": 0,
            "height": 0,
            "ink_pixels": 0,
            "edge_contacts": [],
            "components": 0,
            "signature": "blank",
        }
    left, right, top, bottom = xs.min(), xs.max(), ys.min(), ys.max()
    cropped = mask[top : bottom + 1, left : right + 1]
    rows = ["".join("1" if value else "0" for value in row) for row in cropped]
    edges = []
    if left == 0:
        edges.append("left")
    if right == mask.shape[1] - 1:
        edges.append("right")
    if top == 0:
        edges.append("top")
    if bottom == mask.shape[0] - 1:
        edges.append("bottom")
    # Connected components are intentionally simple 8-neighbour components; the exact
    # topology is retained in the signature so repeated source masks can be checked.
    visited = np.zeros(mask.shape, dtype=bool)
    components = 0
    for start_y, start_x in zip(ys.tolist(), xs.tolist()):
        if visited[start_y, start_x]:
            continue
        components += 1
        stack = [(start_y, start_x)]
        visited[start_y, start_x] = True
        while stack:
            cy, cx = stack.pop()
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    ny, nx = cy + dy, cx + dx
                    if (
                        0 <= ny < mask.shape[0]
                        and 0 <= nx < mask.shape[1]
                        and not visited[ny, nx]
                        and mask[ny, nx]
                    ):
                        visited[ny, nx] = True
                        stack.append((ny, nx))
    return {
        "bbox": {"left": int(left), "top": int(top), "right": int(right), "bottom": int(bottom)},
        "width": int(right - left + 1),
        "height": int(bottom - top + 1),
        "ink_pixels": int(len(xs)),
        "edge_contacts": edges,
        "components": components,
        # Preserve the cell-relative vertical offset.  A dash and an underscore can have the
        # same cropped bitmap but are not the same structural shape when they sit at different
        # baseline positions.
        "signature": f"{right-left+1}x{bottom-top+1}@{top}:{bottom}:{'/'.join(rows)}",
    }


def edge_fragment(mask: np.ndarray) -> bool:
    ys, xs = np.where(mask)
    if len(xs) == 0:
        return False
    return len(xs) <= 4 and (xs.min() == 0 or xs.max() == mask.shape[1] - 1)


def neighbouring_ownership_proven(
    ink: np.ndarray, x0: int, x1: int, y0: int, y1: int, cell_mask: np.ndarray
) -> bool:
    """Only erase a tiny edge fragment when source ink continues at matching coordinates."""
    ys, xs = np.where(cell_mask)
    if len(xs) == 0:
        return False
    height, width = ink.shape
    # Presence anywhere along an edge is not ownership evidence: an unrelated glyph on the same
    # boundary used to make a fragment disappear.  Compare the occupied coordinates on each side
    # and require at least one aligned continuation (the horse fixture uses two pixels).
    if xs.min() == 0 and x0 > 0:
        local_rows = np.any(cell_mask, axis=1)
        neighbour = ink[max(0, y0) : min(height, y1), x0 - 1]
        if neighbour.size == local_rows.size and int(np.logical_and(local_rows, neighbour).sum()) >= 1:
            return True
    if xs.max() == cell_mask.shape[1] - 1 and x1 < width:
        local_rows = np.any(cell_mask, axis=1)
        neighbour = ink[max(0, y0) : min(height, y1), x1]
        if neighbour.size == local_rows.size and int(np.logical_and(local_rows, neighbour).sum()) >= 1:
            return True
    if ys.min() == 0 and y0 > 0:
        local_columns = np.any(cell_mask, axis=0)
        neighbour = ink[y0 - 1, max(0, x0) : min(width, x1)]
        if neighbour.size == local_columns.size and int(np.logical_and(local_columns, neighbour).sum()) >= 1:
            return True
    if ys.max() == cell_mask.shape[0] - 1 and y1 < height:
        local_columns = np.any(cell_mask, axis=0)
        neighbour = ink[y1, max(0, x0) : min(width, x1)]
        if neighbour.size == local_columns.size and int(np.logical_and(local_columns, neighbour).sum()) >= 1:
            return True
    return False


def row_continuation_proven(
    ink: np.ndarray, x0: int, x1: int, y0: int, cell_mask: np.ndarray
) -> bool:
    """Detect a glyph stroke that continues across the preceding row boundary."""
    if y0 <= 0:
        return False
    height, width = ink.shape
    xa, xb = max(0, x0), min(width, x1)
    if xa >= xb or cell_mask.shape[0] < 2:
        return False
    ys, xs = np.where(cell_mask)
    if len(xs) == 0:
        return False
    cell_width = int(xs.max() - xs.min() + 1)
    cell_height = int(ys.max() - ys.min() + 1)
    # A real glyph occupying most of a row must be classified, not erased as spill.  Only
    # small narrow fragments can be owned by the preceding row.
    if len(xs) > 16 or cell_width > 8 or cell_height > 8:
        return False
    current = cell_mask[: min(3, cell_mask.shape[0])]
    current_columns = np.any(current, axis=0)
    previous = ink[y0 - 1, xa:xb]
    if previous.size != current_columns.size:
        return False
    overlap = int(np.logical_and(current_columns, previous).sum())
    # Require a real stroke continuation, not one anti-aliased pixel at the boundary.
    return overlap >= 2 and int(current_columns.sum()) >= 2


def bidirectional_row_spill_proven(
    ink: np.ndarray, x0: int, x1: int, y0: int, y1: int, cell_mask: np.ndarray
) -> bool:
    """Prove that a sparse top-and-bottom composite belongs to adjacent rows.

    A fixed crop can catch the tail of the previous row and the head of the next row in one
    cell.  It is not safe to call that punctuation.  This stricter gate requires both edge
    fragments to continue into their neighbouring rows and requires a clear interior gap, so a
    genuine colon or compact quote is not erased.
    """
    ys, xs = np.where(cell_mask)
    if len(xs) < 8 or len(xs) > 24 or xs.max() - xs.min() + 1 > 6:
        return False
    if ys.min() > 2 or ys.max() < cell_mask.shape[0] - 3:
        return False
    if cell_mask[3 : cell_mask.shape[0] - 3].any():
        return False
    if y0 <= 0 or y1 >= ink.shape[0]:
        return False
    top_columns = np.any(cell_mask[:3], axis=0)
    bottom_columns = np.any(cell_mask[-3:], axis=0)
    previous = ink[y0 - 1, max(0, x0) : min(ink.shape[1], x1)]
    following = ink[y1, max(0, x0) : min(ink.shape[1], x1)]
    if previous.size != top_columns.size or following.size != bottom_columns.size:
        return False
    top_overlap = int(np.logical_and(top_columns, previous).sum())
    bottom_overlap = int(np.logical_and(bottom_columns, following).sum())
    return top_overlap >= 2 and bottom_overlap >= 2


def classify_shape(mask: np.ndarray, baseline: float) -> tuple[str | None, float, str]:
    """Classify isolated fixed-cell punctuation without asking prose OCR to name it.

    The source uses a small structural alphabet.  Tesseract is particularly poor at this
    scale (it calls a parenthesis ``}`` and a colon ``||``), so high-signal geometry owns the
    common strokes.  Tiny ink touching a cell edge is a side-bearing fragment from a neighbour,
    not an independent glyph; treating it as blank prevents one-pixel row/column drift.
    """
    ys, xs = np.where(mask)
    if len(xs) == 0:
        return " ", 1.0, "binary_blank"
    left, right, top, bottom = xs.min(), xs.max(), ys.min(), ys.max()
    width, height = right - left + 1, bottom - top + 1
    original_edge_contacts = {
        edge
        for edge, occupied in (
            ("left", left == 0),
            ("right", right == mask.shape[1] - 1),
            ("top", top == 0),
            ("bottom", bottom == mask.shape[0] - 1),
        )
        if occupied
    }
    row_counts = mask.sum(axis=1)
    column_counts = mask.sum(axis=0)
    if len(xs) <= 4 and (left == 0 or right == mask.shape[1] - 1):
        # Ownership cannot be decided from this cell alone.  The caller may downgrade it to
        # a blank only after proving that ink continues across a neighbouring cell boundary.
        return None, 0.0, "boundary_sidebearing_unproven"

    def groups(values: np.ndarray) -> list[tuple[int, int]]:
        result: list[tuple[int, int]] = []
        for value in values.tolist():
            if not result or value > result[-1][1] + 1:
                result.append((value, value))
            else:
                result[-1] = (result[-1][0], value)
        return result

    occupied_rows = np.where(row_counts > 0)[0]
    row_groups = groups(occupied_rows)
    strong_rows = np.where(row_counts >= max(3, width * 0.55))[0]
    strong_groups = groups(strong_rows)

    # Two small detached dots are a colon.  This must run before vertical/diagonal tests.
    if (
        len(row_groups) == 2
        and all(end - start <= 2 for start, end in row_groups)
        and row_groups[1][0] - row_groups[0][1] >= 2
        and width <= 4
        and (height <= 8 or (width <= 2 and len(xs) <= 8))
    ):
        return ":", 0.96, "geometry_colon"

    # A cell can contain a connected fragment from an adjacent diagonal or row.  Keep the
    # dominant connected component for shape decisions, while retaining the original mask for
    # occupancy.  This is deliberately conservative: only discard small detached components.
    visited = np.zeros(mask.shape, dtype=bool)
    components: list[list[tuple[int, int]]] = []
    for start_y, start_x in zip(ys.tolist(), xs.tolist()):
        if visited[start_y, start_x]:
            continue
        stack = [(start_y, start_x)]
        visited[start_y, start_x] = True
        component: list[tuple[int, int]] = []
        while stack:
            cy, cx = stack.pop()
            component.append((cy, cx))
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    if not dx and not dy:
                        continue
                    ny, nx = cy + dy, cx + dx
                    if 0 <= ny < mask.shape[0] and 0 <= nx < mask.shape[1] and mask[ny, nx] and not visited[ny, nx]:
                        visited[ny, nx] = True
                        stack.append((ny, nx))
        components.append(component)
    components.sort(key=len, reverse=True)
    original_component_count = len(components)
    dominant_size = len(components[0])
    detached_size = sum(len(item) for item in components[1:])

    # A tiny top-of-cell mark can be split by a neighbouring stroke.  When the dominant mark
    # and the detached edge fragment together form a compact upper terminal, preserve it as an
    # apostrophe instead of reducing the dominant piece to an unclassifiable vertical.
    if (
        len(components) > 1
        and dominant_size >= 8
        and detached_size <= 3
        and 4 <= height <= 7
        and width >= 5
        and top <= 2
    ):
        return "'", 0.78, "geometry_split_apostrophe"

    if len(components) > 1 and dominant_size >= 4 and (detached_size <= 6 or dominant_size >= 2.5 * max(len(components[1]), 1)):
        dominant = np.zeros(mask.shape, dtype=bool)
        for cy, cx in components[0]:
            dominant[cy, cx] = True
        mask = dominant
        ys, xs = np.where(mask)
        left, right, top, bottom = xs.min(), xs.max(), ys.min(), ys.max()
        width, height = right - left + 1, bottom - top + 1
        row_counts = mask.sum(axis=1)
        column_counts = mask.sum(axis=0)
        occupied_rows = np.where(row_counts > 0)[0]
        row_groups = groups(occupied_rows)
        strong_rows = np.where(row_counts >= max(3, width * 0.55))[0]
        strong_groups = groups(strong_rows)

    # The horse ear/caret is a compact widening stroke: it starts narrow near its apex and
    # widens toward the lower row.  Diagonals keep roughly constant row occupancy instead.
    if 8 <= height <= 12 and width >= 7:
        occupied = row_counts[np.where(row_counts > 0)[0]]
        if len(occupied) >= 4 and float(occupied[-1]) >= float(occupied[0]) + 2:
            return "^", 0.90, "geometry_caret"

    # A period is a compact terminal; a dash is a short horizontal stroke.  Full-width
    # underscores are intentionally left to the lower horizontal rule below.  A horizontal
    # decision requires a genuinely horizontal band: the old `strong_rows` shortcut promoted
    # four-pixel diagonal fragments (for example 1110/0111/0111/0011) to `-`.  The source also
    # contains a middle band around the calibration baseline and a lower band below it; the
    # middle band is not an underscore merely because it is below the old binary threshold.
    # A compact slanted mark at the bottom of a cell is a comma, not a period.  This check
    # must precede the generic period rule because the horse sheet's comma occupies only three
    # rows after rasterisation.
    if height <= 4 and width <= 5 and bottom >= mask.shape[0] - 4 and len(xs) >= 4:
        slope = np.polyfit(ys, xs, 1)[0] if len(xs) > 1 else 0.0
        if abs(slope) >= 0.15:
            return ",", 0.9, "geometry_compact_comma"
    if height <= 3 and width <= 4:
        return ".", 0.9, "geometry_period"
    # A scaled screenshot can rasterize a horizontal dash/underscore across four rows, and a
    # run of adjacent dashes can fill the complete cell width.  Keep the same baseline-relative
    # distinction as the narrow path, but do not reject a full-width band merely because it
    # touches both cell edges; ownership/row context handles joined runs later.
    if height == 4 and width >= 4 and original_component_count == 1:
        max_row = int(row_counts.max())
        horizontal_band = max_row >= max(4, int(np.ceil(width * 0.80)))
        if horizontal_band:
            band_center = float(ys.mean() + 0.5)
            # A full-width scaled band has less vertical clearance than the horse fixtures;
            # its edge ownership is established by the complete row, so a half-pixel baseline
            # separation is sufficient.  Narrow bands retain the conservative two-pixel rule.
            separation = 0.5 if width >= mask.shape[1] - 1 else 2.0
            if band_center <= baseline - separation:
                return "-", 0.90, "geometry_four_row_horizontal"
            if band_center >= baseline + separation:
                return "_", 0.90, "geometry_four_row_horizontal"
            return None, 0.0, "geometry_middle_horizontal_ambiguous"
    if height <= 3 and width < mask.shape[1] - 1 and original_component_count == 1:
        max_row = int(row_counts.max())
        horizontal_band = max_row >= max(4, int(np.ceil(width * 0.80)))
        if horizontal_band:
            band_center = float(ys.mean() + 0.5)
            if band_center <= baseline - 2:
                return "-", 0.90, "geometry_short_horizontal"
            if band_center >= baseline + 2:
                return "_", 0.90, "geometry_short_horizontal"
            return None, 0.0, "geometry_middle_horizontal_ambiguous"

    # Horse-sheet wave marks are broad, shallow zigzags.  The broad width and low height keep
    # this from stealing slashes or the longer structural diagonals.
    if 4 <= height <= 8 and width >= 7 and len(xs) >= 10:
        centers = []
        for row in np.where(row_counts > 0)[0]:
            row_xs = np.where(mask[row])[0]
            centers.append(float(row_xs.mean()))
        if centers and max(centers) - min(centers) >= 1.0:
            return "~", 0.9, "geometry_tilde"

    # A short, slanted mark at the top or bottom of a cell is an apostrophe or comma.  Keep
    # horizontal fragments on the dash/period path above; they are often neighbouring strokes.
    if 4 <= height <= 7 and width <= 8 and len(xs) >= 4:
        slope = np.polyfit(ys, xs, 1)[0] if len(xs) > 1 else 0.0
        if abs(slope) >= 0.15:
            # Small quote marks sit above the baseline but can be several pixels below the
            # crop's top when the source has fractional row spacing.  Full-height diagonals
            # have already been handled above, so this relaxed upper band remains bounded.
            if top <= mask.shape[0] // 3 and bottom < mask.shape[0] - 4:
                return "'", 0.90, "geometry_apostrophe"
            if bottom >= mask.shape[0] - 4:
                return ",", 0.90, "geometry_comma"
        # Do not promote a broad top fragment to an apostrophe.  The old terminal shortcut
        # converted long horizontal strokes into a false definite glyph; split terminals are
        # handled by geometry_split_apostrophe above.

    # Brackets have two broad horizontal terminals and a one-sided vertical stem.
    if height >= 10:
        terminal_width = max(4, int(width * 0.8))
        top_rows = np.where(row_counts[top : min(height, top + 3)] >= terminal_width)[0]
        bottom_rows = np.where(row_counts[max(top, bottom - 2) : bottom + 1] >= terminal_width)[0]
        if len(top_rows) and len(bottom_rows):
            middle_rows = mask[min(mask.shape[0], top + 2) : max(0, bottom - 1)]
            middle = middle_rows.sum(axis=0) if middle_rows.size else np.array([], dtype=int)
            if middle.size and middle.any():
                stem = int(np.argmax(middle))
                return ("[" if stem < (left + right) / 2 else "]"), 0.93, "geometry_bracket"

    # Parentheses are curved: their centre moves inward through the middle rows and back out.
    if height >= 10 and width >= 4 and original_component_count == 1 and not original_edge_contacts:
        def band_center(start: int, end: int) -> float:
            band = np.where(mask[start:end])[1]
            return float(band.mean()) if len(band) else float((left + right) / 2)

        top_center = band_center(top, min(bottom + 1, top + 4))
        mid_center = band_center(top + height // 3, min(bottom + 1, top + (2 * height) // 3 + 1))
        bottom_center = band_center(max(top, bottom - 3), bottom + 1)
        if abs(top_center - bottom_center) < 2.0 and abs(mid_center - top_center) >= 0.8:
            return (")" if mid_center > top_center else "("), 0.92, "geometry_parenthesis"

    # Equals has two separated long horizontal strokes, unlike a single dash/underscore.
    if len(strong_groups) >= 2 and width >= 4 and height <= 10:
        return "=", 0.9, "geometry_equals"

    if width <= 3 and height >= 7:
        return "|", 0.9, "geometry_vertical"
    if len(strong_rows) and width >= 4 and height <= 3 and original_component_count == 1:
        max_row = int(row_counts.max())
        horizontal_band = max_row >= max(4, int(np.ceil(width * 0.80)))
        if horizontal_band:
            band_center = float(ys.mean() + 0.5)
            if band_center <= baseline - 2:
                return "-", 0.90, "geometry_horizontal"
            if band_center >= baseline + 2:
                return "_", 0.90, "geometry_horizontal"
            return None, 0.0, "geometry_middle_horizontal_ambiguous"
    if height >= 7 and width >= 4 and len(components) == 1:
        slope = np.polyfit(ys, xs, 1)[0]
        residual = float(np.mean(np.abs(xs - (slope * ys + np.mean(xs - slope * ys)))))
        # A short crop-edge leg is not enough evidence for a slash.  Keep full-height
        # diagonals, but fail closed on the common 12-pixel edge fragments; those must be
        # resolved by a later calibration/ownership change rather than guessed here.
        edge_fragment_diagonal = (top == 0 or bottom == mask.shape[0] - 1) and height < 13
        if residual < 2.8 and abs(slope) >= 0.12 and not edge_fragment_diagonal:
            return ("\\" if slope > 0 else "/"), 0.88, "geometry_diagonal"

    # Split diagonals are deliberately not auto-recognized.  A crop boundary can make two
    # unrelated strokes look like one slash, and the previous fit was a source of false-zero
    # transcripts.  They remain visible in cell evidence and become `?` until ownership is
    # proven by calibration.
    return None, 0.0, "geometry_ambiguous"


def remove_repeating_guides(mask: np.ndarray, columns: list[int]) -> None:
    for column in columns:
        if 0 <= column < mask.shape[1]:
            mask[:, column] = False


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--calibration", type=Path, required=True)
    parser.add_argument("--phase", choices=("occupancy", "review", "recognize"), default="recognize")
    parser.add_argument("--occupancy-map", type=Path)
    parser.add_argument("--occupancy-review", type=Path)
    parser.add_argument("--render-font-path", type=str)
    parser.add_argument("--render-font-size", type=int)
    parser.add_argument("--render-origin-offset", type=float, default=0.0)
    parser.add_argument("--render-baseline-offset", type=float, default=0.0)
    parser.add_argument(
        "--render-line-height",
        type=float,
        help="explicit diagnostic renderer line height; does not change the OCR lattice",
    )
    parser.add_argument(
        "--render-supersample",
        type=int,
        default=1,
        help="diagnostic renderer supersampling factor before source-sized downsampling",
    )
    args = parser.parse_args()

    if args.phase == "recognize":
        raise SystemExit(
            "the legacy cell recognizer is diagnostic-only; --phase recognize cannot author "
            "a canonical candidate. Use the lateletter transcription orchestrator."
        )

    source = args.source.resolve()
    output = args.output.resolve()
    calibration_path = args.calibration.resolve()
    calibration = json.loads(calibration_path.read_text(encoding="utf-8"))
    actual_hash = sha256(source)
    if actual_hash != calibration["source_sha256"]:
        raise SystemExit("source hash differs from calibration; refusing OCR")
    output.mkdir(parents=True, exist_ok=True)
    forbidden = [output / name for name in ("machine-cell-ocr.txt", "cell-recognition.json", "manifest.json")]
    existing = [path.name for path in forbidden if path.exists()]
    if existing:
        raise SystemExit(f"refusing to overwrite existing attempt files: {', '.join(existing)}")

    occupancy_map_path = (args.occupancy_map or (output / "occupancy-map.json")).resolve()
    occupancy_review_path = (args.occupancy_review or (output / "occupancy-review.json")).resolve()
    if args.phase == "review":
        if not occupancy_map_path.exists():
            raise SystemExit(f"occupancy map is required before review: {occupancy_map_path}")
        occupancy = json.loads(occupancy_map_path.read_text(encoding="utf-8"))
        grid = calibration["grid"]
        expected_cells = int(grid["columns"]) * int(grid["rows"])
        records = occupancy.get("cells", [])
        identities = {(item.get("row"), item.get("column")) for item in records}
        if occupancy.get("source_sha256") != actual_hash:
            raise SystemExit("occupancy map source hash differs from source")
        if len(records) != expected_cells or len(identities) != expected_cells:
            raise SystemExit("occupancy map does not contain one unique record per declared cell")
        if occupancy.get("calibration_sha256") != sha256(calibration_path):
            raise SystemExit("occupancy map calibration hash differs from calibration")
        review = {
            "reviewer": "occupancy-validator",
            "verdict": "machine_reviewed",
            "source_sha256": actual_hash,
            "occupancy_map": os.path.relpath(occupancy_map_path, output),
            "occupancy_map_sha256": sha256(occupancy_map_path),
            "checks": {"unique_cell_records": True, "declared_dimensions": True, "source_hash": True, "calibration_hash": True},
            "note": "This structural review is not operator visual acceptance and does not promote a transcript.",
        }
        if occupancy_review_path.exists():
            raise SystemExit(f"refusing to overwrite occupancy review: {occupancy_review_path}")
        occupancy_review_path.write_text(json.dumps(review, indent=2) + "\n", encoding="utf-8")
        return

    if args.phase == "recognize":
        if not occupancy_map_path.exists() or not occupancy_review_path.exists():
            raise SystemExit("recognition requires a prior occupancy map and occupancy review phase")
        review = json.loads(occupancy_review_path.read_text(encoding="utf-8"))
        if review.get("verdict") != "machine_reviewed" or review.get("occupancy_map_sha256") != sha256(occupancy_map_path):
            raise SystemExit("occupancy review is missing, stale, or not machine-reviewed")

    with Image.open(source) as opened:
        image = opened.convert("RGB")
    pixels = np.asarray(image)
    bg = np.asarray(calibration["canvas"]["background_rgb"])
    ink = np.max(np.abs(pixels.astype(int) - bg), axis=2) > calibration["normalization"]["ink_threshold_l1"]
    remove_repeating_guides(ink, calibration.get("guide_columns_px", []))
    grid = calibration["grid"]
    columns, rows = int(grid["columns"]), int(grid["rows"])
    origin = float(grid["origin_x_px"])
    first_baseline = float(grid["first_baseline_y_px"])
    advance_x = float(grid["cell_advance_x_px"])
    advance_y = float(grid["line_height_px"])
    top_offset = int(grid["cell_crop_top_offset_px"])
    bottom_offset = int(grid["cell_crop_bottom_offset_px"])
    result = [[" " for _ in range(columns)] for _ in range(rows)]
    evidence: list[dict[str, object]] = []
    occupancy_records: list[dict[str, object]] = []
    height, width = ink.shape
    options = ["tesseract", "--psm", "10"]

    with tempfile.TemporaryDirectory(prefix="lateletter-cell-ocr-") as temp_dir:
        temp = Path(temp_dir) / "cell.png"
        for row in range(rows):
            baseline = first_baseline + row * advance_y
            y0, y1 = round(baseline + top_offset), round(baseline + bottom_offset)
            for column in range(columns):
                x0 = round(origin + column * advance_x)
                x1 = round(origin + (column + 1) * advance_x)
                in_canvas = not (x1 <= 0 or x0 >= width or y1 <= 0 or y0 >= height)
                xa, xb = max(0, x0), min(width, x1)
                ya, yb = max(0, y0), min(height, y1)
                if not in_canvas or xa >= xb or ya >= yb:
                    occupancy_records.append(
                        {"row": row, "column": column, "in_canvas": False, "occupied": False, "ink_pixels": 0}
                    )
                    evidence.append(
                        {
                            "row": row,
                            "column": column,
                            "in_canvas": False,
                            "ink_pixels": 0,
                            "raw": "",
                            "geometric": None,
                            "glyph": " ",
                            "confidence": 1.0,
                            "confidence_method": "outside_canvas_blank",
                            "topology": topology(np.zeros((1, 1), dtype=bool)),
                            "topology_signature": "blank",
                            "proposed_glyph": " ",
                            "alternatives": [],
                            "rejection_reason": None,
                        }
                    )
                    continue
                cell_mask = ink[ya:yb, xa:xb]
                ink_pixels = int(cell_mask.sum())
                occupancy_records.append(
                    {"row": row, "column": column, "in_canvas": True, "occupied": bool(ink_pixels), "ink_pixels": ink_pixels}
                )
                if not cell_mask.any():
                    evidence.append(
                        {
                            "row": row,
                            "column": column,
                            "in_canvas": True,
                            "ink_pixels": 0,
                            "raw": "",
                            "geometric": " ",
                            "glyph": " ",
                            "confidence": 1.0,
                            "confidence_method": "binary_blank",
                            "topology": topology(cell_mask),
                            "topology_signature": "blank",
                            "proposed_glyph": " ",
                            "alternatives": [],
                            "rejection_reason": None,
                        }
                    )
                    continue

                if args.phase == "occupancy":
                    # This phase deliberately stops after segmentation. No transcript or OCR
                    # proposal is produced until the separate review phase has run.
                    continue

                shape = topology(cell_mask)
                signature = str(shape["signature"])
                geometric, geometric_confidence, geometry_method = classify_shape(cell_mask, baseline - y0)
                raw = ""
                alternatives: list[str] = []
                rejection_reasons: list[str] = []
                spill_proven = edge_fragment(cell_mask) and neighbouring_ownership_proven(
                    ink, x0, x1, y0, y1, cell_mask
                )
                row_spill_proven = row_continuation_proven(ink, x0, x1, y0, cell_mask)
                bidirectional_spill_proven = bidirectional_row_spill_proven(
                    ink, x0, x1, y0, y1, cell_mask
                )
                if bidirectional_spill_proven:
                    glyph, confidence, confidence_method = " ", 0.95, "bidirectional_row_spill_proven"
                    geometric = " "
                    geometry_method = confidence_method
                elif row_spill_proven and (
                    geometric is None
                    or geometry_method
                    in {"geometry_period", "geometry_split_apostrophe", "geometry_ambiguous"}
                ):
                    glyph, confidence, confidence_method = " ", 0.95, "row_boundary_spill_proven"
                    geometric = " "
                    geometry_method = confidence_method
                elif edge_fragment(cell_mask) and spill_proven:
                    glyph, confidence, confidence_method = " ", 0.95, "boundary_sidebearing_fragment_proven"
                    geometric = " "
                    geometry_method = confidence_method
                elif edge_fragment(cell_mask) and not spill_proven:
                    glyph, confidence, confidence_method = "?", 0.0, "boundary_sidebearing_unproven"
                    geometric = None
                    rejection_reasons.append("unproven_edge_fragment")
                elif geometric is not None:
                    glyph, confidence, confidence_method = geometric, geometric_confidence, geometry_method
                    if glyph in ("-", "_"):
                        alternatives = ["-", "_"]
                    elif glyph in ("/", "\\"):
                        alternatives = ["/", "\\"]
                    elif glyph in ("'", ","):
                        alternatives = ["'", ","]
                else:
                    prepared = Image.fromarray(np.where(cell_mask, 0, 255).astype(np.uint8))
                    prepared = prepared.resize((prepared.width * 12, prepared.height * 12), Image.Resampling.NEAREST)
                    framed = Image.new("L", (prepared.width + 24, prepared.height + 24), 255)
                    framed.paste(prepared, (12, 12))
                    framed.save(temp)
                    run = subprocess.run(
                        ["tesseract", str(temp), "stdout", "--psm", "10"],
                        check=True,
                        capture_output=True,
                        text=True,
                    )
                    raw = run.stdout.strip()
                    glyph = normalize(raw, np.where(cell_mask)[0] + ya, baseline)
                    alternatives = [glyph] if glyph != "?" else []
                    confidence = 0.25 if glyph != "?" else 0.0
                    confidence_method = "tesseract_restricted_alphabet" if glyph != "?" else "unresolved"
                proposed_glyph = glyph
                if glyph == "?":
                    rejection_reasons.append("unresolved")
                if confidence < MIN_CONFIDENCE and glyph != " ":
                    rejection_reasons.append("low_confidence")
                    glyph = "?"
                result[row][column] = glyph
                evidence.append(
                    {
                        "row": row,
                        "column": column,
                        "in_canvas": True,
                        "ink_pixels": ink_pixels,
                        "raw": raw,
                        "geometric": geometric,
                        "glyph": glyph,
                        "proposed_glyph": proposed_glyph,
                        "confidence": confidence,
                        "confidence_method": confidence_method,
                        "alternatives": alternatives,
                        "topology": shape,
                        "topology_signature": signature,
                        "rejection_reason": rejection_reasons or None,
                    }
                )

    if args.phase == "occupancy":
        occupancy = {
            "format": "lateletter-occupancy-v1",
            "source_sha256": actual_hash,
            "calibration_sha256": sha256(calibration_path),
            "grid": {"columns": columns, "rows": rows, "origin_x_px": origin, "first_baseline_y_px": first_baseline, "advance_x_px": advance_x, "advance_y_px": advance_y},
            "cells": occupancy_records,
            "status": "awaiting_review",
        }
        if occupancy_map_path.exists():
            raise SystemExit(f"refusing to overwrite occupancy map: {occupancy_map_path}")
        occupancy_map_path.write_text(json.dumps(occupancy, indent=2) + "\n", encoding="utf-8")
        return

    raise SystemExit("no authoritative recognition phase exists in this legacy adapter")


if __name__ == "__main__":
    main()
