"""Conformance tests for the v2 garden atlas schema and its compiler.

WHAT THESE TESTS GUARD
----------------------
Atlas v2 introduces a second frame representation: proportional assets store row
STRINGS whose widths are discovered by measurement, alongside the inherited cell
matrices whose widths are counted. Two representations in one file is exactly
the situation in which a schema quietly stops meaning anything -- a frame that
is neither shape, or is silently read as the wrong one, would still parse.

So the compiler is tested from both directions: that a correct atlas is
accepted, and that each specific way of getting it wrong is rejected with an
error naming the problem.

The tests build their fixtures by copying the real generated v2 atlas and
breaking one thing at a time. Building a minimal atlas from scratch is not
practical -- the compiler requires the full set of fixtures, collectibles,
semantic tokens and connected-tile families -- and a hand-built stub would drift
away from the real file it is supposed to represent.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from lateletter.garden.atlas import (
    ATLAS_V2_VERSION,
    PROPORTIONAL_PROFILE,
    AtlasValidationError,
    atlas_asset_rows,
    load_atlas,
    load_atlas_v2,
    validate_atlas,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
V1_PATH = REPOSITORY_ROOT / "src/lateletter/garden/data/atlas.v1.json"
V2_PATH = REPOSITORY_ROOT / "src/lateletter/garden/data/atlas.v2.json"
BROWSER_ART_PATH = REPOSITORY_ROOT / "web/garden-atlas-art.mjs"


@pytest.fixture(scope="module")
def atlas_v2() -> dict:
    """The real generated v2 atlas, validated."""
    return load_atlas_v2(V2_PATH)


def find_asset(atlas: dict, asset_id: str) -> dict:
    """Locate one asset by id, failing loudly if it is absent."""
    for asset in atlas["assets"]:
        if asset["id"] == asset_id:
            return asset
    raise AssertionError(f"atlas has no asset {asset_id}")


def bench_height(atlas: dict) -> int:
    """The bench's declared row count, read rather than assumed."""
    return find_asset(atlas, "fixture.bench")["cell_box"][1]


def broken(atlas_v2: dict, mutate) -> list[str]:
    """Apply a mutation to a copy of the atlas and return the errors raised.

    Deep-copies first so one test's damage cannot leak into another's fixture,
    which would make failures depend on test ordering.
    """
    candidate = copy.deepcopy(atlas_v2)
    mutate(candidate)
    with pytest.raises(AtlasValidationError) as caught:
        validate_atlas(candidate)
    return list(caught.value.errors)


# ---------------------------------------------------------------------------
# The generated atlas is well formed, and v1 is untouched
# ---------------------------------------------------------------------------

def test_generated_v2_atlas_validates(atlas_v2):
    assert atlas_v2["version"] == 2
    assert atlas_v2["id"] == ATLAS_V2_VERSION
    assert atlas_v2["generator_version"]
    assert PROPORTIONAL_PROFILE in atlas_v2["profiles"]
    # Every v1 asset survived the migration; none were dropped or invented.
    assert len(atlas_v2["assets"]) == 26


def test_v1_atlas_still_validates_under_the_shared_compiler(atlas_v2):
    # v2 was added by dispatching on the declared version, and the sections
    # common to both are now validated by shared code. If that refactor had
    # changed v1's behaviour, this is where it would show.
    v1 = load_atlas(V1_PATH)
    assert v1["version"] == 1
    assert PROPORTIONAL_PROFILE not in v1["profiles"]


def test_version_dispatch_is_declared_not_sniffed(atlas_v2):
    # A v2 atlas mislabelled as v1 must be rejected by the v1 rules rather than
    # silently accepted, because the alternative -- guessing from frame shape --
    # produces errors that point at the wrong thing.
    candidate = copy.deepcopy(atlas_v2)
    candidate["version"] = 1
    with pytest.raises(AtlasValidationError) as caught:
        validate_atlas(candidate)
    assert any("expected version 1" in error for error in caught.value.errors)


