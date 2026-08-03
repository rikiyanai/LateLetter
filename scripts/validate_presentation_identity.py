#!/usr/bin/env python3
"""Check that every visible Garden cell can name where its picture came from.

WHY THIS EXISTS
---------------
Five refactor attempts argued about whether a drawing was approved, and lost,
because there was no way to ask the question mechanically.  The only criterion
anyone could check was "does the renderer own this paint", which is the wrong
question -- SPEC 7.2 explicitly assigns sky, ground, weather, hover feedback and
one-cell ambience to the renderer.  Applying it deleted approved art three
times: the ground cover band, the butterflies and fireflies, then the sky.

The right question is IDENTITY.  A cell may be painted by anything, anywhere, as
long as it can say which registered visual source produced it.  There are
exactly two legal sources, and they are not tiers -- they are different
provenance routes:

    canonical object  -> atlas asset         -> emitted cell  (kind 'atlas')
    projection/time   -> presentation recipe -> emitted cell  (kind 'recipe')

Cells on the atlas chain may additionally carry an ``object_id``, inherited only
from canonical projection.  Cells on the recipe chain may not: a recipe owns
visible language, never placement, collision or a command target.

A third thing exists that emits no cell at all and still decides how every cell
looks: a LAW.  Wind, frame cadence, painter order, population density and the
palette are laws.  They are registered, they are graded, and they are reachable
from a paint record through ``law_refs`` -- but a law is never itself the source
id of an emitted cell, because no cell comes only from "the wind".

WHAT IT CHECKS
--------------
1. Register integrity -- both registers are internally coherent, their identity
   spaces do not overlap, and the law dependency graph agrees in both
   directions.
2. Provenance -- every claim about the deployed artifact is verified against the
   immutable blob and against the operator decision record, rather than being
   checked merely for being a non-empty string.
3. Runtime frame identity -- an actual frame is composed through the public
   GardenPresentation interface under the committed accepted-paint authority
   (``scripts/compose_frame_check.mjs``), and every clause of the executable
   presentation contract is applied to the primitives that came back.
4. Active release blockers -- the computed, clearable conditions that must all
   be empty before a root-product deploy.

HOW THE RENDERER IS JUDGED
--------------------------
By EXECUTION, never by reading its source.  The static writer-graph analyzer
that used to live here was deleted on 2026-08-03 per SPEC 7.2.2 clause 4:
eight audit rounds tried to decide "does this cell carry identity" from
source text, and every round was defeated by an invocation spelling the
previous round had not imagined.  Whether a run of code puts an identity in a
cell is a property of execution, so the gate now composes a frame and looks
at the cells.  The one remaining source-text check is the string presence of
the gameplay-art tables (``gameplay_art_outside_atlas``), which is a
route-step ownership fact, not an identity judgement.

USAGE
-----
    python3 scripts/validate_presentation_identity.py            # human report
    python3 scripts/validate_presentation_identity.py --json     # machine output
    python3 scripts/validate_presentation_identity.py --quiet    # exit code only

Exit code is 0 when there are no violations and no active blockers, 1 otherwise.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

# Repository root, derived from this file's location so the script works no
# matter which directory it is invoked from.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


ACCEPTANCE = ROOT / "docs" / "garden-asset-acceptance.json"
RECIPES = ROOT / "docs" / "garden-presentation-recipes.json"
RENDERER = ROOT / "web" / "garden-renderer.mjs"
DECISION_RECORD = ROOT / "docs" / "operator-decision-record.md"
# The operator's four direct-acceptance verdicts. Kept in its own file because a
# judgement made by a person after watching the product is a different kind of
# fact from anything this validator computes, and must never be derivable from
# the things it computes.
_REVIEW_VERDICTS = ROOT / "docs" / "garden-review-verdicts.json"

# Where a review package lives, and therefore the only place a verdict may cite
# its evidence from.
#
# Without this the checker verified that cited bytes had not changed and nothing
# else, so `docs/garden-asset-acceptance.json` -- a registry file -- could stand
# as the evidence for the MOTION verdict. Its digest matched, so the gate was
# satisfied by a document nobody could watch. Evidence integrity without
# evidence relevance is a gate that checks its own paperwork.
_REVIEW_PACKAGE_ROOT = ROOT / "docs" / "visual-review"

# Verdicts that permit a source to appear in a released frame.  Everything else
# -- not_reviewed, rejected, or an unrecognised string -- blocks a release.
#
# ``required`` was previously in this set and has been removed on purpose.
# "The operator asked for this" is a statement about PRESENCE, not about whether
# a particular drawing of it was accepted, and collapsing the two let a
# never-reviewed implementation ride into a release on the strength of the
# operator having asked for the feature.  Presence now lives in its own field,
# ``presence_requirement``.
RELEASE_SAFE_RECIPE_VERDICTS = frozenset({"accepted", "accepted_as_deployed"})
RELEASE_SAFE_ASSET_VERDICTS = frozenset({"accepted"})

# Verdicts that make a provenance claim about the deployed legacy artifact and
# therefore must be verifiable against the immutable blob.
PROVENANCE_CLAIMING_VERDICTS = frozenset({"accepted_as_deployed"})

# Any verdict that grades the record at all must rest on an operator statement.
# A graded verdict with no decision_ref is an assistant assertion in a verdict's
# clothing, which is precisely the failure this register exists to stop.
GRADED_VERDICTS = PROVENANCE_CLAIMING_VERDICTS | {"accepted", "rejected"}

VALID_CANDIDATE_STATUS = frozenset({"absent", "exact", "different", "rejected"})
VALID_PRESENCE = frozenset({"required", "optional"})

# The exhaustive set of invariants the acceptance registry asserts about ITSELF
# -- never about releases, which are governed by release_policy and
# active_release_blockers alone.
#
# These are IDs rather than sentences on purpose.  A free-form list is an
# authority surface: anyone could add "Public artifacts may always ship" and it
# would read as policy to the next person, while no check could tell it from the
# rules that were meant to be there.  Filtering such a line by vocabulary is a
# losing game -- the same claim can always be reworded.  An enumerated set has
# no room to write a new rule into: an unknown ID is refused because it is
# unknown, whatever it says.  Changing policy therefore means editing this
# dictionary, in code, under review.
REGISTRY_INVARIANTS = {
    "asset_verdict_vocabulary_is_enumerated":
        "verdict is one of accepted, rejected, not_reviewed. Every asset begins not_reviewed.",
    "machine_checks_are_admission_not_acceptance":
        "Machine checks are admission criteria for review, never substitutes for it "
        "(SPEC 7.10.1).",
    "unaccepted_assets_get_no_acceptance_vocabulary":
        "An asset without an accepted verdict must not be described with acceptance or "
        "finished-work vocabulary anywhere.",
}

# The EXACT top-level shape of each register.  Not a minimum, not a set of
# required keys with room beside them: an exact set, checked in both directions.
#
# Enumerating the invariant IDs shut one authority surface and left the class
# open, because a new surface only has to be spelled differently:
#
#     {"shipping_policy": ["Public artifacts may always ship."]}
#
# That is not a rules list, not a registry_invariants entry, and it reads to the
# next person as policy while nothing can distinguish it from the real fields.
# The general answer is an exact schema -- any field this module does not know
# is refused for being unknown, so there is no name left to write authority
# under.  Adding a legitimate field means adding it here, deliberately, which is
# the point.
ACCEPTANCE_FIELDS = frozenset({
    "schema", "purpose", "operator_grants", "withdrawn_acceptances",
    "review_candidates", "review_candidates_note", "legacy_ported_renderer_art",
    "assets", "presentation_recipe_register", "release_policy",
    "active_release_blockers", "registry_invariants_note", "registry_invariants",
})
RECIPE_FILE_FIELDS = frozenset({
    "schema", "supersedes", "purpose", "source_chains", "record_fields",
    "verdicts", "provenance_blob", "decisions", "records", "disambiguation",
    "presence_requirements",
})

# The writer-graph constants that lived here (WRITER_METHODS, READER_METHODS,
# SOURCE_PROPERTY, PAINT_API_CLASS, and the invocation-form tables) were
# deleted with the static analyzer on 2026-08-03, per SPEC 7.2.2 clause 4:
# runtime identity is now judged by composing an actual frame through the
# public GardenPresentation interface (scripts/compose_frame_check.mjs) and
# reading the primitives back. Nothing here reads renderer source to decide
# what a cell carries any more.

# A provenance line citation: "412" or "412-431". Register validation still
# verifies every cited range against the immutable blob; that is register
# integrity, not renderer analysis, so it survives the analyzer's deletion.
_RANGE_RE = re.compile(r"^(\d+)(?:-(\d+))?$")

@dataclass
class Report:
    """Everything the check found, separated by what kind of thing it is."""

    # Register integrity problems.  These are defects in the records themselves
    # and are never "currently true, will clear later".
    violations: list[str] = field(default_factory=list)
    # Conditions that block a root-product deploy but can legitimately clear.
    blockers: dict[str, list] = field(default_factory=dict)
    # Counts, so the human report does not have to be believed on trust.
    counts: dict[str, int] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.violations and not any(self.blockers.values())


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# ── Reading the renderer ────────────────────────────────────────────────────


def _git(*args: str) -> tuple[int, str]:
    """Run a git command in the repository and return (exit code, stdout).

    Cached because the same blob is interrogated once per record, and the blob
    is immutable by definition -- if its content could change between calls it
    would not be usable as provenance in the first place.
    """
    result = subprocess.run(
        ["git", "-C", str(ROOT), *args],
        capture_output=True, text=True,
    )
    return result.returncode, result.stdout


@lru_cache(maxsize=None)
def blob_lines(blob: str) -> tuple[str, ...] | None:
    """The blob's lines, or None when the object is not a readable blob.

    Returned as a tuple so the lru_cache entry stays immutable -- a caller that
    mutated a cached list would silently change what every later record is
    validated against.
    """
    kind_code, kind = _git("cat-file", "-t", blob)
    if kind_code != 0 or kind.strip() != "blob":
        return None
    content_code, content = _git("cat-file", "-p", blob)
    if content_code != 0:
        return None
    return tuple(content.split("\n"))


@lru_cache(maxsize=None)
def blob_line_count(blob: str) -> int | None:
    """Number of lines in a git blob, or None when the object is not a blob.

    This is what makes a cited line range falsifiable.  Without it, "lines
    1737-1741" is just a string, and the previous register carried several
    ranges that pointed at unrelated code precisely because nothing compared
    them to anything.
    """
    kind_code, kind = _git("cat-file", "-t", blob)
    if kind_code != 0 or kind.strip() != "blob":
        return None
    content_code, content = _git("cat-file", "-p", blob)
    if content_code != 0:
        return None
    return content.count("\n")


@lru_cache(maxsize=None)
def _decision_record_sections() -> dict[str, str]:
    """Map every heading anchor in the decision record to its section body.

    Anchors are GitHub-style slugs of the heading text: lowercased, punctuation
    dropped, spaces turned into hyphens.  Resolving them for real is what turns
    ``decision_refs`` from a decorative string into a citation -- a reference to
    a heading that does not exist now fails instead of being believed.
    """
    if not DECISION_RECORD.exists():
        return {}
    sections: dict[str, str] = {}
    current: str | None = None
    body: list[str] = []
    for raw_line in DECISION_RECORD.read_text(encoding="utf-8").splitlines():
        if raw_line.startswith("#"):
            if current is not None:
                sections[current] = "\n".join(body)
            heading = raw_line.lstrip("#").strip()
            # GitHub's anchor rule, reproduced exactly so the anchors in the
            # register are real links a human can follow, not a private
            # convention that merely validates against itself: lowercase, drop
            # punctuation, then turn EACH remaining space into a hyphen.
            #
            # Collapsing runs of whitespace instead would be the natural thing
            # to write and would be wrong -- an em dash leaves two spaces behind
            # when it is stripped, so `OPERATOR - 2026-...` anchors as
            # `operator--2026-...` with two hyphens, and a slug with one hyphen
            # scrolls nowhere.
            slug = heading.lower()
            slug = re.sub(r"[^\w\s-]", "", slug)   # drop `:`, backticks, em dash
            current = re.sub(r"\s", "-", slug.strip())
            body = []
        elif current is not None:
            body.append(raw_line)
    if current is not None:
        sections[current] = "\n".join(body)
    return sections


def _unwrap(text: str) -> str:
    """Undo line wrapping only: every run of whitespace becomes one space.

    This is the ONLY normalisation applied to an operator quotation, and the
    limit is deliberate.  The previous version also lowercased, which meant a
    quotation could be rewritten in a different case and still validate -- and
    the operator writes in capitals when something matters, so case is content
    here, not formatting.  Comparison after this is case-sensitive, which is
    what makes "verbatim" an accurate word for it.

    Wrapping is normalised because the register stores quotations inside JSON
    and a long line may be broken anywhere; a line break is not a change of
    words.
    """
    return re.sub(r"\s+", " ", text).strip()


def validate_provenance(recipes: dict) -> list[str]:
    """Verify every provenance and decision claim, rather than its presence.

    Checks, in order:
      * the declared provenance blob exists and really is a blob;
      * the path it claims to be still hashes to that blob;
      * every record's ``source_refs.blob`` is that same blob;
      * every cited line range parses and lies inside the blob;
      * every decision anchor resolves to a real heading in the decision record;
      * every quoted operator statement actually appears in that section.
    """
    problems: list[str] = []

    provenance = recipes.get("provenance_blob") or {}
    blob = provenance.get("blob")
    if not blob:
        return ["register declares no provenance_blob, so no source claim is verifiable"]

    line_count = blob_line_count(blob)
    if line_count is None:
        problems.append(
            f"provenance blob {blob!r} is not a readable git blob in this repository"
        )

    # The blob is the authority; the path is a convenience.  When the path still
    # exists it must still BE that blob, otherwise every line number in the
    # register silently refers to a file nobody is reading.
    declared_path = provenance.get("path")
    if declared_path:
        path = ROOT / declared_path
        if path.exists():
            code, current = _git("hash-object", declared_path)
            if code == 0 and current.strip() != blob:
                problems.append(
                    f"{declared_path} now hashes to {current.strip()[:12]} but the register "
                    f"cites {blob[:12]}; every line range in the register refers to the blob, "
                    "so the two must agree while the path is claimed to be identical"
                )

    sections = _decision_record_sections()

    for key, decision in (recipes.get("decisions") or {}).items():
        anchor = decision.get("anchor", "")
        if "#" not in anchor:
            problems.append(f"decision {key}: anchor {anchor!r} names no heading")
            continue
        document, _, slug = anchor.partition("#")
        if document != "docs/operator-decision-record.md":
            problems.append(f"decision {key}: anchor does not point into the decision record")
            continue
        if slug not in sections:
            problems.append(
                f"decision {key}: anchor {slug!r} does not resolve to any heading in "
                "docs/operator-decision-record.md"
            )
            continue
        # Every quotation must be VERBATIM in the cited section.  A single
        # `statement` field invited summarising -- joining two sentences from
        # different places with an ellipsis, or splicing in a gloss -- and a
        # summary is exactly what nobody can check later.  A list of exact
        # fragments can be checked one at a time, and a paraphrase fails.
        quotes = decision.get("quotes")
        # An empty string is contained by every section, so `quotes: [""]` is a
        # citation that cites nothing while satisfying any containment check.
        # The schema is checked before the content for exactly that reason.
        if not isinstance(quotes, list) or not quotes:
            problems.append(f"decision {key}: quotes must be a non-empty list of operator words")
            continue
        if any(not isinstance(q, str) or not q.strip() for q in quotes):
            problems.append(
                f"decision {key}: holds an empty or blank quotation, which every section "
                "satisfies and none is evidenced by"
            )
            continue
        section = _unwrap(sections[slug])
        for quote in quotes:
            if _unwrap(quote) not in section:
                problems.append(
                    f"decision {key}: the quotation {quote[:48]!r} does not appear verbatim in "
                    "the section it cites, so the register is paraphrasing the operator"
                )

    lines = blob_lines(blob)

    for recipe_id, record in recipes["records"].items():
        refs = record.get("source_refs")
        if not refs:
            continue
        if refs.get("blob") != blob:
            problems.append(
                f"{recipe_id}: source_refs.blob {refs.get('blob')!r} is not the register's "
                f"declared provenance blob"
            )
            continue
        if line_count is None or lines is None:
            continue

        # --- Every range carries and satisfies its OWN evidence --------------
        # Evidence used to be one record-wide list checked against the
        # concatenation of every range, which meant a single good range vouched
        # for all the others: a record could cite four correct spans and one
        # pointing at unrelated code, and the wrong one was covered by tokens
        # found in its neighbours.  Binding evidence per range removes the
        # cover, so each span has to justify itself.
        cited = refs.get("ranges")
        claims_deployment = record.get("verdict") in PROVENANCE_CLAIMING_VERDICTS
        if not isinstance(cited, list) or not cited:
            if claims_deployment:
                problems.append(f"{recipe_id}: claims the deployed implementation but cites no ranges")
            continue

        whole = "\n".join(lines)
        for position, entry in enumerate(cited):
            where = f"{recipe_id} range[{position}]"
            if not isinstance(entry, dict):
                problems.append(
                    f"{where}: must be an object with 'lines' and its own 'contains'; a bare "
                    "string cites a span that nothing has to justify"
                )
                continue

            match = _RANGE_RE.match(str(entry.get("lines")))
            if not match:
                problems.append(f"{where}: lines {entry.get('lines')!r} is not a line or span")
                continue
            first = int(match.group(1))
            last = int(match.group(2) or match.group(1))
            if first < 1 or last < first or last > line_count:
                problems.append(
                    f"{where}: {entry['lines']!r} is impossible in a {line_count}-line blob"
                )
                continue

            evidence = entry.get("contains")
            # The schema before the content: a bare string iterates as
            # characters, and an empty or blank token is contained by every span
            # in the file.  Both satisfy a naive check while proving nothing.
            if not isinstance(evidence, list) or not evidence:
                problems.append(
                    f"{where}: contains must be a non-empty list of evidence strings, not "
                    f"{type(evidence).__name__}"
                )
                continue
            if any(not isinstance(t, str) or not t.strip() for t in evidence):
                problems.append(
                    f"{where}: holds an empty or blank token, which every span in the artifact "
                    "satisfies and no span is pinned by"
                )
                continue

            span = "\n".join(lines[first - 1:last])
            for token in evidence:
                if token not in span:
                    problems.append(
                        f"{where}: lines {entry['lines']} do not contain {token!r}, so the span "
                        "does not hold what the record says is there"
                    )
            # --- One token must PIN this span --------------------------------
            # A token occurring all over the artifact is satisfied by any span
            # containing any one of its occurrences: `a.feedGlyph` appears seven
            # times, so citing the lines that merely null it out satisfied a
            # record describing the lines that PAINT it.
            if not any(whole.count(token) == 1 for token in evidence):
                problems.append(
                    f"{where}: no evidence token is unique in the artifact, so this span is "
                    "satisfied by any occurrence anywhere and pins nothing"
                )

    return problems


# ── Register integrity ──────────────────────────────────────────────────────


def _nested_object_ids(value, trail: str = "") -> list[str]:
    """Every path at which an ``object_id`` key appears, at any depth.

    A top-level-only check was defeated by ``{"metadata": {"object_id": ...}}``,
    which is the shape anyone would reach for while trying to keep the field
    "just for reference".  Gameplay identity is exactly as consequential nested
    as it is at the top level, so the search has to be exhaustive.
    """
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{trail}.{key}" if trail else key
            if key == "object_id":
                found.append(path)
            found.extend(_nested_object_ids(child, path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(_nested_object_ids(child, f"{trail}[{index}]"))
    return found


def validate_registers(acceptance: dict, recipes: dict) -> list[str]:
    """Check both registers for internal coherence and identity crossover.

    Returns a list of human-readable violations; empty means coherent.  These
    are defects in the records, not conditions that clear over time, which is
    why they are kept separate from blockers.
    """
    problems: list[str] = []

    # --- Neither register may grow a field this module does not know ---------
    # Checked in both directions, so a new authority surface cannot be added
    # under an unrecognised name and a documented one cannot quietly vanish.
    for label, register, allowed in (
        ("acceptance registry", acceptance, ACCEPTANCE_FIELDS),
        ("recipe register", recipes, RECIPE_FILE_FIELDS),
    ):
        for field in sorted(set(register) - allowed):
            problems.append(
                f"{label}: top-level field {field!r} is not part of this register's schema; "
                "a field this validator does not define carries no authority and may not "
                "stand as one"
            )
        for field in sorted(allowed - set(register)):
            problems.append(f"{label}: required top-level field {field!r} is missing")

    # --- The registry may only assert invariants this module defines ---------
    # There is no free-form rules list to write a new policy into, and no
    # vocabulary filter to word around; an ID that is not defined here has no
    # meaning and is refused on that basis alone.
    declared = acceptance.get("registry_invariants")
    if not isinstance(declared, list):
        problems.append("registry_invariants must be a list of invariant IDs")
    else:
        for invariant in declared:
            if invariant not in REGISTRY_INVARIANTS:
                problems.append(
                    f"registry_invariants: {invariant!r} is not an invariant this validator "
                    "defines, so it asserts nothing and may not stand as policy"
                )
        if len(set(declared)) != len(declared):
            problems.append("registry_invariants lists the same invariant more than once")
        for missing in sorted(set(REGISTRY_INVARIANTS) - set(declared)):
            problems.append(
                f"registry_invariants: {missing!r} is defined but the registry does not "
                "declare it, so an invariant exists that the file does not state"
            )
    if "rules" in acceptance or "registry_rules" in acceptance:
        problems.append(
            "a free-form rules list is back in the acceptance registry; policy written there "
            "reads as authority while no check can tell it from the real rules"
        )

    asset_ids = {row["asset_id"] for row in acceptance["assets"]}
    records = recipes["records"]
    known_decisions = set(recipes.get("decisions", {}))
    known_verdicts = set(recipes.get("verdicts", {}))
    laws = {rid for rid, rec in records.items() if rec.get("kind") == "law"}

    # --- Identity spaces must not overlap ------------------------------------
    # If one string is both a recipe_id and an asset_id, a cell naming it has an
    # ambiguous acceptance state by construction, and no amount of later care
    # recovers the answer.
    for identity in sorted(set(records) & asset_ids):
        problems.append(
            f"identity crossover: {identity!r} exists in BOTH registers, so its "
            "acceptance state is ambiguous"
        )

    for recipe_id, record in records.items():
        # --- A recipe must never acquire gameplay identity -------------------
        # An object_id would entitle it to placement, collision and a command
        # target, collapsing the distinction the register exists to hold.
        for path in _nested_object_ids(record):
            problems.append(
                f"{recipe_id}: carries object_id at {path!r}; a recipe owns visible "
                "language only, never placement or a command target"
            )

        verdict = record.get("verdict")
        if verdict not in known_verdicts:
            problems.append(
                f"{recipe_id}: verdict {verdict!r} is not defined in the "
                "register's own verdict vocabulary"
            )

        status = record.get("candidate_status")
        if status not in VALID_CANDIDATE_STATUS:
            problems.append(
                f"{recipe_id}: candidate_status {status!r} is not one of "
                f"{sorted(VALID_CANDIDATE_STATUS)}"
            )

        presence = record.get("presence_requirement")
        if presence not in VALID_PRESENCE:
            problems.append(
                f"{recipe_id}: presence_requirement {presence!r} is not one of "
                f"{sorted(VALID_PRESENCE)}; whether the operator asked for a thing is "
                "a separate question from whether a drawing of it was accepted"
            )

        if not record.get("language"):
            problems.append(f"{recipe_id}: does not describe what it draws or decides")

        kind = record.get("kind")
        if kind not in {"paint", "law"}:
            problems.append(f"{recipe_id}: kind must be 'paint' or 'law'")

        # --- Graded verdicts must rest on an operator statement --------------
        decision_refs = record.get("decision_refs") or []
        if verdict in GRADED_VERDICTS and not decision_refs:
            problems.append(
                f"{recipe_id}: verdict {verdict!r} cites no operator decision, so "
                "it is an assistant assertion rather than a recorded decision"
            )
        for ref in decision_refs:
            if ref not in known_decisions:
                problems.append(f"{recipe_id}: decision_ref {ref!r} is not a known decision")

        # --- Provenance claims must cite the immutable blob ------------------
        # A source reference is provenance, not approval; but a verdict that
        # claims "this is the deployed implementation" is unverifiable without
        # one.  Whether the citation is CORRECT is validate_provenance's job.
        if verdict in PROVENANCE_CLAIMING_VERDICTS:
            refs = record.get("source_refs")
            if not refs or not refs.get("blob") or not refs.get("ranges"):
                problems.append(
                    f"{recipe_id}: verdict {verdict!r} claims the deployed "
                    "implementation but cites no blob and ranges"
                )

        # --- The law dependency graph ----------------------------------------
        # A painted cell is produced by its recipe AND by every law in force
        # when it was painted.  One visual_source_id cannot express that, so the
        # dependency is an explicit edge instead of an implied one.
        law_refs = record.get("law_refs")
        if kind == "paint":
            if law_refs is None:
                problems.append(
                    f"{recipe_id}: paint record declares no law_refs; a cell that depends "
                    "on wind, cadence or painter order must say so"
                )
            else:
                for ref in law_refs:
                    if ref not in records:
                        problems.append(f"{recipe_id}: law_ref {ref!r} is not a registered record")
                    elif ref not in laws:
                        problems.append(
                            f"{recipe_id}: law_ref {ref!r} is a paint record, not a law"
                        )
        elif kind == "law" and law_refs:
            for ref in law_refs:
                if ref not in laws:
                    problems.append(
                        f"{recipe_id}: a law may only depend on other laws, not on {ref!r}"
                    )

    # --- Laws must agree with their dependents, in both directions -----------
    # Stating the edge once lets it rot; stating it twice and checking makes a
    # law that quietly loses a dependent fail.  "Wind affects the grass" and
    # "the grass depends on wind" have to be the same fact.
    for law_id in sorted(laws):
        declared = set(records[law_id].get("dependents") or [])
        actual = {
            rid for rid, rec in records.items()
            if law_id in (rec.get("law_refs") or [])
        }
        for missing in sorted(actual - declared):
            problems.append(
                f"{law_id}: {missing!r} declares this law in law_refs but the law does "
                "not list it as a dependent"
            )
        for extra in sorted(declared - actual):
            problems.append(
                f"{law_id}: lists dependent {extra!r} which does not declare this law"
            )
        if not actual:
            problems.append(
                f"{law_id}: no record depends on this law, so nothing it decides reaches "
                "a cell -- either it is dead or a paint record is missing the edge"
            )

    return problems


# ── Release blockers ────────────────────────────────────────────────────────


def runtime_frame_report() -> dict:
    """Compose an actual frame through the public interface and report on it.

    Shells out to ``scripts/compose_frame_check.mjs``, which generates the
    starter world, projects it, composes it under the committed accepted-paint
    authority, and applies every clause of the executable presentation
    contract.  This is the runtime check that REPLACED the static writer
    graph: identity is a property of execution, so it is settled by executing.

    A check that cannot run must block a release rather than pass it, so any
    failure to produce a report -- node missing, script crash, unparsable
    output -- is returned AS violations instead of being raised past the
    gate.

    :returns: ``{"violations": [...], "divergent": [...], "stats": {...}}``
    """
    try:
        completed = subprocess.run(
            ["node", str(ROOT / "scripts" / "compose_frame_check.mjs")],
            capture_output=True, text=True, timeout=120, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return {"violations": [{"clause": "gate-execution",
                                "detail": f"runtime frame check did not run: {error}"}],
                "divergent": [], "stats": {}}
    if completed.returncode != 0:
        return {"violations": [{"clause": "gate-execution",
                                "detail": "runtime frame check exited "
                                          f"{completed.returncode}: {completed.stderr[:400]}"}],
                "divergent": [], "stats": {}}
    try:
        return json.loads(completed.stdout)
    except ValueError as error:
        return {"violations": [{"clause": "gate-execution",
                                "detail": f"runtime frame check output unreadable: {error}"}],
                "divergent": [], "stats": {}}


def compute_blockers(
    acceptance: dict, recipes: dict, renderer_source: str, runtime_report: dict,
) -> dict[str, list]:
    """Compute the clearable conditions that block a root-product deploy.

    Kept strictly apart from ``release_policy`` in the acceptance registry.
    Policy is permanent and can never be satisfied; these can, and a deploy
    requires that they all are.  Mixing the two produced a list that could never
    legitimately be empty, which made asserting emptiness meaningless.

    The KEYS of this dict are the contract: the acceptance registry enumerates
    the same names, and a test asserts the two agree exactly, so a condition
    cannot be added here and left undocumented there.

    Seven static writer-graph blockers were deleted on 2026-08-03 with the
    analyzer that computed them (anonymous_paint_sites,
    unknown_visual_source_ids, laws_used_as_cell_sources,
    unrecognised_paint_methods, unresolvable_paint_call_forms,
    writers_that_cannot_record_identity, and the source-scan half of
    divergent_implementations_claiming_approval).  What they guarded is now
    guarded at RUNTIME by ``runtime_frame_violations``: an anonymous
    primitive, an unknown or law source id, an authority breach or a hidden
    second composer all surface as contract violations on a frame that was
    actually composed.  Divergence keeps its own key because it fails for a
    different reason (register honesty, not frame identity) and clears at a
    different step (the legacy-presentation restoration).
    """
    records = recipes["records"]

    return {
        "unaccepted_atlas_assets": sorted(
            row["asset_id"] for row in acceptance["assets"]
            if row["verdict"] not in RELEASE_SAFE_ASSET_VERDICTS
        ),
        "unaccepted_recipes": sorted(
            recipe_id for recipe_id, record in records.items()
            if record["verdict"] not in RELEASE_SAFE_RECIPE_VERDICTS
        ),
        # The operator asked for this and the product does not do it.  Absence is
        # the defect, so it blocks a release exactly as a rejected drawing does.
        "required_presentation_absent": sorted(
            recipe_id for recipe_id, record in records.items()
            if record.get("presence_requirement") == "required"
            and record.get("candidate_status") in {"absent", "rejected"}
        ),
        # The executable presentation contract, applied to a frame the public
        # interface actually composed: emitted-primitive identity, paint
        # authority, visible-subset-of-attempted, region ownership,
        # determinism and hostname independence, plus any suppression -- a
        # release frame that NEEDED suppression tried to paint something
        # unaccepted, and hiding it is not a release condition.
        "runtime_frame_violations": [
            f"[{item.get('clause', '?')}] {item.get('detail', '')}"
            for item in runtime_report.get("violations", [])
        ],
        # A painted id may only claim a deployed-provenance verdict when the
        # implementation behind it reproduces the deployed one exactly.  A
        # citation of legacy line numbers is provenance, not approval.
        # Reported from the composed frame's painted sources rather than from
        # a source scan.
        "divergent_implementations_claiming_approval": list(
            runtime_report.get("divergent", [])
        ),
        "gameplay_art_outside_atlas": [
            owner for owner in ("plantArt", "animalArt", "collectibleArt", "fixtureArt")
            if owner in renderer_source
        ],
        # The STARTER COMPOSITION -- which population the recipient's world opens
        # with -- as distinct from how any single thing in it is drawn. A garden
        # can be made entirely of accepted drawings and still be the wrong
        # garden, so the two verdicts are separate and both must clear.
        #
        # This is what makes docs/garden-composition-acceptance.json live policy
        # rather than a file only tests read. Before it, the register existed and
        # nothing consulted it, which is indistinguishable from not having one.
        "unaccepted_starter_composition": unaccepted_starter_composition(),
        # The one gate no machine can clear. Everything else in this validator
        # measures structure; none of it can say whether the Garden is worth
        # looking at. Four verdicts, blocked separately, because they fail for
        # different reasons and collapsing them would let three unexamined
        # judgements ride on the easiest one.
        "operator_review_outstanding": outstanding_operator_verdicts(),
    }


def outstanding_operator_verdicts() -> list[str]:
    """Report every direct-acceptance verdict the operator has not given.

    Read from ``docs/garden-review-verdicts.json``.  Nothing computes or infers
    these: a verdict is a person's judgement after watching the moving product,
    and no test result, density number or opened screenshot substitutes for one.

    :returns: one entry per outstanding verdict, empty only when all four are
        accepted
    """
    register = json.loads(_REVIEW_VERDICTS.read_text(encoding="utf-8"))
    vocabulary = set(register["vocabulary"])
    outstanding = []
    for name, record in sorted(register["verdicts"].items()):
        verdict = record.get("verdict", "not_reviewed")

        # An unknown word is not an acceptance. Checking only `!= "accepted"`
        # would also treat a typo as a rejection, which is the safe direction;
        # refusing it outright says which one it actually was.
        if verdict not in vocabulary:
            outstanding.append(f"{name} carries the unknown verdict {verdict!r}")
            continue
        if verdict != "accepted":
            outstanding.append(f"{name} is {verdict}")
            continue

        # An acceptance is only as good as the evidence it was given. Without
        # this, setting four strings to "accepted" cleared the blocker with
        # `evidence: null` -- an approval of nothing, recorded by nobody, at no
        # time. That is the exact shape of the defect this register exists to
        # prevent, reintroduced inside its own checker.
        for field in ("evidence", "decided_by", "decided_at_utc"):
            if not record.get(field):
                outstanding.append(f"{name} is accepted but records no {field}")

        # WHO. A non-empty `decided_by` used to be enough, so "operator", "me"
        # or "ok" all counted as an author. An approval by nobody in particular
        # is not an approval, so the register must declare who the operator is
        # and the verdict must match that declaration. While `operator` is null
        # -- which it is, and which only the operator can change -- no
        # acceptance can clear this gate at all. That is the intended state: the
        # identity has to be established before it can be checked against.
        operator = register.get("operator")
        author = record.get("decided_by")
        if not operator:
            outstanding.append(
                f"{name} cannot be accepted until the register declares who the "
                "operator is in its top-level `operator` field"
            )
        elif author and author != operator:
            outstanding.append(
                f"{name} was decided by {author!r}, not by the declared "
                f"operator {operator!r}"
            )

        # WHEN. A non-empty timestamp used to be enough, so the word "soon"
        # would clear it. Parsed as a real instant, and refused if it is in the
        # future, because a verdict dated after the moment it is read was not
        # given by watching anything.
        stamped = record.get("decided_at_utc")
        if stamped:
            try:
                moment = datetime.datetime.fromisoformat(
                    str(stamped).replace("Z", "+00:00")
                )
            except ValueError:
                outstanding.append(
                    f"{name} records {stamped!r}, which is not an ISO-8601 instant"
                )
            else:
                if moment.tzinfo is None:
                    outstanding.append(
                        f"{name} records {stamped!r} with no timezone; the field "
                        "is decided_at_UTC and must say so"
                    )
                elif moment > datetime.datetime.now(datetime.timezone.utc):
                    outstanding.append(
                        f"{name} is dated {stamped!r}, which is in the future"
                    )

        evidence = record.get("evidence")
        if not evidence:
            continue
        if not isinstance(evidence, list):
            outstanding.append(f"{name} evidence must be a list of artifacts")
            continue
        for artifact in evidence:
            path = artifact.get("path") if isinstance(artifact, dict) else None
            digest = artifact.get("sha256") if isinstance(artifact, dict) else None
            if not path or not digest:
                outstanding.append(f"{name} evidence entry needs a path and a sha256")
                continue
            located = ROOT / path
            # WHAT. Evidence must be something a person can watch, which means
            # it must come from a review package. Before this, any repository
            # file whose digest matched would do, and the satisfiable case in
            # the mutation test used `docs/garden-asset-acceptance.json` -- a
            # registry -- as the evidence for the MOTION verdict. The digest
            # matched, so the gate was cleared by a document nobody could watch.
            try:
                located.resolve().relative_to(_REVIEW_PACKAGE_ROOT.resolve())
            except ValueError:
                outstanding.append(
                    f"{name} cites {path}, which is not in the review package at "
                    f"{_REVIEW_PACKAGE_ROOT.relative_to(ROOT)}; a verdict binds to "
                    "an artifact that was watched, not to a repository file"
                )
                continue
            if not located.exists():
                outstanding.append(f"{name} cites missing evidence {path}")
                continue
            # The verdict binds to the bytes that were watched. Re-rendering the
            # product produces new artifacts and inherits nothing, because
            # approval attaches to what was actually looked at.
            actual = hashlib.sha256(located.read_bytes()).hexdigest()
            if actual != digest:
                outstanding.append(
                    f"{name} evidence {path} has changed since it was accepted "
                    f"(recorded {digest[:12]}, now {actual[:12]})"
                )

        # SHAPE, for the one verdict whose required evidence the register itself
        # already states: motion needs "at least ten seconds of real motion at
        # 1600x1000 and 390x844". Living in the review package is not enough --
        # a still PNG lives there too, and a verdict about whether the Garden
        # moves cannot be given by looking at one.
        #
        # Deliberately narrow. This checks that a video exists for each required
        # size, by the filename the capture tool writes. It does NOT verify
        # duration, that the video shows this candidate, or that anyone watched
        # it; the first would need ffprobe here and the last cannot be checked by
        # any machine. Overstating what this proves would repeat the mistake it
        # exists to correct.
        if name == "motion" and isinstance(evidence, list):
            named = " ".join(
                str(item.get("path", "")) for item in evidence if isinstance(item, dict)
            )
            for size in ("1600x1000", "390x844"):
                if f"{size}.webm" not in named:
                    outstanding.append(
                        f"motion is accepted but cites no {size} video; the "
                        "register requires ten seconds of real motion at both "
                        "required sizes"
                    )
    return outstanding


def unaccepted_starter_composition() -> list[str]:
    """Report the current starter composition unless the operator accepted it.

    Generates the starter through the real generator and looks its revision and
    roster fingerprint up in the acceptance register.  Nothing here reads a
    version number and calls it approval: the number says which candidate this
    is, the register says what the operator thought of it, and only the register
    can clear this blocker.

    :returns: a one-entry list naming the unaccepted composition, or empty when
        a matching accepted verdict exists
    """
    # Imported here rather than at module scope: this validator is run as a
    # standalone script from the repository root, and a top-level import of the
    # package would make the whole gate depend on the package being installed.
    sys.path.insert(0, str(ROOT / "src"))
    from lateletter.garden.world.generation import generate_initial_world
    from lateletter.garden.world.provenance import composition_acceptance

    starter = generate_initial_world("release-gate", "release-gate")
    verdict = composition_acceptance(starter)
    if verdict == "accepted":
        return []
    return [
        f"composition revision {starter.composition_version} "
        f"({starter.composition_fingerprint}) is {verdict}"
    ]


def run() -> Report:
    """Load everything from disk, compose the gate frame, and report."""
    acceptance = _read(ACCEPTANCE)
    recipes = _read(RECIPES)
    renderer_source = RENDERER.read_text(encoding="utf-8")
    runtime = runtime_frame_report()

    report = Report()
    report.violations = validate_registers(acceptance, recipes) + validate_provenance(recipes)
    report.blockers = compute_blockers(acceptance, recipes, renderer_source, runtime)

    records = recipes["records"]
    stats = runtime.get("stats", {})
    report.counts = {
        "recipes": len(records),
        "laws": sum(1 for r in records.values() if r.get("kind") == "law"),
        "paint_records": sum(1 for r in records.values() if r.get("kind") == "paint"),
        "atlas_assets": len(acceptance["assets"]),
        # Runtime facts from the composed gate frame, replacing the deleted
        # static site counts: what was actually attempted and shown.
        "frame_attempted_primitives": stats.get("attempted", 0),
        "frame_visible_primitives": stats.get("visible", 0),
        "frame_suppressed_primitives": stats.get("suppressed", 0),
        "frame_interaction_regions": stats.get("regions", 0),
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit machine-readable output")
    parser.add_argument("--quiet", action="store_true", help="exit code only")
    args = parser.parse_args()

    report = run()

    if args.json:
        print(json.dumps({
            "ok": report.ok,
            "violations": report.violations,
            "blockers": report.blockers,
            "counts": report.counts,
        }, indent=2))
    elif not args.quiet:
        print("presentation identity check")
        for key, value in report.counts.items():
            print(f"  {key:28s}: {value}")
        print()
        if report.violations:
            print(f"register violations ({len(report.violations)}):")
            for problem in report.violations:
                print(f"  - {problem}")
        else:
            print("register violations: none")
        print()
        print("active release blockers:")
        for name, items in report.blockers.items():
            print(f"  {name}: {len(items)}")
            for item in items[:5]:
                print(f"      {item}")
            if len(items) > 5:
                print(f"      ... and {len(items) - 5} more")

    return 0 if report.ok else 1


if __name__ == "__main__":
    sys.exit(main())
