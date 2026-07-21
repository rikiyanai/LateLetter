"""Read-only terminal projection for canonical Garden ``WorldState``."""

from __future__ import annotations

import curses
from datetime import datetime, timezone
from pathlib import Path
import time
from typing import Any, Mapping

from .atlas import animal_glyph, atlas_asset_frame, load_atlas, organ_glyph
from .astronomy import CoarseLocation, resolve_sky_mode, visible_stars
from .camera import Camera, DepthFactor, Point, cells, whole_cells
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
    "well": "fixture.well", "arbor": "fixture.arbor",
    "wind_chime": "fixture.wind_chime", "shed_edge": "fixture.shed_edge",
    "tool_rack": "fixture.tool_rack", "watering_can": "fixture.watering_can",
    "compost": "fixture.compost", "basket": "fixture.basket",
    "sign": "fixture.sign", "memorial_stone": "fixture.memorial_stone",
}
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

    def invalidate(self) -> None:
        """Forget the prior frame after an external owner clears the screen."""
        self._last_lines = ()

    def connected_glyph(self, group: str, mask: int) -> str:
        """Resolve any atlas-declared connected family through the paint owner."""
        if group not in self._connected:
            raise ValueError(f"unsupported connected group {group}")
        return str(self._connected[group][str(int(mask) & 15)])

    def render_lines(self, world: WorldState, *, journal_offset: int = 0) -> list[str]:
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
        for item in projection.objects:
            screen = camera.world_to_screen(
                Point(cells(item.position.x), cells(item.position.y)),
                DepthFactor(item.depth, 100),
            )
            x, y = whole_cells(screen.x), whole_cells(screen.y)
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
                    glyph = organ_glyph(kind, str(organ.get("glyph_family", "")))
                    symbols.append((int(offset[0]), -int(offset[1]), glyph))
            if not symbols:
                if item.kind == "fixture":
                    catalog = str(item.semantic_state.get("catalog_id", ""))
                    group = item.semantic_state.get("connected_group")
                    group = str(group) if group is not None else None
                    asset = self._assets.get(_FIXTURE_ASSET.get(catalog, f"fixture.{catalog}"))
                    frame = atlas_asset_frame(
                        asset, str(item.semantic_state.get("presentation_state", "idle")),
                    ) if asset else (("F",),)
                    render_cells = item.semantic_state.get("render_cells", ())
                    if isinstance(render_cells, (list, tuple)) and render_cells:
                        for cell in render_cells:
                            if not isinstance(cell, Mapping):
                                continue
                            dx, dy = int(cell.get("dx", 0)), int(cell.get("dy", 0))
                            if group and item.semantic_state.get("presentation_state") != "open":
                                mask = int(cell.get("connected_mask", 0)) & 15
                                glyph = self.connected_glyph(group, mask)
                            else:
                                glyph = frame[dy % len(frame)][dx % len(frame[0])]
                            symbols.append((dx, dy, glyph))
                    symbol = frame[0][0]
                elif item.kind == "animal":
                    symbol = animal_glyph(
                        str(item.semantic_state.get("species_id", "")),
                        int(item.semantic_state.get("bond_tier", 0)),
                        choreography=bool(item.semantic_state.get("choreography_locked", False)),
                    )
                else:
                    symbol = _FALLBACKS.get(item.kind, "?")
                if not symbols:
                    symbols.append((0, 0, symbol))
            for dx, dy, symbol in symbols:
                if item.object_id == world.ui.focus_id:
                    symbol = symbol.upper()
                if not (0 <= y + dy < canvas_height):
                    continue
                for offset, char in enumerate(symbol):
                    if 0 <= x + dx + offset < width:
                        canvas[y + dy][x + dx + offset] = char

        weather = str(scene.get("weather", "calm"))
        palette = str(scene.get("palette", "natural"))
        title = (
            f"Garden {world.world_id} · camera {projection.camera.x},{projection.camera.y} · "
            f"{weather}/{palette} · trace {len(world.event_trace)}"
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
        lines = ["".join(row) for row in canvas]
        absence = world.program_state.get("absence_summary", ())
        if isinstance(absence, (list, tuple)) and absence and canvas_height > 3:
            summary = "Welcome back: " + " · ".join(str(item) for item in absence[:3])
            lines[3] = summary[:width].ljust(width)
        missed = scene.get("missed_event_summaries", ())
        if isinstance(missed, (list, tuple)) and missed and canvas_height > 5:
            summary = "While away: " + " · ".join(str(item) for item in missed[:3])
            lines[5] = summary[:width].ljust(width)
        memorial = world.program_state.get("memorial", {})
        if isinstance(memorial, Mapping) and memorial.get("active") and canvas_height > 4:
            gifts = memorial.get("examined_gifts", ())
            summary = f"Memorial lasting · {len(gifts) if isinstance(gifts, (list, tuple)) else 0} gifts remembered"
            lines[4] = summary[:width].ljust(width)
        if world.ui.journal_open and canvas_height > 2:
            journal_rows = ["Inventory"]
            journal_rows.extend(
                f"  {index}. {item}" for index, item in enumerate(world.inventory, start=1)
            )
            if not world.inventory:
                journal_rows.append("  empty")
            journal_rows.append("Journal")
            journal_rows.extend(
                f"  {entry.label}: {entry.description}" for entry in world.journal
            )
            if not world.journal:
                journal_rows.append("  waiting")
            missed = scene.get("missed_event_summaries", ())
            if isinstance(missed, (list, tuple)) and missed:
                journal_rows.append("While you were away")
                journal_rows.extend(f"  {item}" for item in missed[:3])
            page_size = max(1, canvas_height - 2)
            offset = min(max(0, int(journal_offset)), max(0, len(journal_rows) - page_size))
            for row in range(1, canvas_height):
                lines[row] = " " * width
            for row, value in enumerate(journal_rows[offset:offset + page_size], start=1):
                lines[row] = value[:width].ljust(width)
            end = min(len(journal_rows), offset + page_size)
            footer = f"Journal {offset + 1}-{end}/{len(journal_rows)} · ↑↓ scroll · j/esc close"
            lines[-1] = footer[:width].ljust(width)
        return lines

    def render_diff(self, world: WorldState, *, journal_offset: int = 0) -> tuple[tuple[int, int, str], ...]:
        """Return only changed cells after the initial canonical paint."""
        lines = tuple(self.render_lines(world, journal_offset=journal_offset))
        changes: list[tuple[int, int, str]] = []
        for row, line in enumerate(lines):
            previous = self._last_lines[row] if row < len(self._last_lines) else ""
            for col, char in enumerate(line):
                if col >= len(previous) or previous[col] != char:
                    changes.append((row, col, char))
        self._last_lines = lines
        return tuple(changes)

    def blit_curses(self, screen: curses.window, world: WorldState, *, journal_offset: int = 0) -> None:
        for row, col, char in self.render_diff(world, journal_offset=journal_offset):
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
    try:
        curses.curs_set(0)
    except curses.error:
        pass
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
    last_live_tick = time.monotonic()
    while True:
        new_height, new_width = stdscr.getmaxyx()
        if (new_height, new_width) != (height, width):
            height, width = new_height, new_width
            session.resize(width, height)
            renderer.resize(width, height)
        renderer.blit_curses(stdscr, session.world, journal_offset=session.journal_offset)
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
            now = time.monotonic()
            elapsed = int(now - last_live_tick)
            if elapsed > 0:
                result = session.dwell(elapsed)
                message = result.summary if result.accepted else result.reason
                last_live_tick += elapsed
            continue
        was_paused = session.world.ui.motion_paused
        result = handle_terminal_key(session, key)
        if was_paused and not session.world.ui.motion_paused:
            last_live_tick = time.monotonic()
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
