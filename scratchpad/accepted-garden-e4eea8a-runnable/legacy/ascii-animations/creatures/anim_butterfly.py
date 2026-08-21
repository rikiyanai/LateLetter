#!/usr/bin/env python3
"""Butterfly animation — spring garden.

Butterflies wander left-right with occasional up-dips.
Per docs/SPEC.md §7.2: "Small >< or ^v^, wanders L-R, occasional up-dip"

Press 'q' to quit.
Run: python3 ascii-animations/creatures/anim_butterfly.py
"""
from __future__ import annotations
import curses
import math
import random


FRAME_MS = 80
NUM_BUTTERFLIES = 5

# Wing frames
WING_FRAMES = [
    [' \\ / ', '  |  ', ' / \\ '],   # open
    [' \\/ ',  '  |  ', ' /\\ '],     # half
    ['  || ',  '  |  ', '  || '],      # closed
    [' \\/ ',  '  |  ', ' /\\ '],     # half
]

SMALL_FRAMES = [
    ['><'],
    ['||'],
    ['><'],
    ['\\/'],
]

# Flower garden
FLOWERS = [
    ('  @  ', ' /|\\ ', ' /|\\ '),
    (' (*) ', '  |  ', ' /|\\ '),
    (' {*} ', '  |  ', ' /|\\ '),
    (' .-. ', '( o )', ' `-\' '),
]


class Butterfly:
    __slots__ = ('x', 'y', 'vx', 'target_x', 'wing_idx', 'flap_rate',
                 'frame', 'dip_timer', 'dipping', 'color', 'small')

    def __init__(self, x: int, y: int, small: bool = False):
        self.x = float(x)
        self.y = float(y)
        self.vx = random.choice([-0.4, 0.4])
        self.target_x = x + random.randint(-15, 15)
        self.wing_idx = random.randint(0, 3)
        self.flap_rate = random.randint(2, 4)
        self.frame = 0
        self.dip_timer = random.randint(20, 60)
        self.dipping = 0
        self.color = random.randint(1, 3)
        self.small = small

    def update(self, h: int, w: int) -> None:
        self.frame += 1

        # Flap wings
        if self.frame % self.flap_rate == 0:
            self.wing_idx = (self.wing_idx + 1) % 4

        # Horizontal drift toward target
        if abs(self.x - self.target_x) < 2:
            self.target_x = self.x + random.randint(-20, 20)
            self.vx = 0.3 if self.target_x > self.x else -0.3
        self.x += self.vx

        # Up-dip
        self.dip_timer -= 1
        if self.dip_timer <= 0:
            self.dipping = random.randint(4, 8)
            self.dip_timer = random.randint(25, 70)

        if self.dipping > 0:
            if self.dipping > 3:
                self.y -= 0.3  # up
            else:
                self.y += 0.3  # back down
            self.dipping -= 1

        # Gentle vertical bob
        self.y += 0.08 * math.sin(self.frame * 0.06)

        # Bounds
        self.x = max(2, min(w - 6, self.x))
        self.y = max(2, min(h - 6, self.y))


def main(stdscr):
    curses.curs_set(0)
    stdscr.timeout(FRAME_MS)
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_MAGENTA, -1)
    curses.init_pair(2, curses.COLOR_YELLOW, -1)
    curses.init_pair(3, curses.COLOR_CYAN, -1)
    curses.init_pair(4, curses.COLOR_GREEN, -1)
    curses.init_pair(5, curses.COLOR_RED, -1)

    h, w = stdscr.getmaxyx()
    ground = h - 4

    butterflies = []
    for _ in range(NUM_BUTTERFLIES):
        bx = random.randint(5, w - 10)
        by = random.randint(3, ground - 4)
        small = random.random() < 0.4
        butterflies.append(Butterfly(bx, by, small))

    # Place some flowers
    flower_positions = []
    for i in range(min(8, w // 10)):
        fx = random.randint(3, w - 8)
        flower = random.choice(FLOWERS)
        flower_positions.append((fx, flower))

    while True:
        key = stdscr.getch()
        if key in (ord('q'), ord('Q'), 27, 32):  # q/esc/space
            return

        stdscr.erase()

        # Ground
        for c in range(w):
            try:
                stdscr.addch(ground + 1, c, '_', curses.A_DIM)
            except curses.error:
                pass

        # Grass tufts
        for c in range(0, w, 3):
            try:
                ch = random.choice(['"', ',', "'"])
                stdscr.addch(ground, c, ch,
                             curses.color_pair(4) | curses.A_DIM)
            except curses.error:
                pass

        # Flowers
        for fx, flower in flower_positions:
            for i, line in enumerate(flower):
                r = ground - len(flower) + i + 1
                for j, ch in enumerate(line):
                    cx = fx + j
                    if ch != ' ' and 0 <= r < h and 0 <= cx < w:
                        col = curses.color_pair(5) if ch in '@*{}()' else curses.color_pair(4)
                        try:
                            stdscr.addch(r, cx, ch, col)
                        except curses.error:
                            pass

        # Butterflies
        for bf in butterflies:
            bf.update(h, w)
            ix, iy = int(bf.x), int(bf.y)

            if bf.small:
                frames = SMALL_FRAMES
                fr = frames[bf.wing_idx]
                for j, ch in enumerate(fr[0]):
                    cx = ix + j
                    if 0 <= iy < h and 0 <= cx < w:
                        try:
                            stdscr.addch(iy, cx, ch,
                                         curses.color_pair(bf.color) | curses.A_BOLD)
                        except curses.error:
                            pass
            else:
                fr = WING_FRAMES[bf.wing_idx]
                for di, line in enumerate(fr):
                    r = iy + di - 1
                    for j, ch in enumerate(line):
                        cx = ix + j - len(line) // 2
                        if ch != ' ' and 0 <= r < h and 0 <= cx < w:
                            try:
                                stdscr.addch(r, cx, ch,
                                             curses.color_pair(bf.color) | curses.A_BOLD)
                            except curses.error:
                                pass

        status = f' Spring · butterflies: {NUM_BUTTERFLIES} · q=quit '
        try:
            stdscr.addstr(h - 1, 0, status[:w-1], curses.A_DIM)
        except curses.error:
            pass

        stdscr.refresh()


if __name__ == '__main__':
    curses.wrapper(main)
