from dataclasses import replace
import curses

from lateletter.garden.atlas import animal_glyph, load_atlas
from lateletter.garden.renderer import GardenRenderer
from lateletter.garden.terminal import TerminalWorldSession, handle_terminal_key
from lateletter.garden.world.animals import ANIMAL_SPECIES
from lateletter.garden.world.generation import generate_initial_world
from lateletter.garden.world.model import (
    AnimalState, EpisodicMemory, FixtureState, JournalEntry, Personality,
    PlantState, UIState, Vec2,
)
from lateletter.garden.world.projection import (
    Hotspot, SceneObjectProjection, SceneProjection, project_scene,
)


def test_terminal_renderer_is_projection_only_resize_and_uses_partial_diffs():
    world = generate_initial_world("renderer-proof", 42)
    renderer = GardenRenderer(80, 24)
    before = world.to_dict()
    first = renderer.render_diff(world)
    assert first
    assert renderer.render_diff(world) == ()
    renderer.resize(100, 30)
    assert renderer.render_diff(world)
    assert world.to_dict() == before


def test_terminal_camera_pan_moves_projection_without_changing_objects():
    world = generate_initial_world("renderer-pan", 17)
    renderer = GardenRenderer(80, 24)
    before = renderer.render_lines(world)
    panned = replace(world, ui=replace(world.ui, camera=Vec2(
        world.ui.camera.x + 10, world.ui.camera.y,
    )))
    after = renderer.render_lines(panned)
    assert before != after
    assert [item.to_dict() for item in world.plants] == [item.to_dict() for item in panned.plants]


def test_terminal_surfaces_bounded_absence_summary():
    world = generate_initial_world("renderer-absence", 9)
    world = replace(world, program_state={
        **dict(world.program_state),
        "absence_summary": ["one", "two", "three", "must not appear"],
    })
    rendered = GardenRenderer(120, 24).render_ansi(world)
    assert "Welcome back: one · two · three" in rendered
    assert "must not appear" not in rendered


