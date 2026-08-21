"""Raster preprocessing that retains foreground alternatives without naming glyphs."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np
from PIL import Image

from .hashing import require_sha256, sha256_bytes, sha256_file
from .schema import canonical_bytes


def load_rgb(path: str | Path, *, expected_sha256: str | None = None) -> tuple[np.ndarray, str]:
    path = Path(path)
    actual = sha256_file(path)
    if expected_sha256 is not None:
        require_sha256(expected_sha256, field="source_sha256")
        if actual != expected_sha256:
            raise ValueError(f"source hash mismatch: expected {expected_sha256}, got {actual}")
    with Image.open(path) as image:
        return np.asarray(image.convert("RGB")), actual


def build_foreground_alternatives(
    pixels: np.ndarray,
    *,
    backgrounds: Iterable[tuple[int, int, int]] = ((255, 255, 255), (0, 0, 0)),
    thresholds: Iterable[int] = (12, 25, 50),
) -> tuple[dict[str, Any], ...]:
    """Return every deterministic mask option; selection is a later evidence decision."""

    if pixels.ndim != 3 or pixels.shape[2] != 3:
        raise ValueError("pixels must be an HxWx3 RGB array")
    alternatives: list[dict[str, Any]] = []
    values = pixels.astype(np.int16)
    for background in backgrounds:
        bg = np.asarray(background, dtype=np.int16)
        distance = np.max(np.abs(values - bg), axis=2)
        for threshold in thresholds:
            if threshold < 0:
                raise ValueError("foreground threshold must be non-negative")
            mask = distance > threshold
            packed = np.packbits(mask, axis=None).tobytes()
            alternatives.append(
                {
                    "background_rgb": list(background),
                    "threshold": int(threshold),
                    "ink_pixels": int(mask.sum()),
                    "mask_sha256": sha256_bytes(packed),
                    "mask": mask,
                    "selection": "unselected",
                }
            )
    return tuple(alternatives)


def preprocess_source(
    path: str | Path,
    *,
    backgrounds: Iterable[tuple[int, int, int]] = ((255, 255, 255), (0, 0, 0)),
    thresholds: Iterable[int] = (12, 25, 50),
    expected_sha256: str | None = None,
) -> dict[str, Any]:
    pixels, source_hash = load_rgb(path, expected_sha256=expected_sha256)
    alternatives = build_foreground_alternatives(pixels, backgrounds=backgrounds, thresholds=thresholds)
    serializable = [
        {key: value for key, value in item.items() if key != "mask"}
        for item in alternatives
    ]
    return {
        "source_sha256": source_hash,
        "canvas": {"width": int(pixels.shape[1]), "height": int(pixels.shape[0])},
        "foreground_alternatives": serializable,
        "evidence_sha256": sha256_bytes(canonical_bytes(serializable)),
    }
