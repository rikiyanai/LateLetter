#!/usr/bin/env python3
"""Decide, mechanically, whether a set of changed paths belongs to ONE lane.

WHY THIS FILE EXISTS
--------------------
Several sessions edit this single checkout at the same time.  Two of them can
write the same file and both writes apply cleanly, so a lost update is silent;
and a ``git commit`` taken with no pathspec sweeps up whatever another lane
happens to have left staged in the index.  The operator's standing rule -- "do
not execute from a mixed, uncommitted ownership state", and "no mixed Garden +
transcription + typography patch" -- was until now a sentence somebody had to
remember at the right moment.  Remembering is exactly what failed.

This script turns the rule into a question a machine answers.  It reads the
ownership map in ``docs/ownership-lanes.json``, asks git what has changed, and
reports which lane each change belongs to.  With ``--lane NAME`` it answers the
only question that matters before a patch: *would this patch be mixed?*

WHAT A "LANE" IS
----------------
A lane is a set of path patterns owned by one concurrent session.  Two lanes
never own the same path.  One lane is special: ``shared-canon`` is the prose
(SPEC, failure log, audits) that every lane appends to, so carrying a
shared-canon path does not, by itself, make a patch mixed.

WHAT "CONTENDED" MEANS
----------------------
A contended path holds work from more than one lane inside ONE uncommitted
diff.  Path scoping cannot separate those -- the mixture is *inside* the file --
so a contended path is refused even when its lane matches.  It has to be split
hunk by hunk, or left out of the patch.

USAGE
-----
    python3 scripts/check_lane_boundary.py
        Census: every changed path grouped by lane, and every path the manifest
        does not describe.  Exit 1 if anything is unclassified, because an
        unclassified path means the manifest has gone stale and its answers can
        no longer be trusted.

    python3 scripts/check_lane_boundary.py --lane garden-presentation
        Would a patch of this lane's changed paths be clean?  Prints the exact
        pathspec to use, and exits 1 if any contended path is in it or if
        another lane has staged work that a pathspec-less commit would carry.

    python3 scripts/check_lane_boundary.py --lane garden-presentation --paths a b
        The same question about an explicit list of paths rather than the whole
        checkout -- for checking a patch before making it.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

# The repository root, derived from this file's location rather than from the
# caller's current directory, so the script answers about THIS checkout no
# matter where it is invoked from.
ROOT = Path(__file__).resolve().parent.parent

# The ownership map.  Prose lives there, logic lives here; the two are kept
# apart so that changing who owns what does not mean editing code.
MANIFEST = ROOT / "docs" / "ownership-lanes.json"

# The lane that is not a lane.  Every lane appends to these files, so carrying
# one alongside real lane work is expected and is not a mixture.
SHARED = "shared-canon"


def _load_manifest() -> dict:
    """Read the ownership map, or explain why the answer cannot be given."""
    if not MANIFEST.exists():
        # Failing loudly beats defaulting to "everything is fine": a missing
        # manifest means no claim about mixing can be supported at all.
        sys.exit(f"ownership manifest absent: {MANIFEST}")
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def _changed_paths() -> dict[str, str]:
    """Every path git reports as changed, mapped to its two-letter status.

    ``git status --porcelain`` is used rather than ``git diff`` because it is
    the only view that sees all four states at once: staged (index differs from
    HEAD), unstaged (checkout differs from index), both, and untracked.  A path
    that is only staged is invisible to ``git diff`` and is precisely the kind
    of change that a pathspec-less commit would carry away unnoticed.
    """
    result = subprocess.run(
        ["git", "-C", str(ROOT), "status", "--porcelain", "-z"],
        capture_output=True,
        text=True,
        check=True,
    )
    changed: dict[str, str] = {}
    # -z gives NUL-separated records so that a path containing a space or a
    # quote is not mangled.  Each record is two status characters, a space,
    # then the path.
    for record in result.stdout.split("\0"):
        if len(record) < 4:
            continue
        status, path = record[:2], record[3:]
        # A rename record carries "old\0new"; with -z the new name is a
        # separate record, so taking the record as-is is correct here.
        changed[path] = status
    return changed


def _lane_of(path: str, lanes: dict) -> str | None:
    """Which lane owns this path, or None when the manifest does not say.

    Patterns are shell globs.  ``**`` is spelled as a prefix match rather than
    handed to fnmatch, because fnmatch's ``*`` already crosses ``/`` and so
    would make ``web/garden-*.mjs`` match paths in subdirectories it does not
    own.  Being explicit about the two forms keeps the map's meaning obvious to
    a reader who is not thinking about glob semantics.
    """
    for name, lane in lanes.items():
        for pattern in lane["owns"]:
            if pattern.endswith("/**"):
                # A directory claim: everything at or below this prefix.
                if path == pattern[:-3] or path.startswith(pattern[:-2]):
                    return name
            elif fnmatch.fnmatch(path, pattern):
                return name
    return None


def _census(
    changed: dict[str, str], lanes: dict, contended: set[str]
) -> tuple[dict[str, list[str]], list[str], list[str]]:
    """Group changed paths by lane; separate the contended from the unknown.

    Three outcomes, and keeping them apart is the point.  A path owned by one
    lane is ordinary.  A CONTENDED path is known to hold two lanes' work and is
    a described, expected problem.  An UNKNOWN path is the dangerous one: it
    means the manifest no longer describes this checkout, so every other answer
    the script gives is only as current as the map.
    """
    grouped: dict[str, list[str]] = defaultdict(list)
    disputed: list[str] = []
    unclaimed: list[str] = []
    for path in sorted(changed):
        if path in contended:
            disputed.append(path)
            continue
        lane = _lane_of(path, lanes)
        if lane is None:
            unclaimed.append(path)
        else:
            grouped[lane].append(path)
    return grouped, disputed, unclaimed


def _report_census(
    grouped: dict[str, list[str]],
    disputed: list[str],
    unclaimed: list[str],
    changed: dict[str, str],
    contended: dict[str, dict],
) -> int:
    """Print who owns what, and how much of it is already staged."""
    print(f"{len(changed)} changed entries in this checkout\n")
    for lane in sorted(grouped):
        paths = grouped[lane]
        # Staged paths are counted separately because they are the ones a
        # pathspec-less commit would take, whoever ran it.
        staged = sum(1 for p in paths if changed[p][0] not in {" ", "?"})
        print(f"  {lane:<22} {len(paths):>5} paths  ({staged} staged)")
        for path in paths[:6]:
            print(f"      {changed[path]} {path}")
        if len(paths) > 6:
            print(f"      ... and {len(paths) - 6} more")
    if disputed:
        print(f"\n  CONTENDED {len(disputed)} paths — two lanes' work inside one diff:")
        for path in disputed:
            print(f"      {changed[path]} {path}  ({' + '.join(contended[path]['lanes'])})")
    if unclaimed:
        print(f"\n  UNKNOWN {len(unclaimed)} paths — the manifest is stale:")
        for path in unclaimed:
            print(f"      {changed[path]} {path}")
        return 1
    return 0


def _report_lane(
    lane: str,
    grouped: dict[str, list[str]],
    changed: dict[str, str],
    manifest: dict,
    explicit: list[str] | None,
) -> int:
    """Answer the pre-patch question: would this lane's patch be mixed?"""
    lanes = manifest["lanes"]
    if lane not in lanes:
        sys.exit(f"unknown lane {lane!r}; known: {', '.join(sorted(lanes))}")

    # Either the caller named the paths, or we take everything this lane owns
    # that has changed.
    if explicit is None:
        paths = list(grouped.get(lane, []))
        canon = list(grouped.get(SHARED, []))
    else:
        paths, canon = [], []
        for path in explicit:
            owner = _lane_of(path, lanes)
            if owner == SHARED:
                canon.append(path)
            elif owner == lane:
                paths.append(path)
            else:
                # A path from another lane in an explicit list is the exact
                # failure this script exists to catch, so it is fatal rather
                # than a warning.
                print(f"REFUSED: {path} belongs to lane {owner or 'nothing'}, not {lane}")
                return 1

    contended = {row["path"]: row for row in manifest["contended"]}
    blocked = [p for p in paths + canon if p in contended]

    print(f"lane {lane}: {len(paths)} owned paths, {len(canon)} shared-canon paths")

    problems = 0
    if blocked:
        print("\nREFUSED — these hold more than one lane's work inside one diff:")
        for path in blocked:
            row = contended[path]
            print(f"  {path}  ({' + '.join(row['lanes'])})")
            print(f"      {row['evidence']}")
        problems += 1

    # A patch is also unsafe when another lane has staged work, because the
    # habitual `git commit` with no pathspec would carry it.  Naming the number
    # here is what makes the pathspec below non-optional.
    foreign_staged = [
        p
        for p, status in changed.items()
        if status[0] not in {" ", "?"} and _lane_of(p, lanes) not in {lane, SHARED, None}
    ]
    if foreign_staged:
        print(
            f"\nWARNING — {len(foreign_staged)} paths from other lanes are STAGED. "
            "A commit with no pathspec would carry them."
        )
        problems += 1

    if not problems:
        print("\nclean: this lane's changed paths do not mix lanes")
    safe = [p for p in paths + canon if p not in contended]
    if safe:
        print("\npathspec for a single-lane patch:")
        print("  git commit -- " + " ".join(f"'{p}'" for p in safe))
    return 1 if problems else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--lane", help="check whether a patch of this lane would be mixed")
    parser.add_argument(
        "--paths",
        nargs="*",
        help="explicit paths to check instead of everything the lane owns",
    )
    args = parser.parse_args()

    manifest = _load_manifest()
    contended = {row["path"]: row for row in manifest["contended"]}
    changed = _changed_paths()
    grouped, disputed, unclaimed = _census(changed, manifest["lanes"], set(contended))

    if args.lane:
        # A contended path still belongs to its lanes for the purpose of the
        # pre-patch question, so it is put back before that check runs -- the
        # lane report is where it gets refused, with the reason attached.
        for path in disputed:
            for lane in contended[path]["lanes"]:
                grouped[lane].append(path)
        return _report_lane(args.lane, grouped, changed, manifest, args.paths)
    return _report_census(grouped, disputed, unclaimed, changed, contended)


if __name__ == "__main__":
    raise SystemExit(main())