def test_ten_minute_pan_keeps_initialized_horizon_and_partial_diffs():
    world = generate_initial_world("renderer-long-pan", 27)
    renderer = GardenRenderer(80, 24)
    renderer.render_diff(world)
    for second in range(1, 601):
        panned = replace(world, ui=replace(world.ui, camera=Vec2(
            world.ui.camera.x + second, world.ui.camera.y,
        )))
        lines = renderer.render_lines(panned)
        assert "." in lines[(len(lines) * 3) // 5]
        assert len(renderer.render_diff(panned)) < 80 * len(lines)


def test_terminal_renderer_paints_every_canonical_fixture_footprint_cell():
    world = generate_initial_world("renderer-footprint", 5)
    world = replace(
        world,
        plants=(), animals=(), collectibles=(),
        fixtures=(FixtureState("fixture:table", "table_chairs", Vec2(0, 0)),),
        ui=replace(world.ui, camera=Vec2(0, 0)),
    )
    lines = GardenRenderer(80, 24).render_lines(world)
    assert lines[10][40:42] == "TT"
    assert lines[11][40:42] == "TT"


def test_terminal_renderer_covers_all_connected_masks_and_animal_tiers(monkeypatch):
    base = generate_initial_world("renderer-atlas-exhaustive", 71)
    connected = load_atlas()["connected_tiles"]
    assert set(connected) == {"fence", "hedge", "path", "pond_edge", "wall"}
    assert all(set(masks) == {str(mask) for mask in range(16)}
               for masks in connected.values())
    renderer = GardenRenderer(80, 24)
    for group, masks in connected.items():
        for mask in range(16):
            assert renderer.connected_glyph(group, mask) == masks[str(mask)]
    for group, masks in connected.items():
        for mask in range(16):
            projection = SceneProjection(
                base.world_id, base.effective_time, Vec2(0, 0), False, {},
                (SceneObjectProjection(
                    f"fixture:{group}:{mask}", "fixture", group, Vec2(0, 0),
                    100, True, True, (), (), Hotspot(0, 0, 1, 1),
                    {"catalog_id": "fence", "connected_group": group,
                     "presentation_state": "closed",
                     "render_cells": [{"dx": 0, "dy": 0,
                                       "connected_mask": mask}]},
                ),),
            )
            monkeypatch.setattr(
                "lateletter.garden.renderer.project_scene",
                lambda _world, value=projection: value,
            )
            assert GardenRenderer(80, 24).render_lines(base)[10][40] == masks[str(mask)]
    monkeypatch.setattr("lateletter.garden.renderer.project_scene", project_scene)

    for species_id in sorted(ANIMAL_SPECIES):
        for tier in range(4):
            performing = tier % 2 == 1
            animal = AnimalState(
                f"animal:{species_id}:{tier}", species_id, Vec2(0, 0),
                current_intent="greet", bond_tier=tier,
                display_name=f"{species_id.title()} {tier}",
                personality=Personality(playfulness=90, patience=10),
                recent_memories=(EpisodicMemory(
                    f"memory:{species_id}:{tier}", "feed", None, 1, 1, 1,
                ),),
                choreography_lock="animal.present_gift" if performing else None,
            )
            world = replace(
                base, plants=(), fixtures=(), collectibles=(), animals=(animal,),
                ui=UIState(camera=Vec2(0, 0)),
            )
            projection = project_scene(world).objects[0]
            assert projection.semantic_state["presentation_variant"].startswith(
                f"{species_id}.tier{tier}."
            )
            assert f"bond tier {tier}" in projection.semantic_state["semantic_description"]
            assert "greet" in projection.semantic_state["semantic_description"]
            assert "playfulness" in projection.semantic_state["semantic_description"]
            assert "1 memories" in projection.semantic_state["semantic_description"]
            assert projection.semantic_state["choreography_phase"] == (
                "perform" if performing else "orient"
            )
            assert GardenRenderer(80, 24).render_lines(world)[10][40] == animal_glyph(
                species_id, tier, choreography=performing,
            )


def test_terminal_renderer_uses_projected_depth_for_parallax():
    world = generate_initial_world("renderer-parallax", 72)
    animal = AnimalState("animal:cat", "cat", Vec2(5, 4))
    plant = PlantState("plant:rose", "rose", Vec2(10, 0))
    world = replace(
        world, plants=(plant,), animals=(animal,), fixtures=(), collectibles=(),
        ui=UIState(camera=Vec2(0, 0)),
    )
    lines = GardenRenderer(80, 24).render_lines(world)
    assert lines[10][50] == "*"  # world depth 1.00
    assert lines[14][46] == animal_glyph("cat", 0)  # 5 * 1.10 rounds half-away


def test_terminal_journal_inventory_and_missed_events_are_scroll_reachable():
    session = TerminalWorldSession.preview(width=52, height=16, observed_wall_time=100)
    entries = tuple(
        JournalEntry(f"entry:{index}", f"object:{index}", "examined",
                     f"Entry {index}", f"Description {index}", index)
        for index in range(20)
    )
    session.world = replace(
        session.world,
        inventory=("watering can", "pressed flower"),
        journal=entries,
        ui=replace(session.world.ui, journal_open=True),
        program_state={**dict(session.world.program_state),
                       "missed_event_summaries": ["A visit waited."]},
    )
    renderer = GardenRenderer(52, 16)
    first = renderer.render_ansi(session.world)
    assert "Inventory" in first and "Entry 0" in first
    for _ in range(50):
        handle_terminal_key(session, curses.KEY_DOWN)
    last = renderer.render_ansi(session.world) if session.journal_offset == 0 else "\n".join(
        renderer.render_lines(session.world, journal_offset=session.journal_offset)
    )
    assert "Entry 19" in last
    assert "A visit waited." in last


def test_terminal_deferred_persistence_writes_only_on_commit(tmp_path):
    path = tmp_path / "deferred.json"
    session = TerminalWorldSession.open(
        world_id="deferred", seed=73, width=80, height=24, path=path,
        observed_wall_time=100, defer_persistence=True,
    )
    assert session.total_visits == 1
    assert not path.exists()
    session.dwell(30)
    assert not path.exists()
    session.commit_persistence()
    assert path.exists()