def test_load_atlas_v2_refuses_a_v1_file():
    with pytest.raises(AtlasValidationError) as caught:
        load_atlas_v2(V1_PATH)
    assert any("expected version 2" in error for error in caught.value.errors)


# ---------------------------------------------------------------------------
# The bench canary
# ---------------------------------------------------------------------------

def test_redrawn_fixtures_carry_both_a_measured_and_a_terminal_profile(atlas_v2):
    bench = find_asset(atlas_v2, "fixture.bench")

    assert set(bench["profiles"]) == {"ascii-safe", PROPORTIONAL_PROFILE}
    # Drawn for this product, not carried over from the discarded browser art.
    assert bench["art_lineage"]["source"] == "drawn for LateLetter"
    # The old worksheet receipt remains traceable, but it is explicitly not a
    # current verdict. Current release authority lives only in the registry.
    receipt = bench["art_lineage"]["historical_review"]
    assert receipt["verdict"] == "accepted"
    assert int(receipt["round"]) >= 2
    assert receipt["authoritative"] is False
    assert receipt["superseded_by"] == "docs/garden-asset-acceptance.json"
    assert "FIXTURE_DECOR" in bench["art_lineage"]["supersedes"]


VERDICT_VOCABULARY = frozenset(
    {"accepted", "accepted_with_refinement", "rejected", "not_reviewed"}
)


def test_historical_receipts_are_traceable_but_never_claim_current_authority(atlas_v2):
    drawn = [
        asset for asset in atlas_v2["assets"]
        if asset["art_lineage"]["source"] == "drawn for LateLetter"
    ]
    assert drawn, "no drawn assets to check verdicts on"

    for asset in drawn:
        lineage = asset["art_lineage"]
        assert "review" not in lineage
        assert "review_round" not in lineage
        assert "review_quote" not in lineage
        receipt = lineage["historical_review"]
        verdict = receipt.get("verdict")
        assert verdict in VERDICT_VOCABULARY, f"{asset['id']}: unknown verdict {verdict!r}"
        # The words behind the verdict, always. A status flag with no sentence
        # attached cannot be checked against what the operator actually said,
        # which is exactly how round 1's verdicts became unrecoverable.
        assert receipt.get("quote"), f"{asset['id']} records no words behind its receipt"
        assert receipt["authoritative"] is False
        assert receipt["superseded_by"] == "docs/garden-asset-acceptance.json"

    # The one distinction that must never be flattened: an asset marked as
    # reading BUT carrying a change request is not a plain sign-off. The
    # refinement has been applied and still needs confirming, so collapsing it
    # into `accepted` would claim approval that was never given.
    assert "accepted_with_refinement" in VERDICT_VOCABULARY
    assert "accepted_with_refinement" != "accepted"


def test_a_requirement_the_art_cannot_satisfy_is_recorded_not_drawn(atlas_v2):
    # Review round 4 accepted the planter and, in the same note, said the growth
    # "may need to change as it grows". That is not a change to the picture --
    # every asset declares exactly one state, so a second drawing has nowhere to
    # live. Redrawing in response would produce a picture that still cannot do
    # the thing asked for, and would quietly close the request.
    #
    # So the requirement rides on the asset it constrains. This test asserts it
    # survives regeneration and stays attached to the model gap rather than to
    # the art, because the failure mode is that it gets silently dropped the
    # next time the atlas is rebuilt.
    planter = find_asset(atlas_v2, "fixture.planter")
    requirement = planter["art_lineage"].get("pending_requirement")
    assert requirement, "the planter's growth-state requirement was dropped"
    assert "state" in requirement, "the requirement must name what is actually missing"

    # It is genuinely blocked, not merely unstarted: there is one state today,
    # and both profiles agree on it. When growth states arrive they must arrive
    # in both, which the profile-parity rule already enforces.
    assert list(planter["profiles"]["ascii-safe"]) == ["idle"]
    assert list(planter["profiles"][PROPORTIONAL_PROFILE]) == ["idle"]

    # And it is an AUTHORING gap, not a schema limit -- worth pinning, because
    # the two have very different costs and the requirement above would be read
    # as far more expensive if the schema were the obstacle. Every asset that
    # declares more than one state today is an undrawn placeholder; every asset
    # that carries art declares exactly one.
    multi_state = {
        asset["id"]: asset["art_lineage"]["source"]
        for asset in atlas_v2["assets"]
        if len(asset["profiles"]["ascii-safe"]) > 1
    }
    assert multi_state, "no asset exercises multiple states, so the format is unproven"
    assert set(multi_state.values()) == {"placeholder"}
    for asset in atlas_v2["assets"]:
        if asset["art_lineage"]["source"] == "drawn for LateLetter":
            assert list(asset["profiles"]["ascii-safe"]) == ["idle"], (
                f"{asset['id']} now declares more than one state -- if that is "
                "intended, the growth-state requirement above may be satisfiable"
            )

    # Recorded only where a review actually raised one -- an empty field on
    # every other asset would read as "checked and none found".
    carrying = [
        asset["id"] for asset in atlas_v2["assets"]
        if "pending_requirement" in asset["art_lineage"]
    ]
    assert carrying == ["fixture.planter"]


