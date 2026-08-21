"""Tests for the exact runtime font contract of the Garden's browser profile.

Why a contract needs its own tests
----------------------------------
The defect these exist to close: the accepted fixture art was reviewed through
one font and would have been painted through another, and half its characters
were absent from the one that paints. Nothing detected that, because nothing
compared the art's declared font against the font actually used, and nothing
checked that the characters drawn were present in it.

A family name alone is not a contract. Glyph advances differ by weight and by
style within a single family, and letter spacing shifts every advance, so all
of those are asserted here. The bundled file's own hash is asserted too,
because a font resource that silently changes underneath a measured layout
moves every glyph in the Garden.

The cmap test is the important one: it reads the bundled binary's character map
and requires it to contain every code point the browser profile can actually
emit. That is the check whose absence allowed per-glyph fallback to go unseen.
"""

from __future__ import annotations

from pathlib import Path
import hashlib
import json
import re
import sys

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "scripts"))

ATLAS_V2 = REPOSITORY_ROOT / "src/lateletter/garden/data/atlas.v2.json"
VIEWER = REPOSITORY_ROOT / "viewer-bnw.html"
PROPORTIONAL_PROFILE = "browser-proportional"


@pytest.fixture(scope="module")
def contract() -> dict:
    """The font contract as the atlas declares it."""
    atlas = json.loads(ATLAS_V2.read_text(encoding="utf-8"))
    return atlas["fonts"][PROPORTIONAL_PROFILE]


