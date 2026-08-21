#!/usr/bin/env python3
"""Ambient birds — flying across the sky.

Flocks in V-formation cross the screen. Individual birds flap wings.
Per docs/SPEC.md §7.2: "V or > formation across sky"

Press 'q' to quit.
Run: python3 ascii-animations/creatures/anim_birds.py
"""
from __future__ import annotations
import curses
import random


FRAME_MS = 100

# Bird flap frames (2 chars each)
FLAP_FRAMES = [
    ('\\', '/'),   # wings up
    ('_', '_'),    # wings level
    ('/', '\\'),   # wings down
    ('_', '_'),    # wings level
]


class Bird:
    __slots__ = ('x', 'y', 'vx', 'flap_idx', 'flap_rate', 'frame')

    def __init__(self, x: int, y: int, vx: float = 0.8):
        self.x = float(x)
        self.y = float(y)
        self.vx = vx
        self.flap_idx = random.randint(0, len(FLAP_FRAMES) - 1)
        self.flap_rate = random.randint(2, 4)
        self.frame = random.randint(0, 10)

    def update(self) -> None:
        self.frame += 1
        self.x += self.vx
        if self.frame % self.flap_rate == 0:
            self.flap_idx = (self.flap_idx + 1) % len(FLAP_FRAMES)


class Flock:
    """V-formation of birds."""
    __slots__ = ('birds', 'active')

    def __init__(self, start_x: int, start_y: int, count: int, vx: float):
        self.birds: list[Bird] = []
        self.active = True
        for i in range(count):
            # V pattern: leader in front, wings spread back
            if i == 0:
                bx, by = start_x, start_y
            elif i % 2 == 1:
                bx = start_x - (i + 1) // 2 * 3
                by = start_y + (i + 1) // 2
            else:
                bx = start_x - i // 2 * 3
                by = start_y - i // 2
            self.birds.append(Bird(bx, by, vx))

    def update(self, w: int) -> None:
        for bird in self.birds:
            bird.update()
        # Check if flock has exited screen
        if all(b.x > w + 5 or b.x < -5 for b in self.birds):
            self.active = False


def main(stdscr):
    curses.curs_set(0)
    stdscr.timeout(FRAME_MS)
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_WHITE, -1)
    curses.init_pair(2, curses.COLOR_CYAN, -1)

    h, w = stdscr.getmaxyx()

    flocks: list[Flock] = []
    # Start with one flock
    flocks.append(Flock(-5, random.randint(2, h // 3),
                        random.randint(3, 7), random.uniform(0.6, 1.2)))

    # Solo birds
    solos: list[Bird] = []

    frame = 0
    while True:
        key = stdscr.getch()
        if key in (ord('q'), ord('Q'), 27, 32):  # q/esc/space
            return

        frame += 1

        # Spawn new flocks
        if random.random() < 0.008:
            direction = random.choice([-1, 1])
            sx = -8 if direction > 0 else w + 8
            sy = random.randint(1, h // 3)
            count = random.randint(3, 7)
            vx = random.uniform(0.5, 1.0) * direction
            flocks.append(Flock(sx, sy, count, vx))

        # Spawn solo birds
        if random.random() < 0.015:
            direction = random.choice([-1, 1])
            sx = -3 if direction > 0 else w + 3
            sy = random.randint(1, h // 2)
            vx = random.uniform(0.8, 1.5) * direction
            solos.append(Bird(sx, sy, vx))

        # Update
        for flock in flocks:
            flock.update(w)
        flocks = [f for f in flocks if f.active]

        alive_solos = []
        for bird in solos:
            bird.update()
            if -5 < bird.x < w + 5:
                alive_solos.append(bird)
        solos = alive_solos

        # Draw
        stdscr.erase()

        # Sky gradient (subtle)
        for r in range(min(h // 4, 6)):
            for c in range(w):
                try:
                    stdscr.addch(r, c, ' ')
                except curses.error:
                    pass

        # Ground
        ground = h - 3
        for c in range(w):
            try:
                stdscr.addch(ground, c, '_', curses.A_DIM)
            except curses.error:
                pass

        # Simple landscape
        hill = "  _.-~-._    _.-~-._    _.-~-._    _.-~-._  "
        hill_row = (hill * ((w // len(hill)) + 2))[:w]
        try:
            stdscr.addstr(ground - 1, 0, hill_row[:w-1], curses.A_DIM)
        except curses.error:
            pass

        # Draw flocks
        total_birds = 0
        for flock in flocks:
            for bird in flock.birds:
                ix, iy = int(bird.x), int(bird.y)
                lw, rw = FLAP_FRAMES[bird.flap_idx]
                for dx, ch in [(-1, lw), (0, 'v'), (1, rw)]:
                    cx = ix + dx
                    if 0 <= iy < h and 0 <= cx < w:
                        try:
                            stdscr.addch(iy, cx, ch,
                                         curses.color_pair(1) | curses.A_BOLD)
                        except curses.error:
                            pass
                total_birds += 1

        # Draw solos (slightly different rendering)
        for bird in solos:
            ix, iy = int(bird.x), int(bird.y)
            lw, rw = FLAP_FRAMES[bird.flap_idx]
            for dx, ch in [(-1, lw), (0, 'o'), (1, rw)]:
                cx = ix + dx
                if 0 <= iy < h and 0 <= cx < w:
                    try:
                        stdscr.addch(iy, cx, ch, curses.color_pair(2))
                    except curses.error:
                        pass
            total_birds += 1

        status = f' Sky · birds: {total_birds} · flocks: {len(flocks)} · q=quit '
        try:
            stdscr.addstr(h - 1, 0, status[:w-1], curses.A_DIM)
        except curses.error:
            pass

        stdscr.refresh()


if __name__ == '__main__':
    curses.wrapper(main)
