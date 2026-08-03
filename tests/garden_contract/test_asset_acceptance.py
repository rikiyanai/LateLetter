"""Enforcement for SPEC §7.10 per-asset visual acceptance.

Why this file exists
--------------------
§7.10 has required individual operator acceptance of every fixture, plant and
animal since 2026-07-30, and §7.10.2 specified a tracked registry to record it.
The registry was never created, so the rule lived only in prose — and unaccepted
drawings reached live product frames three times running: the ground-cover band,
the butterflies and fireflies, and then the sky clouds and distant birds, each
found by the operator looking at a capture rather than by any check here.

Prose cannot fail a build.  These tests make the registry authoritative: an
asset that appears in a release without an ``accepted`` verdict fails the suite.
Local review candidates are recorded but never treated as release permission.
"""

from __future__ import annotations

import copy
import pathlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

# The identity checks live in the validator, not in this file, so that the
# mutation tests below exercise the same code the release gate runs.  A test
# that reimplements the rule proves only that the test agrees with itself.
sys.path.insert(0, str(Path(__file__).parents[2]))
from scripts.validate_presentation_identity import (  # noqa: E402
    compute_blockers,
    extract_paint_sites,
    extract_reader_sites,
    unlisted_raster_methods,
    unresolvable_writer_calls,
    validate_provenance,
    validate_registers,
)


ROOT = Path(__file__).parents[2]
REGISTRY = ROOT / "docs" / "garden-asset-acceptance.json"
# The companion register created under the operator route of 2026-08-02 step 1.
# REGISTRY answers "is this drawing of a gameplay object accepted"; RECIPES
# answers "is this visible language for disposable presentation accepted".
RECIPES = ROOT / "docs" / "garden-presentation-recipes.json"
ATLAS = ROOT / "src" / "lateletter" / "garden" / "data" / "atlas.v2.json"
VERDICTS = {"accepted", "rejected", "not_reviewed"}

# A raster that actually threads identity through to the cell, used as the
# POSITIVE control wherever a test needs an identified paint site.
#
# It is needed because the live renderer cannot produce one.  `art` destructures
# four options properties and `source` is not among them; `measuredArt` reads
# only `accents` and `animated` from its options object.  Both therefore accept
# a `{source: '...'}` argument and drop it, so the emitted cell carries nothing
# — and a checker that called those calls "identified" would have let route
# step 5 clear every anonymous-paint blocker with dead arguments.
#
# READ FROM A FILE rather than written out here, and that is the whole point.
# The previous version was a string in this module, and it would have thrown
# `TypeError` on its first write: it declared `this.glyphs = []` and then indexed
# `this.glyphs[y][x]`, so no row array ever existed.  It parsed, the static gate
# credited it, and it could not have painted one cell — a positive control that
# cannot run proves nothing about running code.  The same file is EXECUTED by
# `tests/garden_adapters/test_raster_identity_contract.mjs`, which asserts the
# exact id lands on the exact cell, so the static credit below and the executed
# behaviour there are measurements of one artifact and cannot drift apart.
REFERENCE_RASTER = (
    ROOT / "tests" / "garden_contract" / "fixtures" / "identity_reference_raster.mjs"
)
IDENTITY_THREADED_RASTER = REFERENCE_RASTER.read_text(encoding="utf-8")


def threaded(fragment: str) -> str:
    """A fragment as it would read once the raster can record identity."""
    return IDENTITY_THREADED_RASTER + fragment


RECOVERED_ACCEPTED_FIXTURES = {
    "fixture.arbor",
    "fixture.bench",
    "fixture.birdbath",
    "fixture.bridge",
    "fixture.lantern",
    "fixture.mailbox",
    "fixture.planter",
    "fixture.pond",
    "fixture.stepping_stones",
    "fixture.trellis",
}


def _registry() -> dict:
    return json.loads(REGISTRY.read_text(encoding="utf-8"))


def _recipes() -> dict:
    """Load the presentation recipe register.

    Kept separate from ``_registry`` deliberately: the two files answer
    different questions, and merging them in the tests would be the first step
    toward merging them in fact.
    """
    return json.loads(RECIPES.read_text(encoding="utf-8"))


def test_registry_is_well_formed_and_every_verdict_is_legal():
    registry = _registry()
    assert registry["schema"] == 1
    seen = set()
    for row in registry["assets"]:
        assert row["verdict"] in VERDICTS, row
        assert row["asset_id"] not in seen, f"duplicate row for {row['asset_id']}"
        seen.add(row["asset_id"])
        # An accepted verdict has to say when it was accepted and show the
        # capture it was accepted from. Acceptance without evidence is the
        # substitution error §7.10.1 names.
        if row["verdict"] == "accepted":
            assert row["reviewed_at"], f"{row['asset_id']} accepted with no date"
            assert row["capture"], f"{row['asset_id']} accepted with no capture"
            assert row["states_reviewed"], f"{row['asset_id']} accepted with no states"


@pytest.mark.skipif(not ATLAS.exists(), reason="the atlas lane has not landed atlas.v2.json")
def test_every_atlas_asset_has_exactly_one_registry_row():
    """No asset may exist without a verdict, and no verdict without an asset.

    A drawing that is in the atlas but absent from the registry is a drawing
    that can ship without anyone having decided anything about it, which is the
    exact gap that let three rounds of unapproved decoration through.
    """
    atlas = {asset["id"] for asset in json.loads(ATLAS.read_text(encoding="utf-8"))["assets"]}
    recorded = {row["asset_id"] for row in _registry()["assets"]}
    assert atlas - recorded == set(), f"atlas assets with no verdict: {sorted(atlas - recorded)}"
    assert recorded - atlas == set(), f"verdicts for assets that do not exist: {sorted(recorded - atlas)}"


def test_nothing_rejected_is_licensed_to_render():
    """A rejected drawing may never appear, for any reason."""
    registry = _registry()
    rejected = {row["asset_id"] for row in registry["assets"] if row["verdict"] == "rejected"}
    licensed = set(registry["review_candidates"])
    assert rejected & licensed == set(), (
        f"rejected assets are licensed to render: {sorted(rejected & licensed)}"
    )


def test_the_local_scene_draws_only_accepted_assets_or_explicit_review_candidates():
    """Accepted catalog assets may appear; candidates must appear for review.

    Catalog completeness is not scene composition, so accepted assets are not
    required to appear.  Unaccepted candidates are the opposite: every one must
    appear locally or the registry becomes a permission slip for unseen art.
    """
    from lateletter.garden.world.fixtures import STARTER_FIXTURES

    registry = _registry()
    drawn = {f"fixture.{catalog_id}" for catalog_id in STARTER_FIXTURES}
    accepted = {
        row["asset_id"] for row in registry["assets"]
        if row["verdict"] == "accepted"
    }
    candidates = set(registry["review_candidates"])
    assert drawn <= accepted | candidates, (
        "the local scene draws assets with neither acceptance nor review permission: "
        f"{sorted(drawn - accepted - candidates)}"
    )
    assert candidates <= drawn, (
        "review candidates are licensed but absent from the review scene: "
        f"{sorted(candidates - drawn)}"
    )


def test_recovered_operator_fixture_approvals_cannot_be_erased_again():
    """Round 3 plus round 4 explicitly accepted all ten HTML fixtures."""
    rows = {row["asset_id"]: row for row in _registry()["assets"]}
    accepted = {
        asset_id for asset_id, row in rows.items()
        if row["verdict"] == "accepted"
    }
    assert RECOVERED_ACCEPTED_FIXTURES <= accepted
    for asset_id in RECOVERED_ACCEPTED_FIXTURES:
        row = rows[asset_id]
        assert row["states_reviewed"] == ["idle"], asset_id
        assert row["reviewed_at"].startswith("2026-07-31T"), asset_id
        assert row["capture"].startswith("docs/operator-decision-record.md#operator--"), asset_id


def test_exact_legacy_art_migration_retains_the_operator_grant_without_inflation():
    """Moving unchanged approved art does not demand approval a second time.

    The grant follows exact, provenance-verified art.  It does not license a
    renderer to invent a visually similar replacement or an unreviewed pose.
    """
    grants = _registry()["operator_grants"]
    legacy = next(
        grant for grant in grants
        if grant["statement"] == "PLANTS ANIMATIONS IN LEGACY ARE APPROVED VISUALLY"
    )
    effect = legacy["effect"]
    assert "exact, provenance-verified migration into the atlas retains that approval" in effect
    assert "New drawings, changed frames, invented poses" in effect


