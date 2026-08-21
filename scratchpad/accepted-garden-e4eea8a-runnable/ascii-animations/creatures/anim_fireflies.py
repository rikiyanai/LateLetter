#!/usr/bin/env python3
"""Firefly animation — summer night garden.

Fireflies blink using real Photinus species flash patterns.
Stars twinkle in the upper sky. Flowers silhouetted below.

Press 'q' to quit.
Run: python3 ascii-animations/creatures/anim_fireflies.py
"""
from __future__ import annotations
import curses
import math
import random
import time


FRAME_MS = 50
NUM_FIREFLIES = 18
NUM_STARS = 12

FLOWER_ROW = "  _    (_)  )Y(  _   (_)   )Y(    _    (_)  )Y(  _   (_)   )Y(    _    (_)  )Y( "


class Firefly:
    __slots__ = ('x', 'y', 'cycle_len', 'flash_times', 'flash_dur',
                 'cycle_start', 'drift_dx', 'drift_dy', 'drift_timer')

    def __init__(self, x: int, y: int, pattern: str = 'brimleyi'):
        self.x = x
        self.y = y

        if pattern == 'brimleyi':
            self.cycle_len = 20.0
            self.flash_times = [5.0, 15.0]
        elif pattern == 'macdermotti':
            self.cycle_len = 14.5
            self.flash_times = [3.0, 5.0, 10.0, 12.5]
        else:  # carolinus
            self.cycle_len = 15.0
            self.flash_times = [i * 0.5 for i in range(13)]

        self.flash_dur = 0.5
        self.cycle_start = time.monotonic() + random.uniform(-5, 5)
        self.drift_dx = 0
        self.drift_dy = 0
        self.drift_timer = 0

    def update(self, now: float, h: int, w: int) -> tuple[str, int]:
        """Returns (char, attr_flags). ' ' means invisible."""
        # Drift
        self.drift_timer -= 1
        if self.drift_timer <= 0:
            self.drift_dx = random.choice([-1, 0, 0, 0, 1])
            self.drift_dy = random.choice([0, 0, 0, -1, 1])
            self.drift_timer = random.randint(8, 25)
            self.x = max(1, min(w - 2, self.x + self.drift_dx))
            self.y = max(h // 3, min(h - 4, self.y + self.drift_dy))

        elapsed = (now - self.cycle_start) % self.cycle_len
        for ft in self.flash_times:
            if ft <= elapsed <= ft + self.flash_dur:
                mid = ft + self.flash_dur / 2
                if abs(elapsed - mid) < 0.1:
                    return '*', curses.A_BOLD
                elif elapsed < mid:
                    return '.', curses.A_NORMAL
                else:
                    return '.', curses.A_DIM
        return ' ', 0


class Star:
    __slots__ = ('x', 'y', 'phase', 'speed')

    def __init__(self, x: int, y: int):
        self.x = x
        self.y = y
        self.phase = random.uniform(0, 2 * math.pi)
        self.speed = random.uniform(0.3, 1.2)

    def char(self, now: float) -> tuple[str, int]:
        val = math.sin(now * self.speed + self.phase)
        if val > 0.6:
            return '*', curses.A_BOLD
        elif val > 0.0:
            return '.', curses.A_NORMAL
        elif val > -0.5:
            return '.', curses.A_DIM
        return ' ', 0


def main(stdscr):
    curses.curs_set(0)
    stdscr.timeout(FRAME_MS)
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_YELLOW, -1)   # firefly
    curses.init_pair(2, curses.COLOR_WHITE, -1)     # star
    curses.init_pair(3, curses.COLOR_GREEN, -1)     # flowers
    curses.init_pair(4, curses.COLOR_CYAN, -1)      # moon

    h, w = stdscr.getmaxyx()
    ground = h - 4

    # Create fireflies (lower 60%)
    patterns = ['brimleyi', 'macdermotti', 'carolinus']
    fireflies = []
    for _ in range(NUM_FIREFLIES):
        fx = random.randint(2, w - 3)
        fy = random.randint(h // 3, ground - 1)
        pat = random.choice(patterns)
        fireflies.append(Firefly(fx, fy, pat))

    # Stars (upper 30%)
    stars = []
    for _ in range(NUM_STARS):
        sx = random.randint(1, w - 2)
        sy = random.randint(0, h // 3)
        stars.append(Star(sx, sy))

    while True:
        key = stdscr.getch()
        if key in (ord('q'), ord('Q'), 27, 32):  # q/esc/space
            return

        now = time.monotonic()
        stdscr.erase()

        # Moon
        moon_x = w * 3 // 4
        moon_lines = ['  _.._  ', " .'    '.", '|   ()  |', " '.__.' "]
        for i, ml in enumerate(moon_lines):
            r = 1 + i
            c = moon_x - len(ml) // 2
            for j, ch in enumerate(ml):
                if ch != ' ' and 0 <= r < h and 0 <= c + j < w:
                    try:
                        stdscr.addch(r, c + j, ch, curses.color_pair(4))
                    except curses.error:
                        pass

        # Stars
        for star in stars:
            ch, attr = star.char(now)
            if ch != ' ' and 0 <= star.y < h and 0 <= star.x < w:
                try:
                    stdscr.addch(star.y, star.x, ch,
                                 curses.color_pair(2) | attr)
                except curses.error:
                    pass

        # Ground + flowers
        for c in range(w):
            try:
                stdscr.addch(ground + 1, c, '_', curses.A_DIM)
            except curses.error:
                pass
        flower_str = FLOWER_ROW[:w]
        try:
            stdscr.addstr(ground, 0, flower_str[:w-1],
                          curses.color_pair(3) | curses.A_DIM)
        except curses.error:
            pass

        # Fireflies
        for ff in fireflies:
            ch, attr = ff.update(now, h, w)
            if ch != ' ' and 0 <= ff.y < h and 0 <= ff.x < w:
                try:
                    stdscr.addch(ff.y, ff.x, ch,
                                 curses.color_pair(1) | attr)
                except curses.error:
                    pass

        # Status
        active = sum(1 for ff in fireflies
                     if ff.update(now, h, w)[0] != ' ')
        status = f' Summer Night · fireflies: {active}/{NUM_FIREFLIES} glowing · q=quit '
        try:
            stdscr.addstr(h - 1, 0, status[:w-1], curses.A_DIM)
        except curses.error:
            pass

        stdscr.refresh()


if __name__ == '__main__':
    curses.wrapper(main)
