"""Component/preprocess ownership invariants."""

from __future__ import annotations

import numpy as np
import pytest

from lateletter.transcription.components import extract_components
from lateletter.transcription.preprocess import build_foreground_alternatives


H = "c" * 64


def test_preprocess_retains_foreground_alternatives_without_selecting_a_glyph() -> None:
    pixels = np.full((4, 5, 3), 255, dtype=np.uint8)
    pixels[1:3, 2] = (34, 37, 41)
    alternatives = build_foreground_alternatives(pixels, backgrounds=((255, 255, 255),), thresholds=(12, 50))
    assert len(alternatives) == 2
    assert all(item["selection"] == "unselected" for item in alternatives)
    assert all("mask_sha256" in item and item["mask"].dtype == np.bool_ for item in alternatives)


def test_components_are_stable_and_account_for_every_substantive_pixel() -> None:
    mask = np.zeros((6, 8), dtype=bool)
    mask[0:2, 0:2] = True
    mask[3, 3:6] = True
    mask[4:6, 7] = True
    bands = [{"row_index": 0, "y0": 0, "y1": 3}, {"row_index": 1, "y0": 3, "y1": 6}]
    first = extract_components(mask, source_hash=H, row_bands=bands, run_anchors=[{"run_id": "r1", "start_x": 0, "end_x": 8}])
    second = extract_components(mask.copy(), source_hash=H, row_bands=bands, run_anchors=[{"run_id": "r1", "start_x": 0, "end_x": 8}])
    assert [item.output_hash for item in first["components"]] == [item.output_hash for item in second["components"]]
    assert first["substantive_pixel_count"] == first["owned_pixel_count"] == int(mask.sum())
    assert first["glyph_labels_emitted"] is False
    assert first["components"][0].clipped is True
    assert first["components"][0].candidate_row_indices == (0,)
    assert first["components"][0].candidate_run_ids == ("r1",)


def test_component_extraction_rejects_non_boolean_masks_and_bad_source_hash() -> None:
    with pytest.raises(ValueError):
        extract_components(np.zeros((2, 2), dtype=np.uint8), source_hash=H)
    with pytest.raises(ValueError):
        extract_components(np.zeros((2, 2), dtype=bool), source_hash="bad")
