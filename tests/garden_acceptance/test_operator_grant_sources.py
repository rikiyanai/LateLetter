"""Every operator grant's hash-bound source file is present and still hashes.

Why this file exists
--------------------
On 2026-08-06 a concurrent lane silently removed eleven committed files from
``src/lateletter/garden/data/operator-granted-art/``.  The removal rode along
inside ``1bdea41`` -- a DOCUMENTATION commit whose message says nothing about
art assets -- as 355 deletions that nobody had asked for.  Ten of those files
are drawings the operator handed over personally; one is the operator's own
reference sheet.  Nothing in the suite went red, because at that moment no test
anywhere asserted that those files exist.  The loss was noticed only because a
later task happened to try to read one of them.

The bytes were recovered and verified blob-for-blob against the original grant
commit ``bf50d7f``, so no operator art was lost.  What was NOT repaired is the
class of failure: a silent deletion of operator-authored source art still
leaves every test reporting success.

There was already a check, but it fires in the wrong place and far too late.
``scripts/prepare_pages_site.py::_accepted_asset_ids`` refuses to grant paint
identity to an operator grant whose hash-bound source is absent or whose bytes
have drifted -- but that only runs when somebody builds the site.  The next
person to build would have met ``operator-authored asset 'fixture.mixtape'
does not match its hash-bound source`` with no hint that a docs commit three
days earlier had deleted the file.  A guard that fires at build time, in a
different lane, with no pointer back to the cause, is not a guard against a
silent deletion; it is a delayed and confusing symptom.

So this module moves that same question -- does every grant's source exist, and
do its bytes still hash to the digest the register recorded? -- into the garden
lane's own test suite, where it fails IMMEDIATELY and BY NAME the moment such a
file goes missing or is altered.

What a "real grant" is, and why prose rows are skipped
------------------------------------------------------
``docs/garden-asset-acceptance.json`` keeps a single ``operator_grants`` array
that holds two different kinds of row.  Most rows are prose: a historical note
that the operator granted permission for something, carrying ``statement``,
``scope`` and ``granted_at`` but a null (or entirely absent) ``asset_id``,
``source`` and ``source_sha256``.  Those rows license nothing by themselves and
name no file, so there is no file for this module to look for.

The other kind is a real grant: it names an ``asset_id``, a repository-relative
``source`` path, and the ``source_sha256`` of that file's exact bytes.  Those
three strings together are what promotes operator ink into paint authority, and
those are the rows guarded here.

The row-selection rule below is deliberately the SAME rule the release builder
uses -- all three fields must be present and must be strings -- so that this
guard and the builder can never disagree about which rows are grants.  If they
could disagree, a row could slip through here and still detonate at build time,
which is exactly the situation this module exists to end.

Proved by mutation, not asserted
--------------------------------
The sibling module ``test_release_paint_manifest.py`` states the standard this
repository holds itself to: "A check that does not fail when the thing it
guards is broken is not a check."  So the two mutation tests at the bottom
build a scratch copy of the granted sources in a temporary directory, break one
file in each of the two possible ways -- delete it, then alter its bytes -- and
require the guard to report a failure that NAMES the asset, the path, and which
of the two things went wrong.  Nothing in the real checkout is ever touched.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

import pytest

# The builder lives in `scripts/`, which is not an installed package, so its
# directory has to be put on the import path by hand.  This mirrors what
# `test_release_paint_manifest.py` does a few files over.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from prepare_pages_site import (  # noqa: E402  (import follows the path setup above)
    ASSET_REGISTER,
    REPOSITORY_ROOT,
)

# The five grants that name a file today: one promoted transcription result and
# four gift drawings the operator handed over.  This constant is NOT the guard
# -- the guard reads whatever the register currently holds -- it exists so that
# an emptied or gutted `operator_grants` array cannot turn this module into a
# test that quietly proves nothing about zero rows.  See
# `test_the_grant_ledger_still_names_real_hash_bound_sources` below.
GRANTS_EXPECTED_TO_NAME_A_SOURCE = frozenset(
    {
        "plant.rose",
        "fixture.coffee_mug",
        "fixture.ice_cream_cone",
        "fixture.mixtape",
        "fixture.popsicle",
    }
)


def _register() -> dict:
    """The parsed asset acceptance register.

    :returns: The whole of ``docs/garden-asset-acceptance.json`` as a dict.

    Read fresh on every call rather than cached at import time, so that a test
    which needs to reason about the register's real current content can never
    be handed a stale copy from an earlier test in the same session.
    """
    return json.loads((REPOSITORY_ROOT / ASSET_REGISTER).read_text(encoding="utf-8"))


def real_grants(register: dict) -> list[dict]:
    """Only the ``operator_grants`` rows that actually name a source file.

    :param register: A parsed asset acceptance register.
    :returns: The subset of ``operator_grants`` carrying all three of
        ``asset_id``, ``source`` and ``source_sha256`` as strings.

    The three-string test is copied deliberately from
    ``prepare_pages_site._accepted_asset_ids``.  A prose-only historical row
    carries ``asset_id: null`` (or omits the key), so it fails the test and is
    skipped here exactly as the builder skips it.  Keeping the two rules
    identical is what stops a row from being guarded in one place and ignored
    in the other.
    """
    selected: list[dict] = []
    for grant in register.get("operator_grants", []):
        # `.get` rather than `[...]`: a prose row may omit these keys entirely
        # rather than setting them to null, and both spellings mean the same
        # thing -- this row names no file.
        asset_id = grant.get("asset_id")
        source = grant.get("source")
        expected = grant.get("source_sha256")
        if not (
            isinstance(asset_id, str)
            and isinstance(source, str)
            and isinstance(expected, str)
        ):
            continue
        selected.append(grant)
    return selected


def _sha256_of(path: Path) -> str:
    """The SHA-256 of one file's exact bytes.

    :param path: The file to digest; it must already be known to exist.
    :returns: 64 lowercase hex characters.

    Digesting the raw bytes -- not decoded text -- is the point.  These sources
    are ASCII drawings whose meaning is carried by trailing spaces and by the
    exact line endings, and a text-mode read on some platforms would silently
    rewrite both, making an altered file look untouched.
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


