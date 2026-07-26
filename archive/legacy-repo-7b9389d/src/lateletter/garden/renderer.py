"""Garden renderer — 5-layer compositor, curses main loop, ANSI output.

The compositor owns the screen buffer and all layers. Each frame:
  1. Clear the buffer
  2. Update layers that are due (per their update_interval_ms)
  3. Render all layers into the buffer back-to-front (0 → 4)
  4. Blit the buffer to the terminal (curses or ANSI)
"""
from __future__ import annotations

import curses
import math
import random
import time

from .background import BackgroundLayer
from .colors import ANSI_CODES, ANSI_RESET, curses_attr, init_curses_colors
from .creatures import CreatureLayer
from .particles import ParticleLayer
from .plants import PlantLayer
from .screen_buffer import ScreenBuffer
from .seasons import detect_season, get_weights
from .special import SpecialLayer
from .state import GardenState


class GardenRenderer:
    """5-layer compositing renderer for the garden.

    Layers (drawn back-to-front):
      0 — Background  (sky, ground)
      1 — Plants       (trees, flowers, wind sway)
      2 — Particles    (rain, snow, leaves, splashes)
      3 — Creatures    (birds, butterflies, fireflies)
      4 — Special      (letter-bird, overlays)
    """

    def __init__(self, width: int, height: int, seed: int,
                 season: str | None = None) -> None:
        self.state = GardenState(
            width, height, seed,
            season=season or detect_season(),
        )
        self.buf = ScreenBuffer(width, height)

        # Layers in draw order
        self.background = BackgroundLayer()
        self.plants = PlantLayer()
        self.particles = ParticleLayer()
        self.creatures = CreatureLayer()
        self.special = SpecialLayer()
        self._layers = [
            self.background,
            self.plants,
            self.particles,
            self.creatures,
            self.special,
        ]

        # Generate initial garden
        self.plants.regenerate(self.state, get_weights(self.state.season))

    def resize(self, width: int, height: int) -> None:
        self.state.resize(width, height)
        self.buf.resize(width, height)
        self.plants.regenerate(self.state, get_weights(self.state.season))
        for layer in self._layers:
            if layer is not self.plants:
                layer.on_resize(self.state)

    def new_seed(self, seed: int) -> None:
        self.state.seed = seed
        self.plants.regenerate(self.state, get_weights(self.state.season))

    def tick(self) -> None:
        """Advance one frame: update wind/time, update layers, composite."""
        self.state.frame += 1
        self.state.now = time.monotonic()
        self.state.wind = 0.5 * math.sin(self.state.frame * 0.008)

        # Decrement flash counter (set by lightning in particle layer)
        if self.state.flash_frames > 0:
            self.state.flash_frames -= 1

        # Update all layers
        for layer in self._layers:
            layer.update(self.state)

        # Clear and composite back-to-front
        self.buf.clear()
        for layer in self._layers:
            layer.render(self.buf, self.state)

    # ── ANSI static output ──────────────────────────────────────────

    def render_ansi(self) -> str:
        """Render a single composited frame as an ANSI string."""
        self.tick()
        lines: list[str] = []
        buf = self.buf
        for row in range(buf.height - 1):  # reserve last row for status
            line = ''
            prev_color = None
            for col in range(buf.width):
                ch, color = buf.get(row, col)
                if color != prev_color:
                    line += ANSI_RESET + ANSI_CODES.get(color, '')
                    prev_color = color
                line += ch
            lines.append(line + ANSI_RESET)
        return '\n'.join(lines)

    # ── Curses blit ─────────────────────────────────────────────────

    def blit_curses(self, scr: curses.window) -> None:
        """Write the buffer to a curses window, batching same-color runs."""
        buf = self.buf
        w = buf.width
        for row in range(buf.height - 1):  # skip status bar row
            col = 0
            while col < w:
                ch, color = buf.get(row, col)
                if ch == ' ' and color == 'sky':
                    col += 1
                    continue
                # Batch consecutive cells with the same color
                run = ch
                end = col + 1
                while end < w:
                    nch, ncol = buf.get(row, end)
                    if ncol != color:
                        break
                    run += nch
                    end += 1
                try:
                    scr.addstr(row, col, run, curses_attr(color))
                except curses.error:
                    pass
                col = end


# ── Curses main loop ────────────────────────────────────────────────

def run_curses(stdscr: curses.window, seed: int,
               season: str | None = None) -> None:
    """Interactive curses garden with keyboard controls."""
    init_curses_colors()
    curses.curs_set(0)
    stdscr.nodelay(True)

    h, w = stdscr.getmaxyx()
    renderer = GardenRenderer(w, h, seed, season=season)

    while True:
        nh, nw = stdscr.getmaxyx()
        if (nh, nw) != (h, w):
            h, w = nh, nw
            renderer.resize(w, h)

        stdscr.erase()
        renderer.tick()
        renderer.blit_curses(stdscr)

        # Lightning flash (DECSCNM reverse video)
        if renderer.state.flash_frames > 0:
            try:
                curses.flash()
            except curses.error:
                pass

        # Status bar
        bar = f'  seed={renderer.state.seed}  q=quit  r=new garden  '
        try:
            stdscr.addstr(h - 1, 0, bar[:w].ljust(w), curses.A_REVERSE)
        except curses.error:
            pass

        stdscr.refresh()

        key = stdscr.getch()
        if key == ord('q'):
            break
        if key == ord('r'):
            new_seed = random.randint(0, 99999)
            renderer.new_seed(new_seed)

        time.sleep(0.05)


# ── ANSI static entry point ────────────────────────────────────────

def print_ansi(width: int, height: int, seed: int,
               season: str | None = None) -> None:
    """Print a single static ANSI frame to stdout."""
    renderer = GardenRenderer(width, height, seed, season=season)
    print(renderer.render_ansi())
    print(f'\033[2m  --seed {seed}  |  q quit · r new garden\033[0m')
