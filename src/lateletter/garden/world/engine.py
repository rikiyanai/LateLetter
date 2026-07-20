"""Pure semantic command reducer for the internal Garden world core."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Mapping

from .commands import CommandKind, GardenCommand, validate_command
from .model import (
    AnimalState,
    CollectibleState,
    EpisodicMemory,
    FixtureState,
    JournalEntry,
    OrganNode,
    PlantState,
    TraceEntry,
    UIState,
    UndoRecord,
    Vec2,
    WorldState,
    stable_id,
)


@dataclass(frozen=True)
class CommandResult:
    accepted: bool
    changed: bool
    reason: str
    summary: str = ""
    available_actions: tuple[str, ...] = ()
    details: Mapping[str, Any] | None = None


def _reject(reason: str) -> CommandResult:
    return CommandResult(False, False, reason)


def _position(args: Mapping[str, Any]) -> Vec2:
    return Vec2(int(args["x"]), int(args["y"]))


def _inside_world(state: WorldState, position: Vec2) -> bool:
    return 0 <= position.x < state.world_width and 0 <= position.y < state.world_height


def _occupied(state: WorldState, position: Vec2, *, except_id: str | None = None) -> bool:
    positions = [
        (plant.plant_id, plant.position) for plant in state.plants
    ] + [
        (fixture.fixture_id, fixture.position) for fixture in state.fixtures
    ]
    return any(object_id != except_id and current == position for object_id, current in positions)


def _object_kind(state: WorldState, object_id: str) -> str | None:
    if any(item.plant_id == object_id for item in state.plants):
        return "plant"
    if any(item.fixture_id == object_id for item in state.fixtures):
        return "fixture"
    if any(item.animal_id == object_id for item in state.animals):
        return "animal"
    if any(item.collectible_id == object_id and not item.collected for item in state.collectibles):
        return "collectible"
    return None


def _available_actions(state: WorldState, object_id: str) -> tuple[str, ...]:
    kind = _object_kind(state, object_id)
    if kind == "plant":
        return ("inspect", "tend")
    if kind == "fixture":
        return ("inspect", "move_fixture")
    if kind == "animal":
        return ("inspect", "feed", "play")
    if kind == "collectible":
        return ("inspect", "collect")
    return ()


def _journal_entry(
    state: WorldState,
    object_id: str,
    status: str,
    label: str,
    description: str,
) -> tuple[JournalEntry, ...]:
    entry = JournalEntry(
        entry_id=stable_id("journal", state.world_id, object_id),
        object_id=object_id,
        status=status,
        label=label,
        description=description,
        discovered_at=state.effective_time,
    )
    existing = [item for item in state.journal if item.object_id != object_id]
    return tuple(existing + [entry])


def _animal_tier(points: int, counts: Mapping[str, int]) -> int:
    diversity = sum(1 for value in counts.values() if value > 0)
    if points >= 40 and diversity >= 3:
        return 3
    if points >= 20 and diversity >= 2:
        return 2
    if points >= 8:
        return 1
    return 0


def _animal_interaction(
    state: WorldState,
    animal: AnimalState,
    kind: str,
) -> AnimalState:
    session_count = animal.session_interactions.count(kind)
    base = {"observe": 1, "feed": 3, "play": 4}[kind]
    gain = max(0, base - session_count)
    counts = dict(animal.interaction_counts)
    counts[kind] = counts.get(kind, 0) + 1
    points = animal.bond_points + gain
    memory = EpisodicMemory(
        memory_id=stable_id("memory", state.world_id, animal.animal_id, kind, state.command_sequence + 1),
        kind=kind,
        target_id=None,
        timestamp=state.effective_time,
        valence=1,
        salience=max(1, gain),
    )
    energy = animal.energy
    play_appetite = animal.play_appetite
    social_appetite = animal.social_appetite
    if kind == "feed":
        energy = min(100, energy + 8)
    elif kind == "play":
        energy = max(0, energy - 5)
        play_appetite = max(0, play_appetite - 15)
    else:
        social_appetite = max(0, social_appetite - 5)
    return replace(
        animal,
        bond_points=points,
        bond_tier=_animal_tier(points, counts),
        interaction_counts=tuple(sorted(counts.items())),
        session_interactions=animal.session_interactions + (kind,),
        recent_memories=(animal.recent_memories + (memory,))[-16:],
        energy=energy,
        play_appetite=play_appetite,
        social_appetite=social_appetite,
    )


def _inspect(state: WorldState, target_id: str) -> tuple[WorldState, str, Mapping[str, Any]] | None:
    for plant in state.plants:
        if plant.plant_id == target_id:
            journal = _journal_entry(state, target_id, "observed", plant.species_id, "A living plant in the garden.")
            return replace(state, journal=journal), f"Inspected {plant.species_id}.", plant.to_dict()
    for fixture in state.fixtures:
        if fixture.fixture_id == target_id:
            journal = _journal_entry(state, target_id, "observed", fixture.catalog_id, "A fixture that can shape garden routines.")
            return replace(state, journal=journal), f"Inspected {fixture.catalog_id}.", fixture.to_dict()
    for animal in state.animals:
        if animal.animal_id == target_id:
            updated = _animal_interaction(state, animal, "observe")
            animals = tuple(updated if item.animal_id == target_id else item for item in state.animals)
            journal = _journal_entry(state, target_id, "observed", animal.species_id, f"A {animal.species_id} sharing the garden.")
            return replace(state, animals=animals, journal=journal), f"Observed {animal.species_id}.", updated.to_dict()
    for collectible in state.collectibles:
        if collectible.collectible_id == target_id and not collectible.collected:
            journal = _journal_entry(state, target_id, "observed", collectible.label, collectible.description)
            return replace(state, journal=journal), f"Observed {collectible.label}.", collectible.to_dict()
    return None


def _collect(state: WorldState, target_id: str) -> tuple[WorldState, str, Mapping[str, Any]] | None:
    found: CollectibleState | None = next(
        (item for item in state.collectibles if item.collectible_id == target_id), None,
    )
    if found is None or found.collected:
        return None
    collected = replace(found, collected=True)
    items = tuple(collected if item.collectible_id == target_id else item for item in state.collectibles)
    inventory = tuple(sorted(set(state.inventory).union({target_id})))
    journal = _journal_entry(state, target_id, "collected", found.label, found.description)
    return replace(state, collectibles=items, inventory=inventory, journal=journal), f"Collected {found.label}.", collected.to_dict()


def _finish(
    prior: WorldState,
    updated: WorldState,
    value: GardenCommand,
    summary: str,
    *,
    actions: tuple[str, ...] = (),
    details: Mapping[str, Any] | None = None,
) -> tuple[WorldState, CommandResult]:
    trace = TraceEntry(
        trace_id=stable_id("trace", prior.world_id, value.command_id),
        sequence=value.sequence,
        kind=value.kind.value,
        target_id=value.target_id,
        effective_time=prior.effective_time,
        summary=summary,
    )
    final = replace(
        updated,
        command_sequence=value.sequence,
        processed_commands=prior.processed_commands + (value.command_id,),
        event_trace=updated.event_trace + (trace,),
    )
    return final, CommandResult(True, final != prior, "", summary, actions, details)


def dispatch(state: WorldState, value: GardenCommand) -> tuple[WorldState, CommandResult]:
    """Apply one validated semantic command and return a new immutable state."""
    if value.command_id in state.processed_commands:
        return state, CommandResult(True, False, "already applied", "Command was already applied.")
    errors = validate_command(value)
    if errors:
        return state, _reject("; ".join(errors))
    if value.sequence != state.command_sequence + 1:
        return state, _reject(f"expected sequence {state.command_sequence + 1}")

    kind = value.kind
    target = value.target_id

    if kind is CommandKind.MOVE_FOCUS:
        ids = state.object_ids()
        if not ids:
            return state, _reject("world has no focusable objects")
        requested = value.args.get("target_id") or target
        if requested is not None:
            if requested not in ids:
                return state, _reject("focus target does not exist")
            focus = str(requested)
        else:
            current = ids.index(state.ui.focus_id) if state.ui.focus_id in ids else -1
            direction = str(value.args.get("direction", "next"))
            delta = -1 if direction in ("previous", "left", "up") else 1
            focus = ids[(current + delta) % len(ids)]
        updated = replace(state, ui=replace(state.ui, focus_id=focus, actions_open_for=None))
        return _finish(state, updated, value, f"Focused {focus}.", actions=_available_actions(state, focus))

    if kind is CommandKind.PAN:
        dx = int(value.args.get("dx", 0))
        dy = int(value.args.get("dy", 0))
        camera = Vec2(
            max(0, min(state.world_width - 1, state.ui.camera.x + dx)),
            max(0, min(state.world_height - 1, state.ui.camera.y + dy)),
        )
        updated = replace(state, ui=replace(state.ui, camera=camera))
        return _finish(state, updated, value, f"Panned to {camera.x},{camera.y}.")

    if kind in (CommandKind.INSPECT, CommandKind.PRIMARY_INTERACT):
        chosen = target or state.ui.focus_id
        if not chosen:
            return state, _reject("no interaction target")
        if kind is CommandKind.PRIMARY_INTERACT and _object_kind(state, chosen) == "collectible":
            outcome = _collect(state, chosen)
        else:
            outcome = _inspect(state, chosen)
        if outcome is None:
            return state, _reject("target is not available")
        updated, summary, details = outcome
        return _finish(state, updated, value, summary, actions=_available_actions(updated, chosen), details=details)

    if kind is CommandKind.OPEN_ACTIONS:
        chosen = target or state.ui.focus_id
        if not chosen or _object_kind(state, chosen) is None:
            return state, _reject("no action target")
        actions = _available_actions(state, chosen)
        updated = replace(state, ui=replace(state.ui, focus_id=chosen, actions_open_for=chosen, journal_open=False))
        return _finish(state, updated, value, f"Opened actions for {chosen}.", actions=actions)

    if kind is CommandKind.TEND:
        plant = next((item for item in state.plants if item.plant_id == target), None)
        if plant is None:
            return state, _reject("tend target is not a plant")
        care = str(value.args.get("care_action", "water"))
        gains = {"observe": 0, "water": 2, "prune": 1, "train": 2, "transplant": 1}
        if care not in gains:
            return state, _reject("unsupported care action")
        tended = replace(
            plant,
            growth_points=plant.growth_points + gains[care],
            tended_count=plant.tended_count + 1,
            last_tended_at=state.effective_time,
        )
        plants = tuple(tended if item.plant_id == target else item for item in state.plants)
        journal = _journal_entry(state, plant.plant_id, "observed", plant.species_id, f"A {plant.species_id} tended with care.")
        return _finish(state, replace(state, plants=plants, journal=journal), value, f"Used {care} on {plant.species_id}.", details=tended.to_dict())

    if kind in (CommandKind.FEED, CommandKind.PLAY):
        animal = next((item for item in state.animals if item.animal_id == target), None)
        if animal is None:
            return state, _reject(f"{kind.value} target is not an animal")
        interaction = "feed" if kind is CommandKind.FEED else "play"
        updated_animal = _animal_interaction(state, animal, interaction)
        animals = tuple(updated_animal if item.animal_id == target else item for item in state.animals)
        return _finish(state, replace(state, animals=animals), value, f"Shared {interaction} with {animal.species_id}.", details=updated_animal.to_dict())

    if kind is CommandKind.COLLECT:
        outcome = _collect(state, str(target))
        if outcome is None:
            return state, _reject("collectible is unavailable")
        updated, summary, details = outcome
        return _finish(state, updated, value, summary, details=details)

    if kind is CommandKind.PLACE:
        position = _position(value.args)
        if not _inside_world(state, position):
            return state, _reject("placement is outside the world")
        if _occupied(state, position):
            return state, _reject("placement cell is occupied")
        object_kind = str(value.args.get("object_kind", "fixture"))
        catalog = str(value.args["catalog_id"])
        object_id = str(value.args.get("object_id") or stable_id(object_kind, state.world_id, value.command_id))
        if object_id in state.object_ids():
            return state, _reject("object ID already exists")
        undo = UndoRecord(object_kind, object_id, None, None, True)
        if object_kind == "fixture":
            fixture = FixtureState(object_id, catalog, position, int(value.args.get("rotation", 0)) % 360)
            updated = replace(state, fixtures=state.fixtures + (fixture,), undo_stack=state.undo_stack + (undo,))
            details = fixture.to_dict()
        else:
            root = OrganNode(
                node_id=stable_id("organ", object_id, "root"),
                parent_id=None,
                kind="root",
                birth_time=state.effective_time,
                maturity_time=state.effective_time,
                final_direction=Vec2(0, -1),
                final_length=1,
                glyph_family="root",
            )
            plant = PlantState(object_id, catalog, position, topology=(root,))
            updated = replace(state, plants=state.plants + (plant,), undo_stack=state.undo_stack + (undo,))
            details = plant.to_dict()
        return _finish(state, updated, value, f"Placed {catalog} at {position.x},{position.y}.", details=details)

    if kind is CommandKind.MOVE_FIXTURE:
        fixture = next((item for item in state.fixtures if item.fixture_id == target), None)
        if fixture is None:
            return state, _reject("move target is not a fixture")
        position = _position(value.args)
        if not _inside_world(state, position):
            return state, _reject("move is outside the world")
        if _occupied(state, position, except_id=fixture.fixture_id):
            return state, _reject("move cell is occupied")
        moved = replace(fixture, position=position, rotation=int(value.args.get("rotation", fixture.rotation)) % 360)
        fixtures = tuple(moved if item.fixture_id == target else item for item in state.fixtures)
        undo = UndoRecord("fixture", fixture.fixture_id, fixture.position, fixture.rotation)
        updated = replace(state, fixtures=fixtures, undo_stack=state.undo_stack + (undo,))
        return _finish(state, updated, value, f"Moved {fixture.catalog_id} to {position.x},{position.y}.", details=moved.to_dict())

    if kind is CommandKind.UNDO:
        if not state.undo_stack:
            return state, _reject("nothing to undo")
        undo = state.undo_stack[-1]
        if undo.created:
            if undo.kind == "fixture":
                updated = replace(state, fixtures=tuple(item for item in state.fixtures if item.fixture_id != undo.object_id))
            else:
                updated = replace(state, plants=tuple(item for item in state.plants if item.plant_id != undo.object_id))
        elif undo.kind == "fixture" and undo.previous_position is not None:
            fixtures = tuple(
                replace(item, position=undo.previous_position, rotation=undo.previous_rotation or 0)
                if item.fixture_id == undo.object_id else item
                for item in state.fixtures
            )
            updated = replace(state, fixtures=fixtures)
        else:
            return state, _reject("undo record is invalid")
        updated = replace(updated, undo_stack=state.undo_stack[:-1])
        return _finish(state, updated, value, f"Undid {undo.kind} change for {undo.object_id}.")

    if kind is CommandKind.OPEN_JOURNAL:
        updated = replace(state, ui=replace(state.ui, journal_open=True, actions_open_for=None))
        return _finish(state, updated, value, f"Opened journal with {len(state.journal)} entries.", details={"entries": [item.to_dict() for item in state.journal]})

    if kind is CommandKind.PAUSE_MOTION:
        paused = bool(value.args.get("paused", not state.ui.motion_paused))
        updated = replace(state, ui=replace(state.ui, motion_paused=paused))
        return _finish(state, updated, value, "Motion paused." if paused else "Motion resumed.")

    if kind is CommandKind.BACK:
        ui: UIState = state.ui
        if ui.actions_open_for is not None:
            ui = replace(ui, actions_open_for=None)
            summary = "Closed actions."
        elif ui.journal_open:
            ui = replace(ui, journal_open=False)
            summary = "Closed journal."
        elif ui.focus_id is not None:
            ui = replace(ui, focus_id=None)
            summary = "Cleared focus."
        else:
            summary = "Already at the garden."
        return _finish(state, replace(state, ui=ui), value, summary)

    return state, _reject("unsupported command")