def test_historical_receipts_do_not_create_a_second_current_verdict_owner(atlas_v2):
    for asset in atlas_v2["assets"]:
        lineage = asset["art_lineage"]
        assert not ({"review", "review_round", "review_quote"} & set(lineage)), asset["id"]


def test_undrawn_assets_are_never_marked_reviewed(atlas_v2):
    # A placeholder glyph cannot have been judged as artwork.
    for asset in atlas_v2["assets"]:
        if asset["art_lineage"]["source"] == "placeholder":
            assert "historical_review" not in asset["art_lineage"]


def test_all_ten_starter_fixtures_were_redrawn(atlas_v2):
    # These are the fixtures a new garden actually materialises. Any of them
    # left undrawn would put a single placeholder glyph into the first thing a
    # recipient ever sees.
    starter = {
        "pond", "bridge", "birdbath", "trellis", "arbor",
        "lantern", "bench", "mailbox", "stepping_stones", "planter",
    }
    drawn = {
        asset["id"].split(".", 1)[-1] for asset in atlas_v2["assets"]
        if asset["art_lineage"]["source"] == "drawn for LateLetter"
    }
    assert starter <= drawn, f"still undrawn: {sorted(starter - drawn)}"


def test_the_two_profiles_are_the_same_object_not_the_same_characters(atlas_v2):
    # Both profiles must agree on the object's shape -- same row count, same
    # anchor, same states -- but they are deliberately NOT character-identical.
    # The proportional profile exists so it can draw a curve where ASCII can
    # only approximate one; forcing them to match would waste it.
    for asset in atlas_v2["assets"]:
        if PROPORTIONAL_PROFILE not in asset["profiles"]:
            continue
        rows = atlas_asset_rows(asset)
        cells = asset["profiles"]["ascii-safe"]["idle"][0]["cells"]
        assert len(rows) == len(cells), f"{asset['id']}: row counts differ"
        assert len(rows) == asset["cell_box"][1]


def test_no_asset_still_shows_a_bare_placeholder_glyph_in_the_starter_set(atlas_v2):
    # A drawn fixture must be more than one character tall or wide; a 1x1 box is
    # the signature of the placeholder state this work exists to leave.
    for asset in atlas_v2["assets"]:
        if asset["art_lineage"]["source"] != "drawn for LateLetter":
            continue
        width, height = asset["cell_box"]
        assert width > 1 and height > 1, f"{asset['id']} is still a single glyph"


def test_undrawn_assets_still_admit_they_are_placeholders(atlas_v2):
    # Sixteen assets remain undrawn. They must keep saying so rather than
    # inheriting the credibility of the drawn ones.
    placeholders = [
        asset["id"] for asset in atlas_v2["assets"]
        if asset["art_lineage"]["source"] == "placeholder"
    ]
    assert len(placeholders) == 16
    assert "fixture.bench" not in placeholders


