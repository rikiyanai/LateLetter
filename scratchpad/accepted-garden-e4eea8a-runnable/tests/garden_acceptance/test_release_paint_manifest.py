"""The release paint manifest: derivation, independence, and mutation proofs.

Why this file exists
--------------------
The execution order's paint-manifest step requires a build-time accepted-paint
authority: the built artifact must carry, pinned by content hash, exactly which
asset and recipe IDs the verdict registers accept, and nothing else. Before it
existed, paint permission was a RUNTIME property -- hostname checks, query
parameters, `allowUnacceptedArt` -- so the authority travelled with whoever
called the renderer rather than with the artifact that would deploy.

Every guarantee below is proved by mutation, not asserted: each test breaks
one input -- a register, a built file, the manifest's own identity -- and
requires verification to fail with an error that names the cause. A check that
does not fail when the thing it guards is broken is not a check.
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

# The builder lives in `scripts/`, which is not an installed package.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from prepare_pages_site import (  # noqa: E402  (import follows path setup)
    ASSET_REGISTER,
    PAINT_AUTHORITY_FILE,
    PAINT_IDENTITY_SOURCES,
    PAINT_MANIFEST_NAME,
    RECIPE_REGISTER,
    REPOSITORY_ROOT,
    build_paint_manifest,
    paint_authority,
    prepare_pages_site,
    verify_paint_manifest,
)


def test_the_committed_runtime_authority_matches_the_registers():
    """The drift gate for `web/garden-accepted-paint.v1.json`.

    The runtime composer reads this committed file; the registers are the
    truth. If they disagree -- someone edited a register without regenerating,
    or edited the file by hand -- this fails and names the fix. This is the
    same drift discipline the fixture primary-action test established: a
    committed derivative is only trustworthy while a test pins it to its
    source.
    """
    committed_path = REPOSITORY_ROOT / PAINT_AUTHORITY_FILE
    assert committed_path.is_file(), (
        "web/garden-accepted-paint.v1.json is missing; regenerate with "
        "python3 scripts/prepare_pages_site.py --write-paint-authority"
    )
    committed = json.loads(committed_path.read_text(encoding="utf-8"))
    assert committed == paint_authority(), (
        "the committed runtime paint authority disagrees with the registers; "
        "regenerate with python3 scripts/prepare_pages_site.py --write-paint-authority"
    )


@pytest.fixture(scope="module")
def built_site(tmp_path_factory) -> Path:
    """One real built site, reused by every test in this module.

    Module-scoped because the build copies the whole browser dependency graph
    and re-running it per test would multiply the suite's wall time for no
    additional evidence: the tests that MUTATE the site each work on their own
    copy, so sharing the pristine build is safe.
    """
    site = tmp_path_factory.mktemp("paint") / "site"
    prepare_pages_site(site)
    return site


def _mutable_copy(built: Path, destination: Path) -> Path:
    """A private copy of the built site that a mutation test may damage.

    :param built: The shared pristine build.
    :param destination: Where the copy lands; returned for convenience.
    """
    shutil.copytree(built, destination)
    return destination


# ---------------------------------------------------------------------------
# Derivation: what the manifest contains and where it may come from
# ---------------------------------------------------------------------------


def test_the_build_writes_a_manifest_that_verifies(built_site):
    """The builder itself must produce the authority, and it must verify."""
    manifest_path = built_site / PAINT_MANIFEST_NAME
    assert manifest_path.is_file(), "the build produced no paint manifest"
    assert verify_paint_manifest(built_site) == []


def test_review_candidates_are_never_release_paint_authority(built_site):
    """A local review licence must not become public paint permission."""
    manifest = json.loads((built_site / PAINT_MANIFEST_NAME).read_text(encoding="utf-8"))
    assert manifest["review_candidate_assets"] == []
    runtime = json.loads((built_site / PAINT_AUTHORITY_FILE).read_text(encoding="utf-8"))
    assert runtime["review_candidate_assets"] == []
    assert runtime["accepted_assets"] == manifest["accepted_assets"]
    assert runtime["accepted_recipes"] == manifest["accepted_recipes"]
    assert runtime["accepted_legacy_art"] == manifest["accepted_legacy_art"]


def test_rejected_and_unreviewed_paint_is_absent_from_the_authority(built_site):
    """Only accepted verdicts grant paint permission -- by construction.

    Cross-checked against the registers directly rather than trusting the
    builder's own helper twice: the accepted lists must be exactly the IDs
    whose register verdict is accepted, so a rejected or not-reviewed ID in
    the manifest is unreachable rather than merely unlikely.
    """
    manifest = json.loads((built_site / PAINT_MANIFEST_NAME).read_text(encoding="utf-8"))

    assets = json.loads((REPOSITORY_ROOT / ASSET_REGISTER).read_text(encoding="utf-8"))
    by_verdict: dict[str, set[str]] = {}
    for record in assets["assets"]:
        by_verdict.setdefault(record["verdict"], set()).add(record["asset_id"])
    accepted_assets = set(manifest["accepted_assets"])
    assert accepted_assets == by_verdict.get("accepted", set()) | by_verdict.get(
        "accepted_as_deployed", set()
    )
    assert not accepted_assets & by_verdict.get("rejected", set())
    assert not accepted_assets & by_verdict.get("not_reviewed", set())

    recipes = json.loads((REPOSITORY_ROOT / RECIPE_REGISTER).read_text(encoding="utf-8"))
    expected_recipes = {
        recipe_id
        for recipe_id, record in recipes["records"].items()
        if record["verdict"] in {"accepted", "accepted_as_deployed"}
        and record["kind"] == "paint"
    }
    assert set(manifest["accepted_recipes"]) == expected_recipes


def test_laws_are_never_paint_permission(built_site):
    """SPEC 7.2.2 clause 1: a `kind: "law"` record is never a `source_id`.

    Found as a defect in the first build of this manifest: the accepted-recipe
    list was derived from verdicts alone, so all nineteen accepted LAW records
    -- wind, cadence, density, painter order -- were granted paint permission
    they must never have. Laws decide what the painters are given; they emit
    nothing, so an authority that lists one as a paintable source would let a
    composer stamp `recipe.motion.wind_law` on anonymous ink and verify.
    """
    manifest = json.loads((built_site / PAINT_MANIFEST_NAME).read_text(encoding="utf-8"))
    recipes = json.loads((REPOSITORY_ROOT / RECIPE_REGISTER).read_text(encoding="utf-8"))
    law_ids = {
        recipe_id
        for recipe_id, record in recipes["records"].items()
        if record["kind"] == "law"
    }
    assert law_ids, "the register no longer contains laws; this proof went vacuous"
    # No law may appear in either paint-permission list.
    assert not set(manifest["accepted_recipes"]) & law_ids
    assert not set(manifest["accepted_assets"]) & law_ids
    # And accepted laws are carried separately, so a frame checker can tell
    # "names a law" apart from "names an unknown id".
    expected_laws = {
        recipe_id
        for recipe_id in law_ids
        if recipes["records"][recipe_id]["verdict"] in {"accepted", "accepted_as_deployed"}
    }
    assert set(manifest["accepted_laws"]) == expected_laws


def test_the_manifest_is_a_pure_function_of_its_inputs(built_site):
    """Same registers, same files -- byte-identical identity, twice.

    Determinism is what makes the identity hash MEAN anything: if two builds
    of unchanged inputs disagreed, drift detection would report noise and be
    turned off.
    """
    first = build_paint_manifest(built_site)
    second = build_paint_manifest(built_site)
    assert first == second
    assert first["manifest_identity"] == second["manifest_identity"]


def test_the_manifest_pins_the_registers_atlas_and_font_by_content(built_site):
    """Every authority source is bound to exact bytes, not to a path name."""
    import hashlib

    manifest = json.loads((built_site / PAINT_MANIFEST_NAME).read_text(encoding="utf-8"))

    def digest(relative: Path) -> str:
        return hashlib.sha256((REPOSITORY_ROOT / relative).read_bytes()).hexdigest()

    assert manifest["registers"]["asset_register"]["sha256"] == digest(ASSET_REGISTER)
    assert manifest["registers"]["recipe_register"]["sha256"] == digest(RECIPE_REGISTER)
    assert manifest["profile_identity"]["atlas"]["sha256"] == digest(PAINT_IDENTITY_SOURCES[0])
    assert manifest["profile_identity"]["font"]["sha256"] == digest(PAINT_IDENTITY_SOURCES[1])


# ---------------------------------------------------------------------------
# Mutation proofs: breaking any input must break verification
# ---------------------------------------------------------------------------


def test_mutating_a_built_file_fails_verification(built_site, tmp_path):
    """A file altered after the build is a different artifact; it must fail."""
    site = _mutable_copy(built_site, tmp_path / "site")
    target = site / "index.html"
    target.write_text(target.read_text(encoding="utf-8") + "\n<!-- x -->\n", encoding="utf-8")
    errors = verify_paint_manifest(site)
    assert any("index.html" in error for error in errors), errors


def test_hand_editing_the_manifest_fails_its_own_identity(built_site, tmp_path):
    """Quietly adding an ID to an accepted list must be self-detecting.

    This is the hand-edit case the register comparison alone cannot catch in
    every direction, so the manifest digests itself and verification checks
    that digest first.
    """
    site = _mutable_copy(built_site, tmp_path / "site")
    manifest_path = site / PAINT_MANIFEST_NAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["accepted_assets"].append("fixture.invented_by_hand")
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    errors = verify_paint_manifest(site)
    assert any("identity does not match its content" in error for error in errors), errors


def test_mutating_the_asset_register_fails_verification(built_site, tmp_path):
    """The register changing after the build makes the authority stale.

    Proved against a private repository layout holding a deliberately altered
    register copy, because the real register must never be touched by a test.
    """
    fake_root = tmp_path / "repo"
    for relative in (ASSET_REGISTER, RECIPE_REGISTER, *PAINT_IDENTITY_SOURCES):
        destination = fake_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPOSITORY_ROOT / relative, destination)

    register_path = fake_root / ASSET_REGISTER
    register = json.loads(register_path.read_text(encoding="utf-8"))
    # Flip one accepted verdict to rejected: the smallest register change that
    # must invalidate the built artifact's paint authority.
    for record in register["assets"]:
        if record["verdict"] == "accepted":
            record["verdict"] = "rejected"
            break
    register_path.write_text(json.dumps(register, indent=2) + "\n", encoding="utf-8")

    errors = verify_paint_manifest(built_site, repository_root=fake_root)
    assert any("asset_register has changed" in error for error in errors), errors
    assert any("accepted_assets" in error for error in errors), errors


def test_an_unknown_verdict_refuses_to_build_rather_than_guess(built_site, tmp_path):
    """A verdict outside the vocabulary is register corruption, not data."""
    fake_root = tmp_path / "repo"
    for relative in (ASSET_REGISTER, RECIPE_REGISTER, *PAINT_IDENTITY_SOURCES):
        destination = fake_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPOSITORY_ROOT / relative, destination)

    register_path = fake_root / ASSET_REGISTER
    register = json.loads(register_path.read_text(encoding="utf-8"))
    register["assets"][0]["verdict"] = "pending"
    register_path.write_text(json.dumps(register, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="unknown verdict"):
        build_paint_manifest(built_site, repository_root=fake_root)


def test_legacy_art_acceptance_is_exactly_the_ported_grant(built_site):
    """`accepted_legacy_art` is the register's ported list -- no more, no less.

    The ported keys are exact archive transcriptions accepted through the
    recorded 2026-08-01 operator grant, each with per-identity provenance.
    The `not_ported` section names art that keeps renderer-authored
    placeholders and carries NO acceptance; none of those names may appear.
    """
    manifest = json.loads((built_site / PAINT_MANIFEST_NAME).read_text(encoding="utf-8"))
    register = json.loads((REPOSITORY_ROOT / ASSET_REGISTER).read_text(encoding="utf-8"))
    ported = register["legacy_ported_renderer_art"]["ported"]
    assert sorted(manifest["accepted_legacy_art"]) == sorted(ported.keys())
    assert manifest["accepted_legacy_art"], "the grant-backed list went empty"
    # Nothing the register says was NOT ported may be granted paint identity.
    not_ported = register["legacy_ported_renderer_art"]["not_ported"]
    for species in not_ported.get("plants", []):
        assert not any(species in art_id for art_id in manifest["accepted_legacy_art"]), species
    for species in not_ported.get("animals", []):
        assert not any(f"animal.{species}" == art_id for art_id in manifest["accepted_legacy_art"]), species


def test_the_manifest_carries_no_runtime_permission_vocabulary(built_site):
    """The authority must be independent of every runtime permission channel.

    Stated as a text-level absence over the manifest's DATA fields: none of
    the runtime permission names may appear in any field a consumer would
    read, so nothing downstream can be tempted to read them back out of it.
    The `purpose` prose is excluded because it is the one place those names
    legitimately appear -- in the sentence forbidding them.
    """
    manifest = json.loads((built_site / PAINT_MANIFEST_NAME).read_text(encoding="utf-8"))
    data_only = {key: value for key, value in manifest.items() if key != "purpose"}
    text = json.dumps(data_only)
    for forbidden in ("allowUnacceptedArt", "garden_review", "garden_debug", "hostname"):
        assert forbidden not in text, f"the paint manifest carries {forbidden}"
