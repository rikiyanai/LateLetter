"""Contracts for the operator-approved browser-author questionnaire."""

from __future__ import annotations

import json
from pathlib import Path

from lateletter.author_questionnaire import (
    EXPECTED_ROW_IDS,
    load_questionnaire,
    questionnaire_for_browser,
)


ROOT = Path(__file__).resolve().parents[1]


def _rows() -> dict[str, dict]:
    return {row["id"]: row for row in load_questionnaire()["rows"]}


def test_approved_corpus_has_all_forty_rows_and_five_counted_stages():
    questionnaire = load_questionnaire()

    assert questionnaire["status"] == "operator_approved"
    assert [stage["id"] for stage in questionnaire["stages"]] == [
        "people", "letters", "gifts", "review", "export",
    ]
    assert len(questionnaire["rows"]) == 40
    assert {row["id"] for row in questionnaire["rows"]} == EXPECTED_ROW_IDS


def test_operator_redlines_and_visibility_decisions_are_canonical():
    rows = _rows()

    assert rows["B2"]["prompt"] == "What might they not think to ask on a day like this?"
    assert rows["B3"]["status"] == "removed_mvp"
    assert rows["C1"]["prompt"] == "What are you thanking them for? Be specific."
    assert "‘Nothing’ is a complete answer" in rows["C3"]["prompt"]
    assert "permission" in rows["D1"]["prompt"]
    assert "leaving the choice with them" in rows["D5"]["prompt"]
    assert rows["D4"]["partner_only"] is True
    assert rows["D4"]["requires_permission_opt_in"] is True
    assert rows["G1"]["required"] is False
    assert rows["G4"]["role"] == "gift_recurrence"
    assert rows["G6"]["status"] == "hidden_pending_v2_policy"
    assert rows["X3"]["status"] == "no_storage"


def test_browser_gift_choices_are_intersection_with_paint_authority(tmp_path):
    authority = tmp_path / "paint.json"
    authority.write_text(json.dumps({
        "schema": 2,
        "accepted_assets": ["fixture.mixtape", "fixture.review_only"],
    }), encoding="utf-8")

    questionnaire = questionnaire_for_browser(authority)
    gift_row = next(row for row in questionnaire["rows"] if row["id"] == "G2")

    assert [choice["asset_id"] for choice in gift_row["options"]] == [
        "fixture.mixtape",
    ]
    assert questionnaire["paint_authority"] == {
        "schema": 2,
        "gift_asset_ids": ["fixture.mixtape"],
    }


def test_tracked_paint_authority_exposes_only_the_four_approved_gifts():
    questionnaire = questionnaire_for_browser(
        ROOT / "web" / "garden-accepted-paint.v1.json",
    )
    gift_row = next(row for row in questionnaire["rows"] if row["id"] == "G2")

    assert [choice["asset_id"] for choice in gift_row["options"]] == [
        "fixture.coffee_mug",
        "fixture.ice_cream_cone",
        "fixture.mixtape",
        "fixture.popsicle",
    ]
