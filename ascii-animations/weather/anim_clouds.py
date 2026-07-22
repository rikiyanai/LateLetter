#!/usr/bin/env python3
"""Cloud drift — sky animation.

Clouds of various sizes drift slowly left across the sky.
Per docs/SPEC.md §7.2: "(~~~) shapes drifting slowly left at sky row"

Press 'q' to quit.
Run: python3 ascii-animations/weather/anim_clouds.py
"""
from __future__ import annotations
import curses
import random


FRAME_MS = 120

CLOUD_SHAPES = [
    # Tiny
    ['(~)'],
    # Small
    ['(~~~)'],
    # Medium
    ['.--~~~--.', "'~~~~~~'"],
    # Large
    [' .~~~--~~~~--.', '(~~~~~~~~~~~~~)', " '~~~~~~~~~~'"],
    # Puffy
    ['   .-~~-.', ' .(      ).', '(___.__)___.)'],
]


class Cloud:
    __slots__ = ('x', 'y', 'vx', 'shape', 'width')

    def __init__(self, x: float, y: int, shape_idx: int = -1):
        self.x = x
        self.y = y
        if shape_idx < 0:
            shape_idx = random.randint(0, len(CLOUD_SHAPES) - 1)
        self.shape = CLOUD_SHAPES[shape_idx]
        self.width = max(len(line) for line in self.shape)
        self.vx = random.uniform(-0.15, -0.05)


def main(stdscr):
    curses.curs_set(0)
    stdscr.timeout(FRAME_MS)
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_WHITE, -1)
    curses.init_pair(2, curses.COLOR_CYAN, -1)
    curses.init_pair(3, curses.COLOR_GREEN, -1)
    curses.init_pair(4, curses.COLOR_YELLOW, -1)

    h, w = stdscr.getmaxyx()
    sky_rows = max(2, h // 3)
    ground = h - 3

    # Initial clouds
    clouds: list[Cloud] = []
    for _ in range(4):
        cx = random.randint(0, w)
        cy = random.randint(1, sky_rows)
        clouds.append(Cloud(float(cx), cy))

    # Sun
    sun_x = w - 12
    sun_lines = [
        '  \\  |  /  ',
        '   .-\'-. ',
        '--- (   ) ---',
        "   '-._-' ",
        '  /  |  \\  ',
    ]

    frame = 0
    while True:
        key = stdscr.getch()
        if key in (ord('q'), ord('Q'), 27, 32):  # q/esc/space
            return

        frame += 1

        # Spawn new clouds
        if random.random() < 0.008 and len(clouds) < 8:
            cy = random.randint(1, sky_rows)
            clouds.append(Cloud(float(w + 5), cy))

        # Update clouds
        alive = []
        for cloud in clouds:
            cloud.x += cloud.vx
            if cloud.x + cloud.width > -5:
                alive.append(cloud)
        clouds = alive

        # Draw
        stdscr.erase()

        # Sun
        for i, line in enumerate(sun_lines):
            r = 2 + i
            cx = sun_x - len(line) // 2
            for j, ch in enumerate(line):
                cc = cx + j
                if ch != ' ' and 0 <= r < h and 0 <= cc < w:
                    try:
                        stdscr.addch(r, cc, ch,
                                     curses.color_pair(4) | curses.A_BOLD)
                    except curses.error:
                        pass

        # Clouds
        for cloud in clouds:
            for di, line in enumerate(cloud.shape):
                r = cloud.y + di
                for j, ch in enumerate(line):
                    cc = int(cloud.x) + j
                    if ch != ' ' and 0 <= r < h and 0 <= cc < w:
                        try:
                            stdscr.addch(r, cc, ch,
                                         curses.color_pair(1) | curses.A_BOLD)
                        except curses.error:
                            pass

        # Ground
        for c in range(w):
            try:
                stdscr.addch(ground, c, '_', curses.A_DIM)
            except curses.error:
                pass

        # Some grass
        grass = "  _.-~-._    " * ((w // 14) + 2)
        try:
            stdscr.addstr(ground - 1, 0, grass[:w-1],
                          curses.color_pair(3) | curses.A_DIM)
        except curses.error:
            pass

        # Trees on horizon
        tree_str = "  /\\    /\\  ||  /\\  "
        tree_row = (tree_str * ((w // len(tree_str)) + 1))[:w]
        try:
            stdscr.addstr(ground - 2, 0, tree_row[:w-1],
                          curses.color_pair(3) | curses.A_DIM)
        except curses.error:
            pass

        status = f' Sky · clouds: {len(clouds)} · q=quit '
        try:
            stdscr.addstr(h - 1, 0, status[:w-1], curses.A_DIM)
        except curses.error:
            pass

        stdscr.refresh()


if __name__ == '__main__':
    curses.wrapper(main)
