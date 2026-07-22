#!/usr/bin/env python3
"""Snow animation — winter garden.

Slow-drifting snowflakes with sine-wave horizontal oscillation.
Flakes accumulate on the ground and on a small tree.

Press 'q' to quit.
Run: python3 ascii-animations/weather/anim_snow.py
"""
from __future__ import annotations
import curses
import math
import random


FRAME_MS = 60
MAX_FLAKES = 30
SNOW_CHARS = ['.', '*', '.', '*', '.']

BARE_TREE = [
    '    /\\  /\\    ',
    '   /  \\/  \\   ',
    '  /\\  /\\  /\\  ',
    '   \\/  \\/     ',
    '    \\  /      ',
    '     ||       ',
    '     ||       ',
    '     ||       ',
]


class Flake:
    __slots__ = ('x', 'y', 'vy', 'phase', 'freq', 'amp', 'char', 'frame')

    def __init__(self, w: int):
        self.x = float(random.randint(0, max(0, w - 1)))
        self.y = float(random.randint(-8, -1))
        self.vy = random.uniform(0.08, 0.22)
        self.phase = random.uniform(0, 2 * math.pi)
        self.freq = random.uniform(0.03, 0.08)
        self.amp = random.uniform(0.8, 2.5)
        self.char = random.choice(SNOW_CHARS)
        self.frame = 0

    def update(self) -> None:
        self.frame += 1
        self.y += self.vy
        vx = self.amp * math.sin(self.frame * self.freq + self.phase)
        self.x += vx * 0.15


def main(stdscr):
    curses.curs_set(0)
    stdscr.timeout(FRAME_MS)
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_WHITE, -1)
    curses.init_pair(2, curses.COLOR_CYAN, -1)

    h, w = stdscr.getmaxyx()
    ground = h - 3
    tree_x = w // 2

    flakes: list[Flake] = []
    # Snow accumulation: ground_snow[col] = height (0 = no snow)
    ground_snow: dict[int, int] = {}

    # Build tree collision set
    tree_top = ground - len(BARE_TREE)
    tree_cells: set[tuple[int, int]] = set()
    for i, line in enumerate(BARE_TREE):
        r = tree_top + i
        cx = tree_x - len(line) // 2
        for j, ch in enumerate(line):
            if ch != ' ':
                tree_cells.add((r, cx + j))

    frame = 0
    while True:
        key = stdscr.getch()
        if key in (ord('q'), ord('Q'), 27, 32):  # q/esc/space
            return
        if key == curses.KEY_RESIZE:
            h, w = stdscr.getmaxyx()
            ground = h - 3

        frame += 1

        # Spawn
        if random.random() < 0.15 and len(flakes) < MAX_FLAKES:
            flakes.append(Flake(w))

        # Update
        alive = []
        for f in flakes:
            f.update()
            ix, iy = int(f.x), int(f.y)
            snow_h = ground_snow.get(ix, 0)
            effective_ground = ground - snow_h

            if iy >= effective_ground:
                # Accumulate
                if 0 <= ix < w:
                    ground_snow[ix] = ground_snow.get(ix, 0) + 1
            elif (iy, ix) in tree_cells:
                # Land on tree — show as snow on tree
                tree_cells.add((iy - 1, ix))  # snow sits on top
            elif 0 <= ix < w and 0 <= iy < h:
                alive.append(f)
        flakes = alive

        # Draw
        stdscr.erase()

        # Ground
        for c in range(w):
            snow_h = ground_snow.get(c, 0)
            for s in range(min(snow_h, 4)):
                r = ground - s
                if 0 <= r < h:
                    try:
                        ch = '*' if (c + s) % 3 == 0 else '.'
                        stdscr.addch(r, c, ch, curses.color_pair(1) | curses.A_BOLD)
                    except curses.error:
                        pass
            try:
                stdscr.addch(ground, c, '_', curses.A_DIM)
            except curses.error:
                pass

        # Tree
        for i, line in enumerate(BARE_TREE):
            r = tree_top + i
            cx = tree_x - len(line) // 2
            for j, ch in enumerate(line):
                if ch != ' ' and 0 <= r < h and 0 <= cx + j < w:
                    try:
                        stdscr.addch(r, cx + j, ch, curses.color_pair(2))
                    except curses.error:
                        pass

        # Falling flakes
        for f in flakes:
            ix, iy = int(f.x), int(f.y)
            if 0 <= iy < h and 0 <= ix < w:
                try:
                    stdscr.addch(iy, ix, f.char,
                                 curses.color_pair(1) | curses.A_BOLD)
                except curses.error:
                    pass

        # Status
        snow_total = sum(ground_snow.values())
        status = f' Winter · flakes: {len(flakes)} · accumulated: {snow_total} · q=quit '
        try:
            stdscr.addstr(h - 1, 0, status[:w-1], curses.A_DIM)
        except curses.error:
            pass

        stdscr.refresh()


if __name__ == '__main__':
    curses.wrapper(main)
