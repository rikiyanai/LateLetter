#!/usr/bin/env python3
"""Diagnostic compatibility facade for the canonical Unicode profile.

The authoritative reusable validation lives in
``lateletter.transcription.unicode_profile``.  This script intentionally has
no candidate/manifest/acceptance writer.
"""

from lateletter.transcription.unicode_profile import (  # noqa: F401
    ALLOWED_FORMAT_CHARS,
    BIDI_CONTROLS,
    GraphemeRecord,
    UnicodeRunError,
    inspect_row,
    normalize_cluster,
    records_hash,
    records_json,
    require_shaping_profile,
    segment_graphemes,
)

__all__ = [
    "ALLOWED_FORMAT_CHARS",
    "BIDI_CONTROLS",
    "GraphemeRecord",
    "UnicodeRunError",
    "inspect_row",
    "normalize_cluster",
    "records_hash",
    "records_json",
    "require_shaping_profile",
    "segment_graphemes",
]
