"""Renderer-neutral Garden program evaluation and canonical world materialization."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
import json
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from .evaluator import EvaluationResult, evaluate_program
from .program import GardenProgram
from .schedule import expand_schedule, parse_schedule
from .seasons import season_for_month
from .world.animals import ANIMAL_SPECIES, create_animal
from .world.fixtures import FIXTURE_CATALOG, validate_fixture_placement
from .world.model import (
    AnimalState,
    CollectibleState,
    FixtureState,
    JournalEntry,
    Personality,
    PlantState,
    TraceEntry,
    Vec2,
    WorldState,
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


def eligible_occurrences(
    program: GardenProgram,
    *,
    last_seen_utc: datetime,
    now_utc: datetime,
) -> dict[str, str]:
    """Expand authored schedules once in the clock-owning runtime."""
    result: dict[str, str] = {}
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
    return result


def build_runtime_facts(
    world: WorldState,
    program: GardenProgram,
    *,
    now_utc: datetime,
    total_visits: int,
    absence_seconds: int,
    read_ids: set[str],
    due_letter_ids: tuple[str, ...] = (),
) -> dict[str, Any]:
    local = now_utc.astimezone(ZoneInfo(program.author_timezone))
    program_state = world.program_state
    entities = program_state.get("entities", {})
    completed = program_state.get("completed_events", [])
    examined = [entry.object_id for entry in world.journal if entry.status == "examined"]
    return {
        "time.utc": now_utc.astimezone(timezone.utc).isoformat(timespec="seconds"),
        "time.local": local.replace(tzinfo=None).isoformat(timespec="seconds"),
        "date.range": local.date().isoformat(),
        "season.current": season_for_month(local.month),
        "visit.total": total_visits,
        "visit.nth": total_visits,
        "absence.days": max(0, absence_seconds // 86_400),
        "session.duration_seconds": 0,
        "letter.due": list(due_letter_ids),
        "letter.read": sorted(read_ids),
        "gift.revealed": sorted(
            key for key, value in entities.items()
            if isinstance(value, Mapping) and value.get("revealed")
        ) if isinstance(entities, Mapping) else [],
        "gift.examined": sorted(set(examined)),
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


def _catalog(value: Any) -> str:
    raw = str(value or "")
    normalized = raw.rsplit(".", 1)[-1]
    return {"rosebush": "rose", "sapling": "oak"}.get(normalized, normalized)


def _position(value: Any) -> Vec2 | None:
    try:
        if isinstance(value, Mapping):
            return Vec2(int(value["x"]), int(value["y"]))
        if isinstance(value, (list, tuple)) and len(value) == 2:
            return Vec2(int(value[0]), int(value[1]))
    except (KeyError, TypeError, ValueError):
        return None
    return None


def _occupied(world: WorldState) -> set[Vec2]:
    return {
        item.position
        for collection in (world.plants, world.fixtures, world.animals, world.collectibles)
        for item in collection
    }


def _resolve_position(
    world: WorldState,
    target: str,
    kind: str,
    catalog_id: str,
    requested: Any,
) -> Vec2:
    candidate = _position(requested)
    if candidate is not None:
        candidate = Vec2(
            max(1, min(world.world_width - 2, candidate.x)),
            max(1, min(world.world_height - 2, candidate.y)),
        )
        if kind != "fixture" or not validate_fixture_placement(
            world, catalog_id, candidate, fixture_id=target, except_id=target,
        ):
            return candidate
    occupied = _occupied(world)
    rng = DeterministicRNG(derive_seed(world.seed, "program", target, kind, "position"))
    for _ in range(512):
        value = Vec2(
            rng.randint(2, world.world_width - 3),
            rng.randint(2, world.world_height - 3),
        )
        if value in occupied:
            continue
        if kind == "fixture" and validate_fixture_placement(
            world, catalog_id, value, fixture_id=target, except_id=target,
        ):
            continue
        return value
    raise ValueError(f"could not place authored Garden object {target}")


def _definitions(program: GardenProgram) -> dict[str, Mapping[str, Any]]:
    return {
        str(item["id"]): item
        for item in (*program.entities, *program.animals)
        if isinstance(item.get("id"), str)
    }


def _seed_program_state(world: WorldState, program: GardenProgram) -> WorldState:
    state = deepcopy(dict(world.program_state))
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
    state.setdefault("exclusive_claims", {})
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
                destination = _position(params.get("position"))
                if destination is None and params.get("fixture_id"):
                    destination = next((
                        item.position for item in world.fixtures
                        if item.fixture_id == params["fixture_id"]
                    ), None)
                if destination is not None:
                    animal = replace(animal, position=destination)
            elif effect_type in {"animal.deliver", "animal.present_gift"}:
                animal = replace(animal, choreography_lock=effect_type)
            animals.append(animal)
        world = replace(world, animals=tuple(animals))
        if effect_type in {"animal.deliver", "animal.present_gift"}:
            world = _journal(
                world, receipt=receipt, object_id=target,
                label="Authored animal moment",
                description=json.dumps(dict(params), sort_keys=True, ensure_ascii=False),
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
            for key in ("weather", "palette", "story_time", "sky_mode", "ambience", "population"):
                if key in params:
                    scene[key] = deepcopy(params[key])
            world = replace(world, program_state=program_state)
        label = str(params.get("label") or {
            "scene.set": "The Garden changed",
            "letter.present": "A letter is ready",
        }.get(effect_type, "Garden memory"))
        description = str(params.get("text") or json.dumps(
            dict(params), sort_keys=True, ensure_ascii=False,
        ))
        world = _journal(
            world, receipt=receipt, object_id=target or effect_type,
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
    world = _seed_program_state(world, program)
    receipts = set(world.milestone_receipts)
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
        return replace(current, event_trace=current.event_trace + (
            TraceEntry(
                trace_id=stable_id("trace", current.world_id, "program", receipt),
                sequence=current.command_sequence,
                kind=f"program:{effect['type']}",
                target_id=(str(effect["target"]) if effect.get("target") else None),
                effective_time=current.effective_time,
                summary=f"Applied authored Garden event {event_id}.",
            ),
        ))

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
    world = replace(world, milestone_receipts=tuple(sorted(receipts)))
    return ProgramApplyResult(world, evaluation, tuple(created), dict(eligible or {}))
