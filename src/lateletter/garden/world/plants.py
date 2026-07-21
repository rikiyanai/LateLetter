"""Persistent, viewport-independent plant topology generation."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace

from .model import OrganNode, PlantState, Vec2, canonical_json_bytes, stable_id
from .rng import DeterministicRNG, derive_seed


@dataclass(frozen=True)
class SpeciesDefinition:
    species_id: str
    category: str
    minimum_organs: int
    maximum_organs: int
    growth_period_seconds: int
    glyph_families: tuple[str, ...]


SPECIES_CATALOG: dict[str, SpeciesDefinition] = {
    "oak": SpeciesDefinition("oak", "tree", 18, 30, 86_400, ("trunk", "branch", "broadleaf")),
    "pine": SpeciesDefinition("pine", "tree", 16, 26, 86_400, ("trunk", "conifer", "needle")),
    "willow": SpeciesDefinition("willow", "tree", 20, 32, 86_400, ("trunk", "branch", "drooping-leaf")),
    "rose": SpeciesDefinition("rose", "shrub", 10, 18, 64_800, ("stem", "thorn", "rose-bloom")),
    "hydrangea": SpeciesDefinition("hydrangea", "shrub", 12, 20, 64_800, ("stem", "broadleaf", "cluster-bloom")),
    "ivy": SpeciesDefinition("ivy", "vine", 12, 24, 43_200, ("vine", "ivy-leaf")),
    "wisteria": SpeciesDefinition("wisteria", "vine", 14, 26, 43_200, ("vine", "drooping-bloom")),
    "meadow_grass": SpeciesDefinition("meadow_grass", "grass", 8, 16, 21_600, ("blade", "seed-head")),
    "lavender": SpeciesDefinition("lavender", "herb", 9, 17, 32_400, ("stem", "narrow-leaf", "lavender-bloom")),
    "rosemary": SpeciesDefinition("rosemary", "herb", 9, 17, 32_400, ("stem", "needle-leaf", "herb-bloom")),
    "tulip": SpeciesDefinition("tulip", "flower", 6, 10, 21_600, ("stem", "tulip-leaf", "tulip-bloom")),
    "sunflower": SpeciesDefinition("sunflower", "flower", 7, 12, 32_400, ("stem", "broadleaf", "sunflower-bloom")),
    "water_lily": SpeciesDefinition("water_lily", "aquatic", 7, 13, 43_200, ("rhizome", "lily-pad", "water-bloom")),
}


def _organ_kind(definition: SpeciesDefinition, index: int, total: int) -> str:
    progress = index / max(1, total - 1)
    if definition.category in ("tree", "shrub"):
        if progress < 0.28:
            return "stem"
        if progress < 0.68:
            return "branch"
        return "bloom" if "bloom" in definition.glyph_families[-1] else "leaf"
    if definition.category == "vine":
        return "vine" if index % 3 else "leaf"
    if definition.category == "aquatic":
        return "bloom" if progress > 0.8 else "leaf"
    if progress < 0.45:
        return "stem"
    return "bloom" if progress > 0.82 else "leaf"


def generate_topology(
    world_seed: int | str | bytes,
    plant_id: str,
    species_id: str,
    *,
    planted_at: int = 0,
) -> tuple[OrganNode, ...]:
    """Generate a rooted organ graph once from separated deterministic streams."""
    definition = SPECIES_CATALOG[species_id]
    structure = DeterministicRNG(derive_seed(world_seed, "plant", plant_id, "topology", "structure"))
    timing = DeterministicRNG(derive_seed(world_seed, "plant", plant_id, "topology", "timing"))
    styling = DeterministicRNG(derive_seed(world_seed, "plant", plant_id, "topology", "style"))
    total = structure.randint(definition.minimum_organs, definition.maximum_organs)
    root_id = stable_id("organ", plant_id, "root")
    nodes: list[OrganNode] = [
        OrganNode(
            node_id=root_id,
            parent_id=None,
            kind="root",
            birth_time=planted_at,
            maturity_time=planted_at,
            final_direction=Vec2(0, -1),
            final_length=1,
            glyph_family="root",
        )
    ]
    for index in range(1, total):
        kind = _organ_kind(definition, index, total)
        if definition.category == "vine" or index < 4:
            parent_index = index - 1
        else:
            parent_index = structure.randbelow(index)
        parent = nodes[parent_index]
        direction = Vec2(structure.randint(-1, 1), -structure.randint(0, 1))
        if direction == Vec2(0, 0):
            direction = Vec2(0, -1)
        birth = planted_at + index * timing.randint(2_700, 7_200)
        maturity = birth + timing.randint(3_600, 14_400)
        glyph = styling.choice(definition.glyph_families)
        node_id = stable_id("organ", plant_id, index, kind, parent.node_id)
        nodes.append(OrganNode(
            node_id=node_id,
            parent_id=parent.node_id,
            kind=kind,
            birth_time=birth,
            maturity_time=maturity,
            final_direction=direction,
            final_length=structure.randint(1, 4),
            glyph_family=glyph,
            bloom_state="bud" if kind == "bloom" else None,
        ))
    return tuple(nodes)


def create_plant(
    world_seed: int | str | bytes,
    plant_id: str,
    species_id: str,
    position: Vec2,
    *,
    planted_at: int = 0,
) -> PlantState:
    definition = SPECIES_CATALOG[species_id]
    return PlantState(
        plant_id=plant_id,
        species_id=species_id,
        position=position,
        topology=generate_topology(world_seed, plant_id, species_id, planted_at=planted_at),
        growth_period_seconds=definition.growth_period_seconds,
    )


def validate_topology(plant: PlantState) -> tuple[str, ...]:
    errors: list[str] = []
    ids = [node.node_id for node in plant.topology]
    if len(ids) != len(set(ids)):
        errors.append("organ IDs must be unique")
    roots = [node for node in plant.topology if node.parent_id is None]
    if len(roots) != 1:
        errors.append("topology must have exactly one root")
    seen: set[str] = set()
    for node in plant.topology:
        if node.parent_id is not None and node.parent_id not in seen:
            errors.append(f"parent must precede child: {node.node_id}")
        if node.maturity_time < node.birth_time:
            errors.append(f"maturity precedes birth: {node.node_id}")
        seen.add(node.node_id)
    return tuple(errors)


def visible_organs(plant: PlantState, effective_time: int) -> tuple[OrganNode, ...]:
    return tuple(node for node in plant.topology if node.birth_time <= effective_time)


def advance_topology(
    plant: PlantState,
    effective_time: int,
    milestones: int,
) -> PlantState:
    """Persistently reveal a bounded number of the next authored organs.

    Topology is generated once, but care and absence must change more than a
    counter.  Advancing the next unborn nodes preserves the rooted graph and
    deterministic IDs while making growth visible in both renderers.
    """
    remaining = max(0, int(milestones))
    if remaining == 0:
        return plant
    candidates = sorted(
        (node for node in plant.topology if node.birth_time > effective_time),
        key=lambda node: (node.birth_time, node.node_id),
    )[:remaining]
    selected = {node.node_id for node in candidates}
    topology = tuple(
        node if node.node_id not in selected else OrganNode(
            node_id=node.node_id,
            parent_id=node.parent_id,
            kind=node.kind,
            birth_time=effective_time,
            maturity_time=max(effective_time, min(node.maturity_time, effective_time + 3_600)),
            final_direction=node.final_direction,
            final_length=node.final_length,
            glyph_family=node.glyph_family,
            bloom_state=node.bloom_state,
        )
        for node in plant.topology
    )
    return PlantState(
        plant_id=plant.plant_id,
        species_id=plant.species_id,
        position=plant.position,
        topology=topology,
        growth_points=plant.growth_points,
        tended_count=plant.tended_count,
        last_tended_at=plant.last_tended_at,
        growth_period_seconds=plant.growth_period_seconds,
        dormant=plant.dormant,
    )


def care_for_plant(
    plant: PlantState,
    effective_time: int,
    care_action: str,
) -> PlantState:
    """Apply one humane, persistent shaping action to an existing topology.

    Care never destroys an organ or changes its identity/parent. Pruning marks a
    mature terminal organ as shaped, training changes one future organ's final
    direction, watering reveals bounded growth, and rest only pauses automatic
    growth until the next active care action.
    """
    care = str(care_action)
    if care not in {"observe", "water", "prune", "train", "rest"}:
        raise ValueError(f"unsupported care action {care}")
    if care == "observe":
        return plant
    topology = plant.topology
    dormant = care == "rest"
    growth_gain = 0
    if care == "water":
        growth_gain = 2
        dormant = False
        topology = advance_topology(plant, effective_time, growth_gain).topology
    elif care == "prune":
        candidates = sorted(
            (
                node for node in topology
                if node.birth_time <= effective_time and node.kind in {"leaf", "bloom", "branch", "vine"}
            ),
            key=lambda node: (node.birth_time, node.node_id),
        )
        if candidates:
            chosen = candidates[-1]
            topology = tuple(
                replace(node, glyph_family=f"shaped-{node.glyph_family}")
                if node.node_id == chosen.node_id and not node.glyph_family.startswith("shaped-")
                else node
                for node in topology
            )
        growth_gain = 1
        dormant = False
    elif care == "train":
        candidates = sorted(
            (node for node in topology if node.parent_id is not None),
            key=lambda node: (node.birth_time, node.node_id),
        )
        if candidates:
            chosen = candidates[min(len(candidates) - 1, plant.tended_count % len(candidates))]
            direction_x = 1 if plant.tended_count % 2 == 0 else -1
            topology = tuple(
                replace(node, final_direction=Vec2(direction_x, -1))
                if node.node_id == chosen.node_id else node
                for node in topology
            )
        growth_gain = 2
        dormant = False
    return replace(
        plant,
        topology=topology,
        growth_points=plant.growth_points + growth_gain,
        tended_count=plant.tended_count + 1,
        last_tended_at=effective_time,
        dormant=dormant,
    )


def age_visibility_hash(plant: PlantState, effective_time: int) -> str:
    """Hash semantic visibility and quantized maturation, not rendered glyphs."""
    visible = []
    for node in sorted(
        visible_organs(plant, effective_time), key=lambda item: item.node_id,
    ):
        duration = max(1, node.maturity_time - node.birth_time)
        maturity = max(0, min(1_000, ((effective_time - node.birth_time) * 1_000) // duration))
        visible.append([node.node_id, maturity, node.bloom_state])
    return hashlib.sha256(canonical_json_bytes(visible)).hexdigest()
