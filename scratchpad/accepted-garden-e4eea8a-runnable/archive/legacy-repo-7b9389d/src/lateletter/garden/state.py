"""Shared mutable state passed to all garden layers."""
from __future__ import annotations

import time


class GardenState:
    """Holds per-frame state that layers read and write.

    Attributes populated by layers:
      collision_map  – set of (row, col) for all plant-occupied cells (Layer 1)
      top_surfaces   – dict col -> min_row for snow accumulation (Layer 1)
      canopy_cells   – set of (row, col) for leaf detachment points (Layer 1)
    """

    __slots__ = (
        'frame', 'width', 'height', 'ground_y', 'seed',
        'season', 'wind', 'dt', 'now',
        'collision_map', 'top_surfaces', 'canopy_cells',
        'flash_frames',
    )

    def __init__(self, width: int, height: int, seed: int,
                 season: str = 'spring') -> None:
        self.frame: int = 0
        self.width = width
        self.height = height
        self.ground_y = height - 3
        self.seed = seed
        self.season = season
        self.wind: float = 0.0
        self.dt: float = 0.05  # seconds per frame tick
        self.now: float = time.monotonic()
        # Plant collision data (populated by PlantLayer, read by ParticleLayer)
        self.collision_map: set[tuple[int, int]] = set()
        self.top_surfaces: dict[int, int] = {}   # col -> min occupied row
        self.canopy_cells: set[tuple[int, int]] = set()
        # Screen flash for lightning (decremented each frame by renderer)
        self.flash_frames: int = 0

    def resize(self, width: int, height: int) -> None:
        self.width = width
        self.height = height
        self.ground_y = height - 3
