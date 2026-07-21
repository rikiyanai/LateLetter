"""Renderer-neutral scene and interaction projection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .animals import ANIMAL_SPECIES
from .fixtures import FIXTURE_CATALOG
from .model import Vec2, WorldState
from .plants import age_visibility_hash, visible_organs


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
            ("inspect", "tend"),
            Hotspot(plant.position.x, plant.position.y, 1, 1),
            {
                "species_id": plant.species_id,
                "visible_organ_count": len(visible),
                "topology_hash": age_visibility_hash(plant, state.effective_time),
                "growth_points": plant.growth_points,
                "dormant": plant.dormant,
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
            definition.direct_actions,
            Hotspot(fixture.position.x, fixture.position.y, definition.footprint.x, definition.footprint.y),
            {"catalog_id": fixture.catalog_id, "rotation": fixture.rotation,
             "interaction_count": fixture.interaction_count,
             "last_interaction": fixture.last_interaction,
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
        dict(state.program_state.get("scene", {})) if isinstance(
            state.program_state.get("scene", {}), Mapping
        ) else {},
        tuple(sorted(objects, key=lambda item: (item.depth, item.object_id))),
    )
