"""Canonical logical-Unicode validation for proposed text-art runs.

This module validates already-proposed text; it never infers code points from
pixels and never writes a candidate or acceptance manifest.  The historical
``scripts/unicode_run_decoder.py`` module is a diagnostic compatibility import.
"""

from __future__ import annotations

import json
import unicodedata
from dataclasses import asdict, dataclass
from typing import Iterable

try:
    import regex as _regex
except ImportError:  # pragma: no cover - dependency is pinned by the project
    _regex = None

from wcwidth import wcswidth

from .hashing import sha256_bytes


class UnicodeRunError(ValueError):
    """Raised when a proposed run cannot be represented safely."""


BIDI_CONTROLS = {
    "LRE", "RLE", "LRO", "RLO", "PDF", "LRI", "RLI", "FSI", "PDI",
}
ALLOWED_FORMAT_CHARS = {"\u200c", "\u200d", "\ufe0e", "\ufe0f"}


@dataclass(frozen=True)
class GraphemeRecord:
    row: int
    visual_start: float
    visual_end: float
    text: str
    nfc: str
    codepoints: tuple[str, ...]
    grapheme_width: int | None
    east_asian_width: tuple[str, ...]
    direction: str
    script_hint: str
    shaping_required: bool
    alternatives: tuple[str, ...]
    confidence: float
    status: str


def segment_graphemes(text: str) -> list[str]:
    """Segment text using the pinned UAX #29 implementation."""
    if _regex is None:
        raise UnicodeRunError("regex package is required for UAX #29 grapheme segmentation")
    return _regex.findall(r"\X", text)


def _validate_cluster(cluster: str) -> None:
    for char in cluster:
        codepoint = ord(char)
        category = unicodedata.category(char)
        bidi = unicodedata.bidirectional(char)
        if category in {"Cs", "Co"}:
            raise UnicodeRunError(f"unsupported surrogate/private-use code point U+{codepoint:04X}")
        if bidi in BIDI_CONTROLS:
            raise UnicodeRunError(f"bidi control U+{codepoint:04X} is not visual evidence")
        if category == "Cc":
            raise UnicodeRunError(f"control code point U+{codepoint:04X} is not visual evidence")
        if category == "Cf" and char not in ALLOWED_FORMAT_CHARS:
            raise UnicodeRunError(f"format control U+{codepoint:04X} requires an explicit shaping profile")


def normalize_cluster(cluster: str) -> str:
    normalized = unicodedata.normalize("NFC", cluster)
    _validate_cluster(normalized)
    return normalized


def _direction(cluster: str) -> str:
    values = [unicodedata.bidirectional(char) for char in cluster]
    return "rtl" if any(value in {"R", "AL", "RLE", "RLO", "RLI"} for value in values) else "ltr"


def _script_hint(cluster: str) -> str:
    names = " ".join(unicodedata.name(char, "") for char in cluster)
    if any(token in names for token in ("ARABIC", "HEBREW")):
        return "joining_or_rtl"
    if any(token in names for token in ("HIRAGANA", "KATAKANA", "CJK UNIFIED", "IDEOGRAPH")):
        return "cjk_or_kana"
    if any(token in names for token in ("EMOJI", "FACE", "CAT", "ROBOT", "HEART", "WOMAN", "MAN")) or any(
        0x1F000 <= ord(char) <= 0x1FAFF for char in cluster
    ) or "\u200d" in cluster:
        return "emoji_or_symbol"
    return "other"


def _width(cluster: str, ambiguous_width: int | None) -> int | None:
    east_asian = {unicodedata.east_asian_width(char) for char in cluster}
    if "A" in east_asian and ambiguous_width is None:
        return None
    measured = wcswidth(cluster)
    if measured < 0:
        return None
    if "A" in east_asian and ambiguous_width is not None:
        measured += sum(
            (ambiguous_width - 1)
            for char in cluster
            if unicodedata.east_asian_width(char) == "A" and unicodedata.combining(char) == 0
        )
    return int(measured)


def inspect_row(
    row: int,
    text: str,
    *,
    ambiguous_width: int | None = None,
    visual_start: float = 0.0,
    confidence: float = 1.0,
    alternatives: Iterable[str] = (),
) -> list[GraphemeRecord]:
    """Build logical evidence; visual positions never rewrite ``text`` order."""
    records: list[GraphemeRecord] = []
    cursor = float(visual_start)
    for cluster in segment_graphemes(text):
        nfc = normalize_cluster(cluster)
        width = _width(nfc, ambiguous_width)
        hint = _script_hint(nfc)
        shaping_required = hint in {"joining_or_rtl", "cjk_or_kana", "emoji_or_symbol"} or len(nfc) > 1
        status = "candidate" if width is not None and confidence >= 0.85 else "unknown"
        record = GraphemeRecord(
            row=row,
            visual_start=cursor,
            visual_end=cursor + width if width is not None else cursor,
            text=cluster,
            nfc=nfc,
            codepoints=tuple(f"U+{ord(char):04X}" for char in cluster),
            grapheme_width=width,
            east_asian_width=tuple(unicodedata.east_asian_width(char) for char in nfc),
            direction=_direction(nfc),
            script_hint=hint,
            shaping_required=shaping_required,
            alternatives=tuple(alternatives),
            confidence=confidence,
            status=status,
        )
        records.append(record)
        cursor = record.visual_end
    return records


def require_shaping_profile(records: Iterable[GraphemeRecord], shaper: str | None) -> None:
    if any(record.shaping_required for record in records) and not shaper:
        raise UnicodeRunError("script-aware shaping profile is required for this grapheme run")


def records_json(records: Iterable[GraphemeRecord]) -> str:
    return json.dumps([asdict(record) for record in records], ensure_ascii=False, indent=2) + "\n"


def records_hash(records: Iterable[GraphemeRecord]) -> str:
    return sha256_bytes(records_json(records).encode("utf-8"))
