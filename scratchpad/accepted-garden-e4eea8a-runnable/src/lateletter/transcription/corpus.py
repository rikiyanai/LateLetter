"""Validation for the tracked positive and fail-closed transcription corpus."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .hashing import resolve_under, sha256_file, verify_hash_file
from .schema import SchemaError


class CorpusError(ValueError):
    """Raised when a corpus fixture is incomplete, stale, or unsafe."""


REQUIRED_FIXTURE_FIELDS = {
    "id",
    "split",
    "class",
    "source_png",
    "source_sha256",
    "transcript",
    "transcript_sha256",
    "visual_layout",
    "visual_layout_sha256",
    "provenance",
    "source_renderer_receipt",
    "source_renderer_receipt_sha256",
    "expected_geometry_mode",
    "expected_outcome",
    "expected_rejection_codes",
}
ALLOWED_CLASSES = {"positive", "fail_closed", "mutation"}
ALLOWED_SPLITS = {"development", "release_gate"}
ALLOWED_GEOMETRY = {"fixed_lattice", "shaped_runs", "unresolved"}
ALLOWED_OUTCOMES = {"positive", "rejected"}


def _load(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CorpusError(f"cannot read JSON fixture {path}") from exc
    if not isinstance(payload, dict):
        raise CorpusError(f"fixture JSON must be an object: {path}")
    return payload


def _hash_bound_json(root: Path, relative: str, expected: str, label: str) -> dict[str, Any]:
    path = resolve_under(root, relative)
    try:
        verify_hash_file(path, expected, field=label)
    except (OSError, ValueError) as exc:
        raise CorpusError(str(exc)) from exc
    payload = _load(path)
    return payload


def validate_corpus(corpus_path: str | Path) -> dict[str, Any]:
    """Validate every fixture and return a deterministic summary."""

    path = Path(corpus_path)
    corpus = _load(path)
    if corpus.get("schema_version") != "lateletter-transcription-corpus-1":
        raise CorpusError("unsupported corpus schema_version")
    fixtures = corpus.get("fixtures")
    if not isinstance(fixtures, list) or not fixtures:
        raise CorpusError("corpus must contain a non-empty fixtures list")
    root = path.parent
    ids: set[str] = set()
    splits: dict[str, set[str]] = {split: set() for split in ALLOWED_SPLITS}
    expected_release = set(corpus.get("release_gate", []))
    for fixture in fixtures:
        if not isinstance(fixture, dict):
            raise CorpusError("each fixture must be an object")
        unknown = set(fixture) - REQUIRED_FIXTURE_FIELDS - {"parent_fixture_id", "mutation"}
        missing = REQUIRED_FIXTURE_FIELDS - set(fixture)
        if unknown:
            raise CorpusError(f"fixture has unknown fields: {sorted(unknown)}")
        if missing:
            raise CorpusError(f"fixture is missing fields: {sorted(missing)}")
        fixture_id = fixture["id"]
        if not isinstance(fixture_id, str) or not fixture_id or fixture_id in ids:
            raise CorpusError(f"fixture id is missing or duplicated: {fixture_id!r}")
        ids.add(fixture_id)
        split = fixture["split"]
        if split not in ALLOWED_SPLITS:
            raise CorpusError(f"invalid fixture split: {split!r}")
        splits[split].add(fixture_id)
        fixture_class = fixture["class"]
        if fixture_class not in ALLOWED_CLASSES:
            raise CorpusError(f"invalid fixture class: {fixture_class!r}")
        if fixture["expected_geometry_mode"] not in ALLOWED_GEOMETRY:
            raise CorpusError(f"invalid expected geometry mode for {fixture_id}")
        if fixture["expected_outcome"] not in ALLOWED_OUTCOMES:
            raise CorpusError(f"invalid expected outcome for {fixture_id}")
        if not isinstance(fixture["expected_rejection_codes"], list):
            raise CorpusError(f"expected_rejection_codes must be a list for {fixture_id}")
        if not isinstance(fixture["provenance"], dict) or not fixture["provenance"].get("license"):
            raise CorpusError(f"fixture provenance/license missing for {fixture_id}")
        source = resolve_under(root, fixture["source_png"])
        try:
            verify_hash_file(source, fixture["source_sha256"], field=f"{fixture_id}.source_png")
        except (OSError, ValueError) as exc:
            raise CorpusError(str(exc)) from exc
        if source.suffix.lower() != ".png":
            raise CorpusError(f"source is not PNG for {fixture_id}")
        transcript_path = resolve_under(root, fixture["transcript"])
        try:
            verify_hash_file(transcript_path, fixture["transcript_sha256"], field=f"{fixture_id}.transcript")
        except (OSError, ValueError) as exc:
            raise CorpusError(str(exc)) from exc
        transcript_path.read_text(encoding="utf-8")
        layout = _hash_bound_json(root, fixture["visual_layout"], fixture["visual_layout_sha256"], f"{fixture_id}.visual_layout")
        if layout.get("fixture_id") != fixture_id:
            raise CorpusError(f"visual layout fixture id mismatch for {fixture_id}")
        renderer = _hash_bound_json(
            root,
            fixture["source_renderer_receipt"],
            fixture["source_renderer_receipt_sha256"],
            f"{fixture_id}.source_renderer_receipt",
        )
        if renderer.get("fixture_id") != fixture_id:
            raise CorpusError(f"renderer receipt fixture id mismatch for {fixture_id}")
        if fixture_class == "positive" and fixture["expected_outcome"] != "positive":
            raise CorpusError(f"positive fixture must have positive outcome: {fixture_id}")
        if fixture_class in {"fail_closed", "mutation"} and fixture["expected_outcome"] != "rejected":
            raise CorpusError(f"negative fixture must be rejected: {fixture_id}")
        if fixture_class == "mutation" and not fixture.get("parent_fixture_id"):
            raise CorpusError(f"mutation fixture needs parent_fixture_id: {fixture_id}")
    if not expected_release.issubset(ids):
        raise CorpusError("release_gate names an unknown fixture")
    if expected_release != splits["release_gate"]:
        raise CorpusError("release_gate list must exactly match release_gate fixture split")
    if splits["development"] & splits["release_gate"]:
        raise CorpusError("development and release_gate fixtures overlap")
    return {
        "schema_version": corpus["schema_version"],
        "fixture_count": len(fixtures),
        "positive_count": sum(item["class"] == "positive" for item in fixtures),
        "fail_closed_count": sum(item["class"] == "fail_closed" for item in fixtures),
        "mutation_count": sum(item["class"] == "mutation" for item in fixtures),
        "development_count": len(splits["development"]),
        "release_gate_count": len(splits["release_gate"]),
    }
