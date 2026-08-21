"""Version pins for the canonical transcription evidence IR."""

SCHEMA_VERSION = "lateletter-transcription-ir-1"
MODULE_VERSION = "lateletter-transcription/0.1.0"

# Kept explicit so an attempt can pin the tools that produced a record without
# pretending that the IR itself is a recognizer or renderer.
SUPPORTED_SCHEMA_VERSIONS = frozenset({SCHEMA_VERSION})
