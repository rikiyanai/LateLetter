from lateletter.garden.camera import (
    Camera, DepthFactor, Point, Rect, WORLD_DEPTH, cells,
)


def test_world_screen_round_trip_and_resize_preserve_world_center():
    camera = Camera(Point(cells(100), cells(50)), cells(80), cells(24))
    point = Point(cells(112), cells(45))
    screen = camera.world_to_screen(point, WORLD_DEPTH)
    assert camera.screen_to_world(screen, WORLD_DEPTH) == point
    assert camera.resize(cells(120), cells(40)).center == camera.center


def test_parallax_uses_exact_rational_fixed_point_offsets():
    camera = Camera(Point(cells(10), 0), cells(80), cells(24))
    point = Point(cells(20), 0)
    depth = DepthFactor(1, 5)
    screen = camera.world_to_screen(point, depth)
    assert screen.x - camera.viewport_center.x == cells(2)


def test_hit_testing_inverts_the_same_layer_transform():
    camera = Camera(Point(cells(10), cells(10)), cells(20), cells(10))
    hitbox = Rect(cells(11), cells(9), cells(2), cells(2))
    on_screen = camera.world_to_screen(Point(cells(12), cells(10)))
    off_screen = camera.world_to_screen(Point(cells(15), cells(10)))
    assert camera.hit_test(on_screen, hitbox)
    assert not camera.hit_test(off_screen, hitbox)


def test_fixed_depth_cannot_be_used_as_an_interactive_layer():
    camera = Camera(Point(0, 0), cells(10), cells(10))
    fixed = DepthFactor(0, 1)
    try:
        camera.screen_to_world(Point(0, 0), fixed)
    except ValueError as exc:
        assert "hit-tested" in str(exc)
    else:
        raise AssertionError("fixed presentation layer was invertible")
