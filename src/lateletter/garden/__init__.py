"""LateLetter Garden entrypoint."""

from __future__ import annotations

import curses

from .renderer import run_curses
from .terminal import FULL_GARDEN_PARITY, TERMINAL_WORLD_WIRED


def run_garden(*, season_override: str | None = None) -> None:
    curses.wrapper(run_curses, 42_301, season_override)


__all__ = [
    "FULL_GARDEN_PARITY",
    "TERMINAL_WORLD_WIRED",
    "run_garden",
]
