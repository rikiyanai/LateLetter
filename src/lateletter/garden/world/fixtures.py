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
    interaction_verbs: tuple[str, ...] = ()
    # SPEC 7.8.3.1: the single act that happens on a plain click, tap or Enter.
    #
    # AUTHORED, never inferred. It would be easy to take `interaction_verbs[0]`
    # and call that the primary, and it would even be right for the bench -- but
    # then the renderer's behaviour would be a side effect of tuple order, and
    # a fixture whose first verb happens to be consequential would silently get
    # a dangerous primary. Declaring it here is what lets the contract promise
    # that a primary action is always obvious, safe and free of choices.
    #
    # `None` means the fixture declares no primary action. It is then inert to
    # direct activation and its verbs are reached through "more actions" --
    # explicitly allowed by 7.8.3.1. Most of the catalog is currently `None`:
    # the five default-scene fixtures are authored below, and the rest await the
    # same authoring pass. This does NOT change dispatch, which still falls back
    # to `interaction_verbs[0]` in `_fixture_interaction`; it only governs what
    # the world OFFERS as a one-click act.
    primary_verb: str | None = None
    # Second-person imperative shown on hover, on focus, and to screen readers.
    # It names the act, not the object: "Sit on the garden bench", never "Bench".
    primary_label: str | None = None