def test_fixture_review_generator_reads_current_registry_verdicts_not_atlas_history():
    """The review page must not resurrect superseded historical verdict logic."""
    source = (ROOT / "scripts" / "build_fixture_review.py").read_text(encoding="utf-8")
    assert "garden-asset-acceptance.json" in source
    assert 'verdicts = {row["asset_id"]: row for row in registry["assets"]}' in source
    assert 'get("historical_review"' not in source


# The deploy gate that used to live here has been DELETED, not kept alongside
# its replacement.  It returned early whenever the workflow was still on legacy,
# so under the standing legacy deployment it asserted nothing about visual
# acceptance at all, and the one claim it made on the root-deploy branch read a
# registry key (``renderer_local_art_release_blockers``) that no longer exists --
# it would have raised KeyError on the first day root deployment was switched
# on, which is the worst possible moment to discover a broken gate.
#
# Its replacement is test_a_root_deploy_requires_every_computed_blocker_to_clear
# below, which computes on both branches.  Leaving both would have been the
# mixed ownership the route forbids: two tests claiming the same gate, one of
# them wrong.


def test_presentation_registers_are_internally_coherent():
    """The registers must not contradict themselves.

    These are defects in the records rather than conditions that clear over
    time, so they are checked separately from release blockers and must always
    be empty.  The checks themselves live in the validator, not here, so that
    the mutation tests below can exercise the same code the release gate uses
    -- a test that reimplements the rule cannot prove the rule is enforced.
    """
    problems = validate_registers(_registry(), _recipes())
    assert problems == [], "presentation registers are incoherent:\n  " + "\n  ".join(problems)


def test_every_provenance_and_decision_claim_is_verified_against_its_source():
    """Citations must resolve, not merely exist.

    The previous version of this check asked whether ``source_refs`` held a
    non-empty blob string and whether ``decision_refs`` held a known key.  Both
    reported success while eighteen line ranges pointed at unrelated code and
    all three decision anchors addressed a heading that is not in the record at
    all.  A citation nobody can follow is decoration, and decoration is what put
    unreviewed drawings in front of the operator three times.
    """
    problems = validate_provenance(_recipes())
    assert problems == [], "unverifiable provenance:\n  " + "\n  ".join(problems)


def test_anonymous_paint_is_recorded_as_a_release_blocker_not_silently_accepted():
    """The renderer has no identity yet, and that fact must be visible.

    This deliberately does NOT assert that every paint site is identified.
    Route step 1 changes no rendering, so "every paint call carries an id"
    cannot be its closure criterion -- threading ids through the painters is
    step 5, downstream of the accepted-only release authority in step 3.  A step
    gated on work its own contract forbids can never close.

    What step 1 owes is that the gap is COUNTED and BLOCKS, rather than being
    absent from the record.  When step 5 lands, this test starts reporting zero
    and the deploy gate below is what keeps it there.
    """
    source = (ROOT / "web" / "garden-renderer.mjs").read_text(encoding="utf-8")
    sites = extract_paint_sites(source)
    assert sites, "no paint sites found at all -- the scanner has stopped matching the renderer"

    blockers = compute_blockers(_registry(), _recipes(), source)
    anonymous = blockers["anonymous_paint_sites"]
    identified = [site for site in sites if site.source_id is not None]
    assert len(anonymous) + len(identified) == len(sites), (
        "a paint site is neither identified nor counted as anonymous, so the blocker "
        "under-reports the gap"
    )


def test_only_cell_writers_are_treated_as_paint_sites():
    """A serializer is not a painter, and must not be asked to name one source.

    ``raster.line`` returns a row and ``raster.latticeHtml`` turns rows into
    markup.  Counting them as paint sites inflated the anonymous-paint figure
    and, worse, implied that a row could name a single visual source -- which is
    false by construction, because one row routinely holds cells from several
    sources.  Provenance belongs on the cell at the moment it is written and has
    to survive serialisation; that is a different obligation, on a different
    line of code.
    """
    source = (ROOT / "web" / "garden-renderer.mjs").read_text(encoding="utf-8")
    writers = extract_paint_sites(source)
    readers = extract_reader_sites(source)

    assert {site.method for site in writers} <= {"put", "text", "art", "measuredArt"}
    assert {site.method for site in readers} <= {"line", "latticeHtml"}
    assert not ({site.method for site in writers} & {site.method for site in readers})


def test_the_paint_scanner_reads_code_not_text_that_resembles_code():
    """The scanner must be a tokenizer, and this is what proves it.

    Every case below was executed against the previous raw-text scanner and got
    the wrong answer: three inventions, and one real call whose identity was
    lost because a ``)`` inside a string ended the argument walk early.  The
    same family of bug had already been found and corrected once in the Pages
    dependency scanner, which is why this reuses that tokenizer rather than
    adding a second one to go wrong independently.
    """
    invisible = {
        "line comment": "// raster.put(1, 2, 'x')",
        "block comment": "/* raster.put(1, 2) */",
        "quoted prose": "const note = \"raster.put(1, 2)\";",
        "template text": "const t = `raster.put(1, 2)`;",
        "regex literal": "const r = /raster.put(1,2)/;",
        "escaped quote": r"const s = 'raster.put(\'x\')';",
    }
    for name, snippet in invisible.items():
        assert extract_paint_sites(snippet) == [], f"{name} was read as a paint call"

    # A real call whose arguments contain a parenthesis inside a string literal.
    parenthesised = threaded("raster.art(x, y, f(')'), colour, {source: 'recipe.ground.cover'});")
    sites = extract_paint_sites(parenthesised)
    assert [site.source_id for site in sites] == ["recipe.ground.cover"], (
        "a `)` inside a string truncated the argument walk, so an identified call "
        "was reported as anonymous"
    )

    # Code inside a template substitution is still code.
    substituted = threaded("const t = `${raster.art(x, y, g, c, {source: 'recipe.scene.moon'})}`;")
    assert [site.source_id for site in extract_paint_sites(substituted)] == ["recipe.scene.moon"]

    anonymous = [f"garden-renderer.mjs:{s.line} raster.{s.method}" for s in sites if s.source_id is None]
    assert anonymous == [], (
        f"{len(anonymous)} of {len(sites)} paint sites declare no visual source id, "
        "so nothing records whether what they draw was ever approved:\n  "
        + "\n  ".join(anonymous[:12])
    )


def test_a_new_raster_method_cannot_become_an_unwatched_paint_path():
    """Adding an unrecognised paint API must be visible, not silent.

    Every identity check above is scoped to a known list of paint methods.  A
    new ``raster.blit`` would therefore be exempt from all of them by omission.
    This makes the omission itself fail.
    """
    source = (ROOT / "web" / "garden-renderer.mjs").read_text(encoding="utf-8")
    unlisted = unlisted_raster_methods(source)
    assert unlisted == [], (
        f"the renderer calls raster methods the identity checker does not classify: "
        f"{unlisted}. Either add them to WRITER_METHODS or READER_METHODS, or establish "
        "that they cannot emit visible cells."
    )


def test_release_policy_and_active_blockers_are_separate_things():
    """A permanent rule and a clearable condition must not share a list.

    The earlier single list mixed 'anonymous paint blocks a release' (never
    satisfiable) with '16 atlas assets are unreviewed' (clearable).  A deploy
    gate asserting that list empty could never legitimately go quiet, which
    makes the gate unfalsifiable rather than strict.
    """
    registry = _registry()
    assert "renderer_local_art_release_blockers" not in registry, (
        "the location-based blocker list has come back; paint is graded by identity, "
        "not by which file owns it"
    )
    # And no other rule in the file may reach for it either.  The deleted key
    # survived twice as prose after its data was removed -- once in the
    # top-level rules and once in the ported-art note -- which left a second,
    # contradictory release policy standing beside the real one.
    serialised = REGISTRY.read_text(encoding="utf-8")
    assert "renderer_local_art_release_blockers" not in serialised, (
        "a stale reference to the deleted blocker key is still stated in the registry, "
        "so two release policies exist in one file"
    )

    # Banning one identifier's spelling only bans that spelling.  A second
    # contradictory release rule written in different words would have been just
    # as authoritative to a reader, so the fix is structural: the general-purpose
    # top-level `rules` list is gone, and what replaced it may not state a
    # release condition at all.
    assert "rules" not in registry and "registry_rules" not in registry, (
        "a free-form rules list is back; a release rule written there would compete with "
        "release_policy while reading as authority to the next person"
    )
    # What the registry asserts about itself is now a list of IDs whose
    # sentences live in the validator, so there is no prose surface here at
    # all -- see test_mutation_a_new_registry_rule_cannot_be_written_into_authority.
    assert isinstance(registry["registry_invariants"], list)
    assert all(isinstance(name, str) for name in registry["registry_invariants"])
    policy = registry["release_policy"]["rules"]
    assert policy, "release policy must never be empty -- these rules are permanent"
    assert any("anonymous" in rule for rule in policy)
    assert any("never a release criterion" in rule for rule in policy)

    conditions = registry["active_release_blockers"]["conditions"]
    assert conditions, "the computed blocker conditions must be enumerated"
    assert registry["active_release_blockers"]["computed_by"] == (
        "scripts/validate_presentation_identity.py"
    )


