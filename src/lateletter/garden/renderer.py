"""Read-only terminal projection for canonical Garden ``WorldState``."""

from __future__ import annotations

import curses
from pathlib import Path

from .creatures import animal_symbol
from .plants import plant_symbol
from .state import TerminalViewport
from .terminal import (
    TERMINAL_HELP_LINES,
    TerminalWorldSession,
    handle_terminal_key,
)
from .world.model import WorldState
from .world.projection import SceneObjectProjection, project_scene


_FIXTURE_SYMBOLS = {
    "bench": "=",
    "fence": "#",
    "gate": "+",
    "sundial": "@",
    "trellis": "H",
    "birdbath": "U",
    "lantern": "!",
    "pond": "~",
    "memory_shrine": "M",
    "stepping_stone": ".",
    "bridge": "-",
    "planter": "[]",
    "table": "T",
    "chair": "h",
}


def _symbol(item: SceneObjectProjection) -> str:
    if item.kind == "plant":
        return plant_symbol(str(item.semantic_state["species_id"]))
    if item.kind == "animal":
        return animal_symbol(
            str(item.semantic_state["species_id"]),
            str(item.semantic_state["intent"]),
        )
    if item.kind == "fixture":
        return _FIXTURE_SYMBOLS.get(str(item.semantic_state["catalog_id"]), "F")
    return "*"


class GardenRenderer:
    """Quantize a read-only scene projection into a terminal viewport."""

    def __init__(self, width: int, height: int) -> None:
        self.viewport = TerminalViewport(width, height)

    def resize(self, width: int, height: int) -> None:
        self.viewport.resize(width, height)

    def render_lines(self, world: WorldState) -> list[str]:
        width = self.viewport.width
        height = self.viewport.height
        canvas_height = max(1, height - 4)
        canvas = [[" " for _ in range(width)] for _ in range(canvas_height)]
        projection = project_scene(world)
        camera = projection.camera
        for item in projection.objects:
            x = item.position.x - camera.x
            y = item.position.y - camera.y
            symbol = _symbol(item)
            if item.object_id == world.ui.focus_id:
                symbol = symbol.upper()
            if not (0 <= y < canvas_height):
                continue
            for offset, char in enumerate(symbol):
                if 0 <= x + offset < width:
                    canvas[y][x + offset] = char

        title = (
            f"Garden {world.world_id} · camera {camera.x},{camera.y} · "
            f"trace {len(world.event_trace)}"
        )
        if canvas:
            canvas[0][:min(width, len(title))] = list(title[:width])

        objects = [
            item for item in projection.objects
            if item.object_id == world.ui.focus_id
        ]
        if objects and canvas_height > 2:
            focused = objects[0]
            detail = f"> {focused.semantic_name}: {', '.join(focused.actions)}"
            canvas[1][:min(width, len(detail))] = list(detail[:width])
        if world.ui.journal_open and canvas_height > 3:
            journal = f"Journal: {len(world.journal)} entries"
            canvas[2][:min(width, len(journal))] = list(journal[:width])
        return ["".join(row) for row in canvas]

    def blit_curses(self, screen: curses.window, world: WorldState) -> None:
        for row, line in enumerate(self.render_lines(world)):
            try:
                screen.addstr(row, 0, line)
            except curses.error:
                pass

    def render_ansi(self, world: WorldState) -> str:
        return "\n".join(self.render_lines(world))


def run_curses(
    stdscr: curses.window,
    seed: int = 42_301,
    season: str | None = None,
    *,
    world_path: str | Path | None = None,
    observed_wall_time: int | None = None,
) -> None:
    """Run standalone canonical Garden mode with discoverable commands."""
    del season  # Presentation override is not allowed to own canonical season.
    curses.curs_set(0)
    stdscr.timeout(100)
    height, width = stdscr.getmaxyx()
    session = TerminalWorldSession.open(
        world_id="standalone",
        seed=seed,
        width=width,
        height=height,
        path=world_path,
        observed_wall_time=observed_wall_time,
    )
    renderer = GardenRenderer(width, height)
    message = "Use o to select an object; a opens its semantic actions."
    while True:
        new_height, new_width = stdscr.getmaxyx()
        if (new_height, new_width) != (height, width):
            height, width = new_height, new_width
            session.resize(width, height)
            renderer.resize(width, height)
        stdscr.erase()
        renderer.blit_curses(stdscr, session.world)
        status_rows = [message, *TERMINAL_HELP_LINES]
        for offset, line in enumerate(status_rows):
            row = height - len(status_rows) + offset
            if row < 0:
                continue
            try:
                stdscr.addstr(row, 0, line[:width].ljust(width), curses.A_REVERSE)
            except curses.error:
                pass
        stdscr.refresh()
        key = stdscr.getch()
        if key == ord("q"):
            break
        if key == -1:
            continue
        result = handle_terminal_key(session, key)
        if result is not None:
            message = result.summary if result.accepted else result.reason


def print_ansi(
    width: int,
    height: int,
    seed: int,
    season: str | None = None,
) -> None:
    del season
    from .world.generation import generate_initial_world

    world = generate_initial_world("ansi-preview", seed)
    renderer = GardenRenderer(width, height)
    print(renderer.render_ansi(world))
    print("\n".join(TERMINAL_HELP_LINES))
