"""Corpus schema and provenance/hash gate tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from lateletter.transcription import CorpusError, validate_corpus


ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "tests/fixtures/transcription/corpus.json"
CORPUS_V2 = ROOT / "tests/fixtures/transcription-v2/corpus-v2.json"


def test_tracked_corpus_validates_every_fixture() -> None:
    summary = validate_corpus(CORPUS)
    assert summary == {
        "schema_version": "lateletter-transcription-corpus-1",
        "fixture_count": 23,
        "positive_count": 10,
        "fail_closed_count": 10,
        "mutation_count": 3,
        "development_count": 13,
        "release_gate_count": 10,
    }


def test_corpus_rejects_unknown_fixture_fields_and_stale_hashes(tmp_path: Path) -> None:
    payload = json.loads(CORPUS.read_text(encoding="utf-8"))
    payload["fixtures"][0]["unexpected"] = True
    path = tmp_path / "corpus.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    # Copying is deliberately not enough: the relative corpus root must contain the artifacts.
    with pytest.raises(CorpusError, match="unknown|cannot read"):
        validate_corpus(path)

    payload = json.loads(CORPUS.read_text(encoding="utf-8"))
    payload["fixtures"][0]["source_sha256"] = "0" * 64
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(CorpusError):
        validate_corpus(path)


def test_verified_font_corpus_v2_reclassifies_fallback_boxes_fail_closed() -> None:
    summary = validate_corpus(CORPUS_V2)
    assert summary == {
        "schema_version": "lateletter-transcription-corpus-1",
        "fixture_count": 15,
        "positive_count": 10,
        "fail_closed_count": 5,
        "mutation_count": 0,
        "development_count": 5,
        "release_gate_count": 10,
    }
    payload = json.loads(CORPUS_V2.read_text(encoding="utf-8"))
    fallback_ids = {item["id"] for item in payload["fixtures"] if item["split"] == "development"}
    assert fallback_ids == {
        "fallback-kana",
        "fallback-kanji",
        "fallback-width-mixture",
        "fallback-emoji-zwj",
        "fallback-mixed-script",
    }
    for item in payload["fixtures"]:
        if item["id"] not in fallback_ids:
            continue
        receipt = json.loads((CORPUS_V2.parent / item["source_renderer_receipt"]).read_text(encoding="utf-8"))
        assert item["expected_outcome"] == "rejected"
        assert item["expected_rejection_codes"] == ["unicode_visual_collision"]
        assert receipt["fallback_box_expected"] is True
        assert receipt["coverage"]["complete"] is False