def test_the_documented_blockers_are_exactly_the_computed_ones():
    """The registry's condition list and the validator must not drift apart.

    Asserting only that the list is non-empty let the two disagree: the registry
    enumerated five conditions while the validator computed seven, so two real
    gates existed that no reader of the registry would ever know to look for.
    Equality in BOTH directions means a condition cannot be added in code and
    left undocumented, or described here and never actually computed.
    """
    documented = set(_registry()["active_release_blockers"]["conditions"])
    computed = set(compute_blockers(
        _registry(),
        _recipes(),
        (ROOT / "web" / "garden-renderer.mjs").read_text(encoding="utf-8"),
    ))
    assert documented == computed, (
        f"documented but never computed: {sorted(documented - computed)}; "
        f"computed but undocumented: {sorted(computed - documented)}"
    )


def test_acceptance_and_presence_are_recorded_in_separate_fields():
    """"The operator asked for it" is not a verdict on how it was drawn.

    ``required`` used to be a verdict, and the validator treated it as
    release-safe.  That let a presentation the operator had merely ASKED for
    ship without any drawing of it ever being reviewed -- the same conflation,
    in the opposite direction, that made "renderer-local" mean "unapproved".
    """
    recipes = _recipes()
    assert "required" not in recipes["verdicts"], (
        "presence has come back into the verdict vocabulary"
    )
    assert set(recipes["presence_requirements"]) == {"required", "optional"}

    bird = recipes["records"]["recipe.ambient.bird_traversal"]
    assert bird["presence_requirement"] == "required", (
        "D3 asks for full-width traversal, so its absence is a defect"
    )
    assert bird["verdict"] == "accepted_as_deployed", (
        "the deployed implementation is what the 2026-08-01 grant covers"
    )

    # The schema stopped permitting it while two record notes went on DESCRIBING
    # it as a verdict.  A reader believes the prose, so the prose is part of the
    # vocabulary and has to move with it.
    serialised = RECIPES.read_text(encoding="utf-8")
    for stale in ("Verdict is 'required'", "Verdict 'required'", "verdict 'required'"):
        assert stale not in serialised, (
            f"{stale!r} still describes presence as a verdict somewhere in the register"
        )


def test_a_root_deploy_requires_every_computed_blocker_to_clear():
    """The deploy gate, stated against the computed conditions only.

    Unlike the previous version, this does not return early when the workflow
    is still on legacy.  The blockers are computed and reported either way; only
    the assertion that they are empty is conditional on actually deploying the
    root product, because that is the only claim the deploy target changes.
    """
    workflow = (ROOT / ".github" / "workflows" / "deploy.yml").read_text(encoding="utf-8")
    root_deploy = "scripts/prepare_pages_site.py" in workflow and (
        "scripts/prepare_legacy_site.py _site" not in workflow
    )

    blockers = compute_blockers(
        _registry(),
        _recipes(),
        (ROOT / "web" / "garden-renderer.mjs").read_text(encoding="utf-8"),
    )
    outstanding = {name: items for name, items in blockers.items() if items}

    if not root_deploy:
        # Legacy still serves the public site, which is the standing decision.
        # The blockers are non-empty and that is expected; asserting otherwise
        # here would make this test red for a reason it is not about.
        assert "scripts/prepare_legacy_site.py _site" in workflow
        assert outstanding, (
            "every computed blocker has cleared while deployment is still on legacy "
            "-- if that is real, the cutover gate is ready and this test should be "
            "the one that says so"
        )
        return

    assert outstanding == {}, (
        "root-product deploy is configured while these conditions are outstanding: "
        + json.dumps({k: len(v) for k, v in outstanding.items()})
    )


# ── Mutation tests ───────────────────────────────────────────────────────
#
# The checks above only prove the current state.  These prove the CHECKER --
# each one damages a copy of the registers or the renderer in a specific way and
# asserts the damage is caught.  Without them a validator that returned an empty
# list unconditionally would pass every test in this file.


def test_mutation_a_new_anonymous_painter_is_caught():
    """Someone adds a paint call and forgets the source id."""
    mutated = "raster.put(row, col, glyph, colour);"
    sites = extract_paint_sites(mutated)
    assert len(sites) == 1
    assert sites[0].source_id is None, "an undeclared paint call was read as identified"


def test_mutation_an_unknown_visual_source_id_is_caught():
    """A paint call cites an id that no register defines."""
    mutated = threaded("raster.art(r, c, g, col, {source: 'recipe.invented.thing'});")
    blockers = compute_blockers(_registry(), _recipes(), mutated)
    assert blockers["unknown_visual_source_ids"], (
        "an unregistered visual source id was accepted as valid identity"
    )


def test_mutation_a_divergent_implementation_cannot_claim_an_accepted_recipe():
    """The laundering move: cite an approved legacy id from changed code.

    ``recipe.ground.cover`` is accepted_as_deployed with candidate_status
    'absent' -- the candidate has no counterpart.  A paint call claiming that id
    is asserting it reproduces the deployed implementation, which is exactly the
    claim that must be verified rather than assumed.
    """
    mutated = threaded("raster.art(r, c, g, col, {source: 'recipe.ground.cover'});")
    blockers = compute_blockers(_registry(), _recipes(), mutated)
    assert blockers["divergent_implementations_claiming_approval"], (
        "code that does not reproduce the deployed implementation was allowed to "
        "claim its approval"
    )


def test_mutation_a_rejected_or_unreviewed_recipe_blocks_release():
    """A refused drawing must not clear the gate by being registered."""
    recipes = copy.deepcopy(_recipes())
    recipes["records"]["recipe.sky.clouds"]["verdict"] = "rejected"
    blockers = compute_blockers(_registry(), recipes, "")
    assert "recipe.sky.clouds" in blockers["unaccepted_recipes"]

    recipes["records"]["recipe.scene.moon"]["verdict"] = "not_reviewed"
    blockers = compute_blockers(_registry(), recipes, "")
    assert "recipe.scene.moon" in blockers["unaccepted_recipes"], (
        "an unreviewed recipe stopped blocking a release"
    )


def test_mutation_a_recipe_carrying_gameplay_identity_is_caught():
    """A recipe quietly acquires an object_id."""
    recipes = copy.deepcopy(_recipes())
    recipes["records"]["recipe.ground.cover"]["object_id"] = "obj.ground.1"
    problems = validate_registers(_registry(), recipes)
    assert any("object_id" in problem for problem in problems), (
        "a presentation recipe was allowed to own a gameplay object identity"
    )


def test_mutation_identity_crossover_between_the_registers_is_caught():
    """One string becomes both a recipe_id and an asset_id."""
    registry = copy.deepcopy(_registry())
    recipes = copy.deepcopy(_recipes())
    shared = "fixture.bench"
    recipes["records"][shared] = dict(recipes["records"]["recipe.ground.cover"])
    problems = validate_registers(registry, recipes)
    assert any("crossover" in problem for problem in problems), (
        "an id existing in both registers was accepted, leaving its acceptance "
        "state ambiguous by construction"
    )


def test_mutation_a_graded_verdict_without_an_operator_decision_is_caught():
    """A verdict that rests on nobody's statement."""
    recipes = copy.deepcopy(_recipes())
    recipes["records"]["recipe.ground.cover"]["decision_refs"] = []
    problems = validate_registers(_registry(), recipes)
    assert any("cites no operator decision" in problem for problem in problems), (
        "a graded verdict with no operator decision behind it was accepted"
    )


