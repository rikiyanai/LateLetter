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

# Atlas v2 exists because the proportional presentation profile changes how a
# frame is REPRESENTED, not merely what it contains. A v1 frame is a rectangular
# matrix of single-grapheme cells; a v2 proportional frame is a list of row
# strings whose widths are discovered by measurement. Those are different data
# shapes, and quietly widening v1 to accept both would leave every existing
# reader unable to tell which shape it had been handed. A version bump makes the
# distinction checkable instead of guessable.
ATLAS_V2_VERSION = "garden-atlas-2"

# The profile added in v2. Assets in this profile are laid out with a
# proportional font, so a "column count" is not a meaningful quantity for them
# and is deliberately never validated. See SPEC 7.9.3 rule 2.
PROPORTIONAL_PROFILE = "browser-proportional"

# Every profile v2 recognises. The first four are inherited from v1 unchanged
# and remain cell-based; only the fifth is measured.
V2_PROFILES = (
    "ascii-safe",
    "unicode-cell-safe",
    "browser-font-locked",
    "browser-rich",
    PROPORTIONAL_PROFILE,
)

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
    """Validate an atlas of either schema version and return a detached copy.

    Dispatches on the declared `version` field rather than sniffing the frame
    shape. Sniffing would mean a malformed v2 atlas could be silently accepted
    as a v1 one, or vice versa, and the resulting error message would point at
    the wrong thing entirely. An explicit declaration means a mismatch is
    reported as a mismatch.

    :param raw: The parsed atlas JSON.
    :returns: A deep copy, safe for the caller to mutate.
    :raises AtlasValidationError: With every error found, not just the first.
    """
    if not isinstance(raw, Mapping):
        raise AtlasValidationError(["$: atlas must be an object"])
    if raw.get("version") == 2:
        return _validate_atlas_v2(raw)
    return _validate_atlas_v1(raw)


