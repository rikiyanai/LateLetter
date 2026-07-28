#!/usr/bin/env python3
"""Falling leaves — autumn garden animation.

Leaves drift diagonally with sine-wave oscillation and tumble rotation.
Wind gusts shift all leaves together. Leaves accumulate on ground.

Press 'q' to quit.
Run: python3 ascii-animations/nature/anim_leaves.py
"""
from __future__ import annotations
import curses
import math
import random
import time


FRAME_MS = 40
MAX_LEAVES = 35
SPAWN_RATE = 0.12  # probability per frame

LEAF_CHARS = [',', "'", '~', '*', '>', '<', '.']
AUTUMN_COLORS = [curses.COLOR_RED, curses.COLOR_YELLOW, curses.COLOR_WHITE]

# Simple tree shape (relative to tree_x, tree_top)
TREE_TRUNK = '|'
TREE_CANOPY = [
    '    ###    ',
    '   #####   ',
    '  .#.#.#.  ',
    ' .#.#.#.#. ',
    '.#.#.#.#.#.',
    ' .#.#.#.#. ',
    '  .#.#.#.  ',
]


class Leaf:
    __slots__ = ('x', 'y', 'vx', 'vy', 'phase', 'freq', 'amp',
                 'char_idx', 'tumble_rate', 'frame', 'color')

    def __init__(self, x: float, y: float):
        self.x = x
        self.y = y
        self.vx = 0.0
        self.vy = random.uniform(0.15, 0.40)
        self.phase = random.uniform(0, 2 * math.pi)
        self.freq = random.uniform(0.04, 0.12)
        self.amp = random.uniform(1.0, 3.5)
        self.char_idx = random.randint(0, len(LEAF_CHARS) - 1)
        self.tumble_rate = random.randint(3, 8)
        self.frame = 0
        self.color = random.randint(1, 3)

    def update(self, wind: float) -> None:
        self.frame += 1
        self.vy = 0.25 + 0.08 * math.sin(self.frame * 0.08)
        self.y += self.vy
        self.vx = self.amp * math.sin(self.frame * self.freq + self.phase)
        self.x += self.vx * 0.25 + wind * 0.15
        if self.frame % self.tumble_rate == 0:
            self.char_idx = (self.char_idx + 1) % len(LEAF_CHARS)

    @property
    def char(self) -> str:
        return LEAF_CHARS[self.char_idx]


def wind_value(frame: int) -> float:
    base = 0.6 * math.sin(frame * 0.008)
    gust = 0.0
    if random.random() < 0.015:
        gust = random.uniform(1.5, 4.0) * random.choice([-1, 1])
    return base + gust


def draw_tree(stdscr, tx: int, top: int, h: int, w: int, ground: int):
    # Canopy
    for i, line in enumerate(TREE_CANOPY):
        r = top + i
        c = tx - len(line) // 2
        for j, ch in enumerate(line):
            cc = c + j
            if 0 <= r < h and 0 <= cc < w and ch != ' ':
                try:
                    attr = curses.color_pair(2) if ch == '#' else curses.color_pair(3)
                    stdscr.addch(r, cc, ch, attr)
                except curses.error:
                    pass
    # Trunk
    trunk_top = top + len(TREE_CANOPY)
    for r in range(trunk_top, ground):
        if 0 <= r < h and 0 <= tx < w:
            try:
                stdscr.addch(r, tx, '|', curses.color_pair(4))
            except curses.error:
                pass


def main(stdscr):
    curses.curs_set(0)
    stdscr.timeout(FRAME_MS)
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_RED, -1)
    curses.init_pair(2, curses.COLOR_YELLOW, -1)
    curses.init_pair(3, curses.COLOR_GREEN, -1)
    curses.init_pair(4, curses.COLOR_WHITE, -1)

    h, w = stdscr.getmaxyx()
    ground = h - 2
    tree_x = w // 2
    tree_top = max(2, ground - len(TREE_CANOPY) - 6)
    canopy_w = len(TREE_CANOPY[-1]) // 2

    leaves: list[Leaf] = []
    ground_leaves: list[tuple[int, str, int]] = []
    frame = 0

    while True:
        key = stdscr.getch()
        if key in (ord('q'), ord('Q'), 27, 32):  # q/esc/space
            return

        frame += 1
        wind = wind_value(frame)

        # Spawn
        if random.random() < SPAWN_RATE and len(leaves) < MAX_LEAVES:
            lx = tree_x + random.randint(-canopy_w, canopy_w)
            ly = tree_top + random.randint(0, len(TREE_CANOPY) - 1)
            leaves.append(Leaf(float(lx), float(ly)))

        # Update
        alive = []
        for leaf in leaves:
            leaf.update(wind)
            ix, iy = int(leaf.x), int(leaf.y)
            if iy >= ground:
                if 0 <= ix < w:
                    ground_leaves.append((ix, leaf.char, leaf.color))
                    if len(ground_leaves) > w:
                        ground_leaves = ground_leaves[-w:]
            elif 0 <= ix < w and 0 <= iy < h:
                alive.append(leaf)
        leaves = alive

        # Draw
        stdscr.erase()

        # Ground line
        for c in range(w):
            try:
                stdscr.addch(ground, c, '_', curses.A_DIM)
            except curses.error:
                pass

        # Settled leaves
        for gx, gc, gcol in ground_leaves:
            if 0 <= gx < w:
                try:
                    stdscr.addch(ground, gx, gc, curses.color_pair(gcol))
                except curses.error:
                    pass

        # Tree
        draw_tree(stdscr, tree_x, tree_top, h, w, ground)

        # Falling leaves
        for leaf in leaves:
            ix, iy = int(leaf.x), int(leaf.y)
            if 0 <= iy < h and 0 <= ix < w:
                try:
                    stdscr.addch(iy, ix, leaf.char,
                                 curses.color_pair(leaf.color) | curses.A_BOLD)
                except curses.error:
                    pass

        # Status
        wind_dir = '>>>' if wind > 1.5 else '>>' if wind > 0.5 else '~>' if wind > 0 else '<~' if wind > -0.5 else '<<' if wind > -1.5 else '<<<'
        status = f' Autumn · leaves: {len(leaves)} · wind: {wind_dir} · q=quit '
        try:
            stdscr.addstr(h - 1, 0, status[:w-1], curses.A_DIM)
        except curses.error:
            pass

        stdscr.refresh()


if __name__ == '__main__':
    curses.wrapper(main)