def grant_source_failures(grants: list[dict], root: Path) -> list[str]:
    """Everything wrong with these grants' source files, in plain sentences.

    :param grants: Rows from :func:`real_grants` -- each names an asset id, a
        repository-relative source path, and that source's expected digest.
    :param root: The directory the ``source`` paths are relative to.  In the
        real check this is the repository root; the mutation tests pass a
        scratch directory instead, which is how this guard is proved to fire
        without ever disturbing the live checkout.
    :returns: One sentence per problem, empty when every source is present and
        every digest still agrees.

    Returning a LIST rather than raising on the first problem is deliberate.
    The incident this module guards against deleted ELEVEN files at once; a
    check that stopped at the first would have reported one missing drawing and
    hidden the scale of what happened.
    """
    failures: list[str] = []
    for grant in grants:
        asset_id = grant["asset_id"]
        source = grant["source"]
        expected = grant["source_sha256"]
        source_path = root / source
        if not source_path.is_file():
            # The deletion case -- the exact shape of the 2026-08-06 incident.
            # The remedy is named in the message because the person reading it
            # is most likely staring at a red test in a lane that never touched
            # art, and needs to be pointed at a commit that swept up files it
            # did not own.
            failures.append(
                f"operator grant {asset_id!r}: its hash-bound source {source} is "
                "ABSENT. An operator-granted file has been removed from the "
                "checkout. Restore it from the commit that granted it rather "
                "than redrawing it -- these bytes are the operator's own ink."
            )
            continue
        # The corruption case: the file is where it should be, but its bytes
        # are no longer the bytes the operator handed over.
        actual = _sha256_of(source_path)
        if actual != expected:
            failures.append(
                f"operator grant {asset_id!r}: the bytes of {source} NO LONGER "
                f"MATCH the digest recorded in the register (register says "
                f"{expected}, the file on disk hashes to {actual}). Either the "
                "granted art was edited, or the register was updated without "
                "the file."
            )
    return failures


@pytest.fixture
def grant_root() -> Path:
    """The directory that ``operator_grants[].source`` paths resolve against.

    :returns: The repository root, for every ordinary run.

    Expressed as a fixture rather than read straight from ``REPOSITORY_ROOT``
    inside the test so that the real guard can be pointed at a deliberately
    damaged scratch tree -- by a conftest override or a monkeypatch -- and be
    watched to fail. A guard nobody has ever seen fail is only a hope.
    """
    return REPOSITORY_ROOT


def test_every_operator_granted_source_is_present_and_still_hashes(grant_root: Path):
    """The headline guard: no granted source may vanish or drift, silently.

    This is the test that ``1bdea41`` would have turned red on the spot. It
    walks every real grant in the register and requires, for each, that the
    file it names is present in the checkout and that its bytes still hash to
    the digest recorded beside them.
    """
    grants = real_grants(_register())

    # Anti-vacuity, first and separately. If the `operator_grants` array were
    # ever emptied -- or every row stripped of its `source` -- the loop below
    # would iterate over nothing and report no failure while guarding nothing
    # at all. That is the same silent-loss failure mode in a different
    # disguise, so it is refused here explicitly.
    assert grants, (
        "the asset register lists no operator grant that names a hash-bound "
        "source. Either every grant row lost its asset_id/source/source_sha256 "
        "triple, or the operator_grants array was emptied -- and this guard "
        "would then be proving nothing. Investigate before editing this test."
    )

    failures = grant_source_failures(grants, grant_root)
    assert not failures, (
        f"{len(failures)} of {len(grants)} operator-granted sources are not "
        "where the register says they are:\n  " + "\n  ".join(failures)
    )


