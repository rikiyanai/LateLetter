from dataclasses import replace

from lateletter.garden.renderer import GardenRenderer
from lateletter.garden.world.generation import generate_initial_world
from lateletter.garden.world.model import UIState, Vec2


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
