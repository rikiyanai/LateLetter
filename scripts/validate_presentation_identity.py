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
3. Paint-site identity -- every cell-emitting call in the browser renderer names
   a registered visual source.
4. Active release blockers -- the computed, clearable conditions that must all
   be empty before a root-product deploy.

Point 3 currently reports every paint site as anonymous, because the renderer
does not yet pass source ids at all.  That is a true finding and a recorded
release blocker; it is NOT a defect in the register, and it is not this step's
closure criterion.  Threading ids through the painters is route step 5, and a
step may not be gated on work its own contract forbids it to do.

HOW THE RENDERER IS READ
------------------------
Through the JavaScript tokenizer in ``scripts/prepare_pages_site.py``, never
through a regular expression over raw text.  That module already learned this
lesson the expensive way: a regex cannot tell code from things that merely look
like code, so ``// raster.put(...)`` in a comment, ``"raster.put(...)"`` in a
string, the same text inside a template literal, and a real call containing
``f(')')`` were all read wrongly.  One tokenizer, reused -- a second scanner
would relearn the same bug somewhere else.

USAGE
-----
    python3 scripts/validate_presentation_identity.py            # human report
    python3 scripts/validate_presentation_identity.py --json     # machine output
    python3 scripts/validate_presentation_identity.py --quiet    # exit code only

