"""Validated inner schema for encrypted author-directed garden programs.

This module deliberately knows nothing about bundle encryption.  It accepts the
already-decrypted JSON object, rejects executable or ambiguous input, and emits
immutable value objects for the deterministic evaluator.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import re
from typing import Any, Mapping, Sequence

from .schedule import ScheduleValidationError, parse_schedule
from .world.animals import ANIMAL_SPECIES
from .world.fixtures import FIXTURE_CATALOG
from .world.plants import SPECIES_CATALOG


PROGRAM_VERSION = 1
MAX_EVENTS = 1_000
MAX_ACTIONS_PER_EVENT = 100
MAX_CONDITION_DEPTH = 16
MAX_STRING_LENGTH = 16_384
MAX_SAFE_INTEGER = 9_007_199_254_740_991

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_TZ_RE = re.compile(r"^(?:UTC|[A-Za-z_+-]+(?:/[A-Za-z0-9_+.-]+)+)$")
_REMOTE_URL_RE = re.compile(r"(?:https?|ftp|data|javascript):", re.IGNORECASE)

SUPPORTED_FACTS = frozenset({
    "time.utc", "time.local", "date.range", "season.current",
    "visit.total", "visit.nth", "absence.days", "session.duration_seconds",
    "letter.due", "letter.read", "gift.revealed", "gift.examined",
    "event.completed", "animal.arrived", "animal.bond_tier",
    "animal.interaction", "animal.memory", "plant.growth_stage",
    "plant.bloom", "fixture.present", "probability.seeded",
})
SUPPORTED_OPERATORS = frozenset({
    "==", "!=", ">", ">=", "<", "<=", "contains", "not_contains",
    "in", "not_in", "exists",
})

SUPPORTED_ACTIONS = frozenset({
    "letter.present",
    "entity.reveal", "entity.place", "entity.move", "entity.transform",
    "entity.retire",
    "animal.arrive", "animal.depart", "animal.behave", "animal.routine",
    "animal.set_destination", "animal.deliver", "animal.present_gift",
    "plant.plant", "plant.grow", "plant.bloom", "plant.dormancy",
    "plant.prune", "plant.revive",
    "scene.set",
    "narrative.show",
    "variable.set", "variable.increment",
    "event.complete",
})

_TOP_LEVEL_KEYS = frozenset({
    "version", "evaluator_version", "world_state_version", "atlas_version",
    "astronomy_catalog_version", "author_timezone", "variables", "entities",
    "animals", "events",
})
_EVENT_KEYS = frozenset({
    "id", "conditions", "schedule", "occurrence", "priority",
    "exclusive_group", "cooldown", "actions",
})
_LEAF_KEYS = frozenset({"fact", "op", "value", "ref"})
_ACTION_KEYS = frozenset({"type", "target", "params"})
_ENTITY_KEYS = frozenset({
    "id", "kind", "catalog_id", "asset_id", "initial_state", "position",
    "placement", "properties", "tags",
})
_ANIMAL_KEYS = frozenset({
    "id", "species", "catalog_id", "name", "personality", "routine",
    "favorite_places", "prohibited_behaviors", "gifts", "milestones",
    "initial_state",
})
_SCHEDULE_KEYS = frozenset({
    "start", "timezone", "recurrence", "exceptions", "missed",
})
_COOLDOWN_KEYS = frozenset({"duration_seconds", "visits"})

_ACTION_PARAMS: dict[str, frozenset[str]] = {
    "letter.present": frozenset({"letter_id"}),
    "entity.reveal": frozenset({"position", "state"}),
    "entity.place": frozenset({"position"}),
    "entity.move": frozenset({"position"}),
    "entity.transform": frozenset({"state", "asset_id"}),
    "entity.retire": frozenset(),
    "animal.arrive": frozenset({"position", "routine"}),
    "animal.depart": frozenset(),
    "animal.behave": frozenset({"behavior", "duration_ticks"}),
    "animal.routine": frozenset({"routine"}),
    "animal.set_destination": frozenset({"position", "fixture_id"}),
    "animal.deliver": frozenset({"entity_id"}),
    "animal.present_gift": frozenset({"gift_id"}),
    "plant.plant": frozenset({"species_id", "position", "seed"}),
    "plant.grow": frozenset({"stage", "amount"}),
    "plant.bloom": frozenset({"bloom_id"}),
    "plant.dormancy": frozenset({"dormant"}),
    "plant.prune": frozenset({"node_ids"}),
    "plant.revive": frozenset(),
    "scene.set": frozenset({"weather", "palette", "story_time", "sky_mode",
                             "ambience", "population"}),
    "narrative.show": frozenset({"kind", "text", "label"}),
    "variable.set": frozenset({"name", "value"}),
    "variable.increment": frozenset({"name", "amount"}),
    "event.complete": frozenset({"event_id"}),
}

_REQUIRED_ACTION_PARAMS: dict[str, tuple[frozenset[str], ...]] = {
    "letter.present": (frozenset({"letter_id"}),),
    "entity.place": (frozenset({"position"}),),
    "entity.move": (frozenset({"position"}),),
    "animal.behave": (frozenset({"behavior"}),),
    "animal.routine": (frozenset({"routine"}),),
    "animal.set_destination": (frozenset({"position"}), frozenset({"fixture_id"})),
    "animal.deliver": (frozenset({"entity_id"}),),
    "animal.present_gift": (frozenset({"gift_id"}),),
    "plant.plant": (frozenset({"species_id"}),),
    "plant.grow": (frozenset({"stage"}), frozenset({"amount"})),
    "plant.prune": (frozenset({"node_ids"}),),
    "narrative.show": (frozenset({"text"}),),
    "variable.set": (frozenset({"name", "value"}),),
}


class ProgramValidationError(ValueError):
    """Raised with all schema failures found in an inner program."""

    def __init__(self, errors: Sequence[str]) -> None:
        self.errors = tuple(errors)
        super().__init__("Invalid garden program: " + "; ".join(self.errors))


@dataclass(frozen=True)
class Condition:
    kind: str
    children: tuple["Condition", ...] = ()
    fact: str | None = None
    op: str | None = None
    value: Any = None
    ref: str | None = None


@dataclass(frozen=True)
class ProgramAction:
    type: str
    target: str | None
    params: Mapping[str, Any]


@dataclass(frozen=True)
class ProgramEvent:
    id: str
    conditions: Condition
    schedule: Mapping[str, Any] | None
    occurrence: str
    priority: int
    exclusive_group: str | None
    cooldown: Mapping[str, Any] | None
    actions: tuple[ProgramAction, ...]


@dataclass(frozen=True)
class GardenProgram:
    version: int
    evaluator_version: int
    world_state_version: int
    atlas_version: str
    astronomy_catalog_version: str
    author_timezone: str
    variables: Mapping[str, Any]
    entities: tuple[Mapping[str, Any], ...]
    animals: tuple[Mapping[str, Any], ...]
    events: tuple[ProgramEvent, ...]


def _safe_json(value: Any, path: str, errors: list[str], *, depth: int = 0) -> None:
    if depth > MAX_CONDITION_DEPTH + 4:
        errors.append(f"{path}: nesting is too deep")
        return
    if value is None or isinstance(value, bool):
        return
    if isinstance(value, int):
        if abs(value) > MAX_SAFE_INTEGER:
            errors.append(f"{path}: integer exceeds cross-runtime safe range")
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            errors.append(f"{path}: non-finite numbers are forbidden")
        return
    if isinstance(value, str):
        if len(value) > MAX_STRING_LENGTH:
            errors.append(f"{path}: string exceeds {MAX_STRING_LENGTH} characters")
        if any(ord(ch) < 32 and ch not in "\n\r\t" for ch in value) or "\x1b" in value:
            errors.append(f"{path}: terminal/control characters are forbidden")
        if _REMOTE_URL_RE.search(value):
            errors.append(f"{path}: remote or executable URLs are forbidden")
        return
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                errors.append(f"{path}: object keys must be strings")
                continue
            _safe_json(key, f"{path}.<key>", errors, depth=depth + 1)
            _safe_json(child, f"{path}.{key}", errors, depth=depth + 1)
        return
    if isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _safe_json(child, f"{path}[{index}]", errors, depth=depth + 1)
        return
    errors.append(f"{path}: unsupported value type {type(value).__name__}")


def _check_keys(value: Mapping[str, Any], allowed: frozenset[str], path: str,
                errors: list[str]) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        errors.append(f"{path}: unknown fields {', '.join(unknown)}")


def _valid_id(value: Any) -> bool:
    return isinstance(value, str) and bool(_ID_RE.fullmatch(value))


def _catalog_leaf(value: Any) -> str:
    return str(value or "").rsplit(".", 1)[-1]


def _parse_condition(raw: Any, path: str, errors: list[str], depth: int = 0) -> Condition:
    if depth > MAX_CONDITION_DEPTH:
        errors.append(f"{path}: condition depth exceeds {MAX_CONDITION_DEPTH}")
        return Condition("leaf", fact="event.completed", op="exists")
    if not isinstance(raw, Mapping):
        errors.append(f"{path}: condition must be an object")
        return Condition("leaf", fact="event.completed", op="exists")

    logical = [key for key in ("all", "any", "not") if key in raw]
    if logical:
        if len(logical) != 1 or len(raw) != 1:
            errors.append(f"{path}: use exactly one of all, any, or not")
        kind = logical[0]
        child_raw = raw[kind]
        if kind == "not":
            children_raw = [child_raw]
        elif isinstance(child_raw, list) and child_raw:
            children_raw = child_raw
        else:
            errors.append(f"{path}.{kind}: must be a non-empty list")
            children_raw = []
        children = tuple(
            _parse_condition(child, f"{path}.{kind}[{index}]", errors, depth + 1)
            for index, child in enumerate(children_raw)
        )
        return Condition(kind=kind, children=children)

    _check_keys(raw, _LEAF_KEYS, path, errors)
    fact = raw.get("fact")
    op = raw.get("op")
    if fact not in SUPPORTED_FACTS:
        errors.append(f"{path}.fact: unsupported fact {fact!r}")
    if op not in SUPPORTED_OPERATORS:
        errors.append(f"{path}.op: unsupported operator {op!r}")
    if op != "exists" and "value" not in raw and "ref" not in raw:
        errors.append(f"{path}: comparison needs value or ref")
    if "ref" in raw and not _valid_id(raw["ref"]):
        errors.append(f"{path}.ref: invalid stable reference")
    _safe_json(raw.get("value"), f"{path}.value", errors)
    return Condition(kind="leaf", fact=fact if isinstance(fact, str) else None,
                     op=op if isinstance(op, str) else None,
                     value=raw.get("value"), ref=raw.get("ref"))


def _parse_action(raw: Any, path: str, errors: list[str]) -> ProgramAction:
    if not isinstance(raw, Mapping):
        errors.append(f"{path}: action must be an object")
        return ProgramAction("event.complete", None, {})
    _check_keys(raw, _ACTION_KEYS, path, errors)
    action_type = raw.get("type")
    if action_type not in SUPPORTED_ACTIONS:
        errors.append(f"{path}.type: unsupported action {action_type!r}")
        action_type = "event.complete"
    target = raw.get("target")
    if target is not None and not _valid_id(target):
        errors.append(f"{path}.target: invalid stable reference")
        target = None
    params = raw.get("params", {})
    if not isinstance(params, Mapping):
        errors.append(f"{path}.params: must be an object")
        params = {}
    else:
        allowed = _ACTION_PARAMS.get(action_type, frozenset())
        unknown = sorted(set(params) - allowed)
        if unknown:
            errors.append(f"{path}.params: unknown fields {', '.join(unknown)}")
        _safe_json(params, f"{path}.params", errors)
        choices = _REQUIRED_ACTION_PARAMS.get(action_type)
        if choices and not any(required <= set(params) for required in choices):
            rendered = " or ".join("+".join(sorted(required)) for required in choices)
            errors.append(f"{path}.params: requires {rendered}")

    if action_type in {"variable.set", "variable.increment"}:
        if not _valid_id(params.get("name")):
            errors.append(f"{path}.params.name: invalid variable name")
    if action_type == "variable.increment":
        amount = params.get("amount", 1)
        if isinstance(amount, bool) or not isinstance(amount, (int, float)):
            errors.append(f"{path}.params.amount: must be numeric")
    if action_type == "scene.set" and not params:
        errors.append(f"{path}.params: scene.set requires at least one scene field")
    if action_type == "animal.behave" and (
        not isinstance(params.get("behavior"), str) or not params.get("behavior")
    ):
        errors.append(f"{path}.params.behavior: must be non-empty text")
    if action_type == "plant.prune" and not isinstance(params.get("node_ids"), list):
        errors.append(f"{path}.params.node_ids: must be a list")
    for name in ("letter_id", "event_id", "fixture_id", "entity_id", "gift_id"):
        if name in params and not _valid_id(params[name]):
            errors.append(f"{path}.params.{name}: invalid stable reference")
    if action_type.startswith(("entity.", "animal.", "plant.")) and target is None:
        errors.append(f"{path}.target: required for {action_type}")

    return ProgramAction(type=action_type, target=target, params=dict(params))


def parse_program(raw: Mapping[str, Any]) -> GardenProgram:
    """Parse and strictly validate a decrypted ``garden_program`` payload."""
    errors: list[str] = []
    if not isinstance(raw, Mapping):
        raise ProgramValidationError(("$: program must be an object",))
    _check_keys(raw, _TOP_LEVEL_KEYS, "$", errors)
    _safe_json(raw, "$", errors)

    version = raw.get("version")
    if version != PROGRAM_VERSION:
        errors.append(f"$.version: expected {PROGRAM_VERSION}")
    evaluator_version = raw.get("evaluator_version", 1)
    world_state_version = raw.get("world_state_version", 1)
    if evaluator_version != 1:
        errors.append("$.evaluator_version: expected 1")
    if world_state_version != 1:
        errors.append("$.world_state_version: expected 1")

    atlas_version = raw.get("atlas_version", "garden-atlas-1")
    astronomy_version = raw.get("astronomy_catalog_version", "bright-stars-1")
    for field_name, value in (("atlas_version", atlas_version),
                              ("astronomy_catalog_version", astronomy_version)):
        if not _valid_id(value):
            errors.append(f"$.{field_name}: invalid version identifier")

    timezone = raw.get("author_timezone")
    if not isinstance(timezone, str) or not _TZ_RE.fullmatch(timezone):
        errors.append("$.author_timezone: expected UTC or an IANA timezone name")
        timezone = "UTC"

    variables = raw.get("variables", {})
    if not isinstance(variables, Mapping):
        errors.append("$.variables: must be an object")
        variables = {}
    for name in variables:
        if not _valid_id(name):
            errors.append(f"$.variables: invalid variable name {name!r}")

    all_object_ids: set[str] = set()

    def parse_entity_list(field: str) -> tuple[Mapping[str, Any], ...]:
        values = raw.get(field, [])
        if not isinstance(values, list):
            errors.append(f"$.{field}: must be a list")
            return ()
        seen: set[str] = set()
        parsed: list[Mapping[str, Any]] = []
        for index, item in enumerate(values):
            path = f"$.{field}[{index}]"
            if not isinstance(item, Mapping):
                errors.append(f"{path}: must be an object")
                continue
            _check_keys(item, _ANIMAL_KEYS if field == "animals" else _ENTITY_KEYS,
                        path, errors)
            item_id = item.get("id")
            if not _valid_id(item_id):
                errors.append(f"{path}.id: invalid stable identifier")
            elif item_id in seen:
                errors.append(f"{path}.id: duplicate identifier {item_id}")
            else:
                seen.add(item_id)
                if item_id in all_object_ids:
                    errors.append(f"{path}.id: duplicate world identifier {item_id}")
                all_object_ids.add(item_id)
            catalog = _catalog_leaf(
                item.get("species") or item.get("catalog_id") or item.get("asset_id")
            )
            if field == "animals":
                if catalog not in ANIMAL_SPECIES:
                    errors.append(f"{path}.species: unknown runtime animal species {catalog!r}")
                if item.get("name") is not None and (
                    not isinstance(item.get("name"), str) or not item.get("name")
                ):
                    errors.append(f"{path}.name: must be non-empty text")
                personality = item.get("personality")
                if personality is not None and not isinstance(personality, (str, Mapping)):
                    errors.append(f"{path}.personality: expected prose or a trait object")
            else:
                kind = str(item.get("kind", ""))
                if kind == "fixture" and catalog not in FIXTURE_CATALOG:
                    errors.append(f"{path}: unknown runtime fixture asset {catalog!r}")
                if kind == "plant" and catalog not in SPECIES_CATALOG:
                    errors.append(f"{path}: unknown runtime plant asset {catalog!r}")
            parsed.append(dict(item))
        return tuple(parsed)

    entities = parse_entity_list("entities")
    animals = parse_entity_list("animals")

    events_raw = raw.get("events", [])
    if not isinstance(events_raw, list):
        errors.append("$.events: must be a list")
        events_raw = []
    if len(events_raw) > MAX_EVENTS:
        errors.append(f"$.events: exceeds maximum of {MAX_EVENTS}")

    events: list[ProgramEvent] = []
    event_ids: set[str] = set()
    exclusive_priorities: set[tuple[str, int]] = set()
    for index, item in enumerate(events_raw):
        path = f"$.events[{index}]"
        if not isinstance(item, Mapping):
            errors.append(f"{path}: must be an object")
            continue
        _check_keys(item, _EVENT_KEYS, path, errors)
        event_id = item.get("id")
        if not _valid_id(event_id):
            errors.append(f"{path}.id: invalid stable identifier")
            event_id = f"invalid-{index}"
        elif event_id in event_ids:
            errors.append(f"{path}.id: duplicate identifier {event_id}")
        event_ids.add(event_id)

        condition = _parse_condition(item.get("conditions", {"all": []}),
                                     f"{path}.conditions", errors)
        schedule = item.get("schedule")
        if schedule is not None and not isinstance(schedule, Mapping):
            errors.append(f"{path}.schedule: must be an object or null")
            schedule = None
        elif isinstance(schedule, Mapping):
            _check_keys(schedule, _SCHEDULE_KEYS, f"{path}.schedule", errors)
            if schedule.get("missed") not in {
                "skip", "deliver_on_next_visit", "summarize_then_current",
            }:
                errors.append(f"{path}.schedule.missed: unsupported missed-event policy")
            schedule_timezone = schedule.get("timezone")
            if not isinstance(schedule_timezone, str) or not _TZ_RE.fullmatch(schedule_timezone):
                errors.append(f"{path}.schedule.timezone: expected an IANA timezone")
            if not isinstance(schedule.get("start"), str):
                errors.append(f"{path}.schedule.start: required timestamp string")
            if not isinstance(schedule.get("exceptions", []), list):
                errors.append(f"{path}.schedule.exceptions: must be a list")
            recurrence = schedule.get("recurrence")
            if recurrence is not None and not isinstance(recurrence, Mapping):
                errors.append(f"{path}.schedule.recurrence: must be an object or null")
            try:
                parse_schedule(schedule)
            except ScheduleValidationError as exc:
                errors.extend(f"{path}.schedule{error[1:]}" if error.startswith("$")
                              else f"{path}.schedule: {error}" for error in exc.errors)
        cooldown = item.get("cooldown")
        if cooldown is not None and not isinstance(cooldown, Mapping):
            errors.append(f"{path}.cooldown: must be an object or null")
            cooldown = None
        elif isinstance(cooldown, Mapping):
            _check_keys(cooldown, _COOLDOWN_KEYS, f"{path}.cooldown", errors)
            if not cooldown:
                errors.append(f"{path}.cooldown: empty cooldown is ambiguous")
            for name in ("duration_seconds", "visits"):
                value = cooldown.get(name)
                if value is not None and (
                    isinstance(value, bool) or not isinstance(value, int)
                    or not 1 <= value <= 31_536_000
                ):
                    errors.append(f"{path}.cooldown.{name}: expected integer from 1 to 31536000")
        occurrence = item.get("occurrence", "once")
        if occurrence not in {"once", "recurring"}:
            errors.append(f"{path}.occurrence: expected once or recurring")
            occurrence = "once"
        priority = item.get("priority", 0)
        if isinstance(priority, bool) or not isinstance(priority, int) or not -1_000_000 <= priority <= 1_000_000:
            errors.append(f"{path}.priority: expected integer between -1000000 and 1000000")
            priority = 0
        group = item.get("exclusive_group")
        if group is not None and not _valid_id(group):
            errors.append(f"{path}.exclusive_group: invalid identifier")
            group = None
        if group is not None:
            key = (group, priority)
            if key in exclusive_priorities:
                errors.append(f"{path}: unresolved equal-priority exclusivity in {group}")
            exclusive_priorities.add(key)

        actions_raw = item.get("actions", [])
        if not isinstance(actions_raw, list):
            errors.append(f"{path}.actions: must be a list")
            actions_raw = []
        if len(actions_raw) > MAX_ACTIONS_PER_EVENT:
            errors.append(f"{path}.actions: exceeds maximum of {MAX_ACTIONS_PER_EVENT}")
        actions = tuple(_parse_action(action, f"{path}.actions[{action_index}]", errors)
                        for action_index, action in enumerate(actions_raw))
        for action_index, action in enumerate(actions):
            action_path = f"{path}.actions[{action_index}]"
            if action.type.startswith(("entity.", "animal.", "plant.")) and (
                action.target not in all_object_ids
            ):
                errors.append(f"{action_path}.target: unknown world object {action.target!r}")
            for param_name in ("fixture_id", "entity_id", "gift_id"):
                referenced = action.params.get(param_name)
                if referenced is not None and referenced not in all_object_ids:
                    errors.append(f"{action_path}.params.{param_name}: unknown world object {referenced!r}")
        events.append(ProgramEvent(
            id=event_id, conditions=condition,
            schedule=dict(schedule) if isinstance(schedule, Mapping) else None,
            occurrence=occurrence, priority=priority, exclusive_group=group,
            cooldown=dict(cooldown) if isinstance(cooldown, Mapping) else None,
            actions=actions,
        ))

    if errors:
        raise ProgramValidationError(errors)
    return GardenProgram(
        version=version, evaluator_version=evaluator_version,
        world_state_version=world_state_version, atlas_version=atlas_version,
        astronomy_catalog_version=astronomy_version, author_timezone=timezone,
        variables=dict(variables), entities=entities, animals=animals,
        events=tuple(events),
    )