FIXTURE_CATALOG: dict[str, FixtureDefinition] = {
    # Primary actions are authored only for the five default-scene fixtures
    # (`STARTER_FIXTURES`). Every other entry keeps `primary_verb=None` until it
    # has been through the same authoring judgement, because a primary action is
    # a promise about safety, not a convenience default.
    "bench": FixtureDefinition("bench", "Garden bench", ("inspect", "primary_interact"), ("sit", "animal-rest", "author-socket"), Vec2(2, 1), interaction_verbs=("sit", "observe"), primary_verb="sit", primary_label="Sit on the garden bench"),
    "fence": FixtureDefinition("fence", "Fence", ("inspect", "primary_interact"), ("boundary", "perch", "vine-support"), connected_group="fence", interaction_verbs=("open", "close")),
    "gate": FixtureDefinition("gate", "Garden gate", ("inspect", "primary_interact"), ("open-close", "route"), blocks_movement=False, connected_group="fence", interaction_verbs=("open", "close")),
    "sundial": FixtureDefinition("sundial", "Sundial", ("inspect", "primary_interact"), ("garden-time", "authored-beat"), interaction_verbs=("read_time",)),
    "trellis": FixtureDefinition("trellis", "Trellis", ("inspect", "primary_interact"), ("train-plant", "animal-hide"), Vec2(2, 1), interaction_verbs=("train",)),
    "birdbath": FixtureDefinition("birdbath", "Birdbath", ("inspect", "primary_interact"), ("refill", "drink", "bathe"), interaction_verbs=("refill", "observe")),
    # The lantern's primary is deliberately `observe`, NOT `light`. Lighting is
    # state-dependent -- it means something different depending on whether the
    # lantern is already lit -- so it belongs to the spawned-opportunity path in
    # 7.8.3.2, where the world can offer exactly the one that currently applies.
    # Looking at the lantern is the act that is always available and always safe.
    "lantern": FixtureDefinition("lantern", "Lantern", ("inspect", "primary_interact"), ("light", "moth-visit"), interaction_verbs=("light", "extinguish", "observe"), primary_verb="observe", primary_label="Look at the lantern"),
    "pond": FixtureDefinition("pond", "Pond", ("inspect", "primary_interact"), ("ripples", "aquatic-plant", "water-visitor"), Vec2(3, 2), blocks_movement=True, connected_group="pond_edge", interaction_verbs=("observe", "tend")),
    "memory_shrine": FixtureDefinition("memory_shrine", "Memory shrine", ("inspect", "primary_interact", "open_journal"), ("keepsake", "inscription", "memory-discovery"), Vec2(2, 1), interaction_verbs=("open", "remember")),
    "stepping_stone": FixtureDefinition("stepping_stone", "Stepping stone", ("inspect", "primary_interact"), ("path",), blocks_movement=False, connected_group="path", interaction_verbs=("walk",)),
    "bridge": FixtureDefinition("bridge", "Bridge", ("inspect", "primary_interact"), ("cross-water", "animal-route"), Vec2(3, 1), blocks_movement=False, interaction_verbs=("cross", "observe")),
    # `tend`, not `transplant`: transplanting moves a living plant and is a
    # consequential choice, which 7.8.3.1 forbids as a primary action.
    "planter": FixtureDefinition("planter", "Planter", ("inspect", "primary_interact"), ("plant-container", "transplant"), Vec2(2, 1), interaction_verbs=("transplant", "tend"), primary_verb="tend", primary_label="Tend the planter"),
    "table": FixtureDefinition("table", "Garden table", ("inspect", "primary_interact"), ("place-keepsake", "animal-sniff"), Vec2(2, 2), interaction_verbs=("arrange", "sit")),
    "chair": FixtureDefinition("chair", "Garden chair", ("inspect", "primary_interact"), ("sit", "observe"), interaction_verbs=("sit", "observe")),
    # Atlas-backed author fixtures.  These IDs are the prefix-stripped form of
    # ``atlas.v1.json`` assets and are therefore valid runtime catalog IDs, not
    # renderer aliases that silently degrade to collectibles.
    "fence_gate": FixtureDefinition("fence_gate", "Fence and gate", ("inspect", "primary_interact"), ("open-close", "route"), blocks_movement=False, connected_group="fence", interaction_verbs=("open", "close")),
    "mailbox": FixtureDefinition("mailbox", "Memory mailbox", ("inspect", "primary_interact", "open_journal"), ("keepsake", "memory-discovery"), interaction_verbs=("open", "remember"), primary_verb="open", primary_label="Open the memory mailbox"),
    "stepping_stones": FixtureDefinition("stepping_stones", "Stepping stones", ("inspect", "primary_interact"), ("path",), blocks_movement=False, connected_group="path", interaction_verbs=("walk",), primary_verb="walk", primary_label="Walk the stepping stones"),
    "table_chairs": FixtureDefinition("table_chairs", "Garden table and chairs", ("inspect", "primary_interact"), ("sit", "shared-space", "animal-sniff"), Vec2(2, 2), interaction_verbs=("sit", "arrange")),
    "well": FixtureDefinition("well", "Garden well", ("inspect", "primary_interact"), ("water-source", "draw-water"), interaction_verbs=("draw_water",)),
    "arbor": FixtureDefinition("arbor", "Garden arbor", ("inspect", "primary_interact"), ("plant-support", "shade", "animal-rest"), Vec2(2, 1), interaction_verbs=("rest", "observe")),
    "wind_chime": FixtureDefinition("wind_chime", "Wind chime", ("inspect", "primary_interact"), ("ambience", "listen"), blocks_movement=False, interaction_verbs=("listen",)),
    "shed_edge": FixtureDefinition("shed_edge", "Tool shed", ("inspect", "primary_interact"), ("storage", "shelter"), Vec2(2, 1), interaction_verbs=("open", "organize")),
    "tool_rack": FixtureDefinition("tool_rack", "Tool rack", ("inspect", "primary_interact"), ("storage", "tending"), interaction_verbs=("organize",)),
    "watering_can": FixtureDefinition("watering_can", "Watering can", ("inspect", "primary_interact"), ("water", "tending"), blocks_movement=False, interaction_verbs=("fill", "water")),
    "compost": FixtureDefinition("compost", "Compost", ("inspect", "primary_interact"), ("soil", "tending"), interaction_verbs=("turn",)),
    "basket": FixtureDefinition("basket", "Garden basket", ("inspect", "primary_interact"), ("inventory", "gather"), blocks_movement=False, interaction_verbs=("review_inventory", "gather")),
    "sign": FixtureDefinition("sign", "Garden sign", ("inspect", "primary_interact"), ("narrative", "read"), interaction_verbs=("read",)),
    "memorial_stone": FixtureDefinition("memorial_stone", "Memorial stone", ("inspect", "primary_interact", "open_journal"), ("inscription", "memory-discovery"), interaction_verbs=("remember", "observe")),
}

