"""Neutral input normalization for the deterministic Garden command core.

This module does not own gameplay state.  Each modality supplies a resolved
UI intent, and the adapter translates it into the one canonical command type
consumed by :mod:`lateletter.garden.world.commands`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping

from .world.commands import (
    CommandKind,
    GardenCommand,
    command,
    validate_command,
)
from .world.model import canonical_json_bytes


class InputModality(StrEnum):
    TOUCH = "touch"
    MOUSE = "mouse"
    BROWSER_KEYBOARD = "browser_keyboard"
    TERMINAL = "terminal"


_INTENT_FIELDS: Mapping[InputModality, str] = {
    InputModality.TOUCH: "control",
    InputModality.MOUSE: "control",
    InputModality.BROWSER_KEYBOARD: "binding",
    InputModality.TERMINAL: "command",
}


class InputNormalizationError(ValueError):
    """Raised when a raw UI intent cannot become a valid Garden command."""


@dataclass(frozen=True)
class InputEnvelope:
    """A modality-specific raw intent plus non-semantic diagnostics.

    ``metadata`` may contain coordinates, device details, raw key names, or
    terminal menu tokens.  It is intentionally excluded from command
    construction and semantic serialization.
    """

    modality: InputModality | str
    world_id: str
    sequence: int
    raw: Mapping[str, Any]
    metadata: Mapping[str, Any] = field(default_factory=dict)


def normalize_input(value: InputEnvelope) -> GardenCommand:
    """Normalize one resolved raw intent into a validated canonical command."""

    try:
        modality = InputModality(value.modality)
    except ValueError as exc:
        raise InputNormalizationError(
            f"unsupported input modality: {value.modality}"
        ) from exc

    intent_field = _INTENT_FIELDS[modality]
    raw_kind = value.raw.get(intent_field)
    if raw_kind is None:
        raise InputNormalizationError(
            f"{modality.value} intent requires {intent_field}"
        )

    try:
        kind = CommandKind(str(raw_kind))
    except ValueError as exc:
        raise InputNormalizationError(f"unknown garden action: {raw_kind}") from exc

    target = value.raw.get("target_id")
    target_id = str(target) if target is not None else None
    raw_args = value.raw.get("args", {})
    if not isinstance(raw_args, Mapping):
        raise InputNormalizationError("args must be a mapping")

    normalized = command(
        value.world_id,
        value.sequence,
        kind,
        target_id=target_id,
        args=dict(raw_args),
    )
    errors = validate_command(normalized)
    if errors:
        raise InputNormalizationError("; ".join(errors))
    return normalized


def semantic_payload(value: GardenCommand) -> dict[str, Any]:
    """Return the complete modality-free command payload."""

    return {
        "command_id": value.command_id,
        "sequence": value.sequence,
        "kind": value.kind.value,
        "target_id": value.target_id,
        "args": dict(value.args),
    }


def semantic_bytes(value: GardenCommand) -> bytes:
    """Return canonical bytes used for cross-runtime conformance checks."""

    return canonical_json_bytes(semantic_payload(value))


__all__ = [
    "InputEnvelope",
    "InputModality",
    "InputNormalizationError",
    "normalize_input",
    "semantic_bytes",
    "semantic_payload",
]