def test_migration_is_deterministic():
    # Re-running the generator on the same source must reproduce the committed
    # file byte for byte, so a diff always means a real change.
    import sys
    sys.path.insert(0, str(REPOSITORY_ROOT / "scripts"))
    from migrate_atlas_v2 import migrate

    v1 = json.loads(V1_PATH.read_text(encoding="utf-8"))
    regenerated = json.dumps(migrate(v1), ensure_ascii=False, indent=2) + "\n"
    assert regenerated == V2_PATH.read_text(encoding="utf-8")


def test_generated_browser_module_is_byte_exact_with_atlas_v2(atlas_v2):
    import sys
    sys.path.insert(0, str(REPOSITORY_ROOT / "scripts"))
    from migrate_atlas_v2 import emit_browser_art_module

    assert emit_browser_art_module(atlas_v2) == BROWSER_ART_PATH.read_text(encoding="utf-8")


def test_mailbox_signal_accent_survives_the_entire_atlas_pipeline(atlas_v2):
    frame = find_asset(atlas_v2, "fixture.mailbox")["profiles"][PROPORTIONAL_PROFILE]["idle"][0]
    assert frame["rows"][0][3] == "7"
    assert frame["accents"] == {"0,3": "signal"}


def test_accent_coordinates_and_roles_fail_closed(atlas_v2):
    candidate = copy.deepcopy(atlas_v2)
    frame = find_asset(candidate, "fixture.mailbox")["profiles"][PROPORTIONAL_PROFILE]["idle"][0]
    frame["accents"] = {"0,99": "decorative_guess", "not-a-cell": "signal"}
    with pytest.raises(AtlasValidationError) as caught:
        validate_atlas(candidate)
    assert any("coordinate lies outside" in error for error in caught.value.errors)
    assert any("unknown semantic role" in error for error in caught.value.errors)
    assert any("coordinate must be row,column" in error for error in caught.value.errors)


# ---------------------------------------------------------------------------
# Proportional rows: height is checked, width deliberately is not
# ---------------------------------------------------------------------------

def test_proportional_rows_are_strings_not_cell_matrices(atlas_v2):
    bench = find_asset(atlas_v2, "fixture.bench")
    frame = bench["profiles"][PROPORTIONAL_PROFILE]["idle"][0]
    assert set(frame) == {"ticks", "rows"}
    assert all(isinstance(row, str) for row in frame["rows"])


def test_an_authored_compact_drawing_is_storable(atlas_v2):
    # No drawn fixture carries one yet, but the schema must accept it: reducing
    # a picture automatically removes the detail that identifies it, so a
    # narrow-viewport drawing has to be authorable rather than derived.
    candidate = copy.deepcopy(atlas_v2)
    frame = find_asset(candidate, "fixture.bench")["profiles"][PROPORTIONAL_PROFILE]["idle"][0]
    frame["compact_rows"] = ["  ╭─╮", "  │╷│", "  ├─┤", "  ╰─╯", "  ╹ ╹", "  ~"][:bench_height(candidate)]
    validate_atlas(candidate)


def test_a_compact_drawing_must_match_the_declared_row_count(atlas_v2):
    def mutate(atlas):
        frame = find_asset(atlas, "fixture.bench")["profiles"][PROPORTIONAL_PROFILE]["idle"][0]
        frame["compact_rows"] = ["  ╭───╮"]

    errors = broken(atlas_v2, mutate)
    expected = f"compact_rows: frame height must be {bench_height(atlas_v2)}"
    assert any(expected in error for error in errors)


def test_proportional_row_width_is_not_constrained(atlas_v2):
    # THE DEFINING PROPERTY OF THE PROFILE. Under a proportional font, ten
    # narrow glyphs and ten wide ones occupy different widths, so a column count
    # measures nothing. Rows of wildly differing length must validate.
    candidate = copy.deepcopy(atlas_v2)
    bench = find_asset(candidate, "fixture.bench")
    ragged = ["i", "MMMMMMMMMMMMMMMMMMMMMMMMMMMMMM", "  /\\  ", "|", "  ", "\u3000"]
    bench["profiles"][PROPORTIONAL_PROFILE]["idle"][0]["rows"] = ragged[:bench_height(candidate)]
    # No exception: the declared number of rows, and width is nobody's business.
    validate_atlas(candidate)


