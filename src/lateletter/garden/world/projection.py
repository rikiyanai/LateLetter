"""Renderer-neutral scene and interaction projection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .animals import ANIMAL_SPECIES
from .fixtures import FIXTURE_CATALOG
from .model import Vec2, WorldState
from .plants import age_visibility_hash, visible_organs


def _visible_organ_geometry(plant, effective_time: int) -> list[dict[str, Any]]:
    visible = {node.node_id for node in visible_organs(plant, effective_time)}
    offsets: dict[str, Vec2] = {}
    records: list[dict[str, Any]] = []
    for node in plant.topology:
        if node.node_id not in visible:
            continue
        parent = offsets.get(node.parent_id, Vec2(0, 0))
        offset = Vec2(
            parent.x + node.final_direction.x * node.final_length,
            parent.y + node.final_direction.y * node.final_length,
        ) if node.parent_id is not None else Vec2(0, 0)
        offsets[node.node_id] = offset
        records.append({
            "node_id": node.node_id,
            "parent_id": node.parent_id,
            "kind": node.kind,
            "offset": offset.to_list(),
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
        }


@dataclass(frozen=True)
class SceneProjection:
    world_id: str
    effective_time: int
    camera: Vec2
    motion_paused: bool
    scene: Mapping[str, Any]
    objects: tuple[SceneObjectProjection, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "world_id": self.world_id,
            "effective_time": self.effective_time,
            "camera": self.camera.to_list(),
            "motion_paused": self.motion_paused,
            "scene": dict(self.scene),
            "objects": [item.to_dict() for item in self.objects],
        }


def project_scene(state: WorldState) -> SceneProjection:
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
                "visible_organs": _visible_organ_geometry(plant, state.effective_time),
            },
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
            definition.affordances,
            ("inspect", *definition.interaction_verbs, "move", "rotate"),
            Hotspot(fixture.position.x, fixture.position.y, definition.footprint.x, definition.footprint.y),
            {"catalog_id": fixture.catalog_id, "rotation": fixture.rotation,
             "interaction_count": fixture.interaction_count,
             "last_interaction": fixture.last_interaction,
             "interaction_verbs": list(definition.interaction_verbs),
             "connected_group": definition.connected_group,
             "connected_mask": _connected_mask(state, fixture),
             "authored_state": dict(fixture.authored_state)},
        ))
    for animal in state.animals:
        definition = ANIMAL_SPECIES[animal.species_id]
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
            },
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
            },
        ))
    return SceneProjection(
        state.world_id,
        state.effective_time,
        state.ui.camera,
        state.ui.motion_paused,
        {
            **(
                dict(state.program_state.get("scene", {})) if isinstance(
                    state.program_state.get("scene", {}), Mapping
                ) else {}
            ),
            "absence_summary": list(state.program_state.get("absence_summary", [])),
            "absence_elapsed_seconds": int(state.program_state.get("absence_elapsed_seconds", 0)),
            "memorial": dict(state.program_state.get("memorial", {})),
            "inventory": list(state.inventory),
            "journal_entry_count": len(state.journal),
        },
        tuple(sorted(objects, key=lambda item: (item.depth, item.object_id))),
    )
