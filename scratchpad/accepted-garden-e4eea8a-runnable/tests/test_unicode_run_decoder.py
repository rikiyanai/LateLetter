"""Unicode grapheme/run boundary tests for raster transcription candidates."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def load_decoder():
    path = ROOT / "scripts" / "unicode_run_decoder.py"
    spec = importlib.util.spec_from_file_location("unicode_run_decoder", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_grapheme_segmentation_keeps_combining_emoji_and_zwj_runs_intact() -> None:
    decoder = load_decoder()
    clusters = decoder.segment_graphemes("e\u0301👩‍🌾")
    assert clusters == ["e\u0301", "👩‍🌾"]
    records = decoder.inspect_row(2, "e\u0301👩‍🌾", ambiguous_width=1)
    assert [record.nfc for record in records] == ["é", "👩‍🌾"]
    assert records[0].grapheme_width == 1
    assert records[1].shaping_required is True
    assert records[1].script_hint == "emoji_or_symbol"


def test_cjk_and_arabic_runs_record_width_direction_and_shaping_requirement() -> None:
    decoder = load_decoder()
    cjk = decoder.inspect_row(0, "漢字かな", ambiguous_width=1)
    assert [record.grapheme_width for record in cjk] == [2, 2, 2, 2]
    assert all(record.script_hint == "cjk_or_kana" for record in cjk)

    arabic = decoder.inspect_row(1, "سلام", ambiguous_width=1)
    assert all(record.direction == "rtl" for record in arabic)
    assert all(record.shaping_required for record in arabic)
    with pytest.raises(decoder.UnicodeRunError, match="shaping profile"):
        decoder.require_shaping_profile(arabic, None)


def test_ambiguous_width_and_illegal_controls_fail_closed() -> None:
    decoder = load_decoder()
    ambiguous = decoder.inspect_row(0, "·", ambiguous_width=None)
    assert ambiguous[0].grapheme_width is None
    assert ambiguous[0].status == "unknown"
    with pytest.raises(decoder.UnicodeRunError, match="control"):
        decoder.inspect_row(0, "A\u202E B", ambiguous_width=1)
    with pytest.raises(decoder.UnicodeRunError, match="private-use"):
        decoder.inspect_row(0, "\ue000", ambiguous_width=1)


def test_nfc_and_sidecar_preserve_original_cluster_evidence() -> None:
    decoder = load_decoder()
    records = decoder.inspect_row(3, "e\u0301", ambiguous_width=1)
    assert records[0].text == "e\u0301"
    assert records[0].nfc == "é"
    payload = decoder.records_json(records)
    assert '"nfc": "é"' in payload
    assert '"U+0065"' in payload
    assert '"U+0301"' in payload
