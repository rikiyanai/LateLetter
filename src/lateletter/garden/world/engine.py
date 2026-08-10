"""Pure semantic command reducer for the internal Garden world core."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Mapping

from .commands import CommandKind, GardenCommand, validate_command
from .fixtures import (
    fixture_active_affordances,
    layout_is_safe,
    validate_fixture_placement,
)
from .animals import ANIMAL_GIFT_CATALOG, AnimalContext, step_animals
from .fixtures import FIXTURE_CATALOG
from .plants import SPECIES_CATALOG, advance_topology, care_for_plant, create_plant
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
    PROCESSED_COMMAND_LIMIT,
    UNDO_STACK_LIMIT,
    compact_event_trace,
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


def _object_position(state: WorldState, object_id: str) -> Vec2 | None:
    """Canonical position of any focusable object, or ``None`` for an unknown id.

    Focus moving "to the right" is a question about where things STAND, and
    canonical coordinates are the only place that is defined.

    Mirrored by ``objectPosition`` in ``web/garden-world.mjs``.

    :param state: canonical world state
    :param object_id: a plant, fixture, animal or uncollected collectible id
    :returns: its position, or ``None``
    """
    for items, key in (
        (state.plants, "plant_id"), (state.fixtures, "fixture_id"),
        (state.animals, "animal_id"), (state.collectibles, "collectible_id"),
    ):
        for item in items:
            if getattr(item, key) == object_id:
                return item.position
    return None


def _spatial_focus(
    state: WorldState, ids: tuple[str, ...], origin_id: str, direction: str,
) -> str | None:
    """The nearest focusable object in one compass direction, or ``None``.

    SPATIAL FOCUS.  ``move_focus`` has always accepted ``left``, ``right``,
    ``up`` and ``down``, and always treated them as aliases for previous/next
    over id order -- so "left" and "up" were the same operation, and neither had
    anything to do with where the object was.  The destination requires keyboard
    navigation to move canonical focus spatially, and a command whose argument
    names a direction should honour it.

    Candidates are objects strictly beyond the origin on the primary axis.  The
    winner minimises, in order: distance along that axis, then distance across
    it, then object id.  The third term is what makes this deterministic rather
    than merely usually-agreeing, which matters because this engine and the
    browser implementation are held to identical output.

    ``next`` and ``previous`` keep their ring behaviour: they are what ``[``,
    ``]`` and the terminal's cycle command mean, and a ring is the correct model
    for "show me each thing in turn".

    Mirrored by ``spatialFocus`` in ``web/garden-world.mjs``.

    :param state: canonical world state
    :param ids: focusable ids, already sorted
    :param origin_id: the id currently focused
    :param direction: one of ``left``, ``right``, ``up``, ``down``
    :returns: the id to focus, or ``None`` when nothing lies that way
    """
    origin = _object_position(state, origin_id)
    if origin is None:
        return None
    # Screen axes: x grows right, y grows down into the scene.
    axis = 0 if direction in ("left", "right") else 1
    sign = 1 if direction in ("right", "down") else -1
    best: str | None = None
    best_key: tuple[int, int, str] | None = None
    for candidate in ids:
        if candidate == origin_id:
            continue
        position = _object_position(state, candidate)
        if position is None:
            continue
        coordinates = (position.x, position.y)
        anchor = (origin.x, origin.y)
        along = (coordinates[axis] - anchor[axis]) * sign
        if along <= 0:
            continue
        across = abs(coordinates[1 - axis] - anchor[1 - axis])
        key = (along, across, candidate)
        if best_key is None or key < best_key:
            best, best_key = candidate, key
    return best


def _object_kind(state: WorldState, object_id: str) -> str | None:
    if any(item.plant_id == object_id for item in state.plants):
        return "plant"
    if any(item.fixture_id == object_id for item in state.fixtures):
        return "fixture"
    if any(item.animal_id == object_id for item in state.animals):
        return "animal"
    if any(item.collectible_id == object_id for item in state.collectibles):
        return "collectible"
    return None


def _available_actions(state: WorldState, object_id: str) -> tuple[str, ...]:
    kind = _object_kind(state, object_id)
    if kind == "plant":
        return ("inspect", "observe", "water", "prune", "train", "transplant", "rest")
    if kind == "fixture":
        fixture = next(item for item in state.fixtures if item.fixture_id == object_id)
        definition = FIXTURE_CATALOG[fixture.catalog_id]
        return ("inspect", *definition.interaction_verbs, "move", "rotate")
    if kind == "animal":
        return ("inspect", "feed", "play")
    if kind == "collectible":
        item = next(item for item in state.collectibles if item.collectible_id == object_id)
        return ("inspect",) if item.collected else ("inspect", "collect")
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


def _with_bond_gift(
    state: WorldState,
    prior: AnimalState,
    updated: AnimalState,
) -> WorldState:
    if updated.bond_tier < 3 or prior.bond_tier >= 3:
        return state
    catalog_id, label, description = ANIMAL_GIFT_CATALOG[updated.species_id]
    collectible_id = stable_id("collectible", state.world_id, updated.animal_id, catalog_id)
    if any(item.collectible_id == collectible_id for item in state.collectibles):
        return state
    gift = CollectibleState(
        collectible_id=collectible_id,
        family="animal_trace",
        provenance="animal-given",
        label=label,
        description=description,
        position=updated.position,
    )
    journal = _journal_entry(
        state, collectible_id, "hinted", label,
        f"{updated.display_name or updated.species_id} brought something to notice.",
    )
    return replace(state, collectibles=state.collectibles + (gift,), journal=journal)


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
            next_state = replace(state, animals=animals, journal=journal)
            next_state = _with_bond_gift(next_state, animal, updated)
            return next_state, f"Observed {animal.species_id}.", updated.to_dict()
    for collectible in state.collectibles:
        if collectible.collectible_id == target_id:
            journal = _journal_entry(state, target_id, "examined", collectible.label, collectible.description)
            return replace(state, journal=journal), f"Examined {collectible.label}.", collectible.to_dict()
    return None


def activate_memorial(state: WorldState) -> WorldState:
    """Persist the canonical later-launch memorial after story completion."""
    program_state = dict(state.program_state)
    completion = program_state.get("completion", {})
    completion = completion if isinstance(completion, Mapping) else {}
    complete = bool(program_state.get("story_complete") or completion.get("story_complete"))
    if not complete:
        return state
    existing = program_state.get("memorial", {})
    existing = existing if isinstance(existing, Mapping) else {}
    program_state["memorial"] = {
        "active": True,
        "completed_at": int(existing.get("completed_at", state.effective_time)),
        "examined_gifts": sorted(
            entry.object_id for entry in state.journal if entry.status == "examined"
        ),
        "lasting": True,
    }
    return replace(state, program_state=program_state)


def _fixture_interaction(
    state: WorldState,
    fixture: FixtureState,
    requested: str | None,
) -> tuple[WorldState, str, Mapping[str, Any]] | None:
    definition = FIXTURE_CATALOG[fixture.catalog_id]
    verb = str(requested or definition.interaction_verbs[0])
    if verb not in definition.interaction_verbs:
        return None
    values = dict(fixture.authored_state)
    updated_state = state
    toggles = {"open": ("open", True), "close": ("open", False),
               "light": ("lit", True), "extinguish": ("lit", False)}
    if verb in toggles:
        key, value = toggles[verb]
        values[key] = value
    elif verb == "refill":
        values["water_level"] = 3
    elif verb == "draw_water":
        values["draw_count"] = int(values.get("draw_count", 0)) + 1
    elif verb == "turn":
        values["turned_count"] = int(values.get("turned_count", 0)) + 1
    elif verb == "fill":
        values["water_level"] = 3
        values["fill_count"] = int(values.get("fill_count", 0)) + 1
    elif verb == "water" and fixture.catalog_id == "watering_can":
        level = int(values.get("water_level", 0))
        if level <= 0:
            return None
        values["water_level"] = level - 1
        values["water_count"] = int(values.get("water_count", 0)) + 1
    elif verb in {"organize", "arrange", "gather", "water", "tend", "train", "transplant"}:
        values[f"{verb}_count"] = int(values.get(f"{verb}_count", 0)) + 1
    elif verb == "read_time":
        values["last_read_hour"] = (state.effective_time // 3_600) % 24
    elif verb == "review_inventory":
        values["last_inventory_count"] = len(state.inventory)
    elif verb in {"sit", "rest", "observe", "listen", "walk", "cross", "open", "remember", "read"}:
        values[f"{verb}_count"] = int(values.get(f"{verb}_count", 0)) + 1
    updated_fixture = replace(
        fixture,
        interaction_count=fixture.interaction_count + 1,
        last_interaction=verb,
        authored_state=values,
    )
    fixtures = tuple(
        updated_fixture if item.fixture_id == fixture.fixture_id else item
        for item in updated_state.fixtures
    )

    # Fixture verbs change their linked world subsystem, not merely a counter.
    # Tie-breaks are renderer-neutral: nearest Manhattan distance, then ID.
    plants = list(updated_state.plants)
    plant_effects = {
        "train": "train", "transplant": "train", "tend": "water",
        "water": "water", "turn": "water", "organize": "train",
    }
    care = plant_effects.get(verb)
    if care and plants:
        plant_index = min(range(len(plants)), key=lambda index: (
            abs(plants[index].position.x - fixture.position.x)
            + abs(plants[index].position.y - fixture.position.y),
            plants[index].plant_id,
        ))
        plants[plant_index] = care_for_plant(
            plants[plant_index], state.effective_time, care,
        )
        values["linked_plant_id"] = plants[plant_index].plant_id
        updated_state = replace(updated_state, plants=tuple(plants))

    program_state = dict(updated_state.program_state)
    resources = dict(program_state.get("garden_resources", {}))
    if verb in {"refill", "draw_water"}:
        resources["water_units"] = int(resources.get("water_units", 0)) + 3
    elif verb == "fill":
        available = int(resources.get("water_units", 0))
        resources["water_units"] = max(0, available - 3)
    elif verb == "water" and fixture.catalog_id == "watering_can":
        resources["watered_total"] = int(resources.get("watered_total", 0)) + 1
    elif verb == "turn":
        resources["soil_units"] = int(resources.get("soil_units", 0)) + 1
    if verb == "organize":
        resources["tools_ready"] = True
    if resources:
        program_state["garden_resources"] = resources
        updated_state = replace(updated_state, program_state=program_state)

    if verb == "gather":
        available = [
            item for item in updated_state.collectibles if not item.collected
        ]
        if available:
            found = min(available, key=lambda item: (
                abs(item.position.x - fixture.position.x)
                + abs(item.position.y - fixture.position.y),
                item.collectible_id,
            ))
            collectibles = tuple(
                replace(item, collected=True)
                if item.collectible_id == found.collectible_id else item
                for item in updated_state.collectibles
            )
            updated_state = replace(
                updated_state,
                collectibles=collectibles,
                inventory=tuple(sorted(set(updated_state.inventory).union(
                    {found.collectible_id},
                ))),
            )
            values["gathered_collectible_id"] = found.collectible_id
    elif verb == "arrange" and updated_state.inventory:
        arranged_id = sorted(updated_state.inventory)[0]
        updated_state = replace(
            updated_state,
            collectibles=tuple(
                replace(item, position=fixture.position)
                if item.collectible_id == arranged_id else item
                for item in updated_state.collectibles
            ),
        )
        values["arranged_collectible_id"] = arranged_id

    if updated_state.animals:
        animal_index = min(range(len(updated_state.animals)), key=lambda index: (
            abs(updated_state.animals[index].position.x - fixture.position.x)
            + abs(updated_state.animals[index].position.y - fixture.position.y),
            updated_state.animals[index].animal_id,
        ))
        animals = list(updated_state.animals)
        animal = animals[animal_index]
        memory = EpisodicMemory(
            memory_id=stable_id(
                "memory", state.world_id, animal.animal_id,
                "fixture", fixture.fixture_id, verb, state.command_sequence + 1,
            ),
            kind=f"fixture:{verb}",
            target_id=fixture.fixture_id,
            timestamp=state.effective_time,
            valence=1,
            salience=1,
        )
        animals[animal_index] = replace(
            animal,
            current_intent=f"fixture_{verb}",
            intent_started_at=state.effective_time,
            minimum_dwell_until=state.effective_time + 5,
            recent_memories=(animal.recent_memories + (memory,))[-16:],
        )
        updated_state = replace(updated_state, animals=tuple(animals))

    journal_verbs = {"remember", "read", "review_inventory"}
    ui = replace(
        updated_state.ui,
        focus_id=fixture.fixture_id,
        camera=fixture.position,
        journal_open=(updated_state.ui.journal_open or verb in journal_verbs),
    )
    updated_state = replace(updated_state, ui=ui)
    journal = _journal_entry(
        state,
        fixture.fixture_id,
        "observed",
        definition.semantic_name,
        f"{definition.semantic_name}: {verb.replace('_', ' ')}.",
    )
    details = updated_fixture.to_dict()
    details["inventory"] = list(updated_state.inventory)
    return (
        replace(updated_state, fixtures=fixtures, journal=journal),
        f"Used {verb.replace('_', ' ')} at {definition.semantic_name}.",
        details,
    )


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
    interrupted_animal_id: str | None = None,
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
        processed_commands=(prior.processed_commands + (value.command_id,))[
            -PROCESSED_COMMAND_LIMIT:
        ],
        event_trace=compact_event_trace(updated.event_trace + (trace,)),
        undo_stack=updated.undo_stack[-UNDO_STACK_LIMIT:],
    )
    if final.animals:
        scene = final.program_state.get("scene", {})
        scene = scene if isinstance(scene, Mapping) else {}
        hour = (final.effective_time // 3_600) % 24
        affordances = tuple(sorted({
            value
            for fixture in final.fixtures
            for value in (fixture.catalog_id, *fixture_active_affordances(fixture))
        }))
        final, _ = step_animals(final, AnimalContext(
            effective_time=final.effective_time,
            time_of_day="night" if hour < 6 or hour >= 20 else "day",
            weather=str(scene.get("weather", "calm")),
            recipient_focus_id=final.ui.focus_id,
            nearby_affordances=affordances,
            interrupted_animal_id=interrupted_animal_id,
        ))
    final = activate_memorial(final)
    return final, CommandResult(True, final != prior, "", summary, actions, details)


LIVE_TICK_SECONDS = 5
def advance_live_world(state: WorldState, elapsed_seconds: int) -> WorldState:
    """Advance the canonical dwell loop on fixed deterministic boundaries.

    The reducer is aggregation-safe: advancing 600 seconds in one call produces
    the same semantic state and fixed-boundary trace as any partition totaling
    600 seconds. Reduced motion is deliberately presentation-only; the saved
    pause flag is the canonical control that stops world time.
    """
    elapsed = max(0, int(elapsed_seconds))
    if elapsed == 0:
        return state
    observed = (
        None if state.last_observed_wall_time is None
        else state.last_observed_wall_time + elapsed
    )
    if state.ui.motion_paused:
        return replace(state, last_observed_wall_time=observed)
    start = state.effective_time
    end = start + elapsed
    plants: list[PlantState] = []
    for plant in state.plants:
        if plant.dormant:
            plants.append(plant)
            continue
        period = max(1, plant.growth_period_seconds)
        milestones = max(0, end // period - start // period)
        grown = advance_topology(plant, end, milestones) if milestones else plant
        plants.append(replace(grown, growth_points=plant.growth_points + milestones))
    current = replace(state, plants=tuple(plants))
    boundary = ((start // LIVE_TICK_SECONDS) + 1) * LIVE_TICK_SECONDS
    while boundary <= end:
        current = replace(current, effective_time=boundary)
        scene = current.program_state.get("scene", {})
        scene = scene if isinstance(scene, Mapping) else {}
        affordances = tuple(sorted({
            value
            for fixture in current.fixtures
            for value in (fixture.catalog_id, *fixture_active_affordances(fixture))
        }))
        hour = (boundary // 3_600) % 24
        current, decisions = step_animals(current, AnimalContext(
            effective_time=boundary,
            time_of_day="night" if hour < 6 or hour >= 20 else "day",
            weather=str(scene.get("weather", "calm")),
            recipient_focus_id=current.ui.focus_id,
            nearby_affordances=affordances,
        ))
        summary = ", ".join(
            f"{decision.animal_id}:{decision.intent}" for decision in decisions
        ) or "Garden time advanced."
        trace_id = stable_id("trace", current.world_id, "live-tick", boundary)
        if not any(entry.trace_id == trace_id for entry in current.event_trace):
            current = replace(current, event_trace=compact_event_trace(current.event_trace + (TraceEntry(
                trace_id=trace_id,
                sequence=current.command_sequence,
                kind="live_tick",
                target_id=None,
                effective_time=boundary,
                summary=summary,
            ),)))
        boundary += LIVE_TICK_SECONDS
    return activate_memorial(replace(
        current,
        effective_time=end,
        last_observed_wall_time=observed,
    ))


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
            if direction in ("left", "right", "up", "down"):
                # Spatial. With nothing focused there is no origin to move from,
                # so the first press enters the world at the first object rather
                # than rejecting -- the same thing `next` does, and the reader
                # gets a focus for their keypress either way.
                moved = (
                    ids[0] if current < 0
                    else _spatial_focus(state, ids, ids[current], direction)
                )
                if moved is None:
                    return state, _reject(
                        f"nothing lies {direction} of the focused object"
                    )
                focus = moved
            else:
                delta = -1 if direction == "previous" else 1
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
        chosen_kind = _object_kind(state, chosen)
        if kind is CommandKind.PRIMARY_INTERACT and chosen_kind == "collectible":
            outcome = _collect(state, chosen)
        elif kind is CommandKind.PRIMARY_INTERACT and chosen_kind == "fixture":
            fixture = next(item for item in state.fixtures if item.fixture_id == chosen)
            outcome = _fixture_interaction(
                state, fixture, value.args.get("fixture_action") or value.args.get("action"),
            )
        else:
            outcome = _inspect(state, chosen)
        if outcome is None:
            return state, _reject("target is not available")
        updated, summary, details = outcome
        return _finish(
            state, updated, value, summary,
            actions=_available_actions(updated, chosen), details=details,
            interrupted_animal_id=(chosen if chosen_kind == "animal" else None),
        )

    if kind is CommandKind.OPEN_ACTIONS:
        chosen = target or state.ui.focus_id
        if not chosen or _object_kind(state, chosen) is None:
            return state, _reject("no action target")
        actions = _available_actions(state, chosen)
        updated = replace(state, ui=replace(state.ui, focus_id=chosen, actions_open_for=chosen, journal_open=False))
        return _finish(state, updated, value, f"Opened actions for {chosen}.", actions=actions)

    if kind is CommandKind.TEND:
        plant = next((item for item in state.plants if item.plant_id == target), None)
        fixture = next((item for item in state.fixtures if item.fixture_id == target), None)
        if plant is None and fixture is None:
            return state, _reject("tend target is not a plant or tending fixture")
        care = str(value.args.get("care_action", "water"))
        supported = {"observe", "tend", "water", "prune", "train", "transplant", "rest"}
        if plant is not None and care not in supported:
            return state, _reject("unsupported care action")
        if fixture is not None:
            definition = FIXTURE_CATALOG[fixture.catalog_id]
            outcome = _fixture_interaction(state, fixture, care)
            if outcome is None:
                return state, _reject("fixture does not support that action")
            updated, summary, details = outcome
            return _finish(state, updated, value, summary, details=details)
        assert plant is not None
        if care == "transplant":
            if "x" not in value.args or "y" not in value.args:
                return state, _reject("transplant requires x and y")
            position = _position(value.args)
            if not _inside_world(state, position) or _occupied(state, position, except_id=plant.plant_id):
                return state, _reject("transplant position is unavailable")
            tended = replace(plant, position=position, tended_count=plant.tended_count + 1,
                             last_tended_at=state.effective_time, dormant=False)
            candidate_plants = tuple(
                tended if item.plant_id == target else item for item in state.plants
            )
            if not layout_is_safe(replace(state, plants=candidate_plants)):
                return state, _reject("transplant makes the world unsafe or unreachable")
            undo_stack = state.undo_stack + (UndoRecord("plant", plant.plant_id, plant.position, None),)
        else:
            tended = care_for_plant(plant, state.effective_time, care)
            undo_stack = state.undo_stack
        plants = tuple(tended if item.plant_id == target else item for item in state.plants)
        journal = _journal_entry(state, plant.plant_id, "observed", plant.species_id, f"A {plant.species_id} tended with care.")
        return _finish(state, replace(state, plants=plants, journal=journal, undo_stack=undo_stack), value, f"Used {care} on {plant.species_id}.", details=tended.to_dict())

    if kind in (CommandKind.FEED, CommandKind.PLAY):
        animal = next((item for item in state.animals if item.animal_id == target), None)
        if animal is None:
            return state, _reject(f"{kind.value} target is not an animal")
        interaction = "feed" if kind is CommandKind.FEED else "play"
        updated_animal = _animal_interaction(state, animal, interaction)
        animals = tuple(updated_animal if item.animal_id == target else item for item in state.animals)
        updated_state = _with_bond_gift(replace(state, animals=animals), animal, updated_animal)
        return _finish(
            state, updated_state, value,
            f"Shared {interaction} with {animal.species_id}.",
            details=updated_animal.to_dict(), interrupted_animal_id=animal.animal_id,
        )

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
        object_kind = str(value.args.get("object_kind", "fixture"))
        catalog = str(value.args["catalog_id"])
        object_id = str(value.args.get("object_id") or stable_id(object_kind, state.world_id, value.command_id))
        if object_id in state.object_ids():
            return state, _reject("object ID already exists")
        undo = UndoRecord(object_kind, object_id, None, None, True)
        if object_kind == "fixture":
            placement_errors = validate_fixture_placement(
                state, catalog, position, fixture_id=object_id,
            )
            if placement_errors:
                return state, _reject("; ".join(placement_errors))
            fixture = FixtureState(object_id, catalog, position, int(value.args.get("rotation", 0)) % 360)
            updated = replace(state, fixtures=state.fixtures + (fixture,), undo_stack=state.undo_stack + (undo,))
            details = fixture.to_dict()
        else:
            if catalog not in SPECIES_CATALOG:
                return state, _reject("unknown plant catalog ID")
            if _occupied(state, position):
                return state, _reject("placement cell is occupied")
            plant = create_plant(
                state.seed, object_id, catalog, position, planted_at=state.effective_time,
            )
            candidate_state = replace(state, plants=state.plants + (plant,))
            if not layout_is_safe(candidate_state):
                return state, _reject("plant placement makes the world unsafe or unreachable")
            updated = replace(state, plants=state.plants + (plant,), undo_stack=state.undo_stack + (undo,))
            details = plant.to_dict()
        return _finish(state, updated, value, f"Placed {catalog} at {position.x},{position.y}.", details=details)

    if kind is CommandKind.MOVE_FIXTURE:
        fixture = next((item for item in state.fixtures if item.fixture_id == target), None)
        plant = next((item for item in state.plants if item.plant_id == target), None)
        if fixture is None and plant is None:
            return state, _reject("move target is not a fixture or plant")
        position = _position(value.args)
        if not _inside_world(state, position):
            return state, _reject("move is outside the world")
        if plant is not None:
            if _occupied(state, position, except_id=plant.plant_id):
                return state, _reject("move position is occupied")
            moved_plant = replace(plant, position=position, dormant=False)
            plants = tuple(moved_plant if item.plant_id == target else item for item in state.plants)
            if not layout_is_safe(replace(state, plants=plants)):
                return state, _reject("plant move makes the world unsafe or unreachable")
            undo = UndoRecord("plant", plant.plant_id, plant.position, None)
            updated = replace(state, plants=plants, undo_stack=state.undo_stack + (undo,))
            return _finish(state, updated, value, f"Transplanted {plant.species_id} to {position.x},{position.y}.", details=moved_plant.to_dict())
        assert fixture is not None
        placement_errors = validate_fixture_placement(
            state,
            fixture.catalog_id,
            position,
            fixture_id=fixture.fixture_id,
            except_id=fixture.fixture_id,
        )
        if placement_errors:
            return state, _reject("; ".join(placement_errors))
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
        elif undo.kind == "plant" and undo.previous_position is not None:
            plants = tuple(
                replace(item, position=undo.previous_position)
                if item.plant_id == undo.object_id else item
                for item in state.plants
            )
            updated = replace(state, plants=plants)
        else:
            return state, _reject("undo record is invalid")
        updated = replace(updated, undo_stack=state.undo_stack[:-1])
        return _finish(state, updated, value, f"Undid {undo.kind} change for {undo.object_id}.")

    if kind is CommandKind.OPEN_JOURNAL:
        updated = replace(state, ui=replace(state.ui, journal_open=True, actions_open_for=None))
        return _finish(state, updated, value, f"Opened journal with {len(state.journal)} entries.", details={
            "entries": [item.to_dict() for item in state.journal],
            "inventory": list(state.inventory),
            "absence_summary": list(state.program_state.get("absence_summary", [])),
            "memorial": dict(state.program_state.get("memorial", {})),
        })

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
