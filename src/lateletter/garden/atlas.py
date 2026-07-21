"""Versioned semantic atlas loading and portability validation."""

from __future__ import annotations

import json
from functools import lru_cache
from importlib.resources import files
from pathlib import Path
import unicodedata
from typing import Any, Mapping

import regex
from wcwidth import wcswidth


ATLAS_VERSION = "garden-atlas-1"
UNICODE_DATA_VERSION = "15.1.0"
REQUIRED_CONNECTED_FAMILIES = frozenset({"fence", "hedge", "path", "pond_edge", "wall"})
REQUIRED_FIXTURES = frozenset({
    "fixture.bench", "fixture.fence_gate", "fixture.sundial", "fixture.trellis",
    "fixture.birdbath", "fixture.lantern", "fixture.pond", "fixture.mailbox",
    "fixture.stepping_stones", "fixture.bridge", "fixture.planter",
    "fixture.table_chairs", "fixture.well", "fixture.arbor",
    "fixture.wind_chime", "fixture.shed_edge", "fixture.tool_rack",
    "fixture.watering_can", "fixture.compost", "fixture.basket", "fixture.sign",
    "fixture.memorial_stone",
})
REQUIRED_COLLECTIBLES = frozenset({
    "collectible.pressed_flower", "collectible.feather",
    "collectible.seed_packet", "collectible.smooth_stone",
})

_UNSAFE_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Co", "Cn"})
_BIDI_UNSAFE = frozenset({"RLE", "LRE", "RLO", "LRO", "PDF", "RLI", "LRI", "FSI", "PDI"})
_TERMINAL_PROFILES = frozenset({"ascii-safe", "unicode-cell-safe"})

@lru_cache(maxsize=1)
def _semantic_tokens() -> Mapping[str, Any]:
    return load_atlas()["semantic_tokens"]


def animal_glyph(species_id: str, bond_tier: int, *, choreography: bool = False) -> str:
    values = _semantic_tokens()["animal_tier_glyphs"].get(
        species_id, ("a", "A", "a", "A"),
    )
    glyph = values[max(0, min(3, int(bond_tier)))]
    return glyph.upper() if choreography else glyph


def organ_glyph(kind: str, glyph_family: str = "") -> str:
    if "bloom" in glyph_family:
        return "@"
    if "leaf" in glyph_family or glyph_family in {"needle", "blade"}:
        return "*"
    return str(_semantic_tokens()["organ_kind_glyphs"].get(kind, "*"))


def atlas_asset_frame(asset: Mapping[str, Any], state: str = "idle",
                      profile: str = "ascii-safe") -> tuple[tuple[str, ...], ...]:
    states = asset["profiles"][profile]
    frames = states.get(state) or states.get("idle") or states[sorted(states)[0]]
    return tuple(tuple(str(cell) for cell in row) for row in frames[0]["cells"])


def grapheme_cells(value: str) -> tuple[str, ...]:
    """Segment text into Unicode extended grapheme clusters."""
    if not isinstance(value, str):
        raise TypeError("grapheme source must be text")
    return tuple(regex.findall(r"\X", value))


class AtlasValidationError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        self.errors = tuple(errors)
        super().__init__("Invalid garden atlas: " + "; ".join(errors))


def _validate_cell(cell: Any, profile: str, path: str, errors: list[str]) -> None:
    if not isinstance(cell, str) or not cell:
        errors.append(f"{path}: cell must be a non-empty grapheme string")
        return
    if unicodedata.normalize("NFC", cell) != cell:
        errors.append(f"{path}: cell must be NFC-normalized")
    clusters = grapheme_cells(cell)
    if len(clusters) != 1 or clusters[0] != cell:
        errors.append(f"{path}: cell must contain exactly one grapheme cluster")
    if profile == "ascii-safe":
        if len(cell) != 1 or not 32 <= ord(cell) <= 126:
            errors.append(f"{path}: ascii-safe cells must be one printable ASCII character")
        return
    if unicodedata.combining(cell[0]):
        errors.append(f"{path}: standalone combining marks are forbidden")
    unsafe_categories = {
        unicodedata.category(char) for char in cell
        if unicodedata.category(char) in _UNSAFE_CATEGORIES
    }
    if unsafe_categories:
        errors.append(f"{path}: unsafe Unicode category {sorted(unsafe_categories)[0]}")
    if any(unicodedata.bidirectional(char) in _BIDI_UNSAFE for char in cell):
        errors.append(f"{path}: bidirectional controls are forbidden")
    if profile in _TERMINAL_PROFILES:
        width = wcswidth(cell)
        if width != 1:
            errors.append(f"{path}: {profile} cells must occupy exactly one column")
        if profile == "unicode-cell-safe" and any(
                unicodedata.east_asian_width(char) == "A" for char in cell):
            errors.append(f"{path}: ambiguous-width characters need a separate profile")


