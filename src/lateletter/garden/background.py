"""Layer 0 — Background: sky gradient and ground rows.

Updates only on resize or season change. Draws first so everything
else composites on top.
"""
from __future__ import annotations

from .screen_buffer import ScreenBuffer
from .state import GardenState

_GND = ',~.^,.,~^,.,~,.^,~.,'


def _ground_row(width: int, offset: int = 0) -> str:
    base = _GND * (width // len(_GND) + 2)
    return base[offset:offset + width]


class BackgroundLayer:
    """Layer 0: sky (implicit clear) + two ground texture rows."""

    update_interval_ms = 0  # only on resize/season change

    def __init__(self) -> None:
        pass

    def update(self, state: GardenState) -> None:
        pass  # no per-frame state

    def render(self, buf: ScreenBuffer, state: GardenState) -> None:
        w, gy = state.width, state.ground_y
        g1 = _ground_row(w, 0)
        g2 = _ground_row(w, 5)
        for x in range(w):
            buf.put(gy, x, g1[x], 'ground')
            if gy + 1 < state.height:
                buf.put(gy + 1, x, g2[x], 'dim_green')

    def on_resize(self, state: GardenState) -> None:
        pass
