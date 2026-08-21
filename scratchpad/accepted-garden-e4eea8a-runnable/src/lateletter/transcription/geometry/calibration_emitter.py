"""Turn a PROVED lattice into an immutable, hash-bound calibration file.

What this module is for
-----------------------
The repository has two ways to describe "where the character cells are" in a
screenshot of text art, and until now they could not talk to each other:

1.  The **geometry router** (``route_raster_geometry`` next door) measures the
    lattice from the source pixels alone and returns a proof: it says whether
    the row period (pitch), the row origin (phase), and the pixel ownership
    were each *proved*, and it names the reason whenever one of them was not.
    Nothing it produces is written to disk.
2.  The **row-joint decoder** (``lateletter.transcription.row_joint``, whose
    body lives in ``scripts/decode_monospace_rows.py``) is the only recognizer
    in the repository that has ever produced structurally coherent machine text
    from a live screenshot.  It cannot run without a *calibration file* — a
    JSON document, bound to the exact source bytes by SHA-256, that states the
    background colour, the ink threshold, and the grid.  Historically those
    files were produced by hand during the tracked "attempt" history.

This module is the adapter between the two.  It runs the router, refuses
unless the router proved a whole lattice, and then derives every field the
decoder's calibration schema requires — from the router's proof and from the
source pixels, and from nothing else.

The hard rule this module exists to keep
----------------------------------------
**No transcript is ever consulted.**  Not the ``.txt`` file sitting next to the
PNG, not an accepted transcript in the parity history, not a fixture's expected
output.  Every number written into a calibration comes from one of exactly two
places: the router's own measurement of the raster, or a direct measurement of
the source PNG's pixels performed here.  If the router did not prove the
lattice, this module writes nothing at all.  "No provable lattice therefore no
calibration therefore no decode" is the intended destination, not a gap.

Why "write once" and why an index
---------------------------------
A calibration is *evidence*.  Evidence that can be silently rewritten is not
evidence.  So:

* each source gets its own directory named after its SHA-256, and a second
  emission for the same source is REFUSED rather than allowed to overwrite;
* the artifact's own SHA-256 is recorded in a single shared index file at the
  moment of creation, so a later reader can prove the file on disk is the file
  that was emitted and not something edited afterwards;
* nothing in any emitted file comes from the wall clock or from a random
  number generator, and every JSON document is written with sorted keys.  Run
  the emitter twice on the same bytes with the same code and you get the same
  artifact hash.  That property is what makes "replay determinism" checkable
  rather than merely claimed.

Where the numbers come from (the schema adapter)
------------------------------------------------
The decoder's ``segment()`` reads these fields, and here is the source of each:

``canvas.background_rgb``
    The background colour the router's own foreground selection settled on.
    The router tries several (background, threshold) recipes and keeps the one
    whose mask it used for the proof; reusing that exact recipe is what makes
    the decoder's ink mask identical to the mask the lattice was proved against.
``normalization.ink_threshold_l1``
    The threshold from that same recipe.  Both the router (in ``evidence.py``)
    and the decoder compute ink as
    ``max(|pixel - background|, over channels) > threshold``, so one number
    carries across unchanged.
``grid.columns`` / ``grid.cell_advance_x_px`` / ``grid.origin_x_px``
    The horizontal cell contract the router selected for this raster.
``grid.rows`` / ``grid.line_height_px`` / ``grid.first_baseline_y_px``
    The *periodic* row model — deliberately NOT the blank-gap "row bands" that
    also appear in the router's output.  Blank-gap bands group ink that happens
    to touch; they merge two text lines whose glyphs collide and they miss text
    lines that are entirely blank.  The proved lattice is the winning periodic
    row candidate: a single pitch and phase that tiles the whole canvas.  See
    :func:`_winning_periodic_candidate` for how that candidate is identified.
``grid.cell_crop_top_offset_px`` / ``grid.cell_crop_bottom_offset_px``
    The vertical extent of one cell box, expressed relative to that row's
    baseline, taken from the winning candidate's own first row bounds.  The
    decoder reconstructs row ``r``'s box as
    ``[first_baseline + r*line_height + top, first_baseline + r*line_height + bottom)``,
    which reproduces the candidate's row bounds exactly.
``guide_columns_px``
    Always empty.  Guide columns are a hand-authored erasure list used by some
    legacy artifacts to blank out rendered gridlines; the router proves no such
    thing, so this emitter never invents one.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
from PIL import Image

from ..hashing import sha256_bytes, sha256_file
from .router import route_raster_geometry

# ---------------------------------------------------------------------------
# Identity constants
# ---------------------------------------------------------------------------
# These strings are written verbatim into every emitted document.  They are
# literal constants — never derived from the clock or the environment —
# because an artifact's bytes must depend only on the source bytes and on the
# version of this code.

#: Name recorded in the artifact's ``calibrator`` block.  A reader (including
#: the row-joint seam) uses this to tell a router-emitted calibration apart
#: from a hand-authored attempt calibration.
EMITTER_NAME = "LateLetter router lattice calibration emitter"

#: Bumped by hand whenever a change here would alter emitted bytes.
EMITTER_VERSION = "router-calibration-emitter-1"

#: Schema tags, so a future reader can refuse a document it does not understand
#: instead of guessing at its shape.
CALIBRATION_SCHEMA = "router-emitted-calibration-1"
RECEIPT_SCHEMA = "router-emitted-calibration-receipt-1"
INDEX_SCHEMA = "router-emitted-calibration-index-1"

#: Value written into the artifact's ``status`` field.  It is deliberately NOT
#: any of the legacy attempt vocabulary (``calibration_candidate``,
#: ``calibration_rejected``, ``machine_candidate_only``): a router-emitted
#: calibration is a different kind of object with a different provenance, and
#: the row-joint seam's rejection check must be able to see that.
EMITTED_STATUS = "router_emitted"

# Repository root, derived from this file's own location so behaviour never
# depends on the directory the caller happened to start in.
_REPOSITORY_ROOT = Path(__file__).resolve().parents[4]

#: Default home for emitted artifacts.  One directory per source hash lives
#: under here, alongside the single shared ``index.json``.
DEFAULT_OUTPUT_ROOT = (
    _REPOSITORY_ROOT
    / "tracked"
    / "LateLetterResearch"
    / "transcription-parity"
    / "router-calibrations"
)

#: File name of the shared index inside the output root.
INDEX_FILENAME = "index.json"

#: How far an INTERIOR row baseline may sit from where a perfectly periodic
#: ladder would put it, in pixels, before the lattice is declared irregular.
#:
#: Why one pixel and not zero.  The emitted calibration gives every row the
#: same crop offsets, so a row whose true baseline sits N pixels off the
#: modelled position has its cell box shifted N pixels against the ink.  One
#: pixel is the width of a single rasterization decision — a glyph antialiased
#: half a pixel lower rounds its measured baseline down — and every emitted
#: cell box is at least a whole line tall, so a one-pixel shift cannot move ink
#: out of its own box.  Two pixels could, on the tightest crops in this corpus.
#: The value is pinned here a priori; it is not tuned against any transcript.
_BASELINE_RESIDUAL_TOLERANCE_PX = 1

#: Implementation files whose contents decide what an emission produces.  Their
#: hashes go into the receipt so a replay can prove it ran the same code.
_IDENTITY_FILES: tuple[str, ...] = (
    "src/lateletter/transcription/geometry/calibration_emitter.py",
    "src/lateletter/transcription/geometry/router.py",
    "src/lateletter/transcription/geometry/evidence.py",
    "src/lateletter/transcription/geometry/fixed_lattice.py",
    "src/lateletter/transcription/geometry/shaped_runs.py",
    "src/lateletter/transcription/model.py",
)


# ---------------------------------------------------------------------------
# Typed refusal vocabulary
# ---------------------------------------------------------------------------
# Every way this module can decline to emit has a name.  Free-text refusals are
# banned for the same reason untyped absences are banned in the router: an
# unexplained "no" is indistinguishable from a bug.  Each entry below is
# produced by exactly one check in :func:`emit_calibration` or its helpers.
REFUSAL_REASONS: tuple[str, ...] = (
    # The router did not return a proved decision at all (it returned
    # ``unresolved``/``rejected``).
    "emitter_geometry_not_proved",
    # The router proved a decision, but it routed the source to the shaped-run
    # model.  Shaped-run geometry asserts no cell period and no cell origin, so
    # there is no grid to write down.
    "emitter_mode_not_fixed_lattice",
    # One or more of the four per-property proofs came back false.  These four
    # are reported separately so a receipt can say WHICH property was missing.
    "emitter_candidate_invalid",
    "emitter_pitch_unproven",
    "emitter_phase_unproven",
    "emitter_ownership_unproven",
    # The proved periodic row model's own baselines do not sit at a regular
    # multiple of its pitch, so one crop offset cannot serve every row.
    "emitter_baselines_irregular",
    # The lattice branch's own summary says some source pixel is not owned by
    # exactly one cell.
    "emitter_ownership_incomplete",
    # The router proved a pitch, but no periodic row candidate in the evidence
    # carries the winning pitch together with the winning ownership signature,
    # so the concrete row bounds cannot be recovered.  This should not happen;
    # it is checked rather than assumed.
    "emitter_winning_row_candidate_absent",
    # The recovered grid is not usable as a grid: no rows, no columns, or a
    # non-positive advance or line height.
    "emitter_grid_degenerate",
    # The derived cell box is taller than one line advance, which would make
    # neighbouring rows' boxes overlap and let one glyph be decoded twice.
    "emitter_cell_crop_overlaps_neighbour_row",
    # The router's foreground selection carries no usable (background,
    # threshold) recipe, so the decoder's ink mask could not be made to match
    # the mask the lattice was proved against.
    "emitter_foreground_recipe_absent",
    # An artifact already exists for this source hash.  Emission is write-once;
    # the existing file is left untouched.
    "emitter_artifact_already_present",
)


# ---------------------------------------------------------------------------
# Small deterministic helpers
# ---------------------------------------------------------------------------


def _plain(value: Any) -> Any:
    """Convert router output into plain JSON-compatible Python.

    The evidence bundle hands back ``mappingproxy`` objects, tuples, and NumPy
    scalars.  ``json.dumps`` refuses all three.  This walks the structure once
    and replaces them with ``dict``, ``list``, and Python ``int``/``float``.

    :param value: any nested structure produced by the geometry router.
    :returns: the same structure using only ``dict``/``list``/``str``/``int``/
        ``float``/``bool``/``None``.
    """

    # ``mappingproxy`` is not a ``dict`` subclass, so test by protocol.
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    # ``str``/``bytes`` are sequences too; they must not be walked elementwise.
    if isinstance(value, (list, tuple)) or (
        isinstance(value, Sequence) and not isinstance(value, (str, bytes))
    ):
        return [_plain(item) for item in value]
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, np.bool_):
        return bool(value)
    return value


def _document_bytes(payload: Mapping[str, Any]) -> bytes:
    """Serialize one document to the exact bytes that will hit the disk.

    Determinism requirements, all enforced here in one place:

    * ``sort_keys=True`` — dictionary insertion order must never leak into the
      bytes, otherwise the same measurement could hash two different ways;
    * ``indent=2`` — a stable, human-readable layout (these files get read by
      people during review, so minified JSON would be a false economy);
    * ``ensure_ascii=False`` plus an explicit UTF-8 encode — a stable, locale
      independent byte encoding;
    * a single trailing newline, so the file is a well-formed text file.

    :param payload: the document to serialize.
    :returns: the UTF-8 bytes to write, which are also the bytes to hash.
    """

    text = json.dumps(_plain(payload), sort_keys=True, indent=2, ensure_ascii=False)
    return (text + "\n").encode("utf-8")


def _implementation_identity() -> dict[str, str]:
    """Hash the code files that decide what an emission produces.

    :returns: a mapping of repository-relative path to SHA-256, containing only
        the files that actually exist (a missing file is omitted rather than
        recorded as an empty hash, so the receipt never asserts something
        false about the tree).
    """

    identity: dict[str, str] = {}
    for relative in _IDENTITY_FILES:
        path = _REPOSITORY_ROOT / relative
        if path.exists():
            identity[relative] = sha256_file(path)
    return identity


# ---------------------------------------------------------------------------
# Recovering the concrete proved lattice
# ---------------------------------------------------------------------------


def _winning_periodic_candidate(selected_geometry: Mapping[str, Any]) -> dict[str, Any] | None:
    """Find the periodic row candidate the router's pitch/phase proof selected.

    Background.  The router's evidence carries hundreds of periodic row
    candidates — one per (pitch, phase) pair it swept — and separately reports
    which pitch won and what the winning candidate's *ownership signature* is
    (a hash of exactly which pixels each row claims).  It does not re-export
    the winning candidate itself.  This function recovers it by matching on
    both facts at once: the candidate's pitch must equal the winning pitch AND
    its ownership signature must equal the winning ownership signature.

    Why both.  Pitch alone is ambiguous: many phases share one pitch.  The
    ownership signature disambiguates down to the set of phases that claim
    exactly the same pixels for exactly the same rows — which, when more than
    one survives, are by definition interchangeable descriptions of the same
    lattice (this is the router's own ``phase_tie_equivalent`` situation).  In
    that case the lowest phase is taken, purely so the choice is deterministic;
    every surviving candidate would produce an identical row-to-pixel mapping.

    :param selected_geometry: the router decision's
        ``provenance['selected_geometry']`` mapping.
    :returns: the winning candidate as a plain dict, or ``None`` when no
        candidate matches (which means the evidence is internally inconsistent
        and the caller must refuse).
    """

    authority = dict(selected_geometry.get("periodic_authority", {}))
    winning_pitch = authority.get("winning_pitch")
    winning_signature = authority.get("ownership_signature")
    if winning_pitch in (None, 0) or not winning_signature:
        return None
    matches: list[dict[str, Any]] = []
    for raw in selected_geometry.get("periodic_row_candidates", ()):
        candidate = dict(raw)
        if int(candidate.get("pitch", 0)) != int(winning_pitch):
            continue
        ownership = dict(candidate.get("ownership", {}))
        if ownership.get("ownership_signature") != winning_signature:
            continue
        matches.append(candidate)
    if not matches:
        return None
    # Deterministic tie-break among ownership-identical phases.
    matches.sort(key=lambda item: int(item.get("phase", 0)))
    return _plain(matches[0])


# ---------------------------------------------------------------------------
# Direct pixel measurements for the receipt
# ---------------------------------------------------------------------------


def _measure_boundary_ink(
    source_png: Path,
    *,
    background_rgb: Sequence[int],
    threshold: int,
    columns: int,
    rows: int,
    origin_x: float,
    advance_x: float,
    first_baseline: float,
    line_height: float,
    crop_top: int,
    crop_bottom: int,
) -> dict[str, Any]:
    """Measure how much ink the emitted grid leaves on its own boundaries.

    "Boundary-ink legality" is the question: does the grid we are about to
    write down actually cut the picture in empty places?  A grid whose vertical
    cell boundaries slice through glyph strokes, or whose row boxes leave ink
    stranded in the gaps between them, is a wrong grid even when every margin
    test came out positive.  So this reconstructs the exact ink mask and the
    exact cell boxes the decoder will build, and counts three things:

    * ink that lies inside no cell box at all (stranded ink);
    * ink sitting on the one-pixel column lines where two horizontally
      adjacent cells meet;
    * ink sitting in the horizontal gap between one row's box and the next.

    Nothing here gates the emission by itself — the router's ownership proof is
    the gate, and it already accounts for ink that continues across a row seam.
    These numbers are recorded so a reader can judge the artifact rather than
    trust it.

    :param source_png: the image being calibrated.
    :param background_rgb: the router-selected background colour.
    :param threshold: the router-selected ink threshold (L-infinity over RGB).
    :param columns: number of cell columns in the emitted grid.
    :param rows: number of cell rows in the emitted grid.
    :param origin_x: x of the left edge of column 0, in pixels.
    :param advance_x: horizontal cell advance, in pixels.
    :param first_baseline: y of row 0's text baseline, in pixels.
    :param line_height: vertical cell advance, in pixels.
    :param crop_top: cell box top edge relative to that row's baseline.
    :param crop_bottom: cell box bottom edge relative to that row's baseline.
    :returns: a mapping of measured counts (all plain ``int``/``float``/``bool``).
    """

    with Image.open(source_png) as opened:
        pixels = np.asarray(opened.convert("RGB"))
    # Identical formula to the decoder's ``segment`` and to the router's own
    # foreground construction: distance from background in the widest channel.
    distance = np.max(
        np.abs(pixels.astype(np.int32) - np.asarray(background_rgb, dtype=np.int32)), axis=2
    )
    ink = distance > int(threshold)
    height, width = ink.shape

    # Paint the union of every cell box exactly as ``segment`` will build them.
    covered = np.zeros_like(ink)
    for row in range(rows):
        y0 = round(first_baseline + row * line_height + crop_top)
        y1 = round(first_baseline + row * line_height + crop_bottom)
        ya, yb = max(0, y0), min(height, y1)
        if ya >= yb:
            continue
        for column in range(columns):
            x0 = round(origin_x + column * advance_x)
            x1 = round(origin_x + (column + 1) * advance_x)
            xa, xb = max(0, x0), min(width, x1)
            if xa < xb:
                covered[ya:yb, xa:xb] = True

    ink_total = int(ink.sum())
    ink_outside = int(np.logical_and(ink, ~covered).sum())

    # Vertical (column) boundaries: the single pixel column at each interior
    # cell edge.  Ink there means a stroke is being split between two cells.
    column_boundary_ink = 0
    column_boundaries_with_ink = 0
    column_boundary_ink_max = 0
    for column in range(1, columns):
        x = round(origin_x + column * advance_x)
        if not 0 <= x < width:
            continue
        count = int(ink[:, x].sum())
        column_boundary_ink += count
        column_boundary_ink_max = max(column_boundary_ink_max, count)
        if count:
            column_boundaries_with_ink += 1

    # Horizontal (row) seams: the rows of pixels between one cell box's bottom
    # edge and the next box's top edge.  When the crop span equals the line
    # height there is no such gap and these counts are zero by construction.
    row_seam_ink = 0
    row_seams_with_ink = 0
    for row in range(rows - 1):
        gap_start = round(first_baseline + row * line_height + crop_bottom)
        gap_end = round(first_baseline + (row + 1) * line_height + crop_top)
        ya, yb = max(0, gap_start), min(height, gap_end)
        if ya >= yb:
            continue
        count = int(ink[ya:yb, :].sum())
        row_seam_ink += count
        if count:
            row_seams_with_ink += 1

    return {
        "ink_pixels_total": ink_total,
        "ink_pixels_inside_cells": ink_total - ink_outside,
        "ink_pixels_outside_cells": ink_outside,
        "ink_coverage_fraction": round(
            (ink_total - ink_outside) / ink_total if ink_total else 1.0, 6
        ),
        "column_boundary_ink_pixels": column_boundary_ink,
        "column_boundaries_with_ink": column_boundaries_with_ink,
        "column_boundary_ink_max": column_boundary_ink_max,
        "column_boundary_count": max(0, columns - 1),
        "row_seam_ink_pixels": row_seam_ink,
        "row_seams_with_ink": row_seams_with_ink,
        "row_seam_count": max(0, rows - 1),
        # True only when the grid strands no ink at all outside its boxes.
        "all_ink_inside_cells": ink_outside == 0,
    }


# ---------------------------------------------------------------------------
# The index
# ---------------------------------------------------------------------------


def _read_index(index_path: Path) -> dict[str, Any]:
    """Load the shared index, or return an empty one.

    A corrupt or unreadable index is treated as absent rather than guessed at,
    but the caller then rewrites it from scratch — so this never silently
    discards entries it could have read.

    :param index_path: path to ``index.json`` in the output root.
    :returns: the index document, always containing a ``calibrations`` mapping.
    """

    if not index_path.exists():
        return {"schema": INDEX_SCHEMA, "calibrations": {}}
    try:
        payload = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"schema": INDEX_SCHEMA, "calibrations": {}}
    if not isinstance(payload, dict):
        return {"schema": INDEX_SCHEMA, "calibrations": {}}
    payload.setdefault("schema", INDEX_SCHEMA)
    entries = payload.get("calibrations")
    payload["calibrations"] = entries if isinstance(entries, dict) else {}
    return payload


def _append_to_index(
    index_path: Path,
    *,
    source_sha256: str,
    entry: Mapping[str, Any],
) -> str:
    """Record one artifact's hash in the shared index, at creation time.

    Read-modify-write with sorted keys: the whole index is rewritten so that
    its bytes depend only on its contents, never on the order emissions
    happened to run.  Two replays that emit the same set of sources therefore
    produce the same index bytes.

    :param index_path: path to ``index.json``.
    :param source_sha256: the source image hash, used as the entry key.
    :param entry: the entry body (artifact path, artifact hash, receipt hash).
    :returns: the SHA-256 of the index file's new bytes.
    """

    index = _read_index(index_path)
    index["schema"] = INDEX_SCHEMA
    index["emitter"] = {"name": EMITTER_NAME, "version": EMITTER_VERSION}
    index["calibrations"][source_sha256] = dict(entry)
    index["calibration_count"] = len(index["calibrations"])
    data = _document_bytes(index)
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_bytes(data)
    return sha256_bytes(data)


# ---------------------------------------------------------------------------
# The public entry
# ---------------------------------------------------------------------------


def emit_calibration(
    source_png: str | Path,
    output_root: str | Path | None = None,
    *,
    expected_sha256: str | None = None,
    configuration: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Emit one hash-bound calibration artifact for ``source_png``, or refuse.

    This is the module's only deep entry.  It performs the whole job — route,
    gate, derive, measure, write, index — and reports what happened in a single
    receipt mapping.  A refusal is a normal, expected outcome (most sources in
    the corpus are not lattices at all) and is reported as data, not raised.

    :param source_png: path to the PNG to calibrate.  Only its pixels are read;
        no sibling ``.txt`` transcript is ever opened.
    :param output_root: directory that holds ``<source_sha256>/`` artifact
        directories and the shared ``index.json``.  Defaults to
        :data:`DEFAULT_OUTPUT_ROOT`.
    :param expected_sha256: optional source hash the caller already knows; the
        router raises if the bytes disagree, which catches a stale path.
    :param configuration: optional router configuration passthrough.
    :returns: a receipt mapping with ``status`` either ``"emitted"`` or
        ``"refused"``.  A refusal carries ``refusal_reasons`` drawn from
        :data:`REFUSAL_REASONS`; an emission carries the artifact path, the
        artifact SHA-256, and the per-source proof measurements.
    """

    source_path = Path(source_png)
    root = Path(output_root) if output_root is not None else DEFAULT_OUTPUT_ROOT

    # -- Step 1: measure the raster.  This is the only place geometry is
    #    decided; nothing below may promote a source the router did not prove.
    bundle, decision = route_raster_geometry(
        source_path, expected_sha256=expected_sha256, configuration=configuration
    )
    source_sha256 = bundle.source_sha256

    def refuse(reasons: Sequence[str], **extra: Any) -> dict[str, Any]:
        """Build a typed refusal receipt (no file is written)."""

        return {
            "schema": RECEIPT_SCHEMA,
            "status": "refused",
            "source_sha256": source_sha256,
            "source_name": source_path.name,
            "refusal_reasons": list(dict.fromkeys(reasons)),
            "geometry_mode": decision.mode,
            "geometry_status": decision.status,
            "evidence_sha256": bundle.output_hash,
            "geometry_sha256": decision.geometry_hash,
            "emitter": {"name": EMITTER_NAME, "version": EMITTER_VERSION},
            "transcript_input": False,
            **extra,
        }

    # -- Step 2: the gate.  Every condition below names one part of the proof
    #    that is missing.  They are collected rather than short-circuited so a
    #    single receipt reports all of them at once.
    reasons: list[str] = []
    if decision.status != "proved":
        reasons.append("emitter_geometry_not_proved")
    if decision.mode != "fixed_lattice":
        reasons.append("emitter_mode_not_fixed_lattice")
    if not decision.candidate_valid:
        reasons.append("emitter_candidate_invalid")
    if not decision.pitch_proven:
        reasons.append("emitter_pitch_unproven")
    if not decision.phase_proven:
        reasons.append("emitter_phase_unproven")
    if not decision.ownership_proven:
        reasons.append("emitter_ownership_unproven")
    if reasons:
        return refuse(reasons)

    selected = _plain(decision.provenance.get("selected_geometry") or {})
    authority = dict(selected.get("periodic_authority", {}))
    lattice_detail = dict(authority.get("fixed_lattice_authority", {}))

    # Pixel ownership must be exactly-once and total.  This one IS measured on
    # the winning periodic candidate (``winning_candidate_ownership``), so the
    # branch's summary of it can be trusted directly.
    if not lattice_detail.get("ownership_complete", False):
        reasons.append("emitter_ownership_incomplete")
    if reasons:
        return refuse(reasons)

    # -- Step 3: recover the concrete proved row model.
    winning = _winning_periodic_candidate(selected)
    if winning is None:
        return refuse(["emitter_winning_row_candidate_absent"])

    # -- Step 3a: baseline regularity, measured on the model actually being
    #    written down.
    #
    #    A caution worth stating plainly, because it is easy to get wrong.  The
    #    lattice branch also publishes a ``baseline_regular`` flag, and it is
    #    NOT the right gate here: that flag is computed from the *blank-gap row
    #    bands* (groups of touching ink) against the blank-gap line height, not
    #    from the periodic lattice.  On this corpus it reports False for
    #    sources whose periodic baselines are perfectly evenly spaced — two of
    #    them have every single residual at exactly zero.  Gating on it would
    #    refuse correct lattices for a property they do have, using a
    #    measurement of a different model.  It is recorded in the receipt for
    #    completeness, but the gate below reads the periodic candidate's own
    #    numbers.
    #
    #    ``baseline_delta_residuals`` is, per row gap, the difference between
    #    the measured baseline step and the pitch.  The final entry is allowed
    #    to be non-zero when ``terminal_baseline_clamped`` is set: the last row
    #    can run off the bottom of the canvas, and the router clamps its
    #    baseline to the edge.  That is a property of the image border, not of
    #    the lattice, so only the interior gaps are gated.
    residuals = [int(value) for value in winning.get("baseline_delta_residuals", ())]
    terminal_clamped = bool(winning.get("terminal_baseline_clamped", False))
    interior_residuals = residuals[:-1] if (terminal_clamped and residuals) else residuals
    interior_residual_max = max((abs(value) for value in interior_residuals), default=0)
    if interior_residual_max > _BASELINE_RESIDUAL_TOLERANCE_PX:
        return refuse(["emitter_baselines_irregular"])

    foreground = dict(selected.get("selected_foreground") or {})
    background_rgb = foreground.get("background_rgb")
    ink_threshold = foreground.get("threshold")
    if not background_rgb or ink_threshold is None:
        return refuse(["emitter_foreground_recipe_absent"])
    background_rgb = [int(value) for value in background_rgb]
    ink_threshold = int(ink_threshold)

    # Row model: pitch is the line advance; the winning candidate's own first
    # baseline and first row bounds set the origin and the cell box.
    rows = int(winning.get("row_count", 0))
    baselines = [float(value) for value in winning.get("baselines", ())]
    row_bounds = [tuple(int(v) for v in pair) for pair in winning.get("row_bounds", ())]
    line_height = float(winning.get("pitch", 0))

    # Column model: taken straight from the router's selected lattice contract,
    # which is where the horizontal advance was proved.
    columns = int(selected.get("columns", 0))
    advance_x = float(selected.get("advance_x", 0.0))
    origin_x = float(selected.get("origin_x", 0.0))

    if (
        rows < 1
        or columns < 1
        or advance_x <= 0
        or line_height <= 0
        or not baselines
        or not row_bounds
    ):
        return refuse(["emitter_grid_degenerate"])

    first_baseline = float(baselines[0])
    # The cell box, expressed relative to the baseline of its own row.  Taking
    # it from row 0 and applying it to every row is exactly what the decoder
    # does, and it reproduces the candidate's row bounds because the candidate
    # is periodic by construction.
    crop_top = int(row_bounds[0][0] - first_baseline)
    crop_bottom = int(row_bounds[0][1] - first_baseline)
    if crop_bottom - crop_top > round(line_height):
        # A box taller than the line advance would overlap its neighbour, so
        # one glyph could be segmented into two rows.  Refuse rather than trim.
        return refuse(["emitter_cell_crop_overlaps_neighbour_row"])

    # -- Step 4: write-once check, before any measuring work is wasted.
    artifact_directory = root / source_sha256
    artifact_path = artifact_directory / "calibration.json"
    receipt_path = artifact_directory / "receipt.json"
    if artifact_path.exists():
        # The existing artifact's hash is reported so a determinism replay can
        # compare it against what a fresh emission would have produced.
        return refuse(
            ["emitter_artifact_already_present"],
            artifact_path=str(artifact_path),
            existing_artifact_sha256=sha256_file(artifact_path),
        )

    # -- Step 5: measure the grid against the source's own pixels.
    boundary = _measure_boundary_ink(
        source_path,
        background_rgb=background_rgb,
        threshold=ink_threshold,
        columns=columns,
        rows=rows,
        origin_x=origin_x,
        advance_x=advance_x,
        first_baseline=first_baseline,
        line_height=line_height,
        crop_top=crop_top,
        crop_bottom=crop_bottom,
    )

    # Baseline regularity, as numbers rather than a flag: how far the measured
    # baselines drift from a perfectly periodic ladder.  Zero means the rows sit
    # exactly ``line_height`` apart all the way down.  Both the gated interior
    # figure and the branch's differently-derived blank-gap flag are recorded,
    # so a reader can see they disagree and why.
    baseline_regularity = {
        "regular": interior_residual_max <= _BASELINE_RESIDUAL_TOLERANCE_PX,
        "measured_on": "winning_periodic_row_candidate",
        "line_height_px": line_height,
        "interior_residual_max": interior_residual_max,
        "interior_residual_tolerance_px": _BASELINE_RESIDUAL_TOLERANCE_PX,
        "baseline_delta_residual_max": max((abs(value) for value in residuals), default=0),
        "baseline_delta_residuals": residuals,
        "baseline_deltas": [int(value) for value in winning.get("baseline_deltas", ())],
        "terminal_baseline_clamped": terminal_clamped,
        # The lattice branch's own flag, computed from the blank-gap row bands
        # rather than from this periodic model.  Recorded, never gated on.
        "branch_blank_gap_baseline_regular": bool(lattice_detail.get("baseline_regular", False)),
    }

    canvas = dict(selected.get("canvas", {}))
    ownership_detail = dict(authority.get("winning_candidate_ownership", {}))

    # -- Step 6: build the artifact in the legacy decoder's schema.
    calibration: dict[str, Any] = {
        "calibrator": {"name": EMITTER_NAME, "version": EMITTER_VERSION},
        "schema": CALIBRATION_SCHEMA,
        "status": EMITTED_STATUS,
        "source_png": source_path.name,
        "source_sha256": source_sha256,
        "canvas": {
            "width_px": int(canvas.get("width", 0)),
            "height_px": int(canvas.get("height", 0)),
            "background_rgb": background_rgb,
        },
        "normalization": {
            "colour_space": "RGB",
            "ink_threshold_l1": ink_threshold,
            # Names the provenance of the recipe rather than a hand method.
            "background_method": "router_selected_foreground_recipe",
            "foreground_mask_sha256": foreground.get("mask_sha256"),
        },
        # The router proves no rendered gridlines, so nothing is erased.
        "guide_columns_px": [],
        "grid": {
            "columns": columns,
            "rows": rows,
            "origin_x_px": origin_x,
            "first_baseline_y_px": first_baseline,
            "cell_advance_x_px": advance_x,
            "line_height_px": line_height,
            "cell_crop_top_offset_px": crop_top,
            "cell_crop_bottom_offset_px": crop_bottom,
            "x_phase_px_mod_period": round(origin_x % advance_x, 6),
            "y_phase_px_mod_period": int(winning.get("phase", 0)),
            "row_crop_measurement": {
                "top": crop_top,
                "bottom": crop_bottom,
                "boundary_ink": boundary["row_seam_ink_pixels"],
                "boundary_samples": boundary["row_seam_count"],
                "inter_row_clearance_px": int(round(line_height)) - (crop_bottom - crop_top),
            },
        },
        # Provenance: exactly which proof this file was derived from.  A reader
        # can re-run the router and check these three hashes still match.
        "derived_from": {
            "router": "raster_authority_owner",
            "evidence_sha256": bundle.output_hash,
            "geometry_sha256": decision.geometry_hash,
            "selected_foreground_mask_sha256": selected.get("selected_foreground_mask_sha256"),
            "ownership_signature": authority.get("ownership_signature"),
            "winning_pitch": authority.get("winning_pitch"),
            "winning_phase": int(winning.get("phase", 0)),
            "transcript_input": False,
        },
    }
    artifact_bytes = _document_bytes(calibration)
    artifact_sha256 = sha256_bytes(artifact_bytes)

    # -- Step 7: build the receipt.  It says what was proved and by how much,
    #    so a reader never has to re-run the router to judge the artifact.
    receipt: dict[str, Any] = {
        "schema": RECEIPT_SCHEMA,
        "status": "emitted",
        "source_sha256": source_sha256,
        "source_name": source_path.name,
        "artifact_path": f"{source_sha256}/calibration.json",
        "artifact_sha256": artifact_sha256,
        "emitter": {"name": EMITTER_NAME, "version": EMITTER_VERSION},
        "geometry_mode": decision.mode,
        "geometry_status": decision.status,
        "evidence_sha256": bundle.output_hash,
        "geometry_sha256": decision.geometry_hash,
        "implementation_sha256": _implementation_identity(),
        "grid": dict(calibration["grid"]),
        # --- the four proof families the receipt is required to carry ---
        "pitch_margins": {
            "winning_pitch": authority.get("winning_pitch"),
            "normalized_pitch_margin": authority.get("normalized_pitch_margin"),
            "seam_pitch_margin": authority.get("seam_pitch_margin"),
            "seam_winning_pitch": authority.get("seam_winning_pitch"),
            "authority_margin": authority.get("authority_margin"),
            "pitch_margin_sufficient": bool(authority.get("pitch_margin_sufficient")),
            "pitch_tie_equivalent": bool(authority.get("pitch_tie_equivalent")),
            "pitch_authority_stream": authority.get("pitch_authority_stream"),
            "pitch_streams_contested": bool(authority.get("pitch_streams_contested")),
        },
        "phase_margins": {
            "winning_phase": int(winning.get("phase", 0)),
            "normalized_phase_margin": authority.get("normalized_phase_margin"),
            "phase_margin_sufficient": bool(authority.get("phase_margin_sufficient")),
            "phase_tie_equivalent": bool(authority.get("phase_tie_equivalent")),
            "winning_phase_group": authority.get("winning_phase_group"),
        },
        "ownership_completeness": {
            "ownership_complete": bool(lattice_detail.get("ownership_complete", False)),
            "signature": authority.get("ownership_signature"),
            "method": authority.get("ownership_method"),
            "owned_pixel_count": ownership_detail.get("owned_pixel_count"),
            "unowned_pixel_count": ownership_detail.get("unowned_pixel_count"),
            "cross_row_continuation_count": len(
                ownership_detail.get("cross_row_continuations", [])
            ),
        },
        "baseline_regularity": baseline_regularity,
        "boundary_ink_legality": boundary,
        "transcript_input": False,
    }

    # -- Step 8: write.  Artifact first, then receipt, then the index.  The
    #    index entry is what makes the artifact visible to the row-joint seam,
    #    so it is written last: an interrupted emission leaves an orphan
    #    directory that nothing consults, never an index pointing at nothing.
    artifact_directory.mkdir(parents=True, exist_ok=True)
    artifact_path.write_bytes(artifact_bytes)
    receipt_bytes = _document_bytes(receipt)
    receipt_path.write_bytes(receipt_bytes)
    index_sha256 = _append_to_index(
        root / INDEX_FILENAME,
        source_sha256=source_sha256,
        entry={
            "artifact_path": f"{source_sha256}/calibration.json",
            "artifact_sha256": artifact_sha256,
            "receipt_path": f"{source_sha256}/receipt.json",
            "receipt_sha256": sha256_bytes(receipt_bytes),
            "status": EMITTED_STATUS,
        },
    )

    result = dict(receipt)
    result["index_sha256"] = index_sha256
    result["artifact_absolute_path"] = str(artifact_path)
    return result
