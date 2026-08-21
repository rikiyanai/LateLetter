#!/usr/bin/env python3
"""Snail animation — ground-level garden creature.

Snails crawl slowly along the ground. Crawl cycle: eyestalks spread
(reach), stalks together (pull shell forward), repeat. One char of
forward progress per full loop — snails are slow.

Hand-typed keyframes + inbetweens, Stone Story RPG method:
reference pose -> keyframes -> frame count -> inbetween frames,
frames stored as vertical lists of strings (text sprite sheet).

Press 'q' to quit.
Run: python3 ascii-animations/creatures/anim_snail.py
"""
from __future__ import annotations
import curses
import random


FRAME_MS = 120          # snails are slow — long frame time
NUM_SNAILS = 3
FRAMES_PER_STEP = 8     # one char of crawl per this many frames

# Crawl loop: reach -> pull -> reach -> bob
SNAIL_FRAMES = [
    [' @    @ ', '  \\  / ', ' _/"--"\\_', '/________\\'],   # reach
    [' @  @ ',   '  || ',   ' _/"--"\\_', '/_______\\'],    # pull
    [' @    @ ', '  \\  / ', ' _/"--"\\_', '/________\\'],   # reach
    [' @  @ ',   '  \\/ ',   ' _/"--"\\_', '/________\\'],   # bob
]

# Facing-left mirror (computed once)
def _mirror(frames):
    table = str.maketrans('/\\', '\\/')
    return [[line.translate(table)[::-1] for line in fr] for fr in frames]

SNAIL_FRAMES_L = _mirror(SNAIL_FRAMES)


class Snail:
    __slots__ = ('x', 'vx', 'frame_idx', 'frame', 'step_count', 'color')

    def __init__(self, x: int):
        self.x = float(x)
        self.vx = random.choice([-1, 1])   # direction, not speed
        self.frame_idx = random.randint(0, 3)
        self.frame = 0
        self.step_count = 0
        self.color = random.randint(1, 2)

    def update(self, w: int) -> None:
        self.frame += 1
        # Advance animation loop
        if self.frame % 2 == 0:
            self.frame_idx = (self.frame_idx + 1) % 4
        # Crawl one char per FRAMES_PER_STEP frames
        self.step_count += 1
        if self.step_count >= FRAMES_PER_STEP:
            self.step_count = 0
            self.x += self.vx
        # Turn around at edges
        if self.x < 2:
            self.vx = 1
        elif self.x > w - 12:
            self.vx = -1


def main(stdscr):
    curses.curs_set(0)
    stdscr.timeout(FRAME_MS)
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_YELLOW, -1)   # shell
    curses.init_pair(2, curses.COLOR_MAGENTA, -1)  # shell alt
    curses.init_pair(3, curses.COLOR_GREEN, -1)    # grass

    h, w = stdscr.getmaxyx()
    ground = h - 3

    snails = [Snail(random.randint(5, w - 15)) for _ in range(NUM_SNAILS)]

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
        for c in range(0, w, 4):
            try:
                ch = random.choice(['"', ',', "'"])
                stdscr.addch(ground, c, ch,
                             curses.color_pair(3) | curses.A_DIM)
            except curses.error:
                pass

        # Snails
        for sn in snails:
            sn.update(w)
            ix = int(sn.x)
            frames = SNAIL_FRAMES if sn.vx > 0 else SNAIL_FRAMES_L
            fr = frames[sn.frame_idx]
            for di, line in enumerate(fr):
                r = ground - len(fr) + di + 1
                for j, ch in enumerate(line):
                    cx = ix + j
                    if ch != ' ' and 0 <= r < h and 0 <= cx < w:
                        # eyestalks dim, shell bright
                        col = curses.color_pair(sn.color)
                        if ch in '"--':
                            col |= curses.A_BOLD
                        try:
                            stdscr.addch(r, cx, ch, col)
                        except curses.error:
                            pass

        status = f' Garden floor · snails: {NUM_SNAILS} · q=quit '
        try:
            stdscr.addstr(h - 1, 0, status[:w-1], curses.A_DIM)
        except curses.error:
            pass

        stdscr.refresh()


if __name__ == '__main__':
    curses.wrapper(main)
