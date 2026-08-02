#!/usr/bin/env python3
"""Render one text-transcription parity package at source-PNG pixel geometry.

The manifest deliberately contains all placement inputs.  This tool never estimates a grid,
rescales a source, or declares a transcription accepted: it only creates repeatable comparison
surfaces for an already recorded candidate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def rgba(value: str) -> tuple[int, int, int, int]:
    raw = value.lstrip("#")
    if len(raw) == 6:
        raw += "ff"
    if len(raw) != 8:
        raise ValueError(f"colour must be RRGGBB or RRGGBBAA, got {value!r}")
    return tuple(int(raw[index : index + 2], 16) for index in range(0, 8, 2))  # type: ignore[return-value]


def relative_luminance(colour: tuple[int, int, int, int]) -> float:
    channels = []
    for channel in colour[:3]:
        value = channel / 255.0
        channels.append(value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4)
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def contrast_ratio(foreground: tuple[int, int, int, int], background: tuple[int, int, int, int]) -> float:
    first, second = relative_luminance(foreground), relative_luminance(background)
    lighter, darker = max(first, second), min(first, second)
    return (lighter + 0.05) / (darker + 0.05)


def ink_mask(image: Image.Image, background: tuple[int, int, int, int], threshold: int = 25):
    pixels = image.convert("RGB")
    import numpy as np

    values = np.asarray(pixels).astype(int)
    bg = np.asarray(background[:3], dtype=int)
    return np.max(np.abs(values - bg), axis=2) > threshold


def comparison_surface(
    source: Image.Image,
    rendered: Image.Image,
    source_background,
    rendered_background,
    *,
    show_shared: bool,
):
    """Build a high-contrast colour diagnostic instead of a dim raw delta image."""
    import numpy as np

    source_ink = ink_mask(source, source_background)
    candidate_ink = ink_mask(rendered, rendered_background)
    output = np.full((source.height, source.width, 4), 255, dtype=np.uint8)
    shared = source_ink & candidate_ink
    source_only = source_ink & ~candidate_ink
    candidate_only = ~source_ink & candidate_ink
    output[shared] = (78, 32, 112, 255) if show_shared else (255, 255, 255, 255)  # both layers
    output[source_only] = (205, 36, 42, 255)  # source only: red
    output[candidate_only] = (0, 118, 190, 255)  # candidate only: blue
    return Image.fromarray(output, mode="RGBA")


def resampling_filter(name: str):
    try:
        return {
            "lanczos": Image.Resampling.LANCZOS,
            "bicubic": Image.Resampling.BICUBIC,
            "bilinear": Image.Resampling.BILINEAR,
            "box": Image.Resampling.BOX,
        }[name.lower()]
    except KeyError as exc:
        raise SystemExit(f"unsupported resample_filter {name!r}") from exc


def comparison_receipt(
    manifest: dict[str, object], *, artifacts: dict[str, str], **details: object
) -> dict[str, object]:
    """Build a standalone comparison receipt; never mutate candidate authority."""
    return {
        "format": "lateletter-comparison-receipt-v1",
        "candidate_manifest": str(manifest.get("manifest", "legacy-input")),
        "candidate_bundle_hash": manifest.get("candidate_bundle_hash"),
        "artifacts": dict(artifacts),
        **details,
    }


def mark_comparison_pending(manifest: dict[str, object]) -> None:
    """Legacy in-memory diagnostic helper; the renderer no longer calls it.

    It remains for historical tests and callers that only build a display
    projection.  ``main`` writes a standalone comparison receipt and never
    passes the candidate manifest through this mutator.
    """
    review = manifest.setdefault("review", {})
    if not isinstance(review, dict):
        raise ValueError("manifest review must be an object")
    if review.get("verdict") in (None, "not_reviewed", "pending", "rejected_nonzero_diff"):
        review["human_visual_parity"] = "pending_operator_structural_review"
        review["verdict"] = "pending_operator_structural_review"
        if manifest.get("status") in ("machine_candidate_only", "machine_candidate_pending_operator_review"):
            manifest["status"] = "comparison_rendered_pending_operator_review"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()

    manifest_path = args.manifest.resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    root = manifest_path.parent

    source = (root / manifest["source_png"]).resolve()
    transcript = (root / manifest["transcript"]).resolve()
    expected_hash = manifest["source_sha256"]
    actual_hash = sha256(source)
    if actual_hash != expected_hash:
        raise SystemExit(
            f"source hash mismatch: manifest={expected_hash}, actual={actual_hash}; refusing render"
        )
    expected_transcript_hash = manifest.get("transcript_sha256")
    if not expected_transcript_hash:
        raise SystemExit("transcript hash missing; refusing to render an unbound candidate")
    actual_transcript_hash = sha256(transcript)
    if actual_transcript_hash != expected_transcript_hash:
        raise SystemExit(
            "transcript hash mismatch: "
            f"manifest={expected_transcript_hash}, actual={actual_transcript_hash}; refusing render"
        )
    lines = transcript.read_text(encoding="utf-8").splitlines()
    declared_grid = manifest.get("grid", {})
    declared_columns = int(declared_grid.get("columns", 0))
    declared_rows = int(declared_grid.get("rows", 0))
    if declared_rows and len(lines) != declared_rows:
        raise SystemExit(f"transcript has {len(lines)} rows; manifest declares {declared_rows}")
    if declared_columns and any(len(line) != declared_columns for line in lines):
        raise SystemExit("transcript row width differs from the hash-bound manifest grid")
    blocked_counts = {
        key: int(manifest.get(key, 0) or 0)
        for key in ("unknown_cells", "low_confidence_cells", "structural_conflicts", "forced_blank_conflicts")
    }
    if any(blocked_counts.values()):
        raise SystemExit(f"machine recognition gate is not clear; refusing comparison render: {blocked_counts}")

    with Image.open(source) as original:
        source_image = original.convert("RGBA")
    canvas = manifest["canvas"]
    expected_size = (canvas["width_px"], canvas["height_px"])
    if source_image.size != expected_size:
        raise SystemExit(f"source is {source_image.size}, manifest declares {expected_size}")

    placement = manifest["placement"]
    renderer_configuration = manifest.get("renderer_configuration", {})
    if any(
        key in renderer_configuration
        for key in ("source_png", "source_pixels", "source_stencil", "source_cell_stencil")
    ) or "source.normalized.png" in json.dumps(renderer_configuration):
        raise SystemExit("source pixels are forbidden in a genuine parity rerender")
    supersample = int(placement.get("supersample", 1))
    if supersample < 1:
        raise SystemExit("supersample must be >= 1")
    font_path = placement.get("font_path")
    font = (
        ImageFont.truetype(font_path, int(round(placement["font_size_px"] * supersample)))
        if font_path
        else ImageFont.load_default()
    )
    glyph_advance = placement.get("glyph_advance_px")
    background_rgba = rgba(canvas["background_rgba"])
    foreground_rgba = rgba(placement["foreground_rgba"])
    ratio = contrast_ratio(foreground_rgba, background_rgba)
    if ratio < 4.5:
        raise SystemExit(
            "foreground/background contrast is too low for review: "
            f"{placement['foreground_rgba']} on {canvas['background_rgba']} gives {ratio:.2f}:1"
        )
    render_size = (expected_size[0] * supersample, expected_size[1] * supersample)
    rendered_hi = Image.new("RGBA", render_size, background_rgba)
    drawer = ImageDraw.Draw(rendered_hi)
    for row, line in enumerate(lines):
        baseline = (
            placement["first_baseline_y_px"] + row * placement["line_height_px"]
        ) * supersample
        if glyph_advance is None:
            drawer.text(
                (placement["origin_x_px"] * supersample, baseline),
                line,
                font=font,
                fill=foreground_rgba,
                anchor="ls",
                spacing=0,
            )
        else:
            for column, grapheme in enumerate(line):
                drawer.text(
                    (
                        (placement["origin_x_px"] + column * glyph_advance) * supersample,
                        baseline,
                    ),
                    grapheme,
                    font=font,
                    fill=foreground_rgba,
                    anchor="ls",
                    spacing=0,
                )

    resample_name = str(placement.get("resample_filter", "lanczos"))
    rendered = (
        rendered_hi.resize(expected_size, resampling_filter(resample_name)).convert("RGBA")
        if supersample > 1
        else rendered_hi
    )

    artifacts = manifest["artifacts"]
    rerender_path = root / artifacts["rerender_png"]
    overlay_path = root / artifacts["overlay_png"]
    diff_path = root / artifacts["diff_png"]
    rerender_path.parent.mkdir(parents=True, exist_ok=True)
    existing_artifacts = [path for path in (rerender_path, overlay_path, diff_path) if path.exists()]
    if existing_artifacts:
        names = ", ".join(str(path.relative_to(root)) for path in existing_artifacts)
        raise SystemExit(f"refusing to overwrite immutable parity artifacts: {names}")

    # Both operands have the source dimensions.  Deliberately do not resize either image.
    rendered.save(rerender_path)
    # The previous 50/50 white blend and raw ImageChops difference made dark mismatches
    # nearly invisible.  Both review artifacts now use the same explicit source/candidate
    # ink coding: violet = shared, red = source-only, blue = candidate-only.
    diagnostic = comparison_surface(
        source_image,
        rendered,
        background_rgba,
        background_rgba,
        show_shared=True,
    )
    diagnostic.save(overlay_path)
    comparison_surface(
        source_image,
        rendered,
        background_rgba,
        background_rgba,
        show_shared=False,
    ).save(diff_path)

    # A rendered package is not a parity pass merely because the PNGs exist.  Record the
    # source/candidate mask counts in the immutable manifest on this one render transaction so
    # a caller cannot mistake a visible diff for a completed step.  The mask deliberately uses
    # the same threshold as the diagnostic surfaces.
    source_ink = ink_mask(source_image, background_rgba)
    candidate_ink = ink_mask(rendered, background_rgba)
    import numpy as np

    source_only = int(np.logical_and(source_ink, ~candidate_ink).sum())
    candidate_only = int(np.logical_and(~source_ink, candidate_ink).sum())
    diff_pixel_count = source_only + candidate_only
    raw_pixel_diff_count = int(
        np.any(np.asarray(source_image) != np.asarray(rendered), axis=2).sum()
    )

    # Residuals are tied to the *calibration* lattice so a renderer experiment cannot
    # move a disagreement into a different cell by changing its presentation origin,
    # baseline, or line height.  The candidate placement above is deliberately allowed
    # to vary; attribution is not.  This distinction is essential when a glyph crosses a
    # render cell boundary or when a fractional renderer baseline is being probed.
    manifest_grid = manifest.get("grid", {})
    calibration_grid = {}
    calibration_path_value = manifest.get("calibration", {}).get("path")
    calibration_path = (root / calibration_path_value).resolve() if calibration_path_value else None
    if calibration_path and calibration_path.exists():
        calibration_payload = json.loads(calibration_path.read_text(encoding="utf-8"))
        expected_calibration_hash = manifest.get("calibration", {}).get("sha256")
        if expected_calibration_hash and sha256(calibration_path) != expected_calibration_hash:
            raise SystemExit("calibration hash differs from manifest; refusing residual attribution")
        calibration_grid = calibration_payload.get("grid", {})
    columns = int(calibration_grid.get("columns", manifest_grid.get("columns", max((len(line) for line in lines), default=0))))
    rows = int(calibration_grid.get("rows", manifest_grid.get("rows", len(lines))))
    calibration_origin_x = float(
        calibration_grid.get("origin_x_px", manifest_grid.get("origin_x_px", 0))
    )
    calibration_first_baseline = float(
        calibration_grid.get("first_baseline_y_px", manifest_grid.get("first_baseline_y_px", 0))
    )
    advance_x = float(
        calibration_grid.get("cell_advance_x_px", manifest_grid.get("advance_x_px", 0))
    )
    advance_y = float(
        calibration_grid.get("line_height_px", manifest_grid.get("advance_y_px", 0))
    )
    crop_top = float(calibration_grid.get("cell_crop_top_offset_px", -12))
    crop_bottom = float(calibration_grid.get("cell_crop_bottom_offset_px", 9))
    cell_residuals = []
    for row in range(min(rows, len(lines))):
        for column in range(columns):
            x0 = round(calibration_origin_x + column * advance_x)
            x1 = round(calibration_origin_x + (column + 1) * advance_x)
            y0 = round(calibration_first_baseline + row * advance_y + crop_top)
            y1 = round(calibration_first_baseline + row * advance_y + crop_bottom)
            x0, x1 = max(0, x0), min(expected_size[0], x1)
            y0, y1 = max(0, y0), min(expected_size[1], y1)
            if x0 >= x1 or y0 >= y1:
                continue
            source_cell = source_ink[y0:y1, x0:x1]
            candidate_cell = candidate_ink[y0:y1, x0:x1]
            source_only_cell = int(np.logical_and(source_cell, ~candidate_cell).sum())
            candidate_only_cell = int(np.logical_and(~source_cell, candidate_cell).sum())
            raw_cell = int(
                np.any(
                    np.asarray(source_image)[y0:y1, x0:x1]
                    != np.asarray(rendered)[y0:y1, x0:x1],
                    axis=2,
                ).sum()
            )
            if source_only_cell or candidate_only_cell or raw_cell:
                cell_residuals.append(
                    {
                        "row": row,
                        "column": column,
                        "char": lines[row][column] if column < len(lines[row]) else "",
                        "source_only": source_only_cell,
                        "candidate_only": candidate_only_cell,
                        "mask_diff": source_only_cell + candidate_only_cell,
                        "raw_pixel_diff": raw_cell,
                    }
                )

    parity = {
        "mask_threshold": 25,
        "diff_pixel_count": diff_pixel_count,
        "source_only_pixels": source_only,
        "candidate_only_pixels": candidate_only,
        "raw_pixel_diff_count": raw_pixel_diff_count,
        # Pixel equality belongs to optional forensic raster parity.  The source face is often
        # unavailable, so a nonzero comparison-font residual must not reject the TXT candidate.
        "zero_diff_required": False,
        "pixel_exact": diff_pixel_count == 0,
        "font_independent_structural_review_required": True,
        "source_pixels_used_in_candidate": False,
        "resample_filter": resample_name,
        "residual_grid_model": "calibration_cell_boundaries",
        "residual_grid": {
            "columns": columns,
            "rows": rows,
            "origin_x_px": calibration_origin_x,
            "first_baseline_y_px": calibration_first_baseline,
            "advance_x_px": advance_x,
            "advance_y_px": advance_y,
            "crop_top_offset_px": crop_top,
            "crop_bottom_offset_px": crop_bottom,
            "calibration": str(calibration_path.relative_to(root)) if calibration_path and calibration_path.is_relative_to(root) else None,
        },
        "per_cell_residual_count": len(cell_residuals),
        "per_cell_residuals": cell_residuals,
    }
    receipt_path = root / "comparison-receipt.json"
    if receipt_path.exists():
        raise SystemExit(f"refusing to overwrite immutable comparison receipt: {receipt_path}")
    receipt = comparison_receipt(
        manifest,
        artifacts={
            "rerender": sha256(rerender_path),
            "overlay": sha256(overlay_path),
            "diff": sha256(diff_path),
        },
        source_sha256=actual_hash,
        transcript_sha256=actual_transcript_hash,
        parity=parity,
        operator_review="pending",
    )
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "status": "comparison_rendered_pending_operator_review",
                "diff_pixel_count": diff_pixel_count,
                "source_only_pixels": source_only,
                "candidate_only_pixels": candidate_only,
            }
        )
    )


if __name__ == "__main__":
    main()
