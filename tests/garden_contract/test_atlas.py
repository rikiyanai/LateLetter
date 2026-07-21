from copy import deepcopy

import pytest

from lateletter.garden.atlas import (
    AtlasValidationError, REQUIRED_COLLECTIBLES, REQUIRED_CONNECTED_FAMILIES,
    REQUIRED_FIXTURES, UNICODE_DATA_VERSION, grapheme_cells, load_atlas,
    validate_atlas,
)


def test_bundled_atlas_has_required_assets_fallbacks_and_all_connected_masks():
    atlas = load_atlas()
    ids = {asset["id"] for asset in atlas["assets"]}
    assert REQUIRED_FIXTURES <= ids
    assert REQUIRED_COLLECTIBLES <= ids
    assert REQUIRED_CONNECTED_FAMILIES <= set(atlas["connected_tiles"])
    assert all(set(masks) == {str(index) for index in range(16)}
               for masks in atlas["connected_tiles"].values())
    assert all("ascii-safe" in asset["profiles"] for asset in atlas["assets"])
    assert atlas["unicode_version"] == UNICODE_DATA_VERSION


def test_grapheme_segmentation_and_terminal_width_are_validated():
    assert grapheme_cells("e\u0301") == ("e\u0301",)
    atlas = load_atlas()
    multiple = deepcopy(atlas)
    multiple["assets"][0]["profiles"]["unicode-cell-safe"] = {
        "idle": [{"ticks": 1, "cells": [["ab"]]}],
    }
    with pytest.raises(AtlasValidationError, match="exactly one grapheme"):
        validate_atlas(multiple)

    wide = deepcopy(atlas)
    wide["assets"][0]["profiles"]["unicode-cell-safe"] = {
        "idle": [{"ticks": 1, "cells": [["界"]]}],
    }
    with pytest.raises(AtlasValidationError, match="exactly one column"):
        validate_atlas(wide)


def test_atlas_rejects_unsafe_control_private_use_and_width_drift():
    atlas = load_atlas()
    unsafe = deepcopy(atlas)
    unsafe["assets"][0]["profiles"]["ascii-safe"]["idle"][0]["cells"] = [["\x1b"]]
    with pytest.raises(AtlasValidationError):
        validate_atlas(unsafe)

    private = deepcopy(atlas)
    private["assets"][0]["profiles"]["unicode-cell-safe"] = {
        "idle": [{"ticks": 1, "cells": [["\ue000"]]}],
    }
    with pytest.raises(AtlasValidationError):
        validate_atlas(private)

    drift = deepcopy(atlas)
    drift["assets"][0]["profiles"]["ascii-safe"]["idle"][0]["cells"] = [["=", "="]]
    with pytest.raises(AtlasValidationError):
        validate_atlas(drift)