Exit code is 0 when there are no violations and no active blockers, 1 otherwise.
"""

from __future__ import annotations

import argparse
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

from scripts.prepare_pages_site import tokenize_javascript  # noqa: E402

ACCEPTANCE = ROOT / "docs" / "garden-asset-acceptance.json"
RECIPES = ROOT / "docs" / "garden-presentation-recipes.json"
RENDERER = ROOT / "web" / "garden-renderer.mjs"
DECISION_RECORD = ROOT / "docs" / "operator-decision-record.md"
# The operator's four direct-acceptance verdicts. Kept in its own file because a
# judgement made by a person after watching the product is a different kind of
# fact from anything this validator computes, and must never be derivable from
# the things it computes.
_REVIEW_VERDICTS = ROOT / "docs" / "garden-review-verdicts.json"

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

# The two halves of the raster API, split by whether a call can put a NEW
# character on the screen.
#
# Writers emit cells, so each one is a place where provenance must be supplied.
# Readers consume cells that were already written -- ``line`` returns a row and
# ``latticeHtml`` serialises rows to markup.  Demanding a source id from them is
# not merely unnecessary, it is incoherent: a single row routinely holds cells
# from many different sources, so no one id could truthfully describe it.
# Provenance has to be stored per cell when it is WRITTEN and preserved through
# serialisation, which is why the readers are named here rather than ignored.
WRITER_METHODS = ("put", "text", "art", "measuredArt")
READER_METHODS = ("line", "latticeHtml")
KNOWN_RASTER_METHODS = WRITER_METHODS + READER_METHODS

# Argument-position property that carries the identity, e.g.
#     raster.put(x, y, glyph, colour, {source: 'recipe.ground.cover'})
SOURCE_PROPERTY = "source"

# There is deliberately no TERMINAL_WRITER constant here any more.  It named
# `put` as the one place an identity could be stored, which was true of today's
# renderer and was still a fact written down beside the code rather than read
# out of it.  `writer_identity_positions` now derives the terminal writers --
# the ones that assign into a per-cell plane -- and solves the delegation graph
# backward from whichever writers those turn out to be, so moving the store, or
# having two of them, is answered rather than assumed.

# The one class allowed to call the writer methods on itself without naming a
# visual source, because it IS the writer methods.  Named explicitly so the
# exemption cannot widen to any class that happens to define a `put`.
PAINT_API_CLASS = "Raster"

# Function-object methods that invoke their receiver with an explicitly supplied
# `this`.  They are the remaining way to reach a writer without writing a plain
# member call, and they defeat member-call recognition completely:
# `raster.put.call(raster, ...)` never puts `(` after `put`, and
# `const paint = raster[method]; paint.call(raster, ...)` does not even mention
# the raster at the call.  There are ZERO of them in the browser modules today,
# so refusing the whole family costs nothing and closes the class rather than
# the examples.
REFLECTIVE_INVOKERS = ("call", "apply", "bind")

# Matches "1719" or "1719-1725".  Anything else is a malformed range.
_RANGE_RE = re.compile(r"^(\d+)(?:-(\d+))?$")


@dataclass
class PaintSite:
    """One call in the renderer that puts characters on the screen.

    receiver:   the object the method was called on, e.g. ``raster``.
    method:     which raster API was used, e.g. ``put``.
    line:       1-indexed line number in the renderer, for a clickable ref.
    source_id:  the visual source id the call declares, or None when it declares
                nothing -- which is the anonymous-paint case.
    """

    receiver: str
    method: str
    line: int
    source_id: str | None

    def where(self) -> str:
        """A human-readable, clickable location for report output."""
        return f"{RENDERER.name}:{self.line} {self.receiver}.{self.method}"


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


def _line_of(source: str, offset: int) -> int:
    """Turn a 0-indexed byte offset into a 1-indexed line number."""
    return source.count("\n", 0, offset) + 1


def _method_calls(tokens: list[tuple[str, str, int]]) -> list[tuple[int, str, str]]:
    """Every ``<name>.<method>(`` call in the token stream.

    :param tokens: output of ``tokenize_javascript``.
    :returns: tuples of (token index of the method name, receiver, method).

    Because this walks tokens, a call written inside a comment or a string was
    never a token in the first place and cannot appear here.  That is the whole
    reason for the tokenizer, and it is why this returns token indices rather
    than text offsets -- the caller needs to keep walking the stream to find the
    call's arguments, which raw text cannot do reliably either.
    """
    calls: list[tuple[int, str, str]] = []
    for index in range(2, len(tokens) - 1):
        kind, value, _offset = tokens[index]
        if kind != "name":
            continue
        if tokens[index - 1][:2] != ("punct", "."):
            continue
        if tokens[index - 2][0] != "name":
            continue
        if tokens[index + 1][:2] != ("punct", "("):
            continue
        calls.append((index, tokens[index - 2][1], value))
    return calls


def _call_argument_span(tokens: list[tuple[str, str, int]], method_index: int) -> tuple[int, int]:
    """Token indices bounding a call's argument list, exclusive of the parens.

    Depth is tracked over ``(``, ``[`` and ``{`` tokens.  A parenthesis written
    inside a string is not a punct token, so ``f(')')`` -- which truncated the
    previous raw-text scanner and made a real, identified call look anonymous --
    cannot end the span here.

    :param method_index: index of the method-name token; the ``(`` follows it.
    :returns: (first argument token index, index of the closing paren).
    """
    depth = 0
    index = method_index + 1
    while index < len(tokens):
        kind, value, _offset = tokens[index]
        if kind == "punct":
            if value in "([{":
                depth += 1
            elif value in ")]}":
                depth -= 1
                if depth == 0:
                    return method_index + 2, index
        index += 1
    # Unbalanced source: treat the rest of the file as the argument list rather
    # than silently dropping the call, so a truncated file cannot hide paint.
    return method_index + 2, len(tokens)


def _split_arguments(
    tokens: list[tuple[str, str, int]], start: int, end: int
) -> list[tuple[int, int]]:
    """Token spans of each top-level argument in a call, in order.

    Commas nested inside parentheses, brackets or braces belong to a sub-
    expression and do not separate arguments, so depth is tracked.  Knowing
    WHICH argument an object literal is matters: an options object is identified
    by its position in the method's signature, not by being present somewhere.
    """
    spans: list[tuple[int, int]] = []
    depth = 0
    limit = min(end, len(tokens))
    current = start
    index = start
    while index < limit:
        kind, value, _offset = tokens[index]
        if kind == "punct":
            if value in "([{":
                depth += 1
            elif value in ")]}":
                depth -= 1
            elif value == "," and depth == 0:
                spans.append((current, index))
                current = index + 1
        index += 1
    if current < limit:
        spans.append((current, limit))
    return spans


def _object_literal_property(
    tokens: list[tuple[str, str, int]], start: int, end: int, name: str
) -> str | None:
    """A string-valued property of an argument that is a BARE object literal.

    The argument must be exactly ``{ ... }`` -- not a call returning an object,
    not a conditional choosing between two, not a spread of one.  Each of those
    makes the value decidable only at runtime, and an identity this checker
    cannot decide is not an identity.  Returns None unless the property sits at
    the literal's own top level with a string value.
    """
    if tokens[start][:2] != ("punct", "{") or tokens[end - 1][:2] != ("punct", "}"):
        return None
    depth = 0
    for index in range(start, end):
        kind, value, _offset = tokens[index]
        if kind == "punct":
            if value in "([{":
                depth += 1
            elif value in ")]}":
                depth -= 1
            continue
        # Depth 1 is the literal's own property list.
        if (
            depth == 1
            and (kind, value) == ("name", name)
            and index + 2 < end
            and tokens[index + 1][:2] == ("punct", ":")
            and tokens[index + 2][0] == "string"
        ):
            return tokens[index + 2][1]
    return None


def writer_options_index(source: str) -> dict[str, int | None]:
    """Which argument position carries each writer's options object, if any.

    Derived from the ``Raster`` signatures in the renderer rather than written
    down here, so the contract cannot drift away from the code it describes.
    A method whose last parameter is already an options object -- an object
    pattern, or one named ``options`` -- carries it at that parameter's index.

    A method with NO options parameter maps to ``None``, and no call to it can
    carry identity.  The previous version synthesised a position one past the
    declared parameters instead, which invented an argument slot the function
    does not read: ``raster.put(x, y, g, c, animated, owner, {source: '...'})``
    hands a seventh argument to a six-parameter function, which discards it
    silently -- and the checker reported that discarded object as the cell's
    identity.  A position must be one the code actually reads.

    Today that yields ``art`` -> 4 and ``measuredArt`` -> 6, both real, and
    ``put``/``text`` -> None until route step 5 gives them one.

    Position is what makes ``source`` an option rather than a coincidence.
    Without it, ``raster.put({source: '...'}, y, glyph, colour)`` -- where that
    object is the X COORDINATE -- read as identified paint.
    """
    tokens = tokenize_javascript(source)
    indices: dict[str, int | None] = {}
    for open_brace, close_brace in _paint_api_class_spans(tokens):
        depth = 0
        for index in range(open_brace, close_brace):
            kind, value, _offset = tokens[index]
            if kind == "punct" and value == "{":
                depth += 1
                continue
            if kind == "punct" and value == "}":
                depth -= 1
                continue
            if (
                depth != 1
                or kind != "name"
                or value not in WRITER_METHODS
                or tokens[index + 1][:2] != ("punct", "(")
                or tokens[index - 1][:2] == ("punct", ".")
            ):
                continue
            first, close = _call_argument_span(tokens, index)
            params = _split_arguments(tokens, first, close)
            if not params:
                indices[value] = None
                continue
            last_start, _last_end = params[-1]
            trailing_is_options = tokens[last_start][:2] in {
                ("punct", "{"), ("name", "options"),
            }
            indices[value] = len(params) - 1 if trailing_is_options else None
    return indices


def _options_source_accessor(
    tokens: list[tuple[str, str, int]], start: int, end: int
) -> list[tuple[str, str]] | None:
    """How this method's options parameter would spell a read of ``source``.

    An options parameter is written one of two ways, and each is read by a
    different token sequence:

      * an object PATTERN, ``{ baseline, animated, accents, owner }`` -- the
        properties it names are the only ones that become local variables, so
        ``source`` is readable only if the pattern lists it.  ``art`` does not
        list it, which is precisely why a ``{source: '...'}`` handed to ``art``
        is discarded at the door;
      * a plain NAME, ``options`` -- the whole object survives, and a read is
        spelled ``options.source``.  ``measuredArt`` takes this form and reads
        ``options.accents`` and ``options.animated`` from it, never ``source``.

    :param start: first token of the parameter, inclusive.
    :param end: one past the parameter's last token.
    :returns: the token sequence a read would look like, or None when the
        parameter cannot express a ``source`` read at all.
    """
    if tokens[start][:2] == ("punct", "{"):
        # Object pattern: `source` must be one of its own top-level properties.
        depth = 0
        for index in range(start, end):
            kind, value, _offset = tokens[index]
            if kind == "punct":
                if value in "([{":
                    depth += 1
                elif value in ")]}":
                    depth -= 1
                continue
            if depth == 1 and (kind, value) == ("name", SOURCE_PROPERTY):
                # Destructured: the local variable is simply `source`.
                return [("name", SOURCE_PROPERTY)]
        return None
    if tokens[start][0] == "name":
        # Plain parameter: a read is `<name>.source`.
        return [
            ("name", tokens[start][1]),
            ("punct", "."),
            ("name", SOURCE_PROPERTY),
        ]
    return None


def _contains_sequence(
    tokens: list[tuple[str, str, int]],
    start: int,
    end: int,
    wanted: list[tuple[str, str]],
) -> bool:
    """Does the token range contain this exact consecutive token sequence?

    Used to ask "is the identity actually READ here", which a substring search
    of the source text cannot answer -- ``source`` occurs in comments, in the
    word ``source_id``, and in unrelated property names.
    """
    limit = min(end, len(tokens)) - len(wanted) + 1
    for index in range(max(start, 0), max(limit, 0)):
        if all(
            tokens[index + offset][:2] == pair for offset, pair in enumerate(wanted)
        ):
            # A bare `source` that is really `x.source` is a read of something
            # else's property, not of this method's parameter.
            if len(wanted) == 1 and tokens[index - 1][:2] == ("punct", "."):
                continue
            return True
    return False


def _matching_bracket(
    tokens: list[tuple[str, str, int]], open_index: int, end: int
) -> int | None:
    """Index of the bracket closing the one at ``open_index``, or None."""
    depth = 0
    for index in range(open_index, min(end, len(tokens))):
        if tokens[index][0] != "punct":
            continue
        if tokens[index][1] in "([{":
            depth += 1
        elif tokens[index][1] in ")]}":
            depth -= 1
            if depth == 0:
                return index
    return None


def _constructor_allocated_planes(
    tokens: list[tuple[str, str, int]], open_brace: int, close_brace: int
) -> set[str]:
    """Which ``this.<name>`` properties the class constructor actually creates.

    Needed because "assigns into ``this.sources[y][x]``" is not storage if
    ``this.sources`` was never allocated: the first write throws
    ``TypeError: Cannot set properties of undefined``.  Code that cannot run
    cannot carry provenance, and crediting it would have let a raster clear the
    gate by naming a plane it does not have.

    :returns: every property name assigned as ``this.<name> = ...`` inside the
        constructor body.  Membership is the test; the VALUE is not inspected,
        because proving the value is a height x width grid is what the executed
        contract in ``tests/garden_adapters/test_raster_identity_contract.mjs``
        is for.  Static analysis says "the plane exists"; execution says "the id
        reaches the cell".
    """
    planes: set[str] = set()
    depth = 0
    for index in range(open_brace, close_brace):
        kind, value, _offset = tokens[index]
        if kind == "punct" and value == "{":
            depth += 1
            continue
        if kind == "punct" and value == "}":
            depth -= 1
            continue
        # A constructor definition is `constructor` `(` at the class body's own
        # depth -- not a `.constructor` property read somewhere inside a method.
        if (
            depth != 1
            or (kind, value) != ("name", "constructor")
            or tokens[index + 1][:2] != ("punct", "(")
            or tokens[index - 1][:2] == ("punct", ".")
        ):
            continue
        _first, close = _call_argument_span(tokens, index)
        body = _method_body_span(tokens, close, close_brace)
        if body is None:
            continue
        body_start, body_end = body
        for cursor in range(body_start, body_end - 3):
            if (
                tokens[cursor][:2] == ("name", "this")
                and tokens[cursor + 1][:2] == ("punct", ".")
                and tokens[cursor + 2][0] == "name"
                and tokens[cursor + 3][:2] == ("punct", "=")
                # The tokenizer emits single punctuation characters, so `==`
                # arrives as two `=` tokens.  A comparison is not an allocation.
                and tokens[cursor + 4][:2] != ("punct", "=")
            ):
                planes.add(tokens[cursor + 2][1])
    return planes


def _is_direct_identity_assignment(
    tokens: list[tuple[str, str, int]],
    start: int,
    end: int,
    accessor: list[tuple[str, str]],
) -> bool:
    """Is this right-hand side the identity itself, and nothing else?

    An ALLOW-LIST, deliberately, and for the same reason the register schemas
    are exact.  The previous rule asked only whether ``source`` was MENTIONED
    somewhere in the right-hand side, and mentioning is not storing::

        this.sources[y][x] = source ? null : null;   // mentions it, stores null

    That expression named the identity, discarded it, and cleared the gate.
    Every rule of the form "the discarding shapes I thought of are refused"
    leaves the shapes nobody thought of, so the shapes that are ACCEPTED are
    named instead, and there are exactly three:

        = source                 -- the identity
        = source ?? <one token>  -- the identity with a fallback
        = source || <one token>  -- the identity with a fallback

    where ``source`` stands for whichever accessor this writer's options
    parameter spells (bare ``source`` when destructured, ``options.source``
    when named).  Anything else -- a ternary, a call, a concatenation, a
    parenthesised expression -- is refused for not being on the list, and is
    added deliberately if it is ever genuinely wanted.
    """
    span = [token[:2] for token in tokens[start:end]]
    if span == accessor:
        return True
    width = len(accessor)
    # `??` and `||` are each two single-character punctuation tokens, and the
    # fallback is one token: a literal, `null`, or a name.
    if len(span) == width + 3 and span[:width] == accessor:
        operator = span[width:width + 2]
        if operator in ([("punct", "?"), ("punct", "?")], [("punct", "|"), ("punct", "|")]):
            return True
    return False


def _stores_identity_per_cell(
    tokens: list[tuple[str, str, int]],
    start: int,
    end: int,
    accessor: list[tuple[str, str]],
    planes: set[str],
) -> bool:
    """Does this method write the identity into a per-cell store?

    Three conditions, all required:

      * the target is a doubly-indexed property of the raster --
        ``this.<plane>[y][x] = ...`` -- because one subscript is a row and two
        are a cell;
      * ``<plane>`` is a plane the CONSTRUCTOR allocated, because assigning into
        an absent plane throws rather than stores;
      * the right-hand side is the identity itself, per
        ``_is_direct_identity_assignment``, because mentioning a value is not
        keeping it.

    ``Raster`` allocates exactly four such planes today (``glyphs``, ``colors``,
    ``animated``, ``owners``) and none of them holds a visual source, so this
    returns False for every writer.  ``owners`` is the near miss worth naming:
    it stores ``asset:<objectId>``, which is the ATLAS chain's gameplay owner,
    not the presentation identity the SPEC asks each cell to carry.
    """
    index = start
    while index < end - 4:
        # `this` `.` name `[`
        if (
            tokens[index][:2] == ("name", "this")
            and tokens[index + 1][:2] == ("punct", ".")
            and tokens[index + 2][0] == "name"
            and tokens[index + 3][:2] == ("punct", "[")
            # An unallocated plane cannot hold anything; see
            # `_constructor_allocated_planes`.
            and tokens[index + 2][1] in planes
        ):
            cursor = _matching_bracket(tokens, index + 3, end)
            # A second subscript is what makes it per-cell rather than per-row.
            if cursor is not None and tokens[cursor + 1][:2] == ("punct", "["):
                cursor = _matching_bracket(tokens, cursor + 1, end)
                if cursor is not None and tokens[cursor + 1][:2] == ("punct", "="):
                    # Right-hand side runs to the statement's end.
                    stop = cursor + 2
                    depth = 0
                    while stop < end:
                        kind, value, _offset = tokens[stop]
                        if kind == "punct":
                            if value in "([{":
                                depth += 1
                            elif value in ")]}":
                                depth -= 1
                            elif value == ";" and depth == 0:
                                break
                        stop += 1
                    if _is_direct_identity_assignment(tokens, cursor + 2, stop, accessor):
                        return True
        index += 1
    return False


def _method_body_span(
    tokens: list[tuple[str, str, int]], params_close: int, limit: int
) -> tuple[int, int] | None:
    """Token span of a method body, given the index of its closing paren."""
    cursor = params_close + 1
    while cursor < limit and tokens[cursor][:2] != ("punct", "{"):
        cursor += 1
    if cursor >= limit:
        return None
    end = _matching_bracket(tokens, cursor, limit)
    return None if end is None else (cursor, end)


def _identity_argument_carries(
    tokens: list[tuple[str, str, int]],
    start: int,
    end: int,
    accessor: list[tuple[str, str]],
) -> bool:
    """Is this ONE argument an options object handing the identity on?

    The argument must be an object literal with a top-level ``source`` property
    -- either the shorthand ``{ source }`` or ``{ source: <expression naming the
    accessor> }``.  Two separate leaks are refused by insisting on that shape
    rather than searching the argument for the accessor tokens:

      * ``{ owner: source }`` names the identity under a property the callee
        does not read, so the callee's destructuring never sees it;
      * a value handed under the right name to the WRONG argument -- see
        ``_writer_delegations``, which chooses which argument to pass here --
        never reaches the options parameter at all.

    :param start: first token of the argument, inclusive.
    :param end: one past the argument's last token.
    """
    if tokens[start][:2] != ("punct", "{"):
        return False
    close = _matching_bracket(tokens, start, end)
    if close is None:
        return False
    depth = 0
    for index in range(start, close):
        kind, value, _offset = tokens[index]
        if kind == "punct":
            if value in "([{":
                depth += 1
            elif value in ")]}":
                depth -= 1
            continue
        if depth != 1 or (kind, value) != ("name", SOURCE_PROPERTY):
            continue
        # KEY position only.  A property key opens the literal or follows a
        # comma; anywhere else the name is a VALUE, and `{ owner: source }` is
        # the identity handed in under a name the callee does not read -- which
        # was credited while this check looked only at where `source` appeared
        # rather than at what it was doing there.
        if tokens[index - 1][:2] not in {("punct", "{"), ("punct", ",")}:
            continue
        following = tokens[index + 1][:2]
        if following in {("punct", ","), ("punct", "}")}:
            # Shorthand `{ source }`: the key and the value are the same name,
            # so it carries the identity exactly when the accessor is that name.
            return accessor == [("name", SOURCE_PROPERTY)]
        if following != ("punct", ":"):
            continue
        # `source: <value>` -- the value runs to the next top-level comma or the
        # literal's closing brace.
        stop = index + 2
        inner = 0
        while stop < close:
            next_kind, next_value, _next_offset = tokens[stop]
            if next_kind == "punct":
                if next_value in "([{":
                    inner += 1
                elif next_value in ")]}":
                    inner -= 1
                elif next_value == "," and inner == 0:
                    break
            stop += 1
        if _contains_sequence(tokens, index + 2, stop, accessor):
            return True
    return False


def _writer_delegations(
    tokens: list[tuple[str, str, int]], start: int, end: int
) -> list[tuple[str, list[tuple[int, int]]]]:
    """Every ``this.<writer>(...)`` call inside a method body.

    Only calls on ``this`` are collected.  Handing the value to some unrelated
    helper is not propagation into a cell, and counting it would reopen the leak
    one level out.

    :returns: (callee name, argument spans) for each delegation, in source
        order.  Every one of them is checked, because a writer that carries the
        identity down one branch and drops it down another emits cells whose
        provenance depends on which branch ran -- which is not provenance.
    """
    delegations: list[tuple[str, list[tuple[int, int]]]] = []
    for index in range(start, end - 3):
        if (
            tokens[index][:2] == ("name", "this")
            and tokens[index + 1][:2] == ("punct", ".")
            and tokens[index + 2][0] == "name"
            and tokens[index + 2][1] in WRITER_METHODS
            and tokens[index + 3][:2] == ("punct", "(")
        ):
            close = _matching_bracket(tokens, index + 3, end)
            if close is None:
                continue
            delegations.append(
                (tokens[index + 2][1], _split_arguments(tokens, index + 4, close))
            )
    return delegations


def writer_identity_positions(source: str) -> dict[str, int | None]:
    """Which writers can actually give an emitted cell a visual source id.

    This is a DIFFERENT question from ``writer_options_index``, and conflating
    the two was a hole.  A position in the signature says only that an argument
    is received.  ``docs/SPEC.md`` requires the emitted CELL to carry the id, so
    an argument that is received and then dropped identifies nothing -- and both
    of the renderer's options-taking writers drop it today:

      * ``art(anchorX, anchorY, lines, color, {baseline, animated, accents,
        owner})`` destructures four properties and ``source`` is not among them,
        so the value never becomes a variable;
      * ``measuredArt(..., options)`` keeps the object but reads only
        ``options.accents`` and ``options.animated`` from it.

    Reporting those calls as identified would have let route step 5 clear every
    anonymous-paint blocker by adding dead arguments, while not one emitted cell
    gained provenance.  A position is returned only when the identity survives
    the whole journey to a cell, which is computed as a WRITER GRAPH solved
    backward from the terminal emitter:

      * a writer is capable if it stores the identity into a per-cell plane
        itself -- which today only ``put`` is positioned to do;
      * otherwise it is capable only if it delegates, and EVERY delegation it
        makes hands the identity into the callee's own identity ARGUMENT under
        the property name ``source``, and every one of those callees is itself
        capable.

    Each of those clauses answers a leak that "the callee's call mentions
    ``source`` somewhere" did not:

      * ``art`` -> ``text`` -> ``put`` where ``text`` drops it: ``art`` was
        credited for handing the value to a writer that discards it, so the
        chain was scored one hop deep instead of all the way down;
      * ``this.text(source, y, line, ...)``, which passes the identity as the X
        COORDINATE: the tokens were present in the call, so position-blind
        matching credited it;
      * ``this.text(..., { owner: source })``, which passes it under a name the
        callee does not destructure;
      * a writer that carries the identity on its plain branch and drops it on
        its accent branch: ``all`` of the delegations must carry it, not any.

    Today this returns None for all four, which is the true state of the
    product: 24 writer sites, zero of which can identify a cell.
    """
    tokens = tokenize_javascript(source)
    positions = writer_options_index(source)
    bodies: dict[str, tuple[int, int]] = {}
    accessors: dict[str, list[tuple[str, str]]] = {}
    planes: set[str] = set()

    # --- Collect each writer's options accessor and body span ---------------
    for open_brace, close_brace in _paint_api_class_spans(tokens):
        planes |= _constructor_allocated_planes(tokens, open_brace, close_brace)
        depth = 0
        for index in range(open_brace, close_brace):
            kind, value, _offset = tokens[index]
            if kind == "punct" and value == "{":
                depth += 1
                continue
            if kind == "punct" and value == "}":
                depth -= 1
                continue
            if (
                depth != 1
                or kind != "name"
                or value not in WRITER_METHODS
                or tokens[index + 1][:2] != ("punct", "(")
                or tokens[index - 1][:2] == ("punct", ".")
            ):
                continue
            first, close = _call_argument_span(tokens, index)
            params = _split_arguments(tokens, first, close)
            options_index = positions.get(value)
            if options_index is None or options_index >= len(params):
                continue
            param_start, param_end = params[options_index]
            accessor = _options_source_accessor(tokens, param_start, param_end)
            if accessor is None:
                continue
            body = _method_body_span(tokens, close, close_brace)
            if body is None:
                continue
            accessors[value] = accessor
            bodies[value] = body

    # --- Which writers store the identity themselves? ------------------------
    # The base case of the graph.  A writer that assigns the identity into a
    # per-cell plane needs nobody's help; every other writer's capability is
    # borrowed from one of these, transitively.  Today only ``put`` is even
    # positioned to be such a writer, and it does not store one.
    stores = {
        method: _stores_identity_per_cell(
            tokens, body_start, body_end, accessors[method], planes
        )
        for method, (body_start, body_end) in bodies.items()
    }
    delegations = {
        method: _writer_delegations(tokens, body_start, body_end)
        for method, (body_start, body_end) in bodies.items()
    }

    # --- Solve the graph backward from the writers that store ----------------
    # Iterated to a stable answer rather than decided in one pass, because
    # capability travels along chains: `put` stores, so `text` may borrow from
    # `put`, so `art` may borrow from `text`.  A single pass in declaration
    # order would score `art` against a `text` not yet decided.  At most one
    # writer resolves per round, so len(bodies) rounds suffice; a delegation
    # cycle simply never resolves, which is the right answer for a loop that
    # reaches no cell.
    capable = dict(stores)
    for _round in range(len(bodies) + 1):
        settled = True
        for method in bodies:
            if capable[method]:
                continue
            calls = delegations[method]
            if not calls:
                continue
            if all(
                callee in bodies
                and capable[callee]
                and positions.get(callee) is not None
                and positions[callee] < len(arguments)
                and _identity_argument_carries(
                    tokens, *arguments[positions[callee]], accessors[method]
                )
                for callee, arguments in calls
            ):
                capable[method] = True
                settled = False
        if settled:
            break

    return {
        method: positions[method] if capable.get(method) else None
        for method in positions
    }


@lru_cache(maxsize=1)
def _renderer_options_index() -> dict[str, int]:
    """The live renderer's writer identity positions, read once.

    Note what this currently reports: NONE of the four writers can identify a
    cell.  ``put`` and ``text`` declare no options parameter at all, and ``art``
    and ``measuredArt`` declare one but drop ``source`` on the floor -- so no
    call to any of them can carry a visual source, not even one written in the
    obvious ``{source: '...'}`` form.  Every such call is anonymous, and
    reporting it as identified would be inventing a contract the code does not
    offer.  Route step 5 has to add the parameter, the read, and the per-cell
    store; adding only the argument changes nothing this checker will credit.
    """
    if not RENDERER.exists():
        return {}
    return writer_identity_positions(RENDERER.read_text(encoding="utf-8"))


def _declared_source(
    tokens: list[tuple[str, str, int]],
    start: int,
    end: int,
    options_index: int | None,
) -> str | None:
    """The ``source: 'id'`` carried in this call's OPTIONS argument.

    Three conditions, and every one of them was a bypass before it was checked:

      * the id must sit in the argument at the method's options position, not
        anywhere in the argument list -- otherwise an object handed in as a
        coordinate, or forwarded to another function, counts as identity;
      * that argument must be a bare object literal, so a conditional like
        ``flag ? {source: '...'} : {}`` cannot claim an identity it supplies
        only sometimes;
      * the value must be a string literal, because ``source: SOME_CONST`` is
        unresolvable without executing the module.

    :param options_index: the argument position, from ``writer_options_index``.
        None when the method is unknown, in which case nothing can be claimed.
    """
    if options_index is None:
        return None
    arguments = _split_arguments(tokens, start, end)
    if options_index >= len(arguments):
        return None
    first, last = arguments[options_index]
    return _object_literal_property(tokens, first, last, SOURCE_PROPERTY)


def unresolvable_writer_calls(source: str) -> list[str]:
    """Calls written in a form whose identity this checker cannot read.

    The recognised form is a plain member call: ``<receiver>.<writer>(...)``.
    Everything else that can reach a writer is refused here, and the list is
    meant to be EXHAUSTIVE rather than illustrative, because two earlier
    versions of this rule named the shapes they had thought of and leaked the
    rest.  To invoke a method in JavaScript you must do one of:

      1. name it after a dot -- recognised, and read for its identity;
      2. name it after an OPTIONAL dot, ``raster?.put(...)`` -- refused;
      3. invoke it optionally, ``raster.put?.(...)`` -- refused;
      4. reach it through a computed subscript, ``anything[expr](...)``,
         ``anything[expr]?.(...)`` -- refused, whatever expression produced the
         object;
      5. invoke it reflectively through ``call``/``apply``/``bind``, which also
         covers a writer extracted into a variable first, since
         ``const paint = raster[method]`` still has to be invoked somehow and
         ``paint(...)`` alone loses ``this`` and cannot write to any raster.

    None of forms 2-5 appears anywhere in the browser modules, which is exactly
    why all of them are refused now: a gate that only handles the forms already
    present is not a gate.

    Reported rather than silently parsed, because the honest answer is "this
    call may paint and I cannot tell whether it is identified", and that must
    block a release rather than resolve to a guess.
    """
    tokens = tokenize_javascript(source)
    found: list[str] = []
    # Starts at 1, not 2: `raster['put'](...)` puts the subscript bracket at
    # index 1 when the call opens a file or a fragment, and a scan starting at 2
    # steps straight over it.
    for index in range(1, len(tokens) - 1):
        kind, value, offset = tokens[index]
        # `receiver?.method(` -- optional chaining. The tokenizer emits single
        # punctuation characters, so `?.` is two tokens and the `?` sits two
        # places back from the method name.
        if (
            kind == "name"
            and value in WRITER_METHODS
            and tokens[index - 1][:2] == ("punct", ".")
            and tokens[index - 2][:2] == ("punct", "?")
        ):
            # Deliberately not conditioned on `(` following the name.  An
            # optionally-reached writer is opaque however it is then invoked,
            # and requiring the immediate `(` missed `raster?.put?.(...)` and
            # `raster?.put.call(raster, ...)` -- the same mistake as scoping a
            # rule to the shapes already imagined.
            found.append(f"{RENDERER.name}:{_line_of(source, offset)} optional-chained ?.{value}")
            continue
        # `receiver.writer?.(...)` -- a plain member access, invoked optionally.
        # The member-call reader requires `(` directly after the name, so this
        # form is not merely unresolved by it, it is INVISIBLE to it.
        if (
            kind == "name"
            and value in WRITER_METHODS
            and tokens[index - 1][:2] == ("punct", ".")
            and tokens[index + 1][:2] == ("punct", "?")
            and tokens[index + 2][:2] == ("punct", ".")
            and tokens[index + 3][:2] == ("punct", "(")
        ):
            found.append(
                f"{RENDERER.name}:{_line_of(source, offset)} optionally-invoked {value}?.()"
            )
            continue
        # `<anything>.call(...)`, `.apply(...)`, `.bind(...)` -- the receiver of
        # a reflective invocation is a FUNCTION, and which function it is cannot
        # be read off the call.  `raster.put.call(raster, ...)` and
        # `const paint = raster[method]; paint.call(raster, ...)` both land here;
        # the second is the reason the rule is not scoped to receivers that look
        # like rasters, because by then the raster is not mentioned at all.
        if (
            kind == "name"
            and value in REFLECTIVE_INVOKERS
            and tokens[index - 1][:2] == ("punct", ".")
            and tokens[index + 1][:2] == ("punct", "(")
        ):
            receiver = "".join(
                token[1] for token in tokens[max(0, index - 4):index - 1]
            )
            found.append(
                f"{RENDERER.name}:{_line_of(source, offset)} "
                f"reflective ...{receiver}.{value}()"
            )
            continue
        # ANY subscript that is immediately invoked -- `<anything>[expr](...)`.
        #
        # Two earlier versions of this rule were narrower and both leaked.
        # Scoping it to the receiver literally named `raster` leaked because a
        # receiver's NAME is not a fact about the object. Requiring the token
        # before `[` to be a name or a string leaked for the same reason one
        # level up: the receiver is an EXPRESSION, and an expression need not
        # end in a name. All four of these reach the same object:
        #
        #     (brush)[method](...)                  -- ends in `)`
        #     getRaster()[method](...)              -- ends in `)`
        #     brush?.[method](...)                  -- optional computed access
        #     (condition ? raster : brush)[method]  -- ends in `)`
        #
        # So the trigger is the CALL FORM, not the receiver: a matched `]`
        # followed immediately by `(` is a computed member call, whatever
        # produced the object. Alias tracking cannot decide the general case --
        # a renamed parameter is exactly the undecidable one -- so the
        # conservative rule is the only sound one: what may be hiding a writer
        # blocks.
        #
        # The renderer currently contains ZERO such forms, so this costs nothing
        # today. If a legitimate one is ever needed, it must be decided
        # deliberately rather than admitted by an oversight.
        if kind == "punct" and value == "[":
            close = _matching_bracket(tokens, index, len(tokens))
            # Both invocation spellings of a computed access: `](...)` and the
            # optional `]?.(...)`.  A reflective `].call(...)` is refused above,
            # by the rule that refuses reflective invocation outright.
            trailing = (
                [token[:2] for token in tokens[close + 1:close + 4]]
                if close is not None else []
            )
            invoked = trailing[:1] == [("punct", "(")] or trailing == [
                ("punct", "?"), ("punct", "."), ("punct", "("),
            ]
            if close is not None and invoked:
                # Describe the receiver by the tokens leading up to `[`, so the
                # report names the form a reader will actually find in the file.
                receiver = "".join(
                    token[1] for token in tokens[max(0, index - 4):index]
                )
                subscript = "".join(token[1] for token in tokens[index + 1:close])
                found.append(
                    f"{RENDERER.name}:{_line_of(source, offset)} "
                    f"computed ...{receiver}[{subscript}]"
                )
    return sorted(found)


def _paint_api_class_spans(tokens: list[tuple[str, str, int]]) -> list[tuple[int, int]]:
    """Token span of the ``Raster`` class, when it defines the writer methods.

    Inside the class that implements ``put``/``text``/``art``, a ``this.put(...)``
    call is the implementation of the paint API delegating to itself, not an
    independent decision to draw something.  Requiring it to name a visual source
    would be asking the paintbrush which painting it belongs to.

    The exemption is scoped to the class NAMED ``Raster``, not to any class that
    happens to define a method called ``put``.  The looser rule was a bypass: a
    layer defining its own ``put`` helper would have exempted every ``this.put``
    inside it, which is precisely where anonymous paint would hide.  Both
    conditions must hold -- the right name AND the writer definitions -- so
    renaming the class or moving the methods out fails loudly instead of
    silently widening or narrowing what is exempt.

    :returns: (open-brace token index, matching close-brace token index) pairs.
    """
    spans: list[tuple[int, int]] = []
    for index, (kind, value, _offset) in enumerate(tokens):
        if kind != "name" or value != "class":
            continue
        if tokens[index + 1][:2] != ("name", PAINT_API_CLASS):
            continue
        # Walk to the class body's opening brace, skipping the name and any
        # `extends Base` clause.
        cursor = index + 1
        while cursor < len(tokens) and tokens[cursor][:2] != ("punct", "{"):
            cursor += 1
        if cursor >= len(tokens):
            continue
        # Find the matching close brace.
        depth = 0
        end = cursor
        while end < len(tokens):
            if tokens[end][0] == "punct":
                if tokens[end][1] == "{":
                    depth += 1
                elif tokens[end][1] == "}":
                    depth -= 1
                    if depth == 0:
                        break
            end += 1
        # Does this class body define a writer method?  A method definition is a
        # name token followed by `(` at the body's own depth; checking membership
        # in WRITER_METHODS is enough to identify the paint API.
        body_depth = 0
        defines_writer = False
        for probe in range(cursor, min(end, len(tokens))):
            kind_p, value_p, _o = tokens[probe]
            if kind_p == "punct" and value_p == "{":
                body_depth += 1
            elif kind_p == "punct" and value_p == "}":
                body_depth -= 1
            elif (
                body_depth == 1
                and kind_p == "name"
                and value_p in WRITER_METHODS
                and tokens[probe + 1][:2] == ("punct", "(")
                and tokens[probe - 1][:2] != ("punct", ".")
            ):
                defines_writer = True
        if defines_writer:
            spans.append((cursor, end))
    return spans


def _writer_body_spans(tokens: list[tuple[str, str, int]]) -> list[tuple[int, int]]:
    """Token spans of the FOUR writer method bodies inside ``Raster``.

    The exemption for self-delegation belongs to these bodies alone.  Scoping it
    to the whole class was still a bypass: ``class Raster { draw() { this.put(...) } }``
    is a painter like any other, and exempting it would hide anonymous paint
    behind a method name in the one class nobody re-reads.  ``text`` calling
    ``put``, and ``art`` calling ``text``, are the implementation; anything else
    calling them is a decision to draw.
    """
    spans: list[tuple[int, int]] = []
    for open_brace, close_brace in _paint_api_class_spans(tokens):
        depth = 0
        for index in range(open_brace, close_brace):
            kind, value, _offset = tokens[index]
            if kind == "punct" and value == "{":
                depth += 1
                continue
            if kind == "punct" and value == "}":
                depth -= 1
                continue
            if (
                depth != 1
                or kind != "name"
                or value not in WRITER_METHODS
                or tokens[index + 1][:2] != ("punct", "(")
                or tokens[index - 1][:2] == ("punct", ".")
            ):
                continue
            # Step past the parameter list to the method body's opening brace.
            _first, close = _call_argument_span(tokens, index)
            cursor = close + 1
            while cursor < close_brace and tokens[cursor][:2] != ("punct", "{"):
                cursor += 1
            if cursor >= close_brace:
                continue
            body_depth = 0
            end = cursor
            while end < close_brace:
                if tokens[end][0] == "punct":
                    if tokens[end][1] == "{":
                        body_depth += 1
                    elif tokens[end][1] == "}":
                        body_depth -= 1
                        if body_depth == 0:
                            break
                end += 1
            spans.append((cursor, end))
    return spans


def extract_paint_sites(source: str) -> list[PaintSite]:
    """Find every cell-emitting call and the visual source id it declares.

    The convention this enforces: a paint call declares its origin by passing a
    ``source`` property naming a registered id, e.g.

        raster.put(row, col, glyph, colour, {source: 'recipe.ground.cover'})

    Only WRITER_METHODS are returned.  ``raster.line`` and ``raster.latticeHtml``
    read and serialise cells that were already written, so they are not paint
    sites -- see the comment on READER_METHODS.
    """
    tokens = tokenize_javascript(source)
    delegation_spans = _writer_body_spans(tokens)
    # A fragment under test defines no Raster of its own; it is a piece of the
    # renderer, so the renderer's signatures are the ones that govern it.
    #
    # IDENTITY positions, not options positions.  An options object the method
    # receives and then drops -- which is every options-taking writer today --
    # identifies no cell, so a call handing it one is still anonymous paint.
    options_index = writer_identity_positions(source) or _renderer_options_index()
    sites: list[PaintSite] = []

    for method_index, receiver, method in _method_calls(tokens):
        if method not in WRITER_METHODS:
            continue
        # Skip the paint API delegating to itself -- and only there.
        if receiver == "this" and any(
            start <= method_index <= end for start, end in delegation_spans
        ):
            continue
        first, close = _call_argument_span(tokens, method_index)
        sites.append(
            PaintSite(
                receiver=receiver,
                method=method,
                line=_line_of(source, tokens[method_index][2]),
                source_id=_declared_source(
                    tokens, first, close, options_index.get(method)
                ),
            )
        )
    return sites


def extract_reader_sites(source: str) -> list[PaintSite]:
    """Calls that read or serialise cells rather than emitting them.

    Reported separately so the count of "things that touch cells" stays honest.
    These are where stored per-cell provenance must be PRESERVED once step 5
    threads it through; they are not where it is declared.
    """
    tokens = tokenize_javascript(source)
    return [
        PaintSite(
            receiver=receiver,
            method=method,
            line=_line_of(source, tokens[method_index][2]),
            source_id=None,
        )
        for method_index, receiver, method in _method_calls(tokens)
        if method in READER_METHODS
    ]


def unlisted_raster_methods(source: str) -> list[str]:
    """Raster methods called by the renderer that this checker does not classify.

    Without this, adding ``raster.blit(...)`` would create a new anonymous paint
    path that every check above silently ignores, because none of them would
    recognise it as paint.  Anything unrecognised is reported so a human decides
    whether it emits cells, rather than the omission deciding for them.
    """
    tokens = tokenize_javascript(source)
    called = {
        method
        for _index, receiver, method in _method_calls(tokens)
        if receiver == "raster"
    }
    return sorted(called - set(KNOWN_RASTER_METHODS))


# ── Verifying provenance against the artifact and the decision record ───────


@lru_cache(maxsize=None)
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


def compute_blockers(acceptance: dict, recipes: dict, renderer_source: str) -> dict[str, list]:
    """Compute the clearable conditions that block a root-product deploy.

    Kept strictly apart from ``release_policy`` in the acceptance registry.
    Policy is permanent and can never be satisfied; these can, and a deploy
    requires that they all are.  Mixing the two produced a list that could never
    legitimately be empty, which made asserting emptiness meaningless.

    The KEYS of this dict are the contract: the acceptance registry enumerates
    the same names, and a test asserts the two agree exactly, so a condition
    cannot be added here and left undocumented there.
    """
    records = recipes["records"]
    laws = {rid for rid, rec in records.items() if rec.get("kind") == "law"}
    registered = set(records) | {row["asset_id"] for row in acceptance["assets"]}
    sites = extract_paint_sites(renderer_source)

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
        "anonymous_paint_sites": [site.where() for site in sites if site.source_id is None],
        "unknown_visual_source_ids": sorted({
            f"{site.source_id} ({site.where()})"
            for site in sites
            if site.source_id is not None and site.source_id not in registered
        }),
        # A law decides how cells look but emits none of its own, so naming one
        # as a cell's source hides which recipe actually drew it.
        "laws_used_as_cell_sources": sorted({
            f"{site.source_id} ({site.where()})"
            for site in sites if site.source_id in laws
        }),
        # A paint site may only claim a deployed-provenance verdict when the
        # implementation behind it actually reproduces the deployed one.  A
        # citation of legacy line numbers is provenance, not approval: if the
        # candidate's implementation diverges (candidate_status 'different'),
        # claiming the verdict launders an unreviewed drawing through an
        # approved id, which is the exact move the register exists to block.
        "divergent_implementations_claiming_approval": sorted({
            f"{site.source_id} ({site.where()}) is candidate_status "
            f"{records[site.source_id].get('candidate_status')!r}, so it may not "
            f"claim verdict {records[site.source_id]['verdict']!r}"
            for site in sites
            if site.source_id in records
            and records[site.source_id]["verdict"] in PROVENANCE_CLAIMING_VERDICTS
            and records[site.source_id].get("candidate_status") != "exact"
        }),
        "unrecognised_paint_methods": unlisted_raster_methods(renderer_source),
        # A writer reached through optional chaining or a computed member name
        # paints while defeating member-call recognition.  Reported rather than
        # guessed at: "this call paints and I cannot tell whether it is
        # identified" must block a release, not resolve to an assumption.
        "unresolvable_paint_call_forms": unresolvable_writer_calls(renderer_source),
        "gameplay_art_outside_atlas": [
            owner for owner in ("plantArt", "animalArt", "collectibleArt", "fixtureArt")
            if owner in renderer_source
        ],
        # The structural cause behind every anonymous paint site, reported in
        # its own right so the two are not confused.  `anonymous_paint_sites`
        # counts CALLS that declare nothing; this names the writers that could
        # not record an identity even if every call declared one, because the
        # emitted cell has nowhere to keep it.  Without this, route step 5 could
        # look like progress while adding arguments that go nowhere.
        "writers_that_cannot_record_identity": sorted(
            method
            for method, position in (
                writer_identity_positions(renderer_source) or {}
            ).items()
            if position is None
        ),
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
    """Load everything from disk and produce the full report."""
    acceptance = _read(ACCEPTANCE)
    recipes = _read(RECIPES)
    renderer_source = RENDERER.read_text(encoding="utf-8")

    report = Report()
    report.violations = validate_registers(acceptance, recipes) + validate_provenance(recipes)
    report.blockers = compute_blockers(acceptance, recipes, renderer_source)

    sites = extract_paint_sites(renderer_source)
    records = recipes["records"]
    report.counts = {
        "recipes": len(records),
        "laws": sum(1 for r in records.values() if r.get("kind") == "law"),
        "paint_records": sum(1 for r in records.values() if r.get("kind") == "paint"),
        "atlas_assets": len(acceptance["assets"]),
        "cell_writer_sites": len(sites),
        "cell_reader_sites": len(extract_reader_sites(renderer_source)),
        "writer_sites_with_identity": sum(1 for s in sites if s.source_id is not None),
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
