"""Renderer-neutral Garden program evaluation and canonical world materialization."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
import json
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from .evaluator import EvaluationResult, evaluate_program
from .program import GardenProgram, SUPPORTED_FACTS
from .schedule import expand_schedule, parse_schedule
from .seasons import season_for_month
from .world.animals import ANIMAL_SPECIES, create_animal
from .world.fixtures import (
    FIXTURE_CATALOG,
    fixture_cells,
    layout_is_safe,
    validate_fixture_placement,
)
from .world.model import (
    AnimalState,
    CollectibleState,
    FixtureState,
    JournalEntry,
    MILESTONE_RECEIPT_LIMIT,
    Personality,
    PlantState,
    TraceEntry,
    Vec2,
    WorldState,
    compact_event_trace,
    compact_recent_strings,
    stable_id,
)
from .world.plants import SPECIES_CATALOG, create_plant
from .world.plants import advance_topology
from .world.rng import DeterministicRNG, derive_seed


@dataclass(frozen=True)
class ProgramApplyResult:
    world: WorldState
    evaluation: EvaluationResult
    effect_receipts: tuple[str, ...]
    eligible_occurrences: Mapping[str, str]
    missed_event_summaries: tuple[Mapping[str, Any], ...] = ()


MAX_MISSED_EVENT_SUMMARIES = 128


class EligibleOccurrences(dict[str, str]):
    """Occurrence mapping plus bounded canonical missed-event metadata."""

    def __init__(
        self,
        values: Mapping[str, str] | None = None,
        *,
        missed_event_summaries: tuple[Mapping[str, Any], ...] = (),
    ) -> None:
        super().__init__(values or {})
        self.missed_event_summaries = missed_event_summaries


def eligible_occurrences(
    program: GardenProgram,
    *,
    last_seen_utc: datetime,
    now_utc: datetime,
) -> EligibleOccurrences:
    """Expand authored schedules once in the clock-owning runtime."""
    result: dict[str, str] = {}
    summaries: list[Mapping[str, Any]] = []
    for event in program.events:
        if event.schedule is None:
            continue
        expanded = expand_schedule(
            parse_schedule(event.schedule),
            event_id=event.id,
            last_seen_utc=last_seen_utc,
            now_utc=now_utc,
        )
        if expanded.occurrences:
            result[event.id] = expanded.occurrences[-1].id
            if expanded.summarized_missed:
                summaries.append({
                    "event_id": event.id,
                    "occurrence_id": expanded.occurrences[-1].id,
                    "missed_count": min(
                        expanded.summarized_missed,
                        400,
                    ),
                    "catch_up_truncated": bool(expanded.catch_up_truncated),
                })
    summaries.sort(key=lambda item: (str(item["occurrence_id"]), str(item["event_id"])))
    return EligibleOccurrences(
        result,
        missed_event_summaries=tuple(summaries[-MAX_MISSED_EVENT_SUMMARIES:]),
    )


def build_runtime_facts(
    world: WorldState,
    program: GardenProgram,
    *,
    now_utc: datetime,
    total_visits: int,
    absence_seconds: int,
    read_ids: set[str],
    due_letter_ids: tuple[str, ...] = (),
    session_duration_seconds: int = 0,
    examined_ids: set[str] | None = None,
    interaction_facts: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the evaluator contract at a runtime transaction boundary.

    ``session_duration_seconds`` must come from the monotonic session owner,
    while ``examined_ids`` comes from the renderer-neutral examine receipt
    owner. ``interaction_facts`` is a narrow integration hook for canonical
    world adapters; unknown program facts are rejected instead of silently
    inventing renderer-local conditions.
    """
    local = now_utc.astimezone(ZoneInfo(program.author_timezone))
    program_state = world.program_state
    entities = program_state.get("entities", {})
    completed = program_state.get("completed_events", [])
    examined = {
        entry.object_id for entry in world.journal if entry.status == "examined"
    }
    examined.update(examined_ids or set())
    if (
        isinstance(session_duration_seconds, bool)
        or not isinstance(session_duration_seconds, int)
        or session_duration_seconds < 0
    ):
        raise ValueError("session_duration_seconds must be a non-negative integer")
    presented = {
        str(value) for value in program_state.get("presented_letters", [])
        if isinstance(value, str)
    }
    facts = {
        "time.utc": now_utc.astimezone(timezone.utc).isoformat(timespec="seconds"),
        "time.local": local.replace(tzinfo=None).isoformat(timespec="seconds"),
        "date.range": local.date().isoformat(),
        "season.current": season_for_month(local.month),
        "visit.total": total_visits,
        "visit.nth": total_visits,
        "absence.days": max(0, absence_seconds // 86_400),
        "session.duration_seconds": int(session_duration_seconds),
        "letter.due": sorted(set(due_letter_ids) | presented),
        "letter.read": sorted(read_ids),
        "gift.revealed": sorted(
            key for key, value in entities.items()
            if isinstance(value, Mapping) and value.get("revealed")
        ) if isinstance(entities, Mapping) else [],
        "gift.examined": sorted(examined),
        "event.completed": sorted(str(item) for item in completed),
        "animal.arrived": sorted(animal.animal_id for animal in world.animals),
        "animal.bond_tier": max((animal.bond_tier for animal in world.animals), default=0),
        "animal.interaction": sorted(
            {kind for animal in world.animals for kind, _ in animal.interaction_counts}
        ),
        "animal.memory": sorted(
            {memory.kind for animal in world.animals for memory in animal.recent_memories}
        ),
        "plant.growth_stage": max((plant.growth_points for plant in world.plants), default=0),
        "plant.bloom": sorted(
            plant.plant_id for plant in world.plants
            if any(node.bloom_state == "bloom" for node in plant.topology)
        ),
        "fixture.present": sorted(fixture.fixture_id for fixture in world.fixtures),
    }
    if interaction_facts:
        unknown = sorted(set(interaction_facts) - SUPPORTED_FACTS)
        if unknown:
            raise ValueError(
                "interaction_facts contains unsupported fact(s): " + ", ".join(unknown)
            )
        facts.update(deepcopy(dict(interaction_facts)))
    return facts


def _catalog(value: Any) -> str:
    raw = str(value or "")
    return raw.rsplit(".", 1)[-1]


def _position(value: Any) -> Vec2 | None:
    try:
        if isinstance(value, Mapping):
            return Vec2(int(value["x"]), int(value["y"]))
        if isinstance(value, (list, tuple)) and len(value) == 2:
            return Vec2(int(value[0]), int(value[1]))
    except (KeyError, TypeError, ValueError):
        return None
    return None


def _object_cells(world: WorldState, *, except_id: str | None = None) -> set[Vec2]:
    cells: set[Vec2] = set()
    for fixture in world.fixtures:
        if fixture.fixture_id != except_id:
            cells.update(fixture_cells(fixture))
    cells.update(
        plant.position for plant in world.plants if plant.plant_id != except_id
    )
    cells.update(
        animal.position for animal in world.animals if animal.animal_id != except_id
    )
    cells.update(
        item.position for item in world.collectibles
        if item.collectible_id != except_id and not item.collected
    )
    return cells


def _prospective_world(
    world: WorldState,
    *,
    target: str,
    kind: str,
    catalog_id: str,
    position: Vec2,
) -> WorldState:
    plants = tuple(item for item in world.plants if item.plant_id != target)
    fixtures = tuple(item for item in world.fixtures if item.fixture_id != target)
    animals = tuple(item for item in world.animals if item.animal_id != target)
    collectibles = tuple(
        item for item in world.collectibles if item.collectible_id != target
    )
    if kind == "fixture":
        fixtures += (FixtureState(target, catalog_id, position, authored=True),)
    elif kind == "plant":
        plants += (PlantState(target, catalog_id, position),)
    elif kind == "animal":
        animals += (AnimalState(target, catalog_id, position),)
    else:
        collectibles += (CollectibleState(
            target, "authored_keepsake", "author-authored", target,
            "An authored garden keepsake.", position, authored=True,
        ),)
    return replace(
        world,
        plants=plants,
        fixtures=fixtures,
        animals=animals,
        collectibles=collectibles,
    )


def _placement_errors(
    world: WorldState,
    target: str,
    kind: str,
    catalog_id: str,
    candidate: Vec2,
) -> tuple[str, ...]:
    if kind == "fixture":
        if catalog_id not in FIXTURE_CATALOG:
            return (f"unknown fixture catalog ID {catalog_id!r}",)
        candidate_cells = fixture_cells(FixtureState(target, catalog_id, candidate))
    else:
        candidate_cells = frozenset({candidate})
    errors: list[str] = []
    if any(
        not (0 <= cell.x < world.world_width and 0 <= cell.y < world.world_height)
        for cell in candidate_cells
    ):
        errors.append("position is outside the world")
    if candidate_cells.intersection(_object_cells(world, except_id=target)):
        errors.append("position overlaps another Garden object")
    if kind == "fixture":
        errors.extend(validate_fixture_placement(
            world, catalog_id, candidate, fixture_id=target, except_id=target,
        ))
    if errors:
        return tuple(dict.fromkeys(errors))
    prospective = _prospective_world(
        world, target=target, kind=kind, catalog_id=catalog_id,
        position=candidate,
    )
    if not layout_is_safe(prospective):
        errors.append("position makes a Garden object unreachable")
    return tuple(errors)


def _resolve_position(
    world: WorldState,
    target: str,
    kind: str,
    catalog_id: str,
    requested: Any,
) -> Vec2:
    hint: str | None = None
    if isinstance(requested, str):
        if requested not in {
            "random", "authored", "path", "near_tallest_tree",
            "near_bench", "by_edge",
        }:
            raise ValueError(
                f"invalid authored position for Garden object {target}"
            )
        hint, requested = requested, None
    candidate = _position(requested)
    if requested is not None:
        if candidate is None:
            raise ValueError(
                f"invalid authored position for Garden object {target}"
            )
        errors = _placement_errors(world, target, kind, catalog_id, candidate)
        if not errors:
            return candidate
        raise ValueError(
            f"unsafe authored position for Garden object {target}: "
            + "; ".join(errors)
        )
    anchors: list[Vec2] = []
    if hint == "near_tallest_tree" and world.plants:
        anchors = [sorted(
            world.plants,
            key=lambda item: (-len(item.topology), item.plant_id),
        )[0].position]
    elif hint == "near_bench":
        anchors = [
            item.position for item in sorted(
                world.fixtures, key=lambda item: item.fixture_id,
            ) if item.catalog_id == "bench"
        ]
    elif hint == "path":
        anchors = [
            item.position for item in sorted(
                world.fixtures, key=lambda item: item.fixture_id,
            ) if item.catalog_id in {"stepping_stone", "stepping_stones"}
        ]
    relative: list[Vec2] = []
    for anchor in anchors:
        for radius in range(1, 5):
            for dy in range(-radius, radius + 1):
                for dx in range(-radius, radius + 1):
                    if max(abs(dx), abs(dy)) == radius:
                        relative.append(Vec2(anchor.x + dx, anchor.y + dy))
    if hint == "by_edge":
        margin = 2
        relative.extend(
            Vec2(x, y)
            for y in (margin, world.world_height - margin - 1)
            for x in range(margin, world.world_width - margin)
        )
        relative.extend(
            Vec2(x, y)
            for x in (margin, world.world_width - margin - 1)
            for y in range(margin + 1, world.world_height - margin - 1)
        )
    for value in relative:
        if not _placement_errors(world, target, kind, catalog_id, value):
            return value

    rng = DeterministicRNG(derive_seed(world.seed, "program", target, kind, "position"))
    for _ in range(512):
        value = Vec2(
            rng.randint(2, world.world_width - 3),
            rng.randint(2, world.world_height - 3),
        )
        if not _placement_errors(world, target, kind, catalog_id, value):
            return value
    raise ValueError(f"could not place authored Garden object {target}")


def _destination_near_fixture(
    world: WorldState,
    *,
    animal_id: str,
    species_id: str,
    fixture: FixtureState,
) -> Vec2:
    cells = fixture_cells(fixture)
    candidates = {
        neighbor
        for cell in cells
        for neighbor in (
            Vec2(cell.x - 1, cell.y), Vec2(cell.x + 1, cell.y),
            Vec2(cell.x, cell.y - 1), Vec2(cell.x, cell.y + 1),
        )
        if neighbor not in cells
    }
    for candidate in sorted(candidates, key=lambda value: (value.y, value.x)):
        if not _placement_errors(
            world, animal_id, "animal", species_id, candidate,
        ):
            return candidate
    raise ValueError(
        f"fixture {fixture.fixture_id!r} has no safe adjacent animal destination"
    )


def _definitions(program: GardenProgram) -> dict[str, Mapping[str, Any]]:
    return {
        str(item["id"]): item
        for item in (*program.entities, *program.animals)
        if isinstance(item.get("id"), str)
    }


def seed_program_state(world: WorldState, program: GardenProgram) -> WorldState:
    # Authenticated author programs own the complete relationship-animal
    # roster. Catalog animals generated for the standalone sandbox are retired
    # before facts or effects run, while persisted state for declared animals
    # is preserved.
    authored_animal_ids = {
        str(item["id"]) for item in program.animals
        if isinstance(item.get("id"), str)
    }
    removed_sandbox_animals = any(
        animal.animal_id not in authored_animal_ids for animal in world.animals
    )
    world = replace(
        world,
        animals=tuple(
            animal for animal in world.animals
            if animal.animal_id in authored_animal_ids
        ),
    )
    state = deepcopy(dict(world.program_state))
    if removed_sandbox_animals:
        state["absence_summary"] = []
    variables = state.setdefault("variables", {})
    for name, value in program.variables.items():
        variables.setdefault(str(name), deepcopy(value))
    entities = state.setdefault("entities", {})
    for definition in (*program.entities, *program.animals):
        target = str(definition["id"])
        slot = entities.setdefault(target, {"id": target})
        initial = definition.get("initial_state", {})
        if isinstance(initial, Mapping):
            for name, value in initial.items():
                slot.setdefault(str(name), deepcopy(value))
    state.setdefault("applied_occurrences", [])
    state.pop("exclusive_claims", None)
    state.setdefault("exclusive_occurrences", [])
    return replace(world, program_state=state)


def _initial_effects(program: GardenProgram) -> tuple[dict[str, Any], ...]:
    effects: list[dict[str, Any]] = []
    for target, definition in sorted(_definitions(program).items()):
        initial = definition.get("initial_state", {})
        if not isinstance(initial, Mapping):
            continue
        kind, catalog_id = _kind(definition)
        params: dict[str, Any] = {}
        requested = definition.get("position", definition.get("placement"))
        if requested is not None:
            params["position"] = deepcopy(requested)
        effect_type = None
        if kind == "animal" and initial.get("present") is True:
            effect_type = "animal.arrive"
            if definition.get("routine") is not None:
                params["routine"] = deepcopy(definition["routine"])
        elif kind == "plant" and initial.get("planted") is True:
            effect_type = "plant.plant"
            params["species_id"] = catalog_id
        elif kind in {"fixture", "collectible"} and initial.get("revealed") is True:
            effect_type = "entity.reveal"
        if effect_type is not None:
            effect: dict[str, Any] = {
                "type": effect_type, "event_id": "program.initial", "target": target,
            }
            if params:
                effect["params"] = params
            effects.append(effect)
    return tuple(effects)


def _kind(definition: Mapping[str, Any]) -> tuple[str, str]:
    catalog_id = _catalog(
        definition.get("catalog_id") or definition.get("asset_id")
        or definition.get("species")
    )
    raw_kind = str(definition.get("kind", ""))
    if definition.get("species") or catalog_id in ANIMAL_SPECIES:
        return "animal", catalog_id
    if raw_kind == "plant" or catalog_id in SPECIES_CATALOG:
        return "plant", catalog_id
    if raw_kind == "fixture" or catalog_id in FIXTURE_CATALOG:
        return "fixture", catalog_id
    return "collectible", catalog_id or "authored_keepsake"


def _animal_with_authored_data(
    animal: AnimalState,
    definition: Mapping[str, Any],
    routine: Any = None,
) -> AnimalState:
    personality = definition.get("personality")
    personality_note = None
    if isinstance(personality, Mapping):
        animal = replace(animal, personality=Personality.from_dict(personality))
    elif isinstance(personality, str):
        personality_note = personality
    favorite_places = definition.get("favorite_places", [])
    prohibited = definition.get("prohibited_behaviors", [])
    routine_value = routine if routine is not None else definition.get("routine", [])
    preferences = tuple(sorted({str(item) for item in routine_value})) if isinstance(
        routine_value, (list, tuple, set)
    ) else ((str(routine_value),) if routine_value else ())
    return replace(
        animal,
        favorite_fixture_ids=tuple(sorted(str(item) for item in favorite_places)),
        authored_preferences=preferences,
        authored_prohibitions=tuple(sorted(str(item) for item in prohibited)),
        display_name=(str(definition["name"]) if definition.get("name") else animal.display_name),
        personality_note=personality_note or animal.personality_note,
    )


def _journal(
    world: WorldState,
    *,
    receipt: str,
    object_id: str,
    label: str,
    description: str,
    status: str = "discovered",
) -> WorldState:
    entry_id = stable_id("journal", world.world_id, receipt)
    if any(item.entry_id == entry_id for item in world.journal):
        return world
    return replace(world, journal=world.journal + (JournalEntry(
        entry_id=entry_id,
        object_id=object_id,
        status=status,
        label=label,
        description=description,
        discovered_at=world.effective_time,
    ),))


def _persist_missed_event_summaries(
    state: Mapping[str, Any],
    *,
    summaries: tuple[Mapping[str, Any], ...],
    applied_event_ids: set[str],
) -> dict[str, Any]:
    updated = deepcopy(dict(state))
    records: dict[tuple[str, str], dict[str, Any]] = {}
    existing = updated.get("missed_event_summaries", [])
    if isinstance(existing, list):
        for value in existing:
            if not isinstance(value, Mapping):
                continue
            event_id = value.get("event_id")
            occurrence_id = value.get("occurrence_id")
            missed_count = value.get("missed_count")
            if not isinstance(event_id, str) or not isinstance(occurrence_id, str):
                continue
            if isinstance(missed_count, bool) or not isinstance(missed_count, int):
                continue
            records[(event_id, occurrence_id)] = {
                "event_id": event_id,
                "occurrence_id": occurrence_id,
                "missed_count": max(0, min(400, missed_count)),
                "catch_up_truncated": bool(value.get("catch_up_truncated", False)),
            }
    for value in summaries:
        event_id = str(value["event_id"])
        if event_id not in applied_event_ids:
            continue
        occurrence_id = str(value["occurrence_id"])
        records[(event_id, occurrence_id)] = {
            "event_id": event_id,
            "occurrence_id": occurrence_id,
            "missed_count": max(0, min(400, int(value["missed_count"]))),
            "catch_up_truncated": bool(value.get("catch_up_truncated", False)),
        }
    ordered = sorted(
        records.values(),
        key=lambda value: (value["occurrence_id"], value["event_id"]),
    )[-MAX_MISSED_EVENT_SUMMARIES:]
    if ordered or "missed_event_summaries" in updated:
        updated["missed_event_summaries"] = ordered
    return updated


def _materialize_effect(
    world: WorldState,
    program: GardenProgram,
    effect: Mapping[str, Any],
    receipt: str,
) -> WorldState:
    effect_type = str(effect["type"])
    target = str(effect.get("target") or "")
    params = effect.get("params", {})
    params = params if isinstance(params, Mapping) else {}
    definitions = _definitions(program)
    definition = definitions.get(target, {})
    kind, catalog_id = _kind(definition)
    if effect_type == "entity.transform" and params.get("asset_id"):
        catalog_id = _catalog(params["asset_id"])
    requested = params.get("position", definition.get("position", definition.get("placement")))

    if effect_type == "animal.arrive":
        species = _catalog(definition.get("species") or definition.get("catalog_id") or catalog_id)
        if species in ANIMAL_SPECIES:
            animals = [item for item in world.animals if item.animal_id != target]
            animal = create_animal(
                world.seed, target, species,
                _resolve_position(world, target, "animal", species, requested),
            )
            animals.append(_animal_with_authored_data(animal, definition, params.get("routine")))
            world = replace(world, animals=tuple(animals))
    elif effect_type == "animal.depart":
        world = replace(world, animals=tuple(item for item in world.animals if item.animal_id != target))
    elif effect_type.startswith("animal."):
        animals: list[AnimalState] = []
        for animal in world.animals:
            if animal.animal_id != target:
                animals.append(animal)
                continue
            if effect_type == "animal.behave":
                behavior = str(params.get("behavior", "idle"))
                animal = replace(
                    animal,
                    current_intent=behavior,
                    intent_started_at=world.effective_time,
                    minimum_dwell_until=world.effective_time + max(0, int(params.get("duration_ticks", 0))),
                )
            elif effect_type == "animal.routine":
                animal = _animal_with_authored_data(animal, definition, params.get("routine"))
            elif effect_type == "animal.set_destination":
                if params.get("position") is not None:
                    destination = _resolve_position(
                        world, target, "animal", animal.species_id,
                        params.get("position"),
                    )
                elif params.get("fixture_id"):
                    fixture = next((
                        item for item in world.fixtures
                        if item.fixture_id == params["fixture_id"]
                    ), None)
                    if fixture is None:
                        raise ValueError(
                            f"animal destination fixture {params['fixture_id']!r} "
                            "is not present"
                        )
                    destination = _destination_near_fixture(
                        world, animal_id=target, species_id=animal.species_id,
                        fixture=fixture,
                    )
                else:
                    raise ValueError(
                        f"animal destination for {target!r} has no position or fixture"
                    )
                animal = replace(animal, position=destination)
            elif effect_type in {"animal.deliver", "animal.present_gift"}:
                animal = replace(
                    animal,
                    choreography_lock=None,
                    current_intent=effect_type,
                    intent_started_at=world.effective_time,
                    minimum_dwell_until=world.effective_time,
                )
            animals.append(animal)
        world = replace(world, animals=tuple(animals))
        if effect_type in {"animal.deliver", "animal.present_gift"}:
            reference_key = "entity_id" if effect_type == "animal.deliver" else "gift_id"
            delivered_id = params.get(reference_key)
            if isinstance(delivered_id, str) and delivered_id:
                world = _materialize_effect(
                    world,
                    program,
                    {
                        "type": "entity.reveal",
                        "event_id": effect.get("event_id", "animal.delivery"),
                        "target": delivered_id,
                        "params": {},
                    },
                    f"{receipt}:delivered-object",
                )
            world = _journal(
                world, receipt=receipt, object_id=target,
                label="Gift delivered" if effect_type == "animal.present_gift" else "Delivery complete",
                description="An authored animal delivery was completed.",
            )
    elif effect_type == "plant.plant":
        species = _catalog(params.get("species_id") or catalog_id)
        if species in SPECIES_CATALOG:
            plants = [item for item in world.plants if item.plant_id != target]
            plants.append(create_plant(
                world.seed, target, species,
                _resolve_position(world, target, "plant", species, requested),
                planted_at=world.effective_time,
            ))
            world = replace(world, plants=tuple(plants))
    elif effect_type.startswith("plant."):
        plants: list[PlantState] = []
        for plant in world.plants:
            if plant.plant_id != target:
                plants.append(plant)
                continue
            if effect_type == "plant.grow":
                amount = params.get("amount", params.get("stage", 1))
                amount = int(amount) if isinstance(amount, (int, float)) and not isinstance(amount, bool) else 1
                plant = advance_topology(plant, world.effective_time, max(0, amount))
                plant = replace(plant, growth_points=max(0, plant.growth_points + amount))
            elif effect_type == "plant.bloom":
                plant = replace(plant, topology=tuple(
                    replace(node, bloom_state="bloom") if node.kind == "bloom" else node
                    for node in plant.topology
                ))
            elif effect_type == "plant.dormancy":
                plant = replace(plant, dormant=bool(params.get("dormant", True)))
            elif effect_type == "plant.revive":
                plant = replace(plant, dormant=False)
            elif effect_type == "plant.prune":
                pruned = {str(item) for item in params.get("node_ids", [])}
                changed = True
                while changed:
                    before = len(pruned)
                    pruned.update(
                        node.node_id for node in plant.topology
                        if node.parent_id in pruned
                    )
                    changed = len(pruned) != before
                plant = replace(
                    plant,
                    topology=tuple(node for node in plant.topology if node.node_id not in pruned),
                )
            plants.append(plant)
        world = replace(world, plants=tuple(plants))
    elif effect_type.startswith("entity."):
        if effect_type == "entity.retire":
            world = replace(
                world,
                fixtures=tuple(item for item in world.fixtures if item.fixture_id != target),
                plants=tuple(item for item in world.plants if item.plant_id != target),
                collectibles=tuple(item for item in world.collectibles if item.collectible_id != target),
            )
        elif kind == "fixture" and catalog_id in FIXTURE_CATALOG:
            position = _resolve_position(world, target, kind, catalog_id, requested)
            fixtures = [item for item in world.fixtures if item.fixture_id != target]
            authored_state = params.get("state", {})
            if not isinstance(authored_state, Mapping):
                authored_state = {"value": deepcopy(authored_state)}
            fixtures.append(FixtureState(
                target, catalog_id, position, authored=True,
                authored_state=deepcopy(dict(authored_state)),
            ))
            world = replace(world, fixtures=tuple(fixtures))
        elif kind == "plant" and catalog_id in SPECIES_CATALOG:
            position = _resolve_position(world, target, kind, catalog_id, requested)
            plants = [item for item in world.plants if item.plant_id != target]
            plants.append(create_plant(world.seed, target, catalog_id, position, planted_at=world.effective_time))
            world = replace(world, plants=tuple(plants))
        else:
            position = _resolve_position(world, target, "collectible", catalog_id, requested)
            label = str(definition.get("properties", {}).get("label", target)) if isinstance(
                definition.get("properties"), Mapping
            ) else target
            description = str(params.get("state", definition.get("properties", {}).get(
                "description", "An authored garden keepsake."
            ) if isinstance(definition.get("properties"), Mapping) else "An authored garden keepsake."))
            collectibles = [item for item in world.collectibles if item.collectible_id != target]
            collectibles.append(CollectibleState(
                target, "authored_keepsake", "author-authored", label,
                description, position, authored=True,
            ))
            world = replace(world, collectibles=tuple(collectibles))
    elif effect_type in {"narrative.show", "scene.set", "letter.present"}:
        if effect_type == "scene.set":
            program_state = deepcopy(dict(world.program_state))
            scene = program_state.setdefault("scene", {})
            if not isinstance(scene, dict):
                scene = {}
                program_state["scene"] = scene
            for key in ("weather", "palette", "story_time", "sky_mode", "ambience", "population", "author_region"):
                if key in params:
                    scene[key] = deepcopy(params[key])
            world = replace(world, program_state=program_state)
        elif effect_type == "letter.present":
            letter_id = str(params["letter_id"])
            program_state = deepcopy(dict(world.program_state))
            presented = {
                str(value) for value in program_state.get("presented_letters", [])
                if isinstance(value, str)
            }
            presented.add(letter_id)
            program_state["presented_letters"] = sorted(presented)
            world = replace(world, program_state=program_state)
        label = str(params.get("label") or {
            "scene.set": "The Garden changed",
            "letter.present": "A letter is ready",
        }.get(effect_type, "Garden memory"))
        description = str(params.get("text") or json.dumps(
            dict(params), sort_keys=True, ensure_ascii=False,
        ))
        object_id = (
            str(params["letter_id"])
            if effect_type == "letter.present" else target or effect_type
        )
        world = _journal(
            world, receipt=receipt, object_id=object_id,
            label=label, description=description,
        )
    return world


def apply_program(
    world: WorldState,
    program: GardenProgram,
    *,
    facts: Mapping[str, Any],
    eligible: Mapping[str, str] | None = None,
) -> ProgramApplyResult:
    """Evaluate a program and atomically project new effects into ``WorldState``."""
    world = seed_program_state(world, program)
    prior_receipts = list(world.milestone_receipts)
    receipts = set(prior_receipts)
    created: list[str] = []

    def materialize_once(
        current: WorldState,
        effect: Mapping[str, Any],
        event_id: str,
        occurrence_id: str,
        action_index: int,
    ) -> WorldState:
        receipt = stable_id(
            "program-receipt", current.world_id, event_id,
            occurrence_id, action_index, effect,
        )
        if receipt in receipts:
            return current
        current = _materialize_effect(current, program, effect, receipt)
        receipts.add(receipt)
        created.append(receipt)
        return replace(current, event_trace=compact_event_trace(current.event_trace + (
            TraceEntry(
                trace_id=stable_id("trace", current.world_id, "program", receipt),
                sequence=current.command_sequence,
                kind=f"program:{effect['type']}",
                target_id=(str(effect["target"]) if effect.get("target") else None),
                effective_time=current.effective_time,
                summary=f"Applied authored Garden event {event_id}.",
            ),
        )))

    for index, effect in enumerate(_initial_effects(program)):
        world = materialize_once(world, effect, "program.initial", "definition", index)

    evaluation = evaluate_program(program, world.program_state, {
        "seed": world.seed,
        "facts": dict(facts),
        "eligible_occurrences": dict(eligible or {}),
    })
    occurrences = {
        str(row["event_id"]): str(row["occurrence_id"])
        for row in evaluation.trace
        if row.get("status") == "applied" and row.get("occurrence_id")
    }
    applied_event_ids = {
        str(row["event_id"])
        for row in evaluation.trace
        if row.get("status") == "applied" and row.get("event_id")
    }
    schedule_summaries = tuple(
        getattr(eligible, "missed_event_summaries", ())
    )
    evaluation = replace(
        evaluation,
        state=_persist_missed_event_summaries(
            evaluation.state,
            summaries=schedule_summaries,
            applied_event_ids=applied_event_ids,
        ),
    )
    world = replace(world, program_state=evaluation.state)
    action_indexes: dict[str, int] = {}
    for effect in evaluation.effects:
        event_id = str(effect["event_id"])
        action_index = action_indexes.get(event_id, 0)
        action_indexes[event_id] = action_index + 1
        world = materialize_once(
            world, effect, event_id,
            occurrences.get(event_id, "unscheduled"), action_index,
        )
    program_state = deepcopy(dict(world.program_state))
    program_state["milestone_receipt_total"] = max(
        len(prior_receipts), int(program_state.get("milestone_receipt_total", 0)),
    ) + len(created)
    world = replace(
        world,
        milestone_receipts=compact_recent_strings(
            (*prior_receipts, *created), MILESTONE_RECEIPT_LIMIT,
        ),
        program_state=program_state,
    )
    persisted_summaries = tuple(
        dict(value) for value in world.program_state.get("missed_event_summaries", [])
        if isinstance(value, Mapping)
    )
    return ProgramApplyResult(
        world, evaluation, tuple(created), dict(eligible or {}),
        persisted_summaries,
    )
