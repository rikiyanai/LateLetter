"""Terminal presentation state only; canonical gameplay lives in world.model."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TerminalViewport:
    width: int
    height: int

    def resize(self, width: int, height: int) -> None:
        self.width = max(1, int(width))
        self.height = max(1, int(height))


class GardenState(TerminalViewport):
    """Deprecated render-only alias retained for dormant prototype imports.

    It deliberately contains no seed, clock, plants, animals, collision map, or
    progression. New terminal code must use ``WorldState`` for gameplay.
    """