# Full functional catalog required for placement, authored programs, fixtures
# tests, and persisted v1 compatibility. New gardens intentionally start with
# a smaller composed subset; availability must not mean dumping the catalog
# into every recipient's first view.
REQUIRED_FUNCTIONAL_FIXTURES = (
    "bench", "fence_gate", "sundial", "trellis", "birdbath", "lantern",
    "pond", "mailbox", "stepping_stones", "bridge", "planter",
    "table_chairs", "well", "arbor", "wind_chime", "shed_edge",
    "tool_rack", "watering_can", "compost", "basket", "sign",
    "memorial_stone",
)
STARTER_FIXTURES = (
    "bench", "mailbox", "stepping_stones", "planter", "lantern",
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


def fixture_presentation_state(fixture: FixtureState) -> str:
    """Return the renderer-neutral visual state selected by canonical data."""
    values = fixture.authored_state
    if fixture.catalog_id in {"fence", "gate", "fence_gate", "mailbox", "memory_shrine", "shed_edge"}:
        return "open" if bool(values.get("open", False)) else "closed"
    if fixture.catalog_id == "lantern":
        return "on" if bool(values.get("lit", False)) else "off"
    if fixture.catalog_id == "birdbath":
        return "full" if int(values.get("water_level", 0)) > 0 else "empty"
    if fixture.catalog_id == "watering_can":
        return "full" if int(values.get("water_level", 0)) > 0 else "empty"
    if fixture.catalog_id == "compost":
        return "turned" if int(values.get("turned_count", 0)) > 0 else "idle"
    return "active" if fixture.interaction_count else "idle"


def fixture_active_affordances(fixture: FixtureState) -> tuple[str, ...]:
    """Expose only affordances currently enabled by the fixture state machine."""
    definition = FIXTURE_CATALOG[fixture.catalog_id]
    values = fixture.authored_state
    enabled = set(definition.affordances)
    if fixture.catalog_id in {"gate", "fence_gate"} and not bool(values.get("open", False)):
        enabled.discard("route")
    if fixture.catalog_id == "birdbath" and int(values.get("water_level", 0)) <= 0:
        enabled.difference_update({"drink", "bathe"})
    if fixture.catalog_id == "lantern" and not bool(values.get("lit", False)):
        enabled.discard("moth-visit")
    if fixture.catalog_id == "watering_can" and int(values.get("water_level", 0)) <= 0:
        enabled.discard("water")
    return tuple(sorted(enabled))


def fixture_opportunities(fixture: FixtureState) -> tuple[dict[str, str], ...]:
    """Return the spawned opportunities this fixture is currently offering.

    SPEC 7.8.3.2. An opportunity is an act that only makes sense right now,
    given world state -- lighting a lantern that is dark, extinguishing one that
    is burning. It is offered as its own control beside the object rather than
    buried in a menu, and it disappears when it stops applying rather than when
    a timer runs out.

    Computed HERE, in the world model, for the reason the contract insists on:
    the renderer must never decide what looks available. It draws what this
    returns and nothing else, so the browser and the terminal necessarily offer
    the same opportunities from the same state.

    :param fixture: The fixture whose current state decides what is on offer.
    :returns: A tuple of records, each carrying

        * `opportunity_id` -- stable for as long as the same opportunity stands.
          The renderer uses it to tell "this is still the one I already drew"
          from "this is new", which is what stops the attract animation
          replaying on every repaint.
        * `verb` -- an EXISTING canonical fixture verb, dispatched through the
          ordinary `primary_interact` path. Opportunities add no new commands
          and hold no state of their own.
        * `label` -- second-person imperative, used as the control's accessible
          name and its visible text.

        The tuple is ordered by `opportunity_id` so both implementations and
        every repaint agree on control order; empty means nothing is on offer.
    """
    values = fixture.authored_state
    offers: list[dict[str, str]] = []
    if fixture.catalog_id == "lantern":
        # Exactly one of these is ever on offer, because they are the two sides
        # of one piece of state. Offering both at once would be offering the
        # user a choice, which is what the action sheet is for.
        if bool(values.get("lit", False)):
            offers.append({"verb": "extinguish", "label": "Put out the lantern"})
        else:
            offers.append({"verb": "light", "label": "Light the lantern"})
    return tuple(sorted(
        (
            {
                "opportunity_id": f"{fixture.fixture_id}:{offer['verb']}",
                "verb": offer["verb"],
                "label": offer["label"],
            }
            for offer in offers
        ),
        key=lambda offer: offer["opportunity_id"],
    ))


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
    def access_cells(cells: frozenset[Vec2], *, blocking: bool) -> set[int]:
        candidates: set[Vec2] = set()
        if not blocking:
            candidates.update(cells)
        for cell in cells:
            candidates.update((
                Vec2(cell.x + 1, cell.y), Vec2(cell.x - 1, cell.y),
                Vec2(cell.x, cell.y + 1), Vec2(cell.x, cell.y - 1),
            ))
        return {
            cell.y * width + cell.x for cell in candidates
            if 0 <= cell.x < width and 0 <= cell.y < height
            and cell.y * width + cell.x not in blockers
        }

    access_groups: list[set[int]] = []
    access_groups.extend(
        access_cells(frozenset({plant.position}), blocking=True)
        for plant in state.plants
    )
    access_groups.extend(
        access_cells(
            fixture_cells(fixture),
            blocking=FIXTURE_CATALOG[fixture.catalog_id].blocks_movement,
        )
        for fixture in state.fixtures
    )
    access_groups.extend(
        access_cells(frozenset({animal.position}), blocking=False)
        for animal in state.animals
    )
    access_groups.extend(
        access_cells(frozenset({item.position}), blocking=False)
        for item in state.collectibles if not item.collected
    )
    if any(not group for group in access_groups):
        return False
    start = next((index for index in range(width * height) if index not in blockers), None)
    if start is None:
        return not access_groups
    queue = deque([start])
    reached = {start}
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
            queue.append(nxt)
    return all(bool(group.intersection(reached)) for group in access_groups)


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
