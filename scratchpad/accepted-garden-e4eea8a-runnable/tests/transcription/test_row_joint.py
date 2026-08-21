"""Tests for the row-joint lattice bridge and its selector contract.

These tests pin the three properties that make the legacy decoder safe to
re-enter production as proposal evidence:

1. a decode happens only under a hash-bound tracked calibration and is
   deterministic across repeated calls;
2. ``?`` cells survive into the proposal text (the decoder refuses,
   it does not guess); and
3. the production selector never turns a ``?``-bearing row-joint text
   into a candidate, while an unknown-free row-joint text outranks the
   script-membership heuristics.
"""

from __future__ import annotations

from pathlib import Path

from lateletter.transcription import row_joint
from lateletter.transcription.pipeline import _best_effort_candidate_from_report

REPO = Path(__file__).resolve().parents[2]
HORSE_SOURCE = (
    REPO
    / "tracked"
    / "LateLetterResearch"
    / "transcription-parity"
    / "horse-animation-sheet"
    / "source"
    / "source.normalized.png"
)


def test_horse_decode_is_deterministic_and_preserves_unknown_cells() -> None:
    first = row_joint.decode_for_source(HORSE_SOURCE)
    second = row_joint.decode_for_source(HORSE_SOURCE)
    assert first is not None, "horse source must have a tracked hash-bound calibration"
    # Byte-identical output across calls is the determinism contract.
    assert first == second
    # The tracked calibration path must come from the immutable attempt
    # history, bound to this exact source hash.
    assert "calibration.json" in first["calibration_path"]
    assert first["source_sha256"] == row_joint._legacy_module().sha256(HORSE_SOURCE)
    # The decoder must keep refusing low-margin cells instead of guessing:
    # the horse sheet is documented to contain unknown cells.
    assert first["unknown_cells"] > 0
    assert first["unknown_marker"] in first["text"]
    assert first["row_count"] > 0 and first["columns"] > 0


def test_unbound_source_hash_has_no_calibration() -> None:
    assert row_joint.resolve_calibration("0" * 64) is None


BBBB_SOURCE = (
    REPO
    / "tracked"
    / "LateLetterResearch"
    / "transcription-parity"
    / "bbbb-flowers"
    / "source"
    / "source.normalized.png"
)


def test_unknown_naming_reduces_unknowns_only_via_gated_source_evidence() -> None:
    first = row_joint.decode_for_source(BBBB_SOURCE)
    second = row_joint.decode_for_source(BBBB_SOURCE)
    assert first is not None and first == second
    # Naming may only shrink the unknown count, never grow it, and every
    # decision must carry its evidence record.
    assert first["unknown_cells"] <= first["unknown_cells_before_naming"]
    named = [g for g in first["unknown_naming"]["groups"] if g.get("named")]
    refused = [g for g in first["unknown_naming"]["groups"] if not g.get("named")]
    assert named, "bbbb-flowers has repeat-shape unknowns the source bank can name"
    for group in named:
        # Every name so far comes from the screenshot's own font; a
        # rendered-repertoire name is legal but must clear the same
        # record shape.
        assert group["stage"] in {"source_template", "rendered_repertoire"}
        assert group["iou"] >= 0.55
        assert group["margin"] >= 0.04
        assert group["cell_indexes"]
    for group in refused:
        assert group.get("reason"), "a refusal must carry a typed reason"
    # Naming decisions never touch cells the decoder committed to: the
    # named cell indexes must all have been unknown beforehand.
    total_named_cells = sum(len(g["cell_indexes"]) for g in named)
    assert first["unknown_cells_before_naming"] - first["unknown_cells"] == total_named_cells