def test_proportional_row_count_must_match_the_declared_height(atlas_v2):
    # Height IS constrained, because rows stay discrete under uniform leading.
    errors = broken(atlas_v2, lambda atlas: find_asset(atlas, "fixture.bench")
                    ["profiles"][PROPORTIONAL_PROFILE]["idle"][0]["rows"].pop())
    expected = f"frame height must be {bench_height(atlas_v2)}"
    assert any(expected in error for error in errors)


def test_proportional_profile_may_use_wide_east_asian_glyphs(atlas_v2):
    # The Shift_JIS lineage depends on them, and the terminal profiles' one-
    # column rule would forbid exactly the repertoire this profile exists for.
    candidate = copy.deepcopy(atlas_v2)
    bench = find_asset(candidate, "fixture.bench")
    wide = ["　▁▁▁▁▁　", "／￣￣￣＼", "｜　　　｜", "｜　　　｜", "＿||＿＿||＿", "　～　"]
    bench["profiles"][PROPORTIONAL_PROFILE]["idle"][0]["rows"] = wide[:bench_height(candidate)]
    validate_atlas(candidate)


# ---------------------------------------------------------------------------
# Frame-shape confusion between the two representations
# ---------------------------------------------------------------------------

def test_a_proportional_frame_may_not_use_cells(atlas_v2):
    def mutate(atlas):
        frame = find_asset(atlas, "fixture.bench")["profiles"][PROPORTIONAL_PROFILE]["idle"][0]
        frame["cells"] = [list(row) for row in frame.pop("rows")]

    errors = broken(atlas_v2, mutate)
    assert any("expected ticks and rows" in error for error in errors)


def test_a_cell_frame_may_not_use_rows(atlas_v2):
    def mutate(atlas):
        frame = find_asset(atlas, "fixture.bench")["profiles"]["ascii-safe"]["idle"][0]
        frame["rows"] = ["".join(row) for row in frame.pop("cells")]

    errors = broken(atlas_v2, mutate)
    assert any("expected ticks and cells" in error for error in errors)


# ---------------------------------------------------------------------------
# Cross-profile semantic parity
# ---------------------------------------------------------------------------

def test_every_asset_needs_an_ascii_safe_fallback(atlas_v2):
    def mutate(atlas):
        del find_asset(atlas, "fixture.bench")["profiles"]["ascii-safe"]

    errors = broken(atlas_v2, mutate)
    assert any("needs ascii-safe fallback" in error for error in errors)


def test_a_profile_may_not_offer_states_the_fallback_lacks(atlas_v2):
    # An object interactable in the browser and inert in the terminal is a
    # semantic divergence, not a presentation one.
    def mutate(atlas):
        bench = find_asset(atlas, "fixture.bench")
        bench["profiles"][PROPORTIONAL_PROFILE]["occupied"] = [
            {"ticks": 1, "rows": ["x"] * bench_height(atlas)},
        ]

    errors = broken(atlas_v2, mutate)
    assert any("absent from ascii-safe" in error for error in errors)


def test_a_profile_may_not_omit_a_state_the_fallback_declares(atlas_v2):
    def mutate(atlas):
        bench = find_asset(atlas, "fixture.bench")
        bench["profiles"]["ascii-safe"]["occupied"] = [
            {"ticks": 1, "cells": [
                list("x" * find_asset(atlas, "fixture.bench")["cell_box"][0])
                for _ in range(bench_height(atlas))
            ]},
        ]

    errors = broken(atlas_v2, mutate)
    assert any("missing states occupied" in error for error in errors)


def test_frame_counts_must_agree_across_profiles(atlas_v2):
    def mutate(atlas):
        frames = find_asset(atlas, "fixture.bench")["profiles"][PROPORTIONAL_PROFILE]["idle"]
        frames.append(copy.deepcopy(frames[0]))

    errors = broken(atlas_v2, mutate)
    assert any("frame count 2 differs from ascii-safe 1" in error for error in errors)