def test_mutation_a_provenance_claim_without_blob_refs_is_caught():
    """accepted_as_deployed with nothing to verify it against."""
    recipes = copy.deepcopy(_recipes())
    recipes["records"]["recipe.ground.cover"]["source_refs"] = None
    problems = validate_registers(_registry(), recipes)
    assert any("cites no blob and ranges" in problem for problem in problems)


def test_mutation_a_nested_gameplay_identity_is_caught():
    """object_id hidden one level down, where a top-level check cannot see it.

    ``{"metadata": {"object_id": ...}}`` is the exact shape someone reaches for
    while trying to keep the field "just for reference", and it defeated the
    previous check completely.  Nesting changes nothing about what the field
    entitles a record to.
    """
    recipes = copy.deepcopy(_recipes())
    recipes["records"]["recipe.ground.cover"]["metadata"] = {"object_id": "obj.fake"}
    problems = validate_registers(_registry(), recipes)
    assert any("metadata.object_id" in problem for problem in problems), (
        "a nested object_id was invisible to the identity check"
    )


def test_mutation_a_bogus_provenance_blob_is_caught():
    """A record cites a hash that is not an object in this repository."""
    recipes = copy.deepcopy(_recipes())
    recipes["records"]["recipe.ground.cover"]["source_refs"]["blob"] = "0" * 40
    problems = validate_provenance(recipes)
    assert any("provenance blob" in problem for problem in problems), (
        "a record was allowed to cite a blob the register does not declare"
    )


def test_mutation_an_impossible_line_range_is_caught():
    """Line numbers outside the artifact, and ranges that are not ranges."""
    recipes = copy.deepcopy(_recipes())
    ranges = recipes["records"]["recipe.ground.cover"]["source_refs"]["ranges"]
    ranges[0]["lines"] = "9999-10000"
    problems = validate_provenance(recipes)
    assert any("impossible" in problem for problem in problems)

    ranges = recipes["records"]["recipe.ground.cover"]["source_refs"]["ranges"]
    ranges[0]["lines"] = "around line 800"
    problems = validate_provenance(recipes)
    assert any("not a line or span" in problem for problem in problems)


def test_mutation_a_decision_anchor_that_resolves_to_nothing_is_caught():
    """An anchor nobody can follow is not a citation.

    All three anchors in the register were of exactly this kind until the
    validator started resolving them: the headings carry trailing tags the slug
    must include, so every link scrolled nowhere while every check said the
    decision was cited.
    """
    recipes = copy.deepcopy(_recipes())
    recipes["decisions"]["D1"]["anchor"] = "docs/operator-decision-record.md#not-a-heading"
    problems = validate_provenance(recipes)
    assert any("does not resolve to any heading" in problem for problem in problems)


def test_mutation_a_paraphrased_operator_quotation_is_caught():
    """The register may quote the operator; it may not summarise them."""
    recipes = copy.deepcopy(_recipes())
    recipes["decisions"]["D3"]["quotes"] = ["the operator said the garden was too empty"]
    problems = validate_provenance(recipes)
    assert any("paraphrasing the operator" in problem for problem in problems), (
        "a summary of what the operator meant was accepted as their words"
    )


def test_mutation_a_law_cannot_be_named_as_a_cells_visual_source():
    """No cell comes only from "the wind".

    A law decides how cells look and emits none of its own.  Naming one as a
    source would satisfy every identity check while concealing which recipe
    actually drew the cell -- anonymity with a respectable id attached.
    """
    mutated = threaded("raster.art(r, c, g, col, {source: 'recipe.motion.wind_law'});")
    blockers = compute_blockers(_registry(), _recipes(), mutated)
    assert blockers["laws_used_as_cell_sources"], (
        "a law was accepted as the visual source of an emitted cell"
    )


def test_mutation_a_required_presentation_that_is_absent_blocks_a_release():
    """Absence is the defect, so nothing else clears it."""
    recipes = copy.deepcopy(_recipes())
    recipes["records"]["recipe.ground.cover"]["presence_requirement"] = "required"
    recipes["records"]["recipe.ground.cover"]["candidate_status"] = "absent"
    blockers = compute_blockers(_registry(), recipes, "")
    assert "recipe.ground.cover" in blockers["required_presentation_absent"]


def test_mutation_an_in_bounds_but_wrong_range_is_caught():
    """Lines 1-2 are inside the blob and are not the ground cover.

    Bounds checking alone let a citation be legal and wrong at once, which is
    how eighteen ranges came to point at unrelated code while every check
    reported the provenance was sound.  Each record now names text its own cited
    lines must hold, so the range has to contain the implementation rather than
    merely fit inside the file.
    """
    recipes = copy.deepcopy(_recipes())
    recipes["records"]["recipe.ground.cover"]["source_refs"]["ranges"][0]["lines"] = "1-2"
    problems = validate_provenance(recipes)
    assert any("do not contain" in problem for problem in problems), (
        "a range inside the blob but holding none of the implementation was accepted"
    )


def test_mutation_a_deployment_claim_without_evidence_tokens_is_caught():
    """Dropping the evidence must not be a way to stop the evidence check."""
    recipes = copy.deepcopy(_recipes())
    del recipes["records"]["recipe.ground.cover"]["source_refs"]["ranges"][0]["contains"]
    problems = validate_provenance(recipes)
    assert any("non-empty list of evidence strings" in problem for problem in problems)


def test_mutation_a_source_id_smuggled_through_a_nested_call_is_caught():
    """``source`` must be a direct paint option, not an argument to something else.

    ``raster.put(x, y, make({source: 'recipe.ground.cover'}))`` hands the object
    to ``make``, which may return anything at all.  Accepting it let any call
    claim identity by mentioning the property somewhere inside its arguments.
    """
    smuggled = threaded("raster.art(x, y, lines, colour, make({source: 'recipe.ground.cover'}));")
    sites = extract_paint_sites(smuggled)
    assert len(sites) == 1
    assert sites[0].source_id is None, (
        "an id belonging to a nested call's argument was read as this call's identity"
    )

    direct = threaded("raster.art(x, y, lines, colour, {source: 'recipe.ground.cover'});")
    assert extract_paint_sites(direct)[0].source_id == "recipe.ground.cover"


def test_mutation_the_self_delegation_exemption_does_not_widen_past_raster():
    """Only the class named Raster may call the writers on itself unnamed.

    Exempting any class that defines a method called ``put`` was a bypass: a
    layer with its own ``put`` helper would have exempted every ``this.put``
    inside it, which is exactly where anonymous paint would hide.
    """
    impostor = """
    class PlantLayer {
      put(x, y, g) { return g; }
      render() { this.put(1, 2, '*'); }
    }
    """
    sites = extract_paint_sites(impostor)
    assert sites, "a this.put inside a non-Raster class was exempted from identity"
    assert all(site.source_id is None for site in sites)

    genuine = """
    class Raster {
      put(x, y, g) { return g; }
      text(x, y, v) { this.put(x, y, v); }
    }
    """
    assert extract_paint_sites(genuine) == [], (
        "the paint API delegating to itself was counted as an anonymous paint site"
    )


def test_mutation_a_lowercased_operator_quotation_is_caught():
    """Case is content in these quotations, not formatting.

    The operator writes in capitals when something matters, so normalising case
    would let a quotation be rewritten and still validate.  Only line wrapping
    is normalised; comparison is otherwise exact.
    """
    recipes = copy.deepcopy(_recipes())
    recipes["decisions"]["D3"]["quotes"] = [
        quote.lower() for quote in recipes["decisions"]["D3"]["quotes"]
    ]
    problems = validate_provenance(recipes)
    assert any("verbatim" in problem for problem in problems), (
        "a lowercased quotation validated, so the match is not verbatim"
    )

    # Re-wrapping the same words across lines is not a change of words.
    recipes = copy.deepcopy(_recipes())
    recipes["decisions"]["D3"]["quotes"] = [
        quote.replace(" ", "\n   ", 1) for quote in recipes["decisions"]["D3"]["quotes"]
    ]
    assert validate_provenance(recipes) == [], (
        "a line wrap inside a stored quotation was treated as a different quotation"
    )


