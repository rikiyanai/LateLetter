"""Semantic command vocabulary shared by all future input adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping

from .model import stable_id


class CommandKind(StrEnum):
    MOVE_FOCUS = "move_focus"
    PAN = "pan"
    INSPECT = "inspect"
    PRIMARY_INTERACT = "primary_interact"
    OPEN_ACTIONS = "open_actions"
    TEND = "tend"
    FEED = "feed"
    PLAY = "play"
    COLLECT = "collect"
    PLACE = "place"
    MOVE_FIXTURE = "move_fixture"
    UNDO = "undo"
    OPEN_JOURNAL = "open_journal"
    PAUSE_MOTION = "pause_motion"
    BACK = "back"


@dataclass(frozen=True)
class GardenCommand:
    command_id: str
    sequence: int
    kind: CommandKind
    target_id: str | None = None
    args: Mapping[str, Any] = field(default_factory=dict)


def command(
    world_id: str,
    sequence: int,
    kind: CommandKind | str,
    *,
    target_id: str | None = None,
    args: Mapping[str, Any] | None = None,
) -> GardenCommand:
    parsed = CommandKind(kind)
    values = dict(args or {})
    command_id = stable_id(
        "command", world_id, int(sequence), parsed.value, target_id, values,
    )
    return GardenCommand(
        command_id=command_id,
        sequence=int(sequence),
        kind=parsed,
        target_id=target_id,
        args=values,
    )


def validate_command(value: GardenCommand) -> tuple[str, ...]:
    errors: list[str] = []
    if value.sequence < 1:
        errors.append("sequence must be positive")
    target_required = {
        CommandKind.INSPECT,
        CommandKind.TEND,
        CommandKind.FEED,
        CommandKind.PLAY,
        CommandKind.COLLECT,
        CommandKind.MOVE_FIXTURE,
    }
    if value.kind in target_required and not value.target_id:
        errors.append(f"{value.kind.value} requires target_id")
    if value.kind is CommandKind.PAN:
        if not any(key in value.args for key in ("dx", "dy")):
            errors.append("pan requires dx and/or dy")
    if value.kind is CommandKind.PLACE:
        if value.args.get("object_kind", "fixture") not in ("fixture", "plant"):
            errors.append("place object_kind must be fixture or plant")
        if "catalog_id" not in value.args:
            errors.append("place requires catalog_id")
        if "x" not in value.args or "y" not in value.args:
            errors.append("place requires x and y")
    if value.kind is CommandKind.MOVE_FIXTURE:
        if "x" not in value.args or "y" not in value.args:
            errors.append("move_fixture requires x and y")
    return tuple(errors)
