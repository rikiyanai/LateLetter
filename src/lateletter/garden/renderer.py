"""Read-only terminal projection for canonical Garden ``WorldState``."""

from __future__ import annotations

import curses
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .atlas import load_atlas
from .astronomy import CoarseLocation, resolve_sky_mode, visible_stars
from .camera import Camera, Point, WORLD_DEPTH, cells
from .state import TerminalViewport
from .terminal import (
    TERMINAL_HELP_LINES,
    TerminalWorldSession,
    handle_terminal_key,
)
from .world.model import WorldState
from .world.projection import SceneObjectProjection, project_scene


_FALLBACKS = {
    "plant": "*", "animal": "a", "fixture": "F", "collectible": "$",
}
_ANIMAL_FALLBACKS = {"cat": "c", "bird": "v", "rabbit": "r", "turtle": "t"}
_FIXTURE_ASSET = {
    "bench": "fixture.bench", "fence": "fixture.fence_gate",
    "gate": "fixture.fence_gate", "fence_gate": "fixture.fence_gate",
    "sundial": "fixture.sundial", "trellis": "fixture.trellis",
    "birdbath": "fixture.birdbath", "lantern": "fixture.lantern",
    "pond": "fixture.pond", "mailbox": "fixture.mailbox",
    "memory_shrine": "fixture.mailbox", "stepping_stone": "fixture.stepping_stones",
    "stepping_stones": "fixture.stepping_stones", "bridge": "fixture.bridge",
    "planter": "fixture.planter", "table": "fixture.table_chairs",
    "chair": "fixture.table_chairs", "table_chairs": "fixture.table_chairs",
}
_CONNECTED_GROUPS = {
    "fence": "fence", "gate": "fence", "fence_gate": "fence",
    "stepping_stone": "path", "stepping_stones": "path", "pond": "pond_edge",
}


def _connected_masks(items: tuple[SceneObjectProjection, ...]) -> dict[str, int]:
    groups: dict[str, set[tuple[int, int]]] = {}
    for item in items:
        catalog = str(item.semantic_state.get("catalog_id", ""))
        group = _CONNECTED_GROUPS.get(catalog)
        if item.kind == "fixture" and group:
            groups.setdefault(group, set()).add((item.position.x, item.position.y))
    result: dict[str, int] = {}
    for item in items:
        catalog = str(item.semantic_state.get("catalog_id", ""))
        group = _CONNECTED_GROUPS.get(catalog)
        if item.kind != "fixture" or not group:
            continue
        authoritative = item.semantic_state.get("connected_mask")
        if isinstance(authoritative, int) and not isinstance(authoritative, bool):
            result[item.object_id] = authoritative & 15
            continue
        x, y = item.position.x, item.position.y
        cells_in_group = groups[group]
        result[item.object_id] = (
            (1 if (x, y - 1) in cells_in_group else 0)
            | (2 if (x + 1, y) in cells_in_group else 0)
            | (4 if (x, y + 1) in cells_in_group else 0)
            | (8 if (x - 1, y) in cells_in_group else 0)
        )
    return result


def _atlas_cell(asset: Mapping[str, Any], state: str = "idle") -> str:
    states = asset["profiles"]["ascii-safe"]
    chosen = states.get(state) or states.get("idle") or states[sorted(states)[0]]
    return str(chosen[0]["cells"][0][0])


