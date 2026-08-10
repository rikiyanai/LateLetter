"""Renderer-neutral scene and interaction projection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .animals import ANIMAL_SPECIES, animal_opportunities, animal_primary_action
from .fixtures import (
    FIXTURE_CATALOG,
    fixture_active_affordances,
    fixture_cells,
    fixture_opportunities,
    fixture_presentation_state,
)
from .model import Vec2, WorldState
from .plants import age_visibility_hash, visible_organs


PLANT_MATURITY_STAGES = (
    "emergent",
    "sprouting",
    "unfurling",
    "juvenile",
    "developing",
    "near_mature",
    "mature",
)


def _maturity_progress(node, effective_time: int) -> int:
    if node.maturity_time <= node.birth_time:
        return 1_000
    return max(0, min(
        1_000,
        ((effective_time - node.birth_time) * 1_000)
        // (node.maturity_time - node.birth_time),
    ))


def _truncate_milli(value: int) -> int:
    return (1 if value >= 0 else -1) * (abs(value) // 1_000)


def _visible_organ_geometry(plant, effective_time: int) -> list[dict[str, Any]]:
    visible = {node.node_id for node in visible_organs(plant, effective_time)}
    nodes = {node.node_id: node for node in plant.topology}
    offsets_milli: dict[str, tuple[int, int]] = {}

    def resolve(node_id: str) -> tuple[int, int]:
        if node_id in offsets_milli:
            return offsets_milli[node_id]
        node = nodes[node_id]
        if node.parent_id is None:
            offset = (0, 0)
        else:
            parent_x, parent_y = resolve(node.parent_id)
            progress = _maturity_progress(node, effective_time)
            offset = (
                parent_x + node.final_direction.x * node.final_length * progress,
                parent_y + node.final_direction.y * node.final_length * progress,
            )
        offsets_milli[node_id] = offset
        return offset

    records: list[dict[str, Any]] = []
    for node in sorted(plant.topology, key=lambda item: item.node_id):
        if node.node_id not in visible:
            continue
        progress = _maturity_progress(node, effective_time)
        stage_index = 6 if progress == 1_000 else min(5, (progress * 6) // 1_000)
        offset_milli = resolve(node.node_id)
        records.append({
            "node_id": node.node_id,
            "parent_id": node.parent_id,
            "kind": node.kind,
            "offset": [
                _truncate_milli(offset_milli[0]),
                _truncate_milli(offset_milli[1]),
            ],
            "offset_milli": list(offset_milli),
            "maturity_progress": progress,
            "maturity_stage_index": stage_index,
            "maturity_stage": PLANT_MATURITY_STAGES[stage_index],
            "glyph_family": node.glyph_family,
            "bloom_state": node.bloom_state,
        })
    return sorted(records, key=lambda item: item["node_id"])


def _connected_mask(state: WorldState, fixture) -> int:
    definition = FIXTURE_CATALOG[fixture.catalog_id]
    group = definition.connected_group
    if group is None:
        return 0
    cells = {
        (other.position.x + dx, other.position.y + dy)
        for other in state.fixtures
        if other.fixture_id != fixture.fixture_id
        and FIXTURE_CATALOG[other.catalog_id].connected_group == group
        for dy in range(FIXTURE_CATALOG[other.catalog_id].footprint.y)
        for dx in range(FIXTURE_CATALOG[other.catalog_id].footprint.x)
    }
    own = {
        (fixture.position.x + dx, fixture.position.y + dy)
        for dy in range(definition.footprint.y)
        for dx in range(definition.footprint.x)
    }
    mask = 0
    for bit, (dx, dy) in enumerate(((0, -1), (1, 0), (0, 1), (-1, 0))):
        if any((x + dx, y + dy) in cells for x, y in own):
            mask |= 1 << bit
    return mask


def _fixture_render_cells(state: WorldState, fixture) -> list[dict[str, int]]:
    definition = FIXTURE_CATALOG[fixture.catalog_id]
    own = fixture_cells(fixture)
    group = definition.connected_group
    grouped = {
        cell
        for other in state.fixtures
        if FIXTURE_CATALOG[other.catalog_id].connected_group == group
        for cell in fixture_cells(other)
    } if group else set()
    rows: list[dict[str, int]] = []
    for cell in sorted(own, key=lambda value: (value.y, value.x)):
        mask = 0
        if group:
            for bit, (dx, dy) in enumerate(((0, -1), (1, 0), (0, 1), (-1, 0))):
                if Vec2(cell.x + dx, cell.y + dy) in grouped:
                    mask |= 1 << bit
        rows.append({
            "dx": cell.x - fixture.position.x,
            "dy": cell.y - fixture.position.y,
            "connected_mask": mask,
        })
    return rows


def _personality_emphasis(personality) -> str:
    values = personality.to_dict()
    return max(sorted(values), key=lambda key: values[key])


@dataclass(frozen=True)
class Hotspot:
    x: int
    y: int
    width: int
    height: int

    def to_dict(self) -> dict[str, int]:
        return {
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
        }


@dataclass(frozen=True)
class SceneObjectProjection:
    object_id: str
    kind: str
    semantic_name: str
    position: Vec2
    depth: int
    collision: bool
    occlusion: bool
    affordances: tuple[str, ...]
    actions: tuple[str, ...]
    hotspot: Hotspot
    semantic_state: Mapping[str, Any]
    # SPEC 7.8.3.1. What a plain click, tap or Enter on this object does, and
    # what to call it on hover, on focus, and to a screen reader. `None` means
    # the object offers no one-click act; it is then reached through "more
    # actions". The renderer reads this instead of deciding for itself what a
    # bench or a lantern ought to do.
    primary_action: Mapping[str, Any] | None = None
    # SPEC 7.8.3.2. Acts that apply only in the current world state, each drawn
    # as its own control beside the object. Empty for most objects, most of the
    # time -- that is the point: an opportunity is meant to be worth noticing.
    opportunities: tuple[Mapping[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "object_id": self.object_id,
            "kind": self.kind,
            "semantic_name": self.semantic_name,
            "position": self.position.to_list(),
            "depth": self.depth,
            "collision": self.collision,
            "occlusion": self.occlusion,
            "affordances": list(self.affordances),
            "actions": list(self.actions),
            "hotspot": self.hotspot.to_dict(),
            "semantic_state": dict(self.semantic_state),
            "primary_action": None if self.primary_action is None else dict(self.primary_action),
            "opportunities": [dict(item) for item in self.opportunities],
        }


@dataclass(frozen=True)
class SceneProjection:
    world_id: str
    effective_time: int
    camera: Vec2
    motion_paused: bool
    scene: Mapping[str, Any]
    objects: tuple[SceneObjectProjection, ...]
    # Civil/observed time is deliberately separate from effective_time.
    # The latter is the pause-aware elapsed simulation clock and must never be
    # interpreted as a Unix timestamp by a renderer.
    observed_time: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "world_id": self.world_id,
            "effective_time": self.effective_time,
            "observed_time": self.observed_time,
            "camera": self.camera.to_list(),
            "motion_paused": self.motion_paused,
            "scene": dict(self.scene),
            "objects": [item.to_dict() for item in self.objects],
        }


def project_scene(state: WorldState) -> SceneProjection:
    raw_missed = state.program_state.get("missed_event_summaries", ())
    missed_event_summaries: list[str] = []
    if isinstance(raw_missed, (list, tuple)):
        for item in raw_missed[:3]:
            if isinstance(item, Mapping):
                event_id = str(item.get("event_id", "event"))
                count = max(0, int(item.get("missed_count", 0)))
                truncated = "; catch-up truncated" if item.get("catch_up_truncated") else ""
                missed_event_summaries.append(
                    f"{event_id}: {count} missed occurrence{'s' if count != 1 else ''}{truncated}."
                )
            else:
                missed_event_summaries.append(str(item))
    objects: list[SceneObjectProjection] = []
    for plant in state.plants:
        visible = visible_organs(plant, state.effective_time)
        objects.append(SceneObjectProjection(
            plant.plant_id,
            "plant",
            plant.species_id.replace("_", " "),
            plant.position,
            100,
            True,
            True,
            ("observe", "water", "prune", "train", "transplant"),
            ("inspect", "observe", "water", "prune", "train", "transplant", "rest"),
            Hotspot(plant.position.x, plant.position.y, 1, 1),
            {
                "species_id": plant.species_id,
                "visible_organ_count": len(visible),
                "topology_hash": age_visibility_hash(plant, state.effective_time),
                "growth_points": plant.growth_points,
                "dormant": plant.dormant,
                "care_state": "resting" if plant.dormant else "growing",
                "presentation_state": "dormant" if plant.dormant else (
                    "blooming" if any(node.bloom_state == "bloom" for node in visible) else "growing"
                ),
                "semantic_description": (
                    f"{plant.species_id.replace('_', ' ')} at {plant.position.x},{plant.position.y}; "
                    f"{'resting' if plant.dormant else 'growing'}, {len(visible)} visible organs."
                ),
                "visible_organs": _visible_organ_geometry(plant, state.effective_time),
            },
            primary_action={
                "command": "tend",
                "args": {"care_action": "tend"},
                "label": f"tend the {plant.species_id.replace('_', ' ')}",
            },
            opportunities=(
                ({
                    "opportunity_id": f"{plant.plant_id}:water",
                    "command": "tend",
                    "args": {"care_action": "water"},
                    "label": f"water the {plant.species_id.replace('_', ' ')}",
                },) if plant.dormant else ()
            ),
        ))
    for fixture in state.fixtures:
        definition = FIXTURE_CATALOG[fixture.catalog_id]
        objects.append(SceneObjectProjection(
            fixture.fixture_id,
            "fixture",
            definition.semantic_name,
            fixture.position,
            100,
            definition.blocks_movement,
            definition.blocks_movement,
            fixture_active_affordances(fixture),
            ("inspect", *definition.interaction_verbs, "move", "rotate"),
            Hotspot(fixture.position.x, fixture.position.y, definition.footprint.x, definition.footprint.y),
            {"catalog_id": fixture.catalog_id,
             "visual_asset_id": str(
                 fixture.authored_state.get(
                     "visual_asset_id", f"fixture.{fixture.catalog_id}",
                 )
             ),
             "rotation": fixture.rotation,
             "interaction_count": fixture.interaction_count,
             "last_interaction": fixture.last_interaction,
             "interaction_verbs": list(definition.interaction_verbs),
             "connected_group": definition.connected_group,
             "connected_mask": _connected_mask(state, fixture),
             "render_cells": _fixture_render_cells(state, fixture),
             "presentation_state": fixture_presentation_state(fixture),
             "semantic_description": (
                 f"{definition.semantic_name} at {fixture.position.x},{fixture.position.y}; "
                 f"{fixture_presentation_state(fixture)}."
             ),
             "authored_state": dict(fixture.authored_state)},
            # Both of these dispatch the SAME canonical command the action sheet
            # would have dispatched -- `primary_interact` carrying a fixture
            # verb. Nothing new is invented for the point-and-click path; only
            # the route to it is shorter.
            primary_action=(
                {
                    "command": "open_journal",
                    "args": {},
                    "label": "open the memory mailbox",
                }
                if fixture.catalog_id == "mailbox" and (state.journal or state.inventory)
                else None if definition.primary_verb is None else {
                    "command": "primary_interact",
                    "args": {"fixture_action": definition.primary_verb},
                    "label": definition.primary_label,
                }
            ),
            opportunities=tuple(
                {
                    "opportunity_id": offer["opportunity_id"],
                    "command": "primary_interact",
                    "args": {"fixture_action": offer["verb"]},
                    "label": offer["label"],
                }
                for offer in fixture_opportunities(fixture)
            ),
        ))
    for animal in state.animals:
        definition = ANIMAL_SPECIES[animal.species_id]
        raw_decisions = state.program_state.get("animal_decisions", {})
        decision = raw_decisions.get(animal.animal_id, {}) if isinstance(
            raw_decisions, Mapping
        ) else {}
        objects.append(SceneObjectProjection(
            animal.animal_id,
            "animal",
            animal.display_name or animal.species_id,
            animal.position,
            110,
            False,
            True,
            definition.fixture_affinities,
            ("inspect", "feed", "play"),
            Hotspot(animal.position.x, animal.position.y, 1, 1),
            {
                "species_id": animal.species_id,
                "high_level_state": animal.high_level_state,
                "intent": animal.current_intent,
                "bond_tier": animal.bond_tier,
                "choreography_locked": animal.choreography_lock is not None,
                "display_name": animal.display_name,
                "personality_note": animal.personality_note,
                "personality": animal.personality.to_dict(),
                "recent_memories": [memory.to_dict() for memory in animal.recent_memories],
                "routine": animal.current_intent,
                "choreography_phase": (
                    "perform" if animal.choreography_lock else
                    "recover" if animal.current_intent == "recover" else "orient"
                ),
                "presentation_variant": (
                    f"{animal.species_id}.tier{animal.bond_tier}."
                    f"{animal.current_intent}."
                    f"{'perform' if animal.choreography_lock else 'routine'}"
                ),
                "personality_emphasis": _personality_emphasis(animal.personality),
                "memory_count": len(animal.recent_memories),
                "decision_reason": str(decision.get("priority_reason", "not_yet_decided")),
                "decision_score": int(decision.get("score", 0)),
                "decision_context": {
                    "weather": str(decision.get("weather", "calm")),
                    "season": str(decision.get("season", "spring")),
                    "memory_count": int(decision.get("memory_count", 0)),
                    "moved": bool(decision.get("moved", False)),
                    "from_position": list(decision.get("from_position", animal.position.to_list())),
                    "to_position": list(decision.get("to_position", animal.position.to_list())),
                },
                "semantic_description": (
                    f"{animal.display_name or animal.species_id}, {animal.species_id}, "
                    f"bond tier {animal.bond_tier}; {animal.current_intent}; "
                    f"personality {_personality_emphasis(animal.personality)}; "
                    f"{len(animal.recent_memories)} memories; "
                    f"decision {decision.get('priority_reason', 'not_yet_decided')}."
                ),
            },
            # An animal's verb IS the canonical command -- `play` and `feed` are
            # top-level commands, unlike a fixture verb, which travels inside
            # `primary_interact`. The renderer dispatches whatever it is handed
            # either way and does not need to know the difference.
            primary_action={
                "command": animal_primary_action(animal)["verb"],
                "args": {},
                "label": animal_primary_action(animal)["label"],
            },
            opportunities=tuple(
                {
                    "opportunity_id": offer["opportunity_id"],
                    "command": offer["verb"],
                    "args": {},
                    "label": offer["label"],
                }
                for offer in animal_opportunities(animal)
            ),
        ))
    for item in state.collectibles:
        if item.collected:
            continue
        objects.append(SceneObjectProjection(
            item.collectible_id,
            "collectible",
            item.label,
            item.position,
            120,
            False,
            False,
            ("discover", "journal"),
            ("inspect", "collect"),
            Hotspot(item.position.x, item.position.y, 1, 1),
            {
                "family": item.family,
                "provenance": item.provenance,
                "authored": item.authored,
                "semantic_description": (
                    f"{item.label} at {item.position.x},{item.position.y}; "
                    f"{item.provenance}."
                ),
            },
        ))
    return SceneProjection(
        world_id=state.world_id,
        effective_time=state.effective_time,
        camera=state.ui.camera,
        motion_paused=state.ui.motion_paused,
        scene={
            **(
                dict(state.program_state.get("scene", {})) if isinstance(
                    state.program_state.get("scene", {}), Mapping
                ) else {}
            ),
            "absence_summary": list(state.program_state.get("absence_summary", [])),
            "missed_event_summaries": missed_event_summaries,
            "absence_elapsed_seconds": int(state.program_state.get("absence_elapsed_seconds", 0)),
            "memorial": dict(state.program_state.get("memorial", {})),
            "inventory": list(state.inventory),
            "journal_entry_count": len(state.journal),
            "journal_entries": [
                entry.to_dict() for entry in sorted(state.journal, key=lambda value: value.entry_id)
            ],
        },
        objects=tuple(sorted(objects, key=lambda item: (item.depth, item.object_id))),
        observed_time=state.last_observed_wall_time,
    )