def test_the_grant_ledger_still_names_real_hash_bound_sources():
    """Every grant known to name a file on 2026-08-06 still names one.

    Separate from the headline guard because it asks a different question. The
    headline guard asks whether the FILES survived; this asks whether the ROWS
    that point at them survived. Deleting a grant row would make the headline
    guard stop looking for that file, and the file could then be removed with
    nothing going red -- the silent deletion again, one level up.

    A grant that is genuinely retired belongs in ``withdrawn_acceptances``,
    which is a visible, reviewed act; quietly dropping the row is not.
    """
    named = {grant["asset_id"] for grant in real_grants(_register())}
    lost = GRANTS_EXPECTED_TO_NAME_A_SOURCE - named
    assert not lost, (
        f"these grants no longer name a hash-bound source: {sorted(lost)}. A "
        "grant row that loses its asset_id, source or source_sha256 is skipped "
        "by both this guard and the release builder, so its art becomes "
        "unguarded without anything going red."
    )


def _scratch_tree_of_granted_sources(grants: list[dict], destination: Path) -> Path:
    """A private copy of every granted source, safe for a test to damage.

    :param grants: The rows whose ``source`` files should be copied.
    :param destination: A ``tmp_path`` directory to build the copy inside.
    :returns: ``destination``, now usable as a ``root`` for
        :func:`grant_source_failures`.

    The copy preserves each source's repository-relative path, so the guard
    under test resolves exactly the same relative paths it would resolve in the
    real checkout. Nothing under version control is moved, altered or restored
    -- the mutation happens only inside pytest's temporary directory, which
    pytest discards afterwards.
    """
    for grant in grants:
        source = REPOSITORY_ROOT / grant["source"]
        target = destination / grant["source"]
        # `parents=True` because the sources sit several directories deep and
        # `exist_ok=True` because several grants share one parent directory.
        target.parent.mkdir(parents=True, exist_ok=True)
        # `copy2` rather than `copy` so metadata rides along too; only the
        # bytes matter to the digest, but copying faithfully keeps the scratch
        # tree an honest stand-in for the real one.
        shutil.copy2(source, target)
    return destination


def test_mutation_a_deleted_granted_source_is_caught(tmp_path: Path):
    """Delete one granted drawing in a scratch tree; the guard must name it.

    This reproduces the 2026-08-06 incident in miniature. If this test ever
    stops failing-on-purpose, the headline guard above has become decorative.
    """
    grants = real_grants(_register())
    root = _scratch_tree_of_granted_sources(grants, tmp_path / "scratch")

    # Pick the mug deliberately: it is one of the ten drawings the operator
    # personally handed over, and it was among the eleven files `1bdea41`
    # deleted.
    victim = next(g for g in grants if g["asset_id"] == "fixture.coffee_mug")
    (root / victim["source"]).unlink()

    failures = grant_source_failures(grants, root)
    # Exactly one, not "at least one": a guard that reported collateral damage
    # for the four untouched grants would be teaching its readers to skim.
    assert len(failures) == 1, failures
    assert "fixture.coffee_mug" in failures[0]
    assert "ABSENT" in failures[0]
    assert victim["source"] in failures[0]


def test_mutation_an_altered_granted_source_is_caught(tmp_path: Path):
    """Change one byte of granted art; the guard must report the digest drift.

    The deletion case above is the loud one. This is the quiet one: the file is
    still there, the build still finds it, and only the recorded digest knows
    that the operator's ink has been overwritten by somebody else's.
    """
    grants = real_grants(_register())
    root = _scratch_tree_of_granted_sources(grants, tmp_path / "scratch")

    victim = next(g for g in grants if g["asset_id"] == "fixture.mixtape")
    altered = root / victim["source"]
    # A single trailing space is enough, and is chosen precisely because it is
    # the kind of edit an editor or a formatter makes without being asked --
    # invisible on screen, and a different drawing as far as a monospace
    # renderer is concerned.
    altered.write_bytes(altered.read_bytes() + b" ")

    failures = grant_source_failures(grants, root)
    assert len(failures) == 1, failures
    assert "fixture.mixtape" in failures[0]
    assert "NO LONGER" in failures[0]
    # The message must carry both digests, so the reader can tell at a glance
    # whether the file drifted or the register did.
    assert victim["source_sha256"] in failures[0]