def test_frame_durations_must_agree_across_profiles(atlas_v2):
    # Otherwise the same animation drifts out of step between surfaces while
    # both remain individually "correct".
    def mutate(atlas):
        find_asset(atlas, "fixture.bench")["profiles"][PROPORTIONAL_PROFILE]["idle"][0]["ticks"] = 9

    errors = broken(atlas_v2, mutate)
    assert any("differs from ascii-safe" in error for error in errors)


# ---------------------------------------------------------------------------
# Newly required v2 fields
# ---------------------------------------------------------------------------

def test_anchor_is_required(atlas_v2):
    errors = broken(atlas_v2, lambda atlas: find_asset(atlas, "fixture.bench").pop("anchor"))
    assert any("anchor: expected" in error for error in errors)


def test_anchor_must_lie_inside_the_cell_box(atlas_v2):
    def mutate(atlas):
        bench = find_asset(atlas, "fixture.bench")
        # One column past the right edge of the declared box.
        bench["anchor"] = [bench["cell_box"][0], 0]

    errors = broken(atlas_v2, mutate)
    assert any("must lie inside cell_box" in error for error in errors)


def test_art_lineage_is_required_on_every_asset(atlas_v2):
    errors = broken(atlas_v2, lambda atlas: atlas["assets"][0].pop("art_lineage"))
    assert any("art_lineage: required" in error for error in errors)


def test_art_lineage_needs_a_source(atlas_v2):
    def mutate(atlas):
        atlas["assets"][0]["art_lineage"] = {"note": "no source given"}

    errors = broken(atlas_v2, mutate)
    assert any("art_lineage: required" in error for error in errors)


def test_generator_version_is_required(atlas_v2):
    errors = broken(atlas_v2, lambda atlas: atlas.pop("generator_version"))
    assert any("generator_version" in error for error in errors)


def test_the_proportional_profile_must_declare_its_font(atlas_v2):
    # Row strings are meaningless without knowing what they were measured
    # against; measuring them in a different font misaligns every stroke.
    errors = broken(atlas_v2, lambda atlas: atlas["fonts"].pop(PROPORTIONAL_PROFILE))
    assert any("required when the profile is declared" in error for error in errors)


def test_the_declared_font_needs_a_family_and_a_size(atlas_v2):
    def mutate(atlas):
        atlas["fonts"][PROPORTIONAL_PROFILE] = {"family": "", "size_px": 0}

    errors = broken(atlas_v2, mutate)
    assert any("family: required" in error for error in errors)
    assert any("size_px: positive number required" in error for error in errors)


def test_unsupported_profiles_are_rejected(atlas_v2):
    def mutate(atlas):
        atlas["profiles"].append("browser-experimental")

    errors = broken(atlas_v2, mutate)
    assert any("unsupported browser-experimental" in error for error in errors)


# ---------------------------------------------------------------------------
# Character safety inside proportional rows
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "row, expected",
    [
        # A NUL byte: category Cc. Control characters in art would be emitted
        # straight into the terminal, where they are instructions, not pictures.
        ("bad\x00row", "unsafe Unicode category"),
        # U+202E RIGHT-TO-LEFT OVERRIDE reverses the visual order of everything
        # after it, so one row could scramble the rest of the drawing.
        ("bad\u202erow", "bidirectional controls are forbidden"),
        # U+0301 COMBINING ACUTE with no base character attaches to whatever
        # happens to precede it on screen -- possibly another asset's glyph.
        ("\u0301leading", "may not begin with a standalone combining mark"),
        # Decomposed e + combining acute: two encodings of one visible character
        # would compare and hash differently while looking identical.
        ("e\u0301 not normal", "must be NFC-normalized"),
        ("", "must be non-empty text"),
    ],
)
def test_unsafe_proportional_rows_are_rejected(atlas_v2, row, expected):
    def mutate(atlas):
        bench = find_asset(atlas, "fixture.bench")
        bench["profiles"][PROPORTIONAL_PROFILE]["idle"][0]["rows"][0] = row

    errors = broken(atlas_v2, mutate)
    assert any(expected in error for error in errors), errors
