#!/usr/bin/env python3
"""Verify one pushed revision still carries the operator's granted art.

Called by .githooks/pre-push once per revision being published. Reads ONLY
that revision's content through `git show <rev>:<path>` -- never the checkout,
which in this repository is shared between concurrent lanes and is permanently
dirty with in-flight changes that have nothing to do with the push.

The failure this exists to catch
--------------------------------
A concurrent lane's documentation commit deleted eleven operator-granted art
files with no mention of them, and a later index staged the same deletion plus
the deletion of the test that guards it. The register would then have gone on
naming sources that no longer existed, and the next release build would have
raised far from the cause. This makes that refusal happen at push, in terms
that name the missing file.

Exit status
-----------
0 -- every grant source and the guard test are present at this revision.
1 -- something is missing; a message naming each one is printed to stderr.
"""

import json
import subprocess
import sys

# The register that names which asset ids the operator has granted, and which
# exact file supplies each one's ink.
REGISTER = "docs/garden-asset-acceptance.json"

# The suite-level guard. If a commit removes this, the grant check would stop
# running in CI and in local test runs, so its absence is itself a refusal.
GUARD_TEST = "tests/garden_acceptance/test_operator_grant_sources.py"


def blob_at(revision: str, path: str) -> bytes | None:
    """Return the bytes of ``path`` as of ``revision``, or None if absent.

    Uses `git show <rev>:<path>`, which fails when the path does not exist at
    that revision -- that failure IS the signal, so it is caught rather than
    allowed to propagate.
    """
    result = subprocess.run(
        ["git", "show", f"{revision}:{path}"],
        capture_output=True,
    )
    # A non-zero status here means the path is not present at this revision.
    return result.stdout if result.returncode == 0 else None


def main() -> int:
    revision = sys.argv[1]

    register_raw = blob_at(revision, REGISTER)
    if register_raw is None:
        # No register at this revision means there are no grants to verify.
        # That is legitimate for old history, so it is not a refusal.
        return 0

    register = json.loads(register_raw)
    problems: list[str] = []

    # Walk the grant ledger. The same array also holds prose-only historical
    # rows whose asset_id/source/source_sha256 are null; those are not grants
    # and are skipped, exactly as the release builder skips them.
    grants = 0
    for grant in register.get("operator_grants", []):
        asset_id = grant.get("asset_id")
        source = grant.get("source")
        digest = grant.get("source_sha256")
        if not (isinstance(asset_id, str) and isinstance(source, str)
                and isinstance(digest, str)):
            continue
        grants += 1
        if blob_at(revision, source) is None:
            problems.append(
                f"  operator grant {asset_id!r}: its hash-bound source {source} "
                f"is MISSING from this commit. The operator's own ink is being "
                f"deleted. Restore it from the commit that granted it rather "
                f"than redrawing it."
            )

    # The guard test only needs to exist once a grant exists to guard.
    if grants and blob_at(revision, GUARD_TEST) is None:
        problems.append(
            f"  {GUARD_TEST} is MISSING from this commit. That is the test "
            f"which catches deleted grant sources; removing it alongside the "
            f"art is how the previous deletion went unnoticed."
        )

    if problems:
        print(
            f"\nrefusing to push {revision[:12]}: operator-granted art is not "
            f"intact in this commit.\n",
            file=sys.stderr,
        )
        for line in problems:
            print(line, file=sys.stderr)
        print(
            "\nIf a deletion here is genuinely intended, the grant must be "
            "withdrawn from the register in the same commit.\n",
            file=sys.stderr,
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