@pytest.fixture(scope="module")
def atlas() -> dict:
    return json.loads(ATLAS_V2.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def viewer_css() -> str:
    """The `#g` rule body, read as source text.

    Read as text rather than through a browser so the test fails on the
    PRESENCE of a disagreeing declaration, not on a rendered consequence that
    only appears on a machine missing the right fonts.
    """
    source = VIEWER.read_text(encoding="utf-8")
    rule = re.search(r"#g\s*\{([^}]*)\}", source)
    assert rule, "viewer-bnw.html no longer declares a `#g` rule"
    return rule.group(1)


def _font_file(contract: dict) -> Path:
    return REPOSITORY_ROOT / contract["resource"]


# ---------------------------------------------------------------------------
# The contract is whole and internally consistent
# ---------------------------------------------------------------------------


def test_the_contract_names_every_field_that_affects_glyph_advance(contract):
    """A family name alone cannot pin a layout; these fields all move glyphs."""
    for field in (
        "family", "size_px", "line_height_px", "weight", "style",
        "letter_spacing", "resource", "resource_sha256",
    ):
        assert field in contract, f"font contract is missing `{field}`"


def test_the_contract_declares_no_fallback_family(contract):
    """A fallback would paint the art at advances it was never measured against.

    Absence of the face must go through an explicit degraded mode instead, so a
    comma-separated stack here would defeat the whole contract.
    """
    assert "," not in contract["family"], (
        "the contract family lists a fallback; per-glyph substitution is "
        "exactly the defect this contract closes"
    )


def test_the_bundled_font_resource_exists_and_matches_its_declared_hash(contract):
    """A resource changing underneath a measured layout moves every glyph."""
    binary = _font_file(contract)
    assert binary.is_file(), f"bundled font missing: {contract['resource']}"
    digest = hashlib.sha256(binary.read_bytes()).hexdigest()
    assert digest == contract["resource_sha256"], (
        "the bundled font does not match the hash the atlas declares. "
        "Regenerate with scripts/build_garden_font.py and update the contract. "
        f"file={digest} declared={contract['resource_sha256']}"
    )


# ---------------------------------------------------------------------------
# The stylesheet paints what the atlas declares
# ---------------------------------------------------------------------------


def test_the_viewer_font_shorthand_matches_the_declared_contract(contract, viewer_css):
    """`#g` must paint at the exact weight, size, line height and family."""
    shorthand = re.search(r"(?:^|\s)font:\s*([^;]+);", viewer_css)
    assert shorthand, "`#g` no longer sets the `font` shorthand"
    declaration = shorthand.group(1).strip()

    parsed = re.match(
        r"^(\d+)\s+(\d+(?:\.\d+)?)px\s*/\s*(\d+(?:\.\d+)?)px\s+(.+)$", declaration
    )
    assert parsed, (
        "`#g` font shorthand is not in the contracted "
        f"`<weight> <size>px/<line-height>px <family>` form: {declaration}"
    )
    weight, size, line_height, family = parsed.groups()
    family = family.strip().strip("'\"")

    assert int(weight) == contract["weight"]
    assert float(size) == contract["size_px"]
    assert float(line_height) == contract["line_height_px"]
    assert family == contract["family"]


def test_the_viewer_sets_letter_spacing_explicitly(contract, viewer_css):
    """Any tracking would shift every advance the art was measured against."""
    spacing = re.search(r"letter-spacing:\s*([^;]+);", viewer_css)
    assert spacing, "`#g` does not set `letter-spacing` explicitly"
    assert spacing.group(1).strip() == contract["letter_spacing"]


def test_the_font_face_rule_points_at_the_declared_resource(contract):
    """The `@font-face` src is the only path the bundled file reaches the page."""
    source = VIEWER.read_text(encoding="utf-8")
    face = re.search(r"@font-face\s*\{([^}]*)\}", source)
    assert face, "viewer-bnw.html declares no `@font-face` rule"
    body = face.group(1)

    assert contract["family"] in body, "the `@font-face` declares a different family"
    assert Path(contract["resource"]).name in body, (
        "the `@font-face` src does not point at the declared resource"
    )
    # `swap` would paint a frame of fallback text before the real face arrives,
    # at advances the art was never measured against.
    assert "font-display: block" in body, (
        "the face must use `font-display: block`; `swap` paints a frame of "
        "wrong geometry before the real face loads"
    )


# ---------------------------------------------------------------------------
# The bundled binary can actually draw the art
# ---------------------------------------------------------------------------


def _codepoints_in_profile(atlas: dict, profile: str) -> set[int]:
    """Every code point any asset can emit in one profile.

    Walks every asset, state and frame, because a character used by a single
    animation frame of a single asset is exactly the kind of thing a spot check
    misses and a live recipient does not.
    """
    used: set[int] = set()
    for asset in atlas["assets"]:
        frames = asset.get("profiles", {}).get(profile, {})
        for state_frames in frames.values():
            for frame in state_frames:
                if "rows" in frame:
                    for row in frame["rows"]:
                        used.update(ord(ch) for ch in row)
                elif "cells" in frame:
                    for row in frame["cells"]:
                        used.update(ord(ch) for cell in row for ch in cell)
    return used


def test_the_bundled_font_covers_every_codepoint_the_browser_profile_emits(
    contract, atlas
):
    """The check whose absence let per-glyph fallback go unseen.

    A character absent from the declared font is drawn by whatever the browser
    substitutes, whose advance width bears no relation to the declared face's.
    In a measured layout that silently misplaces every following glyph.
    """
    fonttools = pytest.importorskip("fontTools.ttLib")
    font = fonttools.TTFont(_font_file(contract), lazy=True)
    available: set[int] = set()
    for table in font["cmap"].tables:
        available |= set(table.cmap.keys())

    required = _codepoints_in_profile(atlas, PROPORTIONAL_PROFILE)
    missing = sorted(required - available)

    assert not missing, (
        "the bundled font cannot draw characters the browser profile emits, so "
        "the browser would substitute a fallback face for each one and every "
        "following glyph in that row would be misplaced. "
        + ", ".join(f"U+{point:04X} {chr(point)!r}" for point in missing)
    )


def test_the_bundled_font_is_pinned_to_one_weight(contract):
    """A variable font would let some later rule request an unmeasured weight."""
    fonttools = pytest.importorskip("fontTools.ttLib")
    font = fonttools.TTFont(_font_file(contract), lazy=True)
    assert "fvar" not in font, (
        "the bundled font still carries variable axes; pin them in "
        "scripts/build_garden_font.py so the contract is true of the bytes"
    )
