"""Complete-image component extraction with stable, glyph-free ownership evidence."""

from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np

from .hashing import require_sha256, sha256_bytes
from .model import InkComponent
from .schema import canonical_bytes


def _connected_components(mask: np.ndarray) -> list[list[tuple[int, int]]]:
    height, width = mask.shape
    seen = np.zeros_like(mask, dtype=bool)
    components: list[list[tuple[int, int]]] = []
    for y in range(height):
        for x in range(width):
            if not mask[y, x] or seen[y, x]:
                continue
            queue: deque[tuple[int, int]] = deque([(y, x)])
            seen[y, x] = True
            pixels: list[tuple[int, int]] = []
            while queue:
                cy, cx = queue.popleft()
                pixels.append((cy, cx))
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        if not dx and not dy:
                            continue
                        ny, nx = cy + dy, cx + dx
                        if 0 <= ny < height and 0 <= nx < width and mask[ny, nx] and not seen[ny, nx]:
                            seen[ny, nx] = True
                            queue.append((ny, nx))
            components.append(pixels)
    return components


def _row_candidates(y0: int, y1: int, row_bands: Iterable[Mapping[str, Any]] | None) -> tuple[int, ...]:
    if not row_bands:
        return ()
    result = []
    for band in row_bands:
        index = int(band.get("row_index", band.get("row", -1)))
        band_y0 = float(band.get("y0", band.get("top", 0)))
        band_y1 = float(band.get("y1", band.get("bottom", 0)))
        if y0 < band_y1 and y1 > band_y0:
            result.append(index)
    return tuple(sorted(set(result)))


def _run_candidates(x0: int, y0: int, x1: int, y1: int, anchors: Iterable[Mapping[str, Any]] | None) -> tuple[str, ...]:
    if not anchors:
        return ()
    result = []
    for index, anchor in enumerate(anchors):
        ax0 = float(anchor.get("start_x", anchor.get("x0", 0)))
        ax1 = float(anchor.get("end_x", anchor.get("x1", 0)))
        ay0 = float(anchor.get("y0", -float("inf")))
        ay1 = float(anchor.get("y1", float("inf")))
        if x0 < ax1 and x1 > ax0 and y0 < ay1 and y1 > ay0:
            result.append(str(anchor.get("run_id", f"run-{index:06d}")))
    return tuple(sorted(set(result)))


def extract_components(
    mask: np.ndarray,
    *,
    source_hash: str,
    row_bands: Iterable[Mapping[str, Any]] | None = None,
    run_anchors: Iterable[Mapping[str, Any]] | None = None,
    ignored_pixel_evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Extract stable 8-connected components without assigning characters."""

    require_sha256(source_hash, field="source_hash")
    if mask.ndim != 2 or mask.dtype != np.bool_:
        raise ValueError("mask must be a two-dimensional boolean array")
    height, width = mask.shape
    components: list[InkComponent] = []
    for component_number, pixels in enumerate(_connected_components(mask), start=1):
        ys = [item[0] for item in pixels]
        xs = [item[1] for item in pixels]
        x0, x1 = min(xs), max(xs) + 1
        y0, y1 = min(ys), max(ys) + 1
        local = np.zeros((y1 - y0, x1 - x0), dtype=np.uint8)
        local[np.asarray(ys) - y0, np.asarray(xs) - x0] = 1
        contacts = []
        if x0 == 0:
            contacts.append("left")
        if x1 == width:
            contacts.append("right")
        if y0 == 0:
            contacts.append("top")
        if y1 == height:
            contacts.append("bottom")
        component = InkComponent(
            component_id=f"c{component_number:06d}",
            x0=x0,
            y0=y0,
            x1=x1,
            y1=y1,
            mask_sha256=sha256_bytes(np.packbits(local.astype(bool), axis=None).tobytes()),
            edge_contacts=tuple(contacts),
            row_indices=_row_candidates(y0, y1, row_bands),
            candidate_row_indices=_row_candidates(y0, y1, row_bands),
            candidate_run_ids=_run_candidates(x0, y0, x1, y1, run_anchors),
            ignored_pixel_evidence=dict(ignored_pixel_evidence or {}),
            clipped=bool(contacts),
            substantive=True,
            input_hashes={"source": source_hash},
            provenance={"connectivity": 8, "bounds": "x1/y1-exclusive", "glyph_labels_emitted": False},
        )
        components.append(component)
    payload = [component.to_dict() for component in components]
    return {
        "source_sha256": source_hash,
        "canvas": {"width": width, "height": height},
        "components": components,
        "component_hash": sha256_bytes(canonical_bytes(payload)),
        "substantive_pixel_count": int(mask.sum()),
        "owned_pixel_count": int(mask.sum()),
        "ignored_pixel_evidence": dict(ignored_pixel_evidence or {}),
        "glyph_labels_emitted": False,
    }