def _validate_semantic_row(row: Any, path: str, errors: list[str]) -> None:
    """Validate a multi-cell semantic animation row without treating it as one cell."""
    if not isinstance(row, str) or not row:
        errors.append(f"{path}: row must be non-empty text")
        return
    if unicodedata.normalize("NFC", row) != row:
        errors.append(f"{path}: row must be NFC-normalized")
    clusters = grapheme_cells(row)
    if not clusters:
        errors.append(f"{path}: row must contain grapheme clusters")
        return
    for index, cluster in enumerate(clusters):
        cluster_path = f"{path}[{index}]"
        if unicodedata.combining(cluster[0]):
            errors.append(f"{cluster_path}: standalone combining marks are forbidden")
        unsafe_categories = {
            unicodedata.category(char) for char in cluster
            if unicodedata.category(char) in _UNSAFE_CATEGORIES
        }
        if unsafe_categories:
            errors.append(
                f"{cluster_path}: unsafe Unicode category {sorted(unsafe_categories)[0]}"
            )
        if any(unicodedata.bidirectional(char) in _BIDI_UNSAFE for char in cluster):
            errors.append(f"{cluster_path}: bidirectional controls are forbidden")
        if wcswidth(cluster) != 1:
            errors.append(f"{cluster_path}: semantic frame cells must occupy exactly one column")