def _validate_atlas_v1(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a v1 (all-cell-matrix) atlas and return a detached copy."""
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

    _validate_shared_sections(raw, errors)

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


def _validate_shared_sections(raw: Mapping[str, Any], errors: list[str]) -> None:
    """Validate the sections that are identical in both schema versions.

    `semantic_tokens` and `connected_tiles` describe the Garden's single-glyph
    semantic vocabulary -- which character stands for a stem, which for a cat at
    bond tier 2, which for a fence corner. None of that changes when the
    presentation becomes proportional, because it is about meaning rather than
    picture.

    It lives in one function called by both validators so that a rule cannot
    drift between versions by being written down twice. The v1 and v2 copies had
    to agree exactly; now they cannot disagree.

    :param raw: The parsed atlas of either version.
    :param errors: Accumulator, appended to in place.
    """
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



def _validate_proportional_row(row: Any, path: str, errors: list[str]) -> None:
    """Validate one row string of a proportional frame.

    WHAT IS CHECKED, AND WHAT DELIBERATELY IS NOT
    ---------------------------------------------
    Checked: that the row is text, is NFC-normalized, carries no control or
    bidirectional-override characters, and does not begin with a combining mark
    that has nothing to combine with.

    NOT checked: the row's width, in any sense. Not its character count, not its
    column count, not its agreement with the asset's `cell_box`. Under a
    proportional font ten narrow glyphs and ten wide ones occupy visibly
    different widths, so counting characters measures nothing anyone cares
    about. The asset's px extent is discovered by measurement at load time in
    the browser. This absence is the entire point of the profile, so it is
    stated here rather than left to be inferred from missing code.

    Wide East Asian characters are explicitly permitted. The Shift_JIS art
    tradition this profile serves is built on them, and the one-column rule that
    the terminal profiles enforce would forbid exactly the repertoire the
    profile exists to allow.

    :param row: The candidate row, which should be a non-empty string.
    :param path: JSON-pointer-ish location, used in error messages.
    :param errors: Accumulator; every problem is appended, none raise early.
    """
    if not isinstance(row, str) or not row:
        errors.append(f"{path}: proportional row must be non-empty text")
        return
    if unicodedata.normalize("NFC", row) != row:
        errors.append(f"{path}: row must be NFC-normalized")

    clusters = grapheme_cells(row)
    if not clusters:
        errors.append(f"{path}: row must contain grapheme clusters")
        return

    # A combining mark in the first cluster position has no base character to
    # attach to, so it would render against whatever happens to precede it on
    # screen -- including another asset's glyph.
    if unicodedata.combining(clusters[0][0]):
        errors.append(f"{path}: a row may not begin with a standalone combining mark")

    for char in row:
        category = unicodedata.category(char)
        if category in _UNSAFE_CATEGORIES:
            errors.append(f"{path}: unsafe Unicode category {category}")
            break
    if any(unicodedata.bidirectional(char) in _BIDI_UNSAFE for char in row):
        errors.append(f"{path}: bidirectional controls are forbidden")


def _validate_atlas_v2(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a v2 atlas, which may carry both cell and proportional profiles.

    The v2 compiler enforces, beyond everything v1 enforced:

    * an `ascii-safe` fallback for every asset, including proportional ones, so
      the terminal is never left with nothing to draw;
    * cross-profile parity of semantic identity -- the same states, the same
      frame counts, and the same per-frame durations -- so that switching
      profile changes how an object looks and never what it does;
    * a declared `anchor` inside the declared `cell_box`;
    * `art_lineage` on every asset, recording where the drawing came from;
    * explicit `version` and `generator_version`;
    * a declared font for the proportional profile, because measurement is
      meaningless without knowing what was measured.

    :param raw: The parsed atlas JSON, already known to declare version 2.
    :returns: A deep copy.
    :raises AtlasValidationError: With every error found.
    """
    errors: list[str] = []

    allowed_top = {"version", "id", "generator_version", "unicode_version",
                   "profiles", "fonts", "semantic_tokens", "connected_tiles",
                   "assets"}
    unknown = sorted(set(raw) - allowed_top)
    if unknown:
        errors.append(f"$: unknown fields {', '.join(unknown)}")

    if raw.get("id") != ATLAS_V2_VERSION:
        errors.append(f"$: expected id {ATLAS_V2_VERSION}")
    # The generator version is what makes a rebuild reproducible: the same
    # sources under the same generator must produce the same atlas, and a
    # difference in output with no difference in version is a bug worth seeing.
    generator = raw.get("generator_version")
    if not isinstance(generator, str) or not generator:
        errors.append("$.generator_version: required non-empty string")
    if raw.get("unicode_version") != UNICODE_DATA_VERSION:
        errors.append(f"$.unicode_version: expected pinned {UNICODE_DATA_VERSION}")

    profiles = raw.get("profiles")
    if not isinstance(profiles, list) or "ascii-safe" not in profiles:
        errors.append("$.profiles: ascii-safe is mandatory")
        profiles = []
    unsupported = sorted(set(profiles) - set(V2_PROFILES))
    if unsupported:
        errors.append(f"$.profiles: unsupported {', '.join(unsupported)}")
    profile_set = set(profiles)

    # A proportional profile without a declared font is unusable: the row
    # strings mean nothing until something states what they were drawn for, and
    # a reader that guessed would silently measure against the wrong metrics.
    fonts = raw.get("fonts") or {}
    if not isinstance(fonts, Mapping):
        errors.append("$.fonts: must be an object")
        fonts = {}
    if PROPORTIONAL_PROFILE in profile_set:
        font = fonts.get(PROPORTIONAL_PROFILE)
        if not isinstance(font, Mapping):
            errors.append(f"$.fonts.{PROPORTIONAL_PROFILE}: required when the profile is declared")
        else:
            family = font.get("family")
            size = font.get("size_px")
            if not isinstance(family, str) or not family:
                errors.append(f"$.fonts.{PROPORTIONAL_PROFILE}.family: required")
            if isinstance(size, bool) or not isinstance(size, (int, float)) or size <= 0:
                errors.append(f"$.fonts.{PROPORTIONAL_PROFILE}.size_px: positive number required")

    assets = raw.get("assets")
    if not isinstance(assets, list):
        errors.append("$.assets: must be a list")
        assets = []

    seen: set[str] = set()
    for index, asset in enumerate(assets):
        path = f"$.assets[{index}]"
        if not isinstance(asset, Mapping):
            errors.append(f"{path}: must be an object")
            continue

        allowed_asset = {"id", "kind", "label", "description", "cell_box", "anchor",
                         "profiles", "hotspots", "tags", "provenance", "art_lineage"}
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

        # Provenance of the drawing itself. Required on every asset because the
        # art is meant to descend from the existing ASCII / Shift_JIS tradition
        # rather than be invented, and an untraceable picture cannot be reviewed
        # against its source.
        lineage = asset.get("art_lineage")
        if not isinstance(lineage, Mapping) or not lineage.get("source"):
            errors.append(f"{path}.art_lineage: required, with a source")

        box = asset.get("cell_box")
        if (not isinstance(box, list) or len(box) != 2
                or any(isinstance(value, bool) or not isinstance(value, int) or value <= 0
                       for value in box)):
            errors.append(f"{path}.cell_box: expected [positive width, positive height]")
            continue
        width, height = box

        # The anchor is the cell within the footprint that the world coordinate
        # refers to -- the trunk of a tree, the seat of a bench. Without it, art
        # taller than one row would have no defined relationship to the position
        # the world assigned it, and every renderer would pick its own guess.
        anchor = asset.get("anchor")
        if (not isinstance(anchor, list) or len(anchor) != 2
                or any(isinstance(value, bool) or not isinstance(value, int) or value < 0
                       for value in anchor)):
            errors.append(f"{path}.anchor: expected [column, row] non-negative integers")
        else:
            anchor_x, anchor_y = anchor
            if anchor_x >= width or anchor_y >= height:
                errors.append(f"{path}.anchor: must lie inside cell_box {box}")

        asset_profiles = asset.get("profiles")
        if not isinstance(asset_profiles, Mapping) or "ascii-safe" not in asset_profiles:
            errors.append(f"{path}.profiles: every asset needs ascii-safe fallback")
            continue

        # Semantic parity baseline. Every other profile is compared against
        # ascii-safe, which is the profile guaranteed to exist.
        baseline = asset_profiles.get("ascii-safe")
        baseline_states: dict[str, list[Any]] = (
            {name: frames for name, frames in baseline.items()}
            if isinstance(baseline, Mapping) else {}
        )

        for profile, states in asset_profiles.items():
            profile_path = f"{path}.profiles.{profile}"
            if profile not in profile_set:
                errors.append(f"{profile_path}: undeclared profile")
            if not isinstance(states, Mapping) or not states:
                errors.append(f"{profile_path}: states must be a non-empty object")
                continue

            # PARITY. A profile that offers different states than ascii-safe
            # would mean an object could be interactable in the browser and inert
            # in the terminal, or animate through states the other surface has
            # never heard of. Presentation may differ; semantics may not.
            if profile != "ascii-safe" and baseline_states:
                missing = sorted(set(baseline_states) - set(states))
                extra = sorted(set(states) - set(baseline_states))
                if missing:
                    errors.append(f"{profile_path}: missing states {', '.join(missing)}")
                if extra:
                    errors.append(f"{profile_path}: states absent from ascii-safe: {', '.join(extra)}")

            is_proportional = profile == PROPORTIONAL_PROFILE

            for state_name, frames in states.items():
                state_path = f"{profile_path}.{state_name}"
                if not isinstance(frames, list) or not frames:
                    errors.append(f"{state_path}: needs at least one frame")
                    continue

                baseline_frames = baseline_states.get(state_name)
                if (profile != "ascii-safe" and isinstance(baseline_frames, list)
                        and len(baseline_frames) != len(frames)):
                    errors.append(
                        f"{state_path}: frame count {len(frames)} differs from "
                        f"ascii-safe {len(baseline_frames)}"
                    )

                for frame_index, frame in enumerate(frames):
                    frame_path = f"{state_path}[{frame_index}]"
                    payload_key = "rows" if is_proportional else "cells"
                    # A proportional frame may carry a second, independently
                    # drawn picture for narrow viewports. This is not a state and
                    # not a separate asset: it is the same object at the same
                    # moment, drawn smaller. Reducing the full picture
                    # automatically produces a phone drawing with its
                    # identifying middle cut out, so the compact version is
                    # authored rather than derived -- and it therefore has to be
                    # storable, or migrating an asset would silently discard it.
                    allowed_frame_keys = {"ticks", payload_key}
                    if is_proportional:
                        allowed_frame_keys.add("compact_rows")
                        allowed_frame_keys.add("accents")
                    if (not isinstance(frame, Mapping)
                            or payload_key not in frame
                            or "ticks" not in frame
                            or set(frame) - allowed_frame_keys):
                        errors.append(f"{frame_path}: expected ticks and {payload_key}")
                        continue

                    ticks = frame.get("ticks")
                    if isinstance(ticks, bool) or not isinstance(ticks, int) or ticks <= 0:
                        errors.append(f"{frame_path}.ticks: must be a positive integer")

                    # Timing parity. If one profile held a frame twice as long as
                    # another, the same animation would drift out of step between
                    # surfaces even though both were "correct".
                    if profile != "ascii-safe" and isinstance(baseline_frames, list) \
                            and frame_index < len(baseline_frames):
                        baseline_frame = baseline_frames[frame_index]
                        if isinstance(baseline_frame, Mapping) \
                                and baseline_frame.get("ticks") != ticks:
                            errors.append(
                                f"{frame_path}.ticks: {ticks} differs from ascii-safe "
                                f"{baseline_frame.get('ticks')}"
                            )

                    rows = frame.get(payload_key)
                    if not isinstance(rows, list) or len(rows) != height:
                        errors.append(f"{frame_path}.{payload_key}: frame height must be {height}")
                        continue

                    if is_proportional:
                        # Rows are strings. Height is checked above; width is not
                        # checked at all, on purpose.
                        for row_index, row in enumerate(rows):
                            _validate_proportional_row(
                                row, f"{frame_path}.rows[{row_index}]", errors,
                            )
                        compact = frame.get("compact_rows")
                        if compact is not None:
                            # The compact drawing must have the same number of
                            # rows, because both are laid out against the same
                            # uniform line height and the asset's declared box.
                            # Its widths are as unconstrained as the full
                            # drawing's.
                            if not isinstance(compact, list) or len(compact) != height:
                                errors.append(
                                    f"{frame_path}.compact_rows: frame height must be {height}"
                                )
                            else:
                                for row_index, row in enumerate(compact):
                                    _validate_proportional_row(
                                        row, f"{frame_path}.compact_rows[{row_index}]", errors,
                                    )
                        accents = frame.get("accents")
                        if accents is not None:
                            if not isinstance(accents, Mapping):
                                errors.append(f"{frame_path}.accents: must be an object")
                            else:
                                for coordinate, role in accents.items():
                                    try:
                                        row_text, column_text = str(coordinate).split(",", 1)
                                        accent_row = int(row_text)
                                        accent_column = int(column_text)
                                    except (TypeError, ValueError):
                                        errors.append(
                                            f"{frame_path}.accents.{coordinate}: "
                                            "coordinate must be row,column"
                                        )
                                        continue
                                    if (accent_row < 0 or accent_row >= len(rows)
                                            or accent_column < 0
                                            or accent_column >= len(grapheme_cells(rows[accent_row]))):
                                        errors.append(
                                            f"{frame_path}.accents.{coordinate}: "
                                            "coordinate lies outside the frame"
                                        )
                                    if role not in {"signal"}:
                                        errors.append(
                                            f"{frame_path}.accents.{coordinate}: "
                                            f"unknown semantic role {role!r}"
                                        )
                    else:
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

    # v2 inherits v1's completeness requirements verbatim: a garden missing a
    # required fixture cannot be composed, regardless of schema version.
    missing_fixtures = sorted(REQUIRED_FIXTURES - seen)
    missing_collectibles = sorted(REQUIRED_COLLECTIBLES - seen)
    if missing_fixtures:
        errors.append("$.assets: missing fixtures " + ", ".join(missing_fixtures))
    if missing_collectibles:
        errors.append("$.assets: missing collectibles " + ", ".join(missing_collectibles))

    # Semantic tokens and connected tiles are unchanged from v1 and are
    # validated by the same code, so that a rule can never drift between the two
    # schema versions by being written down twice.
    _validate_shared_sections(raw, errors)

    if errors:
        raise AtlasValidationError(errors)
    return json.loads(json.dumps(raw, ensure_ascii=False))


def atlas_asset_rows(asset: Mapping[str, Any], state: str = "idle",
                     profile: str = PROPORTIONAL_PROFILE) -> tuple[str, ...]:
    """Return one frame of a proportional asset as row strings.

    The proportional counterpart of `atlas_asset_frame`. It returns strings
    rather than a cell matrix because that is what the browser's geometry module
    measures; converting to a matrix here would throw away exactly the
    information the profile exists to carry.

    :param asset: A validated v2 asset.
    :param state: Desired state; falls back to `idle`, then to the first state
      in sorted order, matching `atlas_asset_frame`'s behaviour.
    :param profile: Which profile to read.
    :returns: The rows of the first frame of that state.
    """
    states = asset["profiles"][profile]
    frames = states.get(state) or states.get("idle") or states[sorted(states)[0]]
    return tuple(str(row) for row in frames[0]["rows"])


def load_atlas(path: Path | None = None) -> dict[str, Any]:
    target = path or Path(str(files(__package__).joinpath("data/atlas.v1.json")))
    with target.open(encoding="utf-8") as handle:
        raw = json.load(handle)
    return validate_atlas(raw)


def load_atlas_v2(path: Path | None = None) -> dict[str, Any]:
    """Load and validate the v2 atlas.

    Kept separate from `load_atlas` so that callers state which schema they
    expect. A caller that silently accepted either would have to branch on frame
    shape at every use site, which is how the two representations would end up
    confused with one another.
    """
    target = path or Path(str(files(__package__).joinpath("data/atlas.v2.json")))
    with target.open(encoding="utf-8") as handle:
        raw = json.load(handle)
    if raw.get("version") != 2:
        raise AtlasValidationError(["$: expected version 2"])
    return validate_atlas(raw)