def test_the_spec_and_the_checker_agree_on_what_a_cell_must_carry():
    """A contract nothing produces or reads is prose that cannot fail a build.

    §7.2.1 required both ``visual_source_kind`` and ``visual_source_id`` while
    the checker only ever enforced the id.  Rather than add a second field that
    duplicates a fact the first already implies -- and could then contradict it --
    the contract now derives the kind from the disjoint registries, and this
    keeps the document and the checker from drifting apart again.
    """
    # Wrapping is normalised before the search for the same reason it is when
    # matching an operator quotation: a line break is not a change of words, and
    # a test that fails on one tests the paragraph filling, not the contract.
    spec = re.sub(r"\s+", " ", (ROOT / "docs" / "SPEC.md").read_text(encoding="utf-8"))
    assert "`visual_source_kind` is derived, not stored" in spec, (
        "the SPEC requires a field the checker does not enforce"
    )
    validator = (ROOT / "scripts" / "validate_presentation_identity.py").read_text(
        encoding="utf-8"
    )
    assert "visual_source_kind" not in validator, (
        "the checker has started enforcing a stored kind while the SPEC derives it"
    )

    # The derivation is only sound while the two identity spaces stay disjoint,
    # which is what makes an id sufficient to name its chain.
    recipes = _recipes()
    asset_ids = {row["asset_id"] for row in _registry()["assets"]}
    assert not (set(recipes["records"]) & asset_ids)


def test_mutation_vacuous_evidence_is_caught():
    """An empty token is contained by every range and pins none of them."""
    for vacuous in ([""], [" "], "Ground cover:"):
        recipes = copy.deepcopy(_recipes())
        recipes["records"]["recipe.ground.cover"]["source_refs"]["ranges"][0]["contains"] = vacuous
        problems = validate_provenance(recipes)
        assert problems, f"evidence {vacuous!r} was accepted as proof of anything"


def test_mutation_evidence_that_pins_no_location_is_caught():
    """A shared token is satisfied by any of its occurrences, anywhere.

    ``a.feedGlyph`` appears seven times in the artifact, so a record describing
    the lines that PAINT the feed glyph was satisfied by citing the lines that
    merely null it out.  At least one token must be unique in the whole blob,
    which is what makes a citation point somewhere rather than anywhere.
    """
    recipes = copy.deepcopy(_recipes())
    record = recipes["records"]["recipe.feedback.feed_glyph"]
    record["source_refs"]["ranges"] = [
        {"lines": "1218-1221", "contains": ["a.feedGlyph"]},
    ]
    problems = validate_provenance(recipes)
    assert problems, (
        "a record cited the lines that clear the feed glyph instead of the lines that "
        "paint it, and a shared token accepted the substitution"
    )


def test_mutation_vacuous_operator_quotations_are_caught():
    """An empty quotation is present in every section and quotes nobody."""
    for vacuous in ([""], [" "], [], "a string not a list"):
        recipes = copy.deepcopy(_recipes())
        recipes["decisions"]["D1"]["quotes"] = vacuous
        problems = validate_provenance(recipes)
        assert problems, f"quotes={vacuous!r} was accepted as evidence of a decision"


def test_mutation_source_metadata_must_occupy_the_methods_options_position():
    """Position is what makes ``source`` an option rather than a coincidence.

    ``art`` takes its options object as the fifth argument, so that is the only
    place its identity can live.  An object in the coordinate position, or one
    chosen at runtime by a conditional, supplies an identity this checker cannot
    decide -- and an identity that cannot be decided is not one.
    """
    accepted = threaded("raster.art(x, y, lines, colour, {source: 'recipe.ground.cover'});")
    assert extract_paint_sites(accepted)[0].source_id == "recipe.ground.cover"

    for bypass in (
        # The object is the X COORDINATE, not the options.
        "raster.art({source: 'recipe.ground.cover'}, y, lines, colour);",
        # Supplied only on one branch, so the identity is a runtime coin toss.
        "raster.art(x, y, lines, colour, flag ? {source: 'recipe.ground.cover'} : {});",
        # Handed to another function, which may return anything at all.
        "raster.art(x, y, lines, colour, make({source: 'recipe.ground.cover'}));",
        # Not a literal, so unresolvable without executing the module.
        "raster.art(x, y, lines, colour, {source: SOME_CONST});",
    ):
        # Threaded, so each one fails for its OWN reason rather than because the
        # raster has nowhere to keep an identity.
        sites = extract_paint_sites(threaded(bypass))
        assert sites and sites[0].source_id is None, f"{bypass} was read as identified paint"


def test_mutation_the_delegation_exemption_covers_only_the_writer_bodies():
    """Not every method of Raster -- only the four that implement painting.

    ``class Raster { draw() { this.put(...) } }`` is a painter like any other,
    and exempting it would hide anonymous paint behind a method name in the one
    class nobody re-reads.
    """
    impostor = """
    class Raster {
      put(x, y, glyph, color = null, animated = false, owner = null) { return glyph; }
      draw() { this.put(1, 2, 'x'); }
    }
    """
    sites = extract_paint_sites(impostor)
    assert sites, "a this.put inside a non-writer method of Raster was exempted"
    assert all(site.source_id is None for site in sites)

    genuine = """
    class Raster {
      put(x, y, glyph, color = null, animated = false, owner = null) { return glyph; }
      text(x, y, value, color = null) { this.put(x, y, value, color); }
    }
    """
    assert extract_paint_sites(genuine) == [], (
        "the paint API delegating to itself was counted as an anonymous paint site"
    )


def test_mutation_a_surplus_argument_is_not_an_options_position():
    """A position must be one the function actually reads.

    ``Raster.put`` declares six parameters and no options among them.  Deriving
    a position "one past the signature" invented an argument slot: a seventh
    argument to a six-parameter function is discarded silently at runtime, and
    the checker was reporting that discarded object as the cell's identity --
    an id that exists in the source and nowhere in the running program.
    """
    from scripts.validate_presentation_identity import writer_options_index

    renderer = (ROOT / "web" / "garden-renderer.mjs").read_text(encoding="utf-8")
    indices = writer_options_index(renderer)
    assert indices["put"] is None and indices["text"] is None, (
        "a synthesised options position has come back for a method that has none"
    )
    assert indices["art"] == 4 and indices["measuredArt"] == 6

    for surplus in (
        "raster.put(x, y, glyph, colour, true, null, {source: 'recipe.ground.cover'});",
        "raster.text(x, y, value, colour, true, null, {source: 'recipe.ground.cover'});",
        "raster.put(x, y, glyph, colour, {source: 'recipe.ground.cover'});",
    ):
        sites = extract_paint_sites(surplus)
        assert sites and sites[0].source_id is None, (
            f"{surplus} was read as identified, but the function has no options parameter "
            "to receive it"
        )


def test_mutation_each_cited_range_must_justify_itself():
    """One good span must not vouch for a wrong one.

    Evidence used to be a record-wide list checked against every range
    concatenated, so a record could cite four correct spans and one pointing at
    unrelated code, and the wrong one was covered by tokens found in its
    neighbours.  Replacing each span independently must fail, even while every
    other span in the record stays valid.
    """
    recipes = _recipes()
    multi = [
        recipe_id for recipe_id, record in recipes["records"].items()
        if len(((record.get("source_refs") or {}).get("ranges") or [])) > 1
    ]
    assert multi, "no record cites more than one range, so this cannot be proven"

    for recipe_id in multi:
        span_count = len(recipes["records"][recipe_id]["source_refs"]["ranges"])
        for position in range(span_count):
            mutated = copy.deepcopy(recipes)
            # Lines 1-2 are inside the blob and hold none of the implementation.
            mutated["records"][recipe_id]["source_refs"]["ranges"][position]["lines"] = "1-2"
            problems = validate_provenance(mutated)
            assert any(f"{recipe_id} range[{position}]" in p for p in problems), (
                f"{recipe_id} span {position} was replaced with lines 1-2 and the record still "
                "validated, so its neighbours were vouching for it"
            )


