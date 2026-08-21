"""Fixed-point canonical camera and parallax transforms.

All coordinates are integer subcells so Python and browser adapters can share
exact state without floating-point drift.  One logical cell is 256 subcells.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import gcd


SUBCELLS_PER_CELL = 256


def cells(value: int) -> int:
    """Convert a whole-cell count to canonical subcells."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("cell counts must be integers")
    return value * SUBCELLS_PER_CELL


def whole_cells(value: int) -> int:
    """Quantize subcells to the nearest cell with canonical half-away ties."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("subcell coordinates must be integers")
    return _round_ratio(value, SUBCELLS_PER_CELL)


def _round_ratio(numerator: int, denominator: int) -> int:
    """Integer division rounded to nearest, with halves away from zero."""
    if denominator <= 0:
        raise ValueError("denominator must be positive")
    sign = -1 if numerator < 0 else 1
    magnitude = abs(numerator)
    return sign * ((magnitude + denominator // 2) // denominator)


@dataclass(frozen=True)
class DepthFactor:
    numerator: int
    denominator: int = 100

    def __post_init__(self) -> None:
        if isinstance(self.numerator, bool) or isinstance(self.denominator, bool):
            raise TypeError("depth factors must be integers")
        if self.denominator <= 0 or self.numerator < 0:
            raise ValueError("depth factor must be a non-negative rational")
        common = gcd(self.numerator, self.denominator)
        object.__setattr__(self, "numerator", self.numerator // common)
        object.__setattr__(self, "denominator", self.denominator // common)

    def scale(self, value: int) -> int:
        return _round_ratio(value * self.numerator, self.denominator)

    def unscale(self, value: int) -> int:
        if self.numerator == 0:
            raise ValueError("a fixed presentation layer cannot be hit-tested")
        return _round_ratio(value * self.denominator, self.numerator)


STAR_DEPTH = DepthFactor(2, 100)
DISTANT_DEPTH = DepthFactor(20, 100)
FAR_DEPTH = DepthFactor(55, 100)
WORLD_DEPTH = DepthFactor(1, 1)
FOREGROUND_DEPTH = DepthFactor(115, 100)


@dataclass(frozen=True)
class Point:
    x: int
    y: int


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    width: int
    height: int

    def __post_init__(self) -> None:
        if self.width < 0 or self.height < 0:
            raise ValueError("rectangle dimensions cannot be negative")

    def contains(self, point: Point) -> bool:
        return (self.x <= point.x < self.x + self.width
                and self.y <= point.y < self.y + self.height)


@dataclass(frozen=True)
class Camera:
    center: Point
    viewport_width: int
    viewport_height: int

    def __post_init__(self) -> None:
        if self.viewport_width <= 0 or self.viewport_height <= 0:
            raise ValueError("camera viewport must be positive")

    @property
    def viewport_center(self) -> Point:
        return Point(self.viewport_width // 2, self.viewport_height // 2)

    def world_to_screen(self, point: Point,
                        depth: DepthFactor = WORLD_DEPTH) -> Point:
        viewport = self.viewport_center
        return Point(
            viewport.x + depth.scale(point.x - self.center.x),
            viewport.y + depth.scale(point.y - self.center.y),
        )

    def screen_to_world(self, point: Point,
                        depth: DepthFactor = WORLD_DEPTH) -> Point:
        viewport = self.viewport_center
        return Point(
            self.center.x + depth.unscale(point.x - viewport.x),
            self.center.y + depth.unscale(point.y - viewport.y),
        )

    def visible_world_rect(self, depth: DepthFactor = WORLD_DEPTH) -> Rect:
        top_left = self.screen_to_world(Point(0, 0), depth)
        bottom_right = self.screen_to_world(
            Point(self.viewport_width, self.viewport_height), depth,
        )
        return Rect(
            min(top_left.x, bottom_right.x), min(top_left.y, bottom_right.y),
            abs(bottom_right.x - top_left.x),
            abs(bottom_right.y - top_left.y),
        )

    def hit_test(self, screen_point: Point, world_hitbox: Rect,
                 depth: DepthFactor = WORLD_DEPTH) -> bool:
        return world_hitbox.contains(self.screen_to_world(screen_point, depth))

    def pan(self, dx: int, dy: int) -> "Camera":
        return Camera(Point(self.center.x + dx, self.center.y + dy),
                      self.viewport_width, self.viewport_height)

    def resize(self, width: int, height: int) -> "Camera":
        """Resize without changing the canonical world-space center."""
        return Camera(self.center, width, height)
