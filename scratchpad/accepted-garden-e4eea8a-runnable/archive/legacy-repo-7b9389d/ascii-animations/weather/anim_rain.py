#!/usr/bin/env python3
"""Rain + Lightning storm animation.

Diagonal rain with variable speed, ground splashes, and periodic lightning.
Based on anim_J_bounce.py physics patterns from asciicker.

Press 'q' to quit.
Run: python3 ascii-animations/weather/anim_rain.py
"""
from __future__ import annotations
import curses
import math
import random
import time


FRAME_MS = 40
MAX_DROPS = 50
GRAVITY = 0.06
RAIN_VX = 0.20
RAIN_VY = (0.4, 1.6)
SPLASH_LIFE = 6
BOLT_LIFE_S = 0.6
BOLT_INTERVAL = (4.0, 10.0)


class Drop:
    __slots__ = ('x', 'y', 'vx', 'vy')

    def __init__(self, w: int):
        self.x = float(random.randint(0, max(0, w - 1)))
        self.y = float(random.randint(-12, -1))
        self.vx = max(0.0, RAIN_VX + random.gauss(0, 0.10))
        self.vy = random.uniform(*RAIN_VY)


class Splash:
    __slots__ = ('x', 'dx', 'life')

    def __init__(self, x: int):
        self.x = float(x)
        self.dx = random.choice([-1, 1]) * random.uniform(0.3, 1.5)
        self.life = random.randint(3, SPLASH_LIFE)


class BoltSeg:
    __slots__ = ('r', 'c', 't')

    def __init__(self, r: int, c: int, t: float):
        self.r = r
        self.c = c
        self.t = t


def make_bolt(h: int, w: int, now: float) -> list[BoltSeg]:
    segs = []
    ground = h - 3
    c = random.randint(w // 6, w * 5 // 6)
    r = 0
    while r < ground:
        segs.append(BoltSeg(r, c, now))
        r += 1
        c += random.choice([-2, -1, -1, 0, 0, 0, 0, 1, 1, 2])
        c = max(1, min(w - 2, c))
    # One fork
    if len(segs) > 5:
        fork_seg = segs[len(segs) // 3]
        fr, fc = fork_seg.r, fork_seg.c
        direction = random.choice([-3, 3])
        for _ in range(random.randint(3, 8)):
            fr += 1
            fc += direction + random.choice([-1, 0, 0, 1])
            fc = max(1, min(w - 2, fc))
            if fr >= ground:
                break
            segs.append(BoltSeg(fr, fc, now))
    return segs


def main(stdscr):
    curses.curs_set(0)
    stdscr.timeout(FRAME_MS)
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_CYAN, -1)      # rain
    curses.init_pair(2, curses.COLOR_WHITE, -1)      # splash
    curses.init_pair(3, curses.COLOR_YELLOW, -1)     # bolt bright
    curses.init_pair(4, curses.COLOR_WHITE, -1)      # bolt dim

    h, w = stdscr.getmaxyx()
    ground = h - 3

    drops: list[Drop] = [Drop(w) for _ in range(MAX_DROPS // 2)]
    splashes: list[Splash] = []
    bolts: list[list[BoltSeg]] = []
    next_bolt = time.monotonic() + random.uniform(2.0, 4.0)
    flash_frames = 0

    while True:
        key = stdscr.getch()
        if key in (ord('q'), ord('Q'), 27, 32):  # q/esc/space
            return
        if key == curses.KEY_RESIZE:
            h, w = stdscr.getmaxyx()
            ground = h - 3

        now = time.monotonic()

        # Lightning
        if now >= next_bolt:
            bolts.append(make_bolt(h, w, now))
            next_bolt = now + random.uniform(*BOLT_INTERVAL)
            flash_frames = 2
            try:
                curses.flash()
            except curses.error:
                pass

        # Expire bolts
        bolts = [b for b in bolts if any(now - s.t < BOLT_LIFE_S for s in b)]

        # Update drops
        alive_drops = []
        new_splashes = []
        for d in drops:
            d.vy += GRAVITY
            d.x += d.vx
            d.y += d.vy
            ix, iy = int(d.x), int(d.y)
            if iy >= ground:
                new_splashes.append(Splash(ix))
                continue
            if ix < 0 or ix >= w:
                continue
            alive_drops.append(d)
        drops = alive_drops

        # Refill drops
        while len(drops) < MAX_DROPS:
            drops.append(Drop(w))

        # Update splashes
        splashes.extend(new_splashes)
        alive_splashes = []
        for s in splashes:
            s.x += s.dx
            s.life -= 1
            if s.life > 0:
                alive_splashes.append(s)
        splashes = alive_splashes

        # Draw
        stdscr.erase()

        # Ground
        for c in range(w):
            try:
                stdscr.addch(ground, c, '_', curses.A_DIM)
            except curses.error:
                pass

        # Drops
        for d in drops:
            ix, iy = int(d.x), int(d.y)
            if 0 <= iy < h and 0 <= ix < w:
                ch = '\\' if d.vx > 0.15 else '|'
                try:
                    stdscr.addch(iy, ix, ch, curses.color_pair(1) | curses.A_DIM)
                except curses.error:
                    pass

        # Splashes
        for s in splashes:
            ix = int(s.x)
            if 0 <= ix < w:
                ch = "'" if s.life > 3 else '.'
                try:
                    stdscr.addch(ground, ix, ch, curses.color_pair(2) | curses.A_BOLD)
                except curses.error:
                    pass

        # Bolts
        for bolt in bolts:
            for seg in bolt:
                age = now - seg.t
                if age >= BOLT_LIFE_S:
                    continue
                frac = age / BOLT_LIFE_S
                if frac < 0.2:
                    ch, attr = '#', curses.color_pair(3) | curses.A_BOLD
                elif frac < 0.5:
                    ch, attr = '+', curses.color_pair(3)
                else:
                    ch, attr = '*', curses.color_pair(4) | curses.A_DIM
                if 0 <= seg.r < h and 0 <= seg.c < w:
                    try:
                        stdscr.addch(seg.r, seg.c, ch, attr)
                    except curses.error:
                        pass

        # Status
        status = f' Storm · drops: {len(drops)} · q=quit '
        try:
            stdscr.addstr(h - 1, 0, status[:w-1], curses.A_DIM)
        except curses.error:
            pass

        stdscr.refresh()


if __name__ == '__main__':
    curses.wrapper(main)
