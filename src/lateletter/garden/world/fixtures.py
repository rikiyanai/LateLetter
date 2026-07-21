"""Functional fixture catalog, connected-tile masks, and layout safety."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, replace

from .model import FixtureState, Vec2, WorldState


@dataclass(frozen=True)
class FixtureDefinition:
    catalog_id: str
    semantic_name: str
    direct_actions: tuple[str, ...]
    affordances: tuple[str, ...]
    footprint: Vec2 = Vec2(1, 1)
    blocks_movement: bool = True
    connected_group: str | None = None


FIXTURE_CATALOG: dict[str, FixtureDefinition] = {
    "bench": FixtureDefinition("bench", "Garden bench", ("inspect", "primary_interact"), ("sit", "animal-rest", "author-socket"), Vec2(2, 1)),
    "fence": FixtureDefinition("fence", "Fence", ("inspect",), ("boundary", "perch", "vine-support"), connected_group="fence"),
    "gate": FixtureDefinition("gate", "Garden gate", ("inspect", "primary_interact"), ("open-close", "route"), blocks_movement=False, connected_group="fence"),
    "sundial": FixtureDefinition("sundial", "Sundial", ("inspect",), ("garden-time", "authored-beat")),
    "trellis": FixtureDefinition("trellis", "Trellis", ("inspect", "tend"), ("train-plant", "animal-hide"), Vec2(2, 1)),
    "birdbath": FixtureDefinition("birdbath", "Birdbath", ("inspect", "tend"), ("refill", "drink", "bathe")),
    "lantern": FixtureDefinition("lantern", "Lantern", ("inspect", "primary_interact"), ("light", "moth-visit")),
    "pond": FixtureDefinition("pond", "Pond", ("inspect", "tend"), ("ripples", "aquatic-plant", "water-visitor"), Vec2(3, 2), blocks_movement=True, connected_group="pond_edge"),
    "memory_shrine": FixtureDefinition("memory_shrine", "Memory shrine", ("inspect", "open_journal"), ("keepsake", "inscription", "memory-discovery"), Vec2(2, 1)),
    "stepping_stone": FixtureDefinition("stepping_stone", "Stepping stone", ("inspect",), ("path",), blocks_movement=False, connected_group="path"),
    "bridge": FixtureDefinition("bridge", "Bridge", ("inspect", "primary_interact"), ("cross-water", "animal-route"), Vec2(3, 1), blocks_movement=False),
    "planter": FixtureDefinition("planter", "Planter", ("inspect", "tend"), ("plant-container", "transplant"), Vec2(2, 1)),
    "table": FixtureDefinition("table", "Garden table", ("inspect", "primary_interact"), ("place-keepsake", "animal-sniff"), Vec2(2, 2)),
    "chair": FixtureDefinition("chair", "Garden chair", ("inspect", "primary_interact"), ("sit", "observe")),
    # Atlas-backed author fixtures.  These IDs are the prefix-stripped form of
    # ``atlas.v1.json`` assets and are therefore valid runtime catalog IDs, not
    # renderer aliases that silently degrade to collectibles.
    "fence_gate": FixtureDefinition("fence_gate", "Fence and gate", ("inspect", "primary_interact"), ("open-close", "route"), blocks_movement=False, connected_group="fence"),
    "mailbox": FixtureDefinition("mailbox", "Memory mailbox", ("inspect", "open_journal"), ("keepsake", "memory-discovery")),
    "stepping_stones": FixtureDefinition("stepping_stones", "Stepping stones", ("inspect",), ("path",), blocks_movement=False, connected_group="path"),
    "table_chairs": FixtureDefinition("table_chairs", "Garden table and chairs", ("inspect", "primary_interact"), ("sit", "shared-space", "animal-sniff"), Vec2(2, 2)),
    "well": FixtureDefinition("well", "Garden well", ("inspect", "tend"), ("water-source", "draw-water")),
    "arbor": FixtureDefinition("arbor", "Garden arbor", ("inspect", "primary_interact"), ("plant-support", "shade", "animal-rest"), Vec2(2, 1)),
    "wind_chime": FixtureDefinition("wind_chime", "Wind chime", ("inspect", "primary_interact"), ("ambience", "listen"), blocks_movement=False),
    "shed_edge": FixtureDefinition("shed_edge", "Tool shed", ("inspect", "primary_interact"), ("storage", "shelter"), Vec2(2, 1)),
    "tool_rack": FixtureDefinition("tool_rack", "Tool rack", ("inspect", "primary_interact"), ("storage", "tending")),
    "watering_can": FixtureDefinition("watering_can", "Watering can", ("inspect", "tend"), ("water", "tending"), blocks_movement=False),
    "compost": FixtureDefinition("compost", "Compost", ("inspect", "tend"), ("soil", "tending")),
    "basket": FixtureDefinition("basket", "Garden basket", ("inspect", "primary_interact"), ("inventory", "gather"), blocks_movement=False),
    "sign": FixtureDefinition("sign", "Garden sign", ("inspect", "primary_interact"), ("narrative", "read")),
    "memorial_stone": FixtureDefinition("memorial_stone", "Memorial stone", ("inspect", "open_journal"), ("inscription", "memory-discovery")),
}

# The generated-world minimum follows the versioned atlas.  Older internal IDs
# remain readable for persisted v1 worlds, but are not a second content owner.
REQUIRED_FUNCTIONAL_FIXTURES = (
    "bench", "fence_gate", "sundial", "trellis", "birdbath", "lantern",
    "pond", "mailbox", "stepping_stones", "bridge", "planter",
    "table_chairs", "well", "arbor", "wind_chime", "shed_edge",
    "tool_rack", "watering_can", "compost", "basket", "sign",
    "memorial_stone",
)
CONNECTED_GROUPS = ("fence", "hedge", "path", "pond_edge", "wall")
CONNECTED_TILE_MASKS: dict[str, tuple[int, ...]] = {
    group: tuple(range(16)) for group in CONNECTED_GROUPS
}


def connected_tile_mask(*, north: bool, east: bool, south: bool, west: bool) -> int:
    return int(north) | (int(east) << 1) | (int(south) << 2) | (int(west) << 3)


def connected_tile_key(group: str, mask: int) -> str:
    if group not in CONNECTED_TILE_MASKS or mask not in CONNECTED_TILE_MASKS[group]:
        raise ValueError("unsupported connected-tile group or mask")
    return f"{group}:{mask:02x}"


def fixture_cells(fixture: FixtureState) -> frozenset[Vec2]:
    definition = FIXTURE_CATALOG[fixture.catalog_id]
    return frozenset(
        Vec2(fixture.position.x + dx, fixture.position.y + dy)
        for dy in range(definition.footprint.y)
        for dx in range(definition.footprint.x)
    )


def _all_fixture_cells(state: WorldState, *, except_id: str | None = None) -> set[Vec2]:
    cells: set[Vec2] = set()
    for fixture in state.fixtures:
        if fixture.fixture_id != except_id:
            cells.update(fixture_cells(fixture))
    return cells


def blocked_cells(state: WorldState) -> frozenset[Vec2]:
    cells = {plant.position for plant in state.plants}
    for fixture in state.fixtures:
        if FIXTURE_CATALOG[fixture.catalog_id].blocks_movement:
            cells.update(fixture_cells(fixture))
    return frozenset(cells)


def layout_is_safe(state: WorldState) -> bool:
    occupied: set[Vec2] = set()
    for fixture in state.fixtures:
        if fixture.catalog_id not in FIXTURE_CATALOG:
            return False
        for cell in fixture_cells(fixture):
            if not (0 <= cell.x < state.world_width and 0 <= cell.y < state.world_height):
                return False
            if cell in occupied:
                return False
            occupied.add(cell)
    width = state.world_width
    height = state.world_height
    blockers = {
        cell.y * width + cell.x for cell in blocked_cells(state)
    }
    goals = {
        position.y * width + position.x
        for position in (
            [animal.position for animal in state.animals]
            + [item.position for item in state.collectibles if not item.collected]
        )
    }
    if goals.intersection(blockers):
        return False
    start = next((index for index in range(width * height) if index not in blockers), None)
    if start is None:
        return not goals
    queue = deque([start])
    reached = {start}
    remaining = goals - reached
    if not remaining:
        return True
    while queue:
        current = queue.popleft()
        x = current % width
        neighbors = []
        if x + 1 < width:
            neighbors.append(current + 1)
        if x > 0:
            neighbors.append(current - 1)
        if current + width < width * height:
            neighbors.append(current + width)
        if current >= width:
            neighbors.append(current - width)
        for nxt in neighbors:
            if nxt in blockers or nxt in reached:
                continue
            reached.add(nxt)
            remaining.discard(nxt)
            if not remaining:
                return True
            queue.append(nxt)
    return not remaining


def validate_fixture_placement(
    state: WorldState,
    catalog_id: str,
    position: Vec2,
    *,
    fixture_id: str = "candidate",
    except_id: str | None = None,
) -> tuple[str, ...]:
    if catalog_id not in FIXTURE_CATALOG:
        return ("unknown fixture catalog ID",)
    candidate = FixtureState(fixture_id, catalog_id, position)
    cells = fixture_cells(candidate)
    errors: list[str] = []
    if any(not (0 <= cell.x < state.world_width and 0 <= cell.y < state.world_height) for cell in cells):
        errors.append("fixture footprint is outside the world")
    if cells.intersection(_all_fixture_cells(state, except_id=except_id)):
        errors.append("fixture footprint overlaps another fixture")
    if cells.intersection(plant.position for plant in state.plants):
        errors.append("fixture footprint overlaps a plant")
    if errors:
        return tuple(errors)
    fixtures = tuple(item for item in state.fixtures if item.fixture_id != except_id) + (candidate,)
    if not layout_is_safe(replace(state, fixtures=fixtures)):
        errors.append("fixture placement makes the world unsafe or unreachable")
    return tuple(errors)