def validate_atlas(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Validate an atlas and return a detached JSON-compatible copy."""
    errors: list[str] = []
    if not isinstance(raw, Mapping):
        raise AtlasValidationError(["$: atlas must be an object"])
    allowed_top = {"version", "id", "unicode_version", "profiles",
                   "semantic_tokens", "connected_tiles", "assets"}
    unknown = sorted(set(raw) - allowed_top)
    if unknown:
        errors.append(f"$: unknown fields {', '.join(unknown)}")
    if raw.get("version") != 1 or raw.get("id") != ATLAS_VERSION:
        errors.append(f"$: expected version 1 and id {ATLAS_VERSION}")
    if raw.get("unicode_version") != UNICODE_DATA_VERSION:
        errors.append(f"$.unicode_version: expected pinned {UNICODE_DATA_VERSION}")
    profiles = raw.get("profiles")
    if not isinstance(profiles, list) or "ascii-safe" not in profiles:
        errors.append("$.profiles: ascii-safe is mandatory")
        profiles = []
    profile_set = set(profiles)

    semantic = raw.get("semantic_tokens")
    if not isinstance(semantic, Mapping):
        errors.append("$.semantic_tokens: required object")
    else:
        organ = semantic.get("organ_kind_glyphs")
        plants = semantic.get("plant_species_glyphs")
        animals = semantic.get("animal_tier_glyphs")
        delivery = semantic.get("delivery_frames")
        required_organs = {"root", "stem", "branch", "vine", "leaf", "bloom", "fruit"}
        if not isinstance(organ, Mapping) or not required_organs.issubset(organ):
            errors.append("$.semantic_tokens.organ_kind_glyphs: incomplete")
        if isinstance(organ, Mapping):
            for kind, glyph in organ.items():
                _validate_cell(
                    glyph, "ascii-safe",
                    f"$.semantic_tokens.organ_kind_glyphs.{kind}", errors,
                )
        if not isinstance(plants, Mapping) or not plants:
            errors.append("$.semantic_tokens.plant_species_glyphs: required non-empty object")
        else:
            for species, glyph in plants.items():
                _validate_cell(
                    glyph, "ascii-safe",
                    f"$.semantic_tokens.plant_species_glyphs.{species}", errors,
                )
        if (not isinstance(animals, Mapping)
                or set(animals) != {"bird", "cat", "rabbit", "turtle"}
                or any(not isinstance(values, list) or len(values) != 4
                       for values in animals.values())):
            errors.append("$.semantic_tokens.animal_tier_glyphs: four species need four tiers")
        if isinstance(animals, Mapping):
            for species, values in animals.items():
                if not isinstance(values, list):
                    continue
                for tier, glyph in enumerate(values):
                    _validate_cell(
                        glyph, "ascii-safe",
                        f"$.semantic_tokens.animal_tier_glyphs.{species}[{tier}]", errors,
                    )
        if (not isinstance(delivery, Mapping)
                or not {"letterbird", "bird", "cat", "rabbit", "turtle"}.issubset(delivery)):
            errors.append("$.semantic_tokens.delivery_frames: incomplete")
        if isinstance(delivery, Mapping):
            for species, frames in delivery.items():
                frame_path = f"$.semantic_tokens.delivery_frames.{species}"
                if not isinstance(frames, list) or not frames:
                    errors.append(f"{frame_path}: needs at least one frame")
                    continue
                for frame_index, frame in enumerate(frames):
                    if not isinstance(frame, list) or not frame:
                        errors.append(f"{frame_path}[{frame_index}]: frame must contain rows")
                        continue
                    for row_index, row in enumerate(frame):
                        _validate_semantic_row(
                            row, f"{frame_path}[{frame_index}][{row_index}]", errors,
                        )

    connected = raw.get("connected_tiles")
    if not isinstance(connected, Mapping):
        errors.append("$.connected_tiles: must be an object")
        connected = {}
    missing_families = sorted(REQUIRED_CONNECTED_FAMILIES - set(connected))
    if missing_families:
        errors.append("$.connected_tiles: missing " + ", ".join(missing_families))
    expected_masks = {str(index) for index in range(16)}
    for family, masks in connected.items():
        path = f"$.connected_tiles.{family}"
        if not isinstance(masks, Mapping):
            errors.append(f"{path}: must be an object")
            continue
        if set(masks) != expected_masks:
            errors.append(f"{path}: must define exactly masks 0 through 15")
        for mask, cell in masks.items():
            _validate_cell(cell, "ascii-safe", f"{path}.{mask}", errors)

    assets = raw.get("assets")
    if not isinstance(assets, list):
        errors.append("$.assets: must be a list")
        assets = []
    seen: set[str] = set()
    kinds: dict[str, str] = {}
    for index, asset in enumerate(assets):
        path = f"$.assets[{index}]"
        if not isinstance(asset, Mapping):
            errors.append(f"{path}: must be an object")
            continue
        allowed_asset = {"id", "kind", "label", "description", "cell_box",
                         "profiles", "hotspots", "tags", "provenance"}
        asset_unknown = sorted(set(asset) - allowed_asset)
        if asset_unknown:
            errors.append(f"{path}: unknown fields {', '.join(asset_unknown)}")
        asset_id = asset.get("id")
        if not isinstance(asset_id, str) or not asset_id:
            errors.append(f"{path}.id: required")
            continue
        if asset_id in seen:
            errors.append(f"{path}.id: duplicate {asset_id}")
        seen.add(asset_id)
        kind = asset.get("kind")
        if kind not in {"fixture", "collectible", "terrain", "plant", "animal", "ambience"}:
            errors.append(f"{path}.kind: unsupported kind")
        kinds[asset_id] = kind
        box = asset.get("cell_box")
        if (not isinstance(box, list) or len(box) != 2
                or any(isinstance(value, bool) or not isinstance(value, int) or value <= 0
                       for value in box)):
            errors.append(f"{path}.cell_box: expected [positive width, positive height]")
            continue
        width, height = box
        asset_profiles = asset.get("profiles")
        if not isinstance(asset_profiles, Mapping) or "ascii-safe" not in asset_profiles:
            errors.append(f"{path}.profiles: every asset needs ascii-safe fallback")
            continue
        for profile, states in asset_profiles.items():
            profile_path = f"{path}.profiles.{profile}"
            if profile not in profile_set:
                errors.append(f"{profile_path}: undeclared profile")
            if not isinstance(states, Mapping) or not states:
                errors.append(f"{profile_path}: states must be a non-empty object")
                continue
            for state_name, frames in states.items():
                state_path = f"{profile_path}.{state_name}"
                if not isinstance(frames, list) or not frames:
                    errors.append(f"{state_path}: needs at least one frame")
                    continue
                for frame_index, frame in enumerate(frames):
                    frame_path = f"{state_path}[{frame_index}]"
                    if not isinstance(frame, Mapping) or set(frame) != {"ticks", "cells"}:
                        errors.append(f"{frame_path}: expected ticks and cells")
                        continue
                    ticks = frame.get("ticks")
                    if isinstance(ticks, bool) or not isinstance(ticks, int) or ticks <= 0:
                        errors.append(f"{frame_path}.ticks: must be a positive integer")
                    rows = frame.get("cells")
                    if not isinstance(rows, list) or len(rows) != height:
                        errors.append(f"{frame_path}.cells: frame height must be {height}")
                        continue
                    for row_index, row in enumerate(rows):
                        row_path = f"{frame_path}.cells[{row_index}]"
                        if not isinstance(row, list) or len(row) != width:
                            errors.append(f"{row_path}: frame width must be {width}")
                            continue
                        for col_index, cell in enumerate(row):
                            _validate_cell(cell, profile, f"{row_path}[{col_index}]", errors)
        if kind == "fixture":
            hotspots = asset.get("hotspots")
            if not isinstance(hotspots, list) or not hotspots:
                errors.append(f"{path}.hotspots: functional fixtures need an interaction")
        if kind == "collectible" and not asset.get("provenance"):
            errors.append(f"{path}.provenance: collectible provenance is required")

    missing_fixtures = sorted(REQUIRED_FIXTURES - seen)
    missing_collectibles = sorted(REQUIRED_COLLECTIBLES - seen)
    if missing_fixtures:
        errors.append("$.assets: missing fixtures " + ", ".join(missing_fixtures))
    if missing_collectibles:
        errors.append("$.assets: missing collectibles " + ", ".join(missing_collectibles))
    if errors:
        raise AtlasValidationError(errors)
    return json.loads(json.dumps(raw, ensure_ascii=False))


def load_atlas(path: Path | None = None) -> dict[str, Any]:
    target = path or Path(str(files(__package__).joinpath("data/atlas.v1.json")))
    with target.open(encoding="utf-8") as handle:
        raw = json.load(handle)
    return validate_atlas(raw)