def test_bbbb_decode_states_no_wrong_characters_against_accepted_holdout() -> None:
    """Accepted-corpus regression pin: every character the machine STATES
    on bbbb-flowers must match the accepted transcript; imperfection is
    only allowed as an explicit ``?`` refusal.  The accepted text is a
    holdout — the decode path never reads it."""

    import unicodedata

    res = row_joint.decode_for_source(BBBB_SOURCE)
    assert res is not None
    accepted = (
        REPO / "tracked" / "LateLetterResearch" / "transcription-parity" / "bbbb-flowers" / "accepted.txt"
    )
    truth = [
        unicodedata.normalize("NFC", line.rstrip())
        for line in accepted.read_text(encoding="utf-8").rstrip("\n").splitlines()
    ]
    machine = [line.rstrip() for line in res["text"].splitlines()]
    wrong = [
        (row, col, m_ch, t_ch)
        for row, (m_line, t_line) in enumerate(zip(machine, truth))
        for col, (m_ch, t_ch) in enumerate(zip(m_line.ljust(80), t_line.ljust(80)))
        if m_ch != t_ch and m_ch != res["unknown_marker"]
    ]
    assert wrong == [], f"machine stated wrong characters: {wrong}"
    exact_rows = sum(1 for m_line, t_line in zip(machine, truth) if m_line == t_line)
    assert exact_rows >= 8


def _report_with(adapters: list[dict]) -> dict:
    return {"results": [{"adapters": adapters}]}


def test_selector_refuses_row_joint_text_with_unknown_cells() -> None:
    report = _report_with(
        [
            {
                "adapter": "row-joint-lattice",
                "deterministic": True,
                "budget_exceeded": False,
                "unsupported_status": [],
                "top_k_logical_sequences": ["/\\_|?\n(=)"],
            }
        ]
    )
    selected = _best_effort_candidate_from_report(report, source_png=HORSE_SOURCE)
    # The only offered text carries ``?`` so no candidate may exist.
    assert selected is None


def test_selector_refuses_weaker_adapters_when_row_joint_evidence_exists() -> None:
    # Row-joint evidence exists for the source but its text carries ``?``:
    # the whitelist adapters may not step in as a fallback guess.
    report = _report_with(
        [
            {
                "adapter": "fixed-lattice-structural",
                "deterministic": True,
                "budget_exceeded": False,
                "unsupported_status": [],
                "top_k_logical_sequences": ["---___\n\\\\_--"],
            },
            {
                "adapter": "row-joint-lattice",
                "deterministic": True,
                "budget_exceeded": False,
                "unsupported_status": [],
                "top_k_logical_sequences": ["/\\_|?\n(=)"],
            },
        ]
    )
    selected = _best_effort_candidate_from_report(
        report, source_png=HORSE_SOURCE, row_joint_available=True
    )
    assert selected is None


def test_selector_refuses_whitelist_candidates_at_live_component_scale() -> None:
    # Whitelist rules are fixture-scoped evidence; on a source with
    # hundreds of ink components they may not author a candidate.
    report = _report_with(
        [
            {
                "adapter": "fixed-lattice-structural",
                "deterministic": True,
                "budget_exceeded": False,
                "unsupported_status": [],
                "top_k_logical_sequences": ["---___---___\n\\\\_--_--_--"],
            }
        ]
    )
    selected = _best_effort_candidate_from_report(
        report, source_png=HORSE_SOURCE, source_component_count=300
    )
    assert selected is None


def test_selector_prefers_unknown_free_row_joint_over_ocr_profiles() -> None:
    report = _report_with(
        [
            {
                "adapter": "psm7-eng",
                "deterministic": True,
                "budget_exceeded": False,
                "unsupported_status": [],
                "top_k_logical_sequences": ["L L L L\nA A A A"],
            },
            {
                "adapter": "row-joint-lattice",
                "deterministic": True,
                "budget_exceeded": False,
                "unsupported_status": [],
                "top_k_logical_sequences": ["/\\_|~~\n(==__)"],
            },
        ]
    )
    selected = _best_effort_candidate_from_report(report, source_png=HORSE_SOURCE)
    assert selected is not None
    assert selected["adapter"] == "row-joint-lattice"
    assert selected["reason"] == "row_joint_screenshot_local_template_fit"
