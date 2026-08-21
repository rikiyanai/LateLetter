"""Layer 4 — Special: letter-bird and message overlays.

Event-driven layer controlled by bundle auth state, not animation timers.
Highest z-order — draws over everything else.

This layer is wired in step 8 (recipient mode). The infrastructure
is here so the compositor can iterate all 5 layers from the start.
"""
from __future__ import annotations

from .screen_buffer import ScreenBuffer
from .state import GardenState


class SpecialLayer:
    """Layer 4: event-driven overlays (letter-bird, reading UI).

    Update cadence: event-driven (no regular timer).
    """

    update_interval_ms = 0  # event-driven

    def __init__(self) -> None:
        pass

    def update(self, state: GardenState) -> None:
        pass

    def render(self, buf: ScreenBuffer, state: GardenState) -> None:
        pass  # nothing until recipient mode

    def on_resize(self, state: GardenState) -> None:
        pass
