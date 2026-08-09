"""Canonical approved author-questionnaire content and paint-safe gift choices.

The browser receives this package through ``author_web``. JavaScript renders
it but never owns a copied question bank. The old v0 banks remain preserved
prototype evidence; this v1 artifact is the sole approved browser corpus.

Gift candidacy and paint permission stay separate. This package says which
accepted kinds would make sense as authored gifts, while the generated paint
manifest says which exact assets may currently paint. The payload exposes only
the intersection, so questionnaire content cannot grant art acceptance.
"""

from __future__ import annotations

from copy import deepcopy
import json
from importlib.resources import files
from pathlib import Path
from typing import Any


QUESTIONNAIRE_RESOURCE = "data/author_questionnaire.v1.json"
EXPECTED_ROW_IDS = frozenset({
    "P1", "P2", "P3", "P4", "L0", "L1", "L2", "L3",
    "A1", "A2", "A3",
    "B1", "B2", "B3", "B4", "B5", "B6", "B7", "B8", "B9", "B10",
    "C1", "C2", "C3", "C4",
    "D1", "D2", "D3", "D4", "D5", "E1",
    "G1", "G2", "G3", "G4", "G5", "G6", "X1", "X2", "X3",
})


def load_questionnaire() -> dict[str, Any]:
    """Load and structurally verify the packaged operator-approved corpus."""
    resource = files("lateletter").joinpath(QUESTIONNAIRE_RESOURCE)
    payload = json.loads(resource.read_text(encoding="utf-8"))
    if payload.get("schema") != 1 or payload.get("status") != "operator_approved":
        raise RuntimeError("author questionnaire is not approved schema 1")
    rows = payload.get("rows")
    if not isinstance(rows, list):
        raise RuntimeError("author questionnaire rows must be a list")
    identifiers = [row.get("id") for row in rows if isinstance(row, dict)]
    if len(rows) != 40 or len(set(identifiers)) != 40:
        raise RuntimeError("author questionnaire must contain 40 unique rows")
    if set(identifiers) != EXPECTED_ROW_IDS:
        raise RuntimeError("author questionnaire row identity does not match approval")
    return payload


def questionnaire_for_browser(paint_manifest_path: Path) -> dict[str, Any]:
    """Return the corpus with G2 choices filtered by accepted paint authority."""
    questionnaire = deepcopy(load_questionnaire())
    try:
        manifest = json.loads(Path(paint_manifest_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("accepted-paint authority is unavailable") from exc
    accepted = {
        value for value in manifest.get("accepted_assets", [])
        if isinstance(value, str)
    }
    gift_row = next(row for row in questionnaire["rows"] if row["id"] == "G2")
    gift_row["options"] = [
        option for option in gift_row.get("options", [])
        if option.get("asset_id") in accepted
    ]
    questionnaire["paint_authority"] = {
        "schema": manifest.get("schema"),
        "gift_asset_ids": [option["asset_id"] for option in gift_row["options"]],
    }
    return questionnaire