def test_mutation_every_computed_member_call_blocks_whatever_produced_the_receiver():
    """Neither the receiver's NAME nor its SHAPE is a fact about the object.

    Two narrower versions of this rule leaked in turn.  Scoping it to a receiver
    literally named ``raster`` leaked because ``const brush = raster`` paints
    through the same object under a different word.  Requiring the token before
    ``[`` to be a name or a string leaked one level up, because a receiver is an
    EXPRESSION and an expression need not end in a name -- ``(brush)``,
    ``getRaster()`` and ``(c ? a : b)`` all end in a closing parenthesis.

    Alias tracking cannot decide the general case, so the trigger is the call
    FORM: a matched ``]`` invoked immediately, however the object was obtained.
    """
    for evasion in (
        # Named receivers, the first generation of this rule.
        "raster['put'](x, y, g, colour);",
        "const method = 'put'; raster[method](x, y, g, colour);",
        "raster[WRITERS[i]](x, y, g, colour);",
        "const brush = raster; brush['put'](x, y, g, colour);",
        "const brush = raster; brush[method](x, y, g, colour);",
        "this[method](x, y, g, colour);",
        "function paint(surface) { surface[method](x, y, g, colour); }",
        # Receivers that are expressions, the second generation.
        "(brush)[method](x, y, g, colour);",
        "getRaster()[method](x, y, g, colour);",
        "brush?.[method](x, y, g, colour);",
        "(condition ? raster : brush)[method](x, y, g, colour);",
        # And the optional-chained plain member call, the other unresolvable form.
        "raster?.put(x, y, g, colour);",
        # Third generation: the INVOCATION, not just the access, can be written
        # in forms the earlier rules stepped straight over.  Each of these was
        # invisible to both the paint-site reader and the blocker list while the
        # rule required a `(` immediately after the `]` or after the method name.
        "brush?.[method]?.(x, y, g, colour);",
        "brush[method]?.(x, y, g, colour);",
        "raster.put?.(x, y, g, colour);",
        "raster?.put?.(x, y, g, colour);",
        # Reflective invocation, including a writer extracted into a variable
        # first -- by the call, the raster is not mentioned at all, which is why
        # the rule cannot be scoped to receivers that look like rasters.
        "raster[method].call(raster, x, y, g, colour);",
        "const paint = raster[method]; paint.call(raster, x, y, g, colour);",
        "raster.put.call(raster, x, y, g, colour);",
        "raster.put.apply(raster, [x, y, g, colour]);",
        "const paint = raster.put.bind(raster); paint(x, y, g, colour);",
    ):
        assert unresolvable_writer_calls(evasion), f"{evasion} was invisible to the checker"
        blockers = compute_blockers(_registry(), _recipes(), evasion)
        assert blockers["unresolvable_paint_call_forms"], f"{evasion} did not block a release"

    # The rule costs nothing today, which is the point of adopting it now: it is
    # decided before a legitimate use exists to argue about.
    renderer = (ROOT / "web" / "garden-renderer.mjs").read_text(encoding="utf-8")
    assert unresolvable_writer_calls(renderer) == []

    # And it does not fire on ordinary subscripting, which is everywhere in the
    # renderer.  A rule that blocks `this.glyphs[y][x]` would have to be turned
    # off, and a gate that is turned off is not a gate.
    for innocent in (
        "const row = this.glyphs[y]; const cell = this.glyphs[y][x];",
        "const colour = accents[`${row},${column}`] ?? color;",
        "raster.put(x, y, g, colour);",
    ):
        assert unresolvable_writer_calls(innocent) == [], (
            f"{innocent} was refused, but it reaches no writer indirectly"
        )