class GardenRenderer:
    """Quantize a read-only scene projection into a terminal viewport."""

    def __init__(self, width: int, height: int) -> None:
        self.viewport = TerminalViewport(width, height)
        atlas = load_atlas()
        self._assets = {asset["id"]: asset for asset in atlas["assets"]}
        self._connected = atlas["connected_tiles"]
        self._last_lines: tuple[str, ...] = ()

    def resize(self, width: int, height: int) -> None:
        self.viewport.resize(width, height)
        self._last_lines = ()

    def render_lines(self, world: WorldState) -> list[str]:
        width = self.viewport.width
        height = self.viewport.height
        canvas_height = max(1, height - 4)
        canvas = [[" " for _ in range(width)] for _ in range(canvas_height)]
        # Presentation-only terrain continuation prevents camera pans from
        # exposing uninitialized columns; semantic terrain ownership remains
        # in the canonical scene projection.
        horizon = min(canvas_height - 1, max(1, canvas_height * 3 // 5))
        canvas[horizon] = ["."] * width
        projection = project_scene(world)
        scene = projection.scene
        author_location = None
        raw_region = scene.get("author_region") if isinstance(scene, Mapping) else None
        if isinstance(raw_region, Mapping):
            try:
                author_location = CoarseLocation.from_mapping(raw_region)
            except (TypeError, ValueError):
                author_location = None
        try:
            sky = resolve_sky_mode(
                str(scene.get("sky_mode", "storybook_fallback")),
                author_location=author_location,
            )
        except ValueError:
            sky = resolve_sky_mode("storybook_fallback")
        if sky.is_astronomical and sky.location is not None:
            when = datetime.fromtimestamp(projection.effective_time, tz=timezone.utc)
            for star in visible_stars(when, sky.location):
                x = min(width - 1, int(float(star["azimuth_degrees"]) / 360 * width))
                y = max(0, int((1 - float(star["altitude_degrees"]) / 90) * max(1, horizon - 1)))
                canvas[y][x] = "*" if float(star["visual_magnitude"]) < 0.2 else "."
        else:
            for ratio, row, glyph in ((0.18, 1, "."), (0.52, 2, "*"), (0.82, 1, ".")):
                if row < canvas_height:
                    canvas[row][min(width - 1, int(width * ratio))] = glyph
        camera = Camera(
            Point(cells(projection.camera.x), cells(projection.camera.y)),
            cells(width), cells(canvas_height),
        )
        connected_masks = _connected_masks(projection.objects)
        for item in projection.objects:
            screen = camera.world_to_screen(
                Point(cells(item.position.x), cells(item.position.y)), WORLD_DEPTH,
            )
            x, y = screen.x // 256, screen.y // 256
            symbols: list[tuple[int, int, str]] = []
            visible_organs = item.semantic_state.get("visible_organs", ())
            if item.kind == "plant" and isinstance(visible_organs, (list, tuple)):
                for organ in visible_organs:
                    if not isinstance(organ, Mapping):
                        continue
                    offset = organ.get("offset", (0, 0))
                    if not isinstance(offset, (list, tuple)) or len(offset) != 2:
                        continue
                    kind = str(organ.get("kind", "stem"))
                    glyph = {"root": "+", "stem": "|", "branch": "/", "leaf": "*",
                             "bloom": "@", "fruit": "o"}.get(kind, "*")
                    symbols.append((int(offset[0]), -int(offset[1]), glyph))
            if not symbols:
                if item.kind == "fixture":
                    catalog = str(item.semantic_state.get("catalog_id", ""))
                    group = _CONNECTED_GROUPS.get(catalog)
                    if group:
                        symbol = str(self._connected[group][str(connected_masks[item.object_id])])
                    else:
                        asset = self._assets.get(_FIXTURE_ASSET.get(catalog, f"fixture.{catalog}"))
                        symbol = _atlas_cell(asset) if asset else "F"
                elif item.kind == "animal":
                    symbol = _ANIMAL_FALLBACKS.get(
                        str(item.semantic_state.get("species_id", "")), "a",
                    )
                else:
                    symbol = _FALLBACKS.get(item.kind, "?")
                symbols.append((0, 0, symbol))
            for dx, dy, symbol in symbols:
                if item.object_id == world.ui.focus_id:
                    symbol = symbol.upper()
                if not (0 <= y + dy < canvas_height):
                    continue
                for offset, char in enumerate(symbol):
                    if 0 <= x + dx + offset < width:
                        canvas[y + dy][x + dx + offset] = char

        title = (
            f"Garden {world.world_id} · camera {projection.camera.x},{projection.camera.y} · "
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
        lines = ["".join(row) for row in canvas]
        absence = world.program_state.get("absence_summary", ())
        if isinstance(absence, (list, tuple)) and absence and canvas_height > 3:
            summary = "Welcome back: " + " · ".join(str(item) for item in absence[:3])
            lines[3] = summary[:width].ljust(width)
        return lines

    def render_diff(self, world: WorldState) -> tuple[tuple[int, int, str], ...]:
        """Return only changed cells after the initial canonical paint."""
        lines = tuple(self.render_lines(world))
        changes: list[tuple[int, int, str]] = []
        for row, line in enumerate(lines):
            previous = self._last_lines[row] if row < len(self._last_lines) else ""
            for col, char in enumerate(line):
                if col >= len(previous) or previous[col] != char:
                    changes.append((row, col, char))
        self._last_lines = lines
        return tuple(changes)

    def blit_curses(self, screen: curses.window, world: WorldState) -> None:
        for row, col, char in self.render_diff(world):
            try:
                screen.addstr(row, col, char)
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
    stdscr.erase()
    message = "Use o to select an object; a opens its semantic actions."
    while True:
        new_height, new_width = stdscr.getmaxyx()
        if (new_height, new_width) != (height, width):
            height, width = new_height, new_width
            session.resize(width, height)
            renderer.resize(width, height)
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