def test_the_static_identity_verdict_is_confirmed_by_running_the_code():
    """Static credit is not evidence until something executes.

    Reading source text is all a static gate can do, and it has been wrong twice
    in the same way: it accepted a MENTION of the identity as proof the identity
    was kept.  ``this.sources[y][x] = source ? null : null`` names it and stores
    null; a reference raster that declared ``this.glyphs = []`` and then indexed
    ``this.glyphs[y][x]`` could not have painted one cell.  Both cleared the gate
    as it stood.

    Tightening the text rules again would only postpone the next discarding
    expression nobody thought of.  So the claim is settled by RUNNING the code:
    ``tests/garden_adapters/test_raster_identity_contract.mjs`` executes both
    rasters and looks at the cells.  This test binds the two measurements to the
    same artifacts, so neither can be satisfied alone.
    """
    from scripts.validate_presentation_identity import writer_identity_positions

    contract = ROOT / "tests" / "garden_adapters" / "test_raster_identity_contract.mjs"
    assert contract.exists(), "the executed identity contract is missing"

    # The file the static gate credits must be the file Node executes.  If these
    # ever diverge, the positive control proves something about a raster that no
    # longer exists.
    assert REFERENCE_RASTER.name in contract.read_text(encoding="utf-8")
    assert writer_identity_positions(IDENTITY_THREADED_RASTER) == {
        "put": 6, "text": 6, "art": 4, "measuredArt": 6,
    }, "the raster the executed contract proves out is not credited by the gate"

    node = shutil.which("node")
    if node is None:  # pragma: no cover - depends on the developer's machine
        pytest.skip("node is not installed, so the executed contract cannot run here")
    completed = subprocess.run(
        [node, "--test", str(contract.relative_to(ROOT))],
        cwd=ROOT, check=False, capture_output=True, text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_mutation_a_new_registry_rule_cannot_be_written_into_authority():
    """There is no surface left to write policy onto.

    A free-form list could always be extended with something like "Public
    artifacts may always ship", which reads as policy to the next person while
    no check can tell it from the rules that belong -- and filtering by
    vocabulary is a losing game, since the same claim can be reworded.  An
    unknown invariant ID is refused for being unknown, whatever it says.
    """
    registry = copy.deepcopy(_registry())
    registry["registry_invariants"].append("public_artifacts_may_always_ship")
    problems = validate_registers(registry, _recipes())
    assert any("public_artifacts_may_always_ship" in p for p in problems), (
        "a new rule was accepted as registry policy"
    )

    # And the free-form surface itself may not return under either old name.
    for resurrected in ("rules", "registry_rules"):
        registry = copy.deepcopy(_registry())
        registry[resurrected] = ["Public artifacts may always ship."]
        problems = validate_registers(registry, _recipes())
        assert any("free-form rules list" in p for p in problems), (
            f"a free-form {resurrected} list was accepted as an authority surface"
        )

    # An invariant that exists in code but goes unstated in the file is equally
    # a drift, in the other direction.
    registry = copy.deepcopy(_registry())
    registry["registry_invariants"] = registry["registry_invariants"][:-1]
    problems = validate_registers(registry, _recipes())
    assert any("does not declare it" in p for p in problems)


def test_mutation_a_dead_options_argument_cannot_identify_a_cell():
    """Receiving an argument is not carrying an identity.

    ``docs/SPEC.md`` requires the emitted CELL to carry ``visual_source_id``.
    The live raster stores glyph, colour, animation and owner, and neither
    options-taking writer even reads ``source``: ``art`` destructures four
    properties without it, and ``measuredArt`` reads only ``accents`` and
    ``animated`` from its options object.  Both silently drop the value.

    Reporting those calls as identified would have let route step 5 clear every
    anonymous-paint blocker by adding dead arguments while not one cell gained
    provenance -- the gate passing precisely as the product failed.
    """
    from scripts.validate_presentation_identity import (
        writer_identity_positions,
        writer_options_index,
    )

    renderer = (ROOT / "web" / "garden-renderer.mjs").read_text(encoding="utf-8")

    # The signature fact and the identity fact are different, and the gate is
    # the second one.
    assert writer_options_index(renderer)["art"] == 4
    assert writer_identity_positions(renderer) == {
        "put": None, "text": None, "art": None, "measuredArt": None,
    }, "a writer that discards `source` was credited with carrying identity"

    for dead in (
        "raster.art(x, y, lines, colour, {source: 'recipe.ground.cover'});",
        "raster.measuredArt(id, x, y, lines, anchor, colour, "
        "{source: 'recipe.ground.cover'});",
    ):
        sites = extract_paint_sites(renderer + dead)
        assert sites[-1].source_id is None, (
            f"{dead} was read as identified, but the method drops the property and the "
            "emitted cell has nowhere to keep it"
        )
        assert compute_blockers(_registry(), _recipes(), renderer + dead)[
            "anonymous_paint_sites"
        ], "a dead argument cleared the anonymous-paint blocker"

    # The gate must be SATISFIABLE, or step 5 could never pass it and the check
    # would be a permanent refusal wearing a rule's clothes.
    threaded_positions = writer_identity_positions(IDENTITY_THREADED_RASTER)
    assert threaded_positions == {"put": 6, "text": 6, "art": 4, "measuredArt": 6}
    identified = extract_paint_sites(
        threaded("raster.art(x, y, lines, colour, {source: 'recipe.ground.cover'});")
    )
    assert identified[-1].source_id == "recipe.ground.cover"

    # Every way the chain can break, each caught on its own.  These are stated
    # as (what to break, which writers must lose their credit) rather than
    # prose, because the previous version of this check credited a writer when
    # `source` appeared ANYWHERE in any call it made downstream -- which is
    # co-occurrence, not dataflow, and every one of the breakages below cleared
    # it.
    for description, before, after, expected in (
        (
            "put stops storing the identity, so nothing above it can carry one",
            "    this.sources[y][x] = source;\n", "",
            {"put": None, "text": None, "art": None, "measuredArt": None},
        ),
        (
            "put stores a discarding expression that merely MENTIONS the identity",
            "this.sources[y][x] = source;",
            "this.sources[y][x] = source ? null : null;",
            {"put": None, "text": None, "art": None, "measuredArt": None},
        ),
        (
            "the plane put assigns into was never allocated, so the write throws",
            "    this.sources = Array.from"
            "({ length: height }, () => Array(width).fill(null));\n", "",
            {"put": None, "text": None, "art": None, "measuredArt": None},
        ),
        (
            "text takes the identity and drops it, breaking art's chain one hop down",
            "this.put(x + index, y, glyph, color, animated, owner, { source }));",
            "this.put(x + index, y, glyph, color, animated, owner));",
            # `measuredArt` keeps its credit because it calls `put` directly and
            # never goes through `text`: the graph is followed, not assumed.
            {"put": 6, "text": None, "art": None, "measuredArt": 6},
        ),
        (
            "art hands the identity to text as the X COORDINATE",
            "this.text(left, top + row, line, color, animated, owner, { source });",
            "this.text(source, top + row, line, color, animated, owner);",
            {"put": 6, "text": 6, "art": None, "measuredArt": 6},
        ),
        (
            "art hands it down under a property name the callee does not read",
            "this.text(left, top + row, line, color, animated, owner, { source });",
            "this.text(left, top + row, line, color, animated, owner, { owner: source });",
            {"put": 6, "text": 6, "art": None, "measuredArt": 6},
        ),
        (
            "art carries it on the plain branch and drops it on the accent branch",
            "accents[`${row},${column}`] ?? color, animated, owner, { source });",
            "accents[`${row},${column}`] ?? color, animated, owner);",
            {"put": 6, "text": 6, "art": None, "measuredArt": 6},
        ),
        (
            "measuredArt stops reading source out of its options object",
            "Boolean(options.animated), owner, { source: options.source });",
            "Boolean(options.animated), owner);",
            {"put": 6, "text": 6, "art": 4, "measuredArt": None},
        ),
    ):
        mutated = IDENTITY_THREADED_RASTER.replace(before, after)
        # A mutation that did not apply tests nothing while looking like proof.
        assert mutated != IDENTITY_THREADED_RASTER, (
            f"the mutation for {description!r} matched no text in the reference "
            "raster, so it proved nothing"
        )
        assert writer_identity_positions(mutated) == expected, description

    # A fallback is still storage: the allow-list must not be so tight that the
    # obvious real implementation fails it.
    with_fallback = IDENTITY_THREADED_RASTER.replace(
        "this.sources[y][x] = source;", "this.sources[y][x] = source ?? null;"
    )
    assert with_fallback != IDENTITY_THREADED_RASTER
    assert writer_identity_positions(with_fallback) == threaded_positions


def test_mutation_a_new_authority_surface_cannot_be_added_under_a_new_name():
    """Enumerating the invariant IDs shut one surface, not the class.

    A new surface only has to be spelled differently:
    ``{"shipping_policy": ["Public artifacts may always ship."]}`` is not a
    rules list and not an invariant entry, and it reads to the next person as
    policy while nothing distinguishes it from the fields that belong.  The
    general answer is an exact schema, checked in both directions.
    """
    for surface in ("shipping_policy", "deployment_notes", "addendum"):
        registry = copy.deepcopy(_registry())
        registry[surface] = ["Public artifacts may always ship."]
        problems = validate_registers(registry, _recipes())
        assert any(surface in problem for problem in problems), (
            f"{surface!r} was accepted as a top-level field and can hold policy"
        )

        # The companion register is exactly as writable, so it is held to the
        # same schema rather than left as the easier door.
        recipes = copy.deepcopy(_recipes())
        recipes[surface] = ["Public artifacts may always ship."]
        problems = validate_registers(_registry(), recipes)
        assert any(surface in problem for problem in problems), (
            f"{surface!r} was accepted in the recipe register"
        )

    # And a documented field cannot quietly disappear either.
    for register, key in (("acceptance", "release_policy"), ("recipes", "decisions")):
        acceptance = copy.deepcopy(_registry())
        recipes = copy.deepcopy(_recipes())
        if register == "acceptance":
            del acceptance[key]
        else:
            del recipes[key]
        problems = validate_registers(acceptance, recipes)
        assert any("missing" in problem and key in problem for problem in problems), (
            f"the {register} register lost {key!r} without a violation"
        )


def test_mutation_a_law_that_loses_a_dependent_is_caught():
    """The dependency graph must agree in both directions.

    Stating an edge once lets it rot silently; stating it twice and checking
    means a paint record that quietly stops depending on the wind, or a law that
    quietly drops a dependent, fails instead of drifting.
    """
    recipes = copy.deepcopy(_recipes())
    recipes["records"]["recipe.motion.wind_law"]["dependents"] = []
    problems = validate_registers(_registry(), recipes)
    assert any("does not list it as a dependent" in problem for problem in problems)

    recipes = copy.deepcopy(_recipes())
    recipes["records"]["recipe.vegetation.grass_blades"]["law_refs"] = []
    problems = validate_registers(_registry(), recipes)
    assert any("which does not declare this law" in problem for problem in problems)


def test_the_legacy_port_record_matches_the_renderer_it_describes():
    """The registry's provenance record and the code's must be the same record.

    The operator's grant attaches to the archive, so a drawing may claim it only
    by being an archived drawing.  The claim is made in two places -- this
    registry and ``LEGACY_ART_PROVENANCE`` in ``web/garden-legacy-art.mjs`` --
    and two independent lists of what came from where is exactly the
    arrangement that lets one of them quietly acquire an entry the other never
    had.  Comparing them makes the claim single-sourced in effect.

    The node suite separately checks that every cited archive file exists; this
    checks that the citing is agreed on.
    """
    module = (ROOT / "web" / "garden-legacy-art.mjs").read_text(encoding="utf-8")
    recorded = _registry()["legacy_ported_renderer_art"]["ported"]

    # Each ported entry names its source in a `source:` field in the module.
    # Reading the strings rather than executing the module keeps this test free
    # of a node dependency; the node suite executes it.
    for asset_id, source in recorded.items():
        head = source.split(" + ")[0]
        assert head in module, (
            f"{asset_id} is recorded as ported from {source!r}, but "
            "web/garden-legacy-art.mjs does not cite that source"
        )

    # And the other direction: nothing may be ported in code without being
    # recorded here, or the registry stops being the place the answer lives.
    for source in re.findall(r"source: '([^']+)'", module):
        assert any(source in value for value in recorded.values()), (
            f"web/garden-legacy-art.mjs cites {source!r} but no registry entry records it"
        )


def test_the_legacy_port_does_not_quietly_clear_the_release_blockers():
    """Porting the ART does not migrate the ASSET.

    It would be easy to read "the operator approved the legacy plants" as "the
    plant art question is settled".  It is not: SPEC §7.10.4 step 2 is the
    migration of plant and animal drawings into the versioned atlas, and that
    has not happened.  Until it does they are painted by renderer-local code
    with no per-asset verdict row, which is a release blocker regardless of
    where the pictures came from.
    """
    registry = _registry()
    # Gameplay art is graded on the ATLAS chain, so it blocks for a different
    # reason than presentation paint does: not "anonymous" but "not yet a
    # versioned asset with its own verdict row".  The condition is computed
    # rather than hand-listed, so it clears by migration actually happening.
    blockers = compute_blockers(
        registry,
        _recipes(),
        (ROOT / "web" / "garden-renderer.mjs").read_text(encoding="utf-8"),
    )["gameplay_art_outside_atlas"]
    assert "plantArt" in blockers, (
        "the plant paint owner stopped being a release blocker without being "
        "migrated into the atlas"
    )
    assert "animalArt" in blockers, (
        "the animal paint owner stopped being a release blocker without being "
        "migrated into the atlas"
    )
    atlas_ids = {row["asset_id"] for row in registry["assets"]}
    ported = registry["legacy_ported_renderer_art"]["ported"]
    assert not (set(ported) & atlas_ids), (
        "a ported renderer-local drawing is also claiming an atlas verdict row"
    )


def test_spec_and_registry_agree_on_the_recovered_fixture_acceptances():
    """The specification cannot erase or inflate the recovered verdict set."""
    spec = (ROOT / "docs" / "SPEC.md").read_text(encoding="utf-8")
    accepted = {
        row["asset_id"] for row in _registry()["assets"]
        if row["verdict"] == "accepted"
    }
    assert accepted == RECOVERED_ACCEPTED_FIXTURES
    assert "all ten drawn fixture assets carry an `accepted` verdict" in spec
    assert "zero assets carry an `accepted` verdict" not in spec


def test_atlas_lineage_cannot_claim_a_current_acceptance_verdict():
    atlas = json.loads(ATLAS.read_text(encoding="utf-8"))
    for asset in atlas["assets"]:
        lineage = asset["art_lineage"]
        assert not ({"review", "review_round", "review_quote"} & set(lineage)), asset["id"]
        if "historical_review" in lineage:
            receipt = lineage["historical_review"]
            assert receipt["authoritative"] is False
            assert receipt["superseded_by"] == "docs/garden-asset-acceptance.json"


def test_mutation_an_operator_verdict_cannot_be_accepted_without_evidence():
    """Four strings set to "accepted" must not clear the acceptance gate.

    The first version of ``outstanding_operator_verdicts`` checked only
    ``verdict != "accepted"``, so editing four words cleared the blocker with
    ``evidence: null`` -- an approval of nothing, recorded by nobody, at no
    time.  That is the exact defect the register exists to prevent, rebuilt
    inside its own checker, and it was reported as working without ever being
    exercised.

    Each mutation below is the smallest edit that would have passed then.
    """
    import hashlib as _hashlib
    import json as _json

    from scripts.validate_presentation_identity import (  # noqa: PLC0415
        _REVIEW_VERDICTS,
        outstanding_operator_verdicts,
    )

    register = _json.loads(_REVIEW_VERDICTS.read_text(encoding="utf-8"))

    def _with(verdict_patch: dict, register_patch: dict | None = None) -> list[str]:
        mutated = copy.deepcopy(register)
        mutated.update(register_patch or {})
        for name in mutated["verdicts"]:
            mutated["verdicts"][name].update(verdict_patch)
        original = _REVIEW_VERDICTS.read_text(encoding="utf-8")
        _REVIEW_VERDICTS.write_text(_json.dumps(mutated), encoding="utf-8")
        try:
            return outstanding_operator_verdicts()
        finally:
            _REVIEW_VERDICTS.write_text(original, encoding="utf-8")

    # The declared operator every satisfiable case below must be signed by. The
    # real register carries `operator: null` on purpose, so nothing here can be
    # cleared without saying who is clearing it.
    DECLARED = {"operator": "the-operator"}

    # Bare "accepted" with nothing behind it.
    problems = _with({"verdict": "accepted"})
    assert problems, "four words cleared the operator acceptance gate"
    assert any("records no evidence" in problem for problem in problems)

    # Evidence named but absent from disk. Inside the review package, so this
    # fails for absence rather than for location.
    problems = _with({
        "verdict": "accepted",
        "evidence": [
            {"path": "docs/visual-review/no-such-capture.png", "sha256": "0" * 64}
        ],
        "decided_by": "the-operator",
        "decided_at_utc": "2026-08-03T00:00:00Z",
    }, DECLARED)
    assert any("missing evidence" in problem for problem in problems)

    # A word nobody defined is not an acceptance.
    problems = _with({"verdict": "approved-ish"})
    assert any("unknown verdict" in problem for problem in problems)

    # A repository file whose digest matches is not something anybody watched.
    # This is the hole the gate had: `docs/garden-asset-acceptance.json` is a
    # registry, and it stood as the evidence for the MOTION verdict purely
    # because its sha256 was correct.
    registry = ROOT / "docs" / "garden-asset-acceptance.json"
    problems = _with({
        "verdict": "accepted",
        "evidence": [{
            "path": "docs/garden-asset-acceptance.json",
            "sha256": _hashlib.sha256(registry.read_bytes()).hexdigest(),
        }],
        "decided_by": "the-operator",
        "decided_at_utc": "2026-08-03T00:00:00Z",
    }, DECLARED)
    assert any("not in the review package" in problem for problem in problems)

    # A real review artifact, correctly cited, but signed by somebody who is not
    # the declared operator.
    package = ROOT / "docs" / "visual-review" / ".acceptance-gate-probe"
    package.mkdir(parents=True, exist_ok=True)
    watched = package / "probe.txt"
    watched.write_text("stand-in for a capture the operator watched\n", encoding="utf-8")
    # Stand-ins for the two videos the register requires the MOTION verdict to
    # cite. Named exactly as the capture tool names them, because that filename
    # is what the shape check reads.
    videos = [
        package / "probe-desktop-1600x1000.webm",
        package / "probe-mobile-390x844.webm",
    ]
    for video in videos:
        video.write_text(f"stand-in for {video.name}\n", encoding="utf-8")
    try:
        def _cite(path: pathlib.Path) -> dict:
            return {
                "path": str(path.relative_to(ROOT)),
                "sha256": _hashlib.sha256(path.read_bytes()).hexdigest(),
            }

        cited = [_cite(watched), *(_cite(video) for video in videos)]
        problems = _with({
            "verdict": "accepted", "evidence": cited,
            "decided_by": "somebody-else",
            "decided_at_utc": "2026-08-03T00:00:00Z",
        }, DECLARED)
        assert any("not by the declared operator" in problem for problem in problems)

        # Nobody has said who the operator is, so nobody can accept anything.
        # This is the register's real state.
        problems = _with({
            "verdict": "accepted", "evidence": cited,
            "decided_by": "the-operator",
            "decided_at_utc": "2026-08-03T00:00:00Z",
        })
        assert any("declares who the operator is" in problem for problem in problems)

        # "soon" is not a time.
        problems = _with({
            "verdict": "accepted", "evidence": cited,
            "decided_by": "the-operator", "decided_at_utc": "soon",
        }, DECLARED)
        assert any("not an ISO-8601 instant" in problem for problem in problems)

        # A verdict cannot be given for a capture that has not been made yet.
        problems = _with({
            "verdict": "accepted", "evidence": cited,
            "decided_by": "the-operator", "decided_at_utc": "2999-01-01T00:00:00Z",
        }, DECLARED)
        assert any("in the future" in problem for problem in problems)

        # A still image cannot answer "does it move". The register says the
        # motion verdict needs ten seconds at both required sizes, and evidence
        # merely living in the review package does not satisfy that.
        problems = _with({
            "verdict": "accepted", "evidence": [_cite(watched)],
            "decided_by": "the-operator",
            "decided_at_utc": "2026-08-03T00:00:00Z",
        }, DECLARED)
        assert any("cites no 1600x1000 video" in problem for problem in problems)
        assert any("cites no 390x844 video" in problem for problem in problems)
        # ...and only the motion verdict is held to it.
        assert all(problem.startswith("motion ") for problem in problems), problems

        # Digest bound to bytes: change the artifact and the verdict lapses.
        watched.write_text("re-rendered, so nothing was inherited\n", encoding="utf-8")
        problems = _with({
            "verdict": "accepted", "evidence": cited,
            "decided_by": "the-operator",
            "decided_at_utc": "2026-08-03T00:00:00Z",
        }, DECLARED)
        assert any("has changed since it was accepted" in problem for problem in problems)

        # The satisfiable case: a watched artifact in the review package, its
        # real digest, the declared operator, and a real past instant. A gate
        # that can never be cleared teaches nothing about the gate.
        cited[0] = _cite(watched)
        assert _with({
            "verdict": "accepted", "evidence": cited,
            "decided_by": "the-operator",
            "decided_at_utc": "2026-08-03T00:00:00Z",
        }, DECLARED) == []
    finally:
        watched.unlink(missing_ok=True)
        for video in videos:
            video.unlink(missing_ok=True)
        package.rmdir()
