#!/usr/bin/env python3
"""Combined garden scene — all animations layered together.

Shows a garden with tree, flowers, falling leaves, drifting clouds,
a butterfly, and fireflies at dusk. Cycles through seasons.

Press 'q' to quit, 's' to change season.
Run: python3 ascii-animations/anim_garden.py
"""
from __future__ import annotations
import curses
import math
import random
import time


FRAME_MS = 50

SEASONS = ['spring', 'summer', 'autumn', 'winter']
SEASON_COLORS = {
    'spring': {'leaf': curses.COLOR_GREEN, 'sky': curses.COLOR_CYAN},
    'summer': {'leaf': curses.COLOR_GREEN, 'sky': curses.COLOR_BLUE},
    'autumn': {'leaf': curses.COLOR_RED, 'sky': curses.COLOR_YELLOW},
    'winter': {'leaf': curses.COLOR_WHITE, 'sky': curses.COLOR_WHITE},
}

TREE_CANOPY_FULL = [
    '     @@@@@     ',
    '   @@@@@@@@@   ',
    '  @@@@@@@@@@@  ',
    ' @@@@@@@@@@@@@ ',
    '  @@@@@@@@@@@  ',
    '   @@@@@@@@@   ',
]

TREE_CANOPY_AUTUMN = [
    '     .o.o.     ',
    '   .o. .o.o.   ',
    '  .o .  o. .o  ',
    ' .o  .o   .o.o ',
    '  .o  .o .o .  ',
    '   .  .o .o    ',
]

TREE_CANOPY_BARE = [
    '    /\\  /\\     ',
    '   /  \\/  \\    ',
    '  /\\  /\\  /\\   ',
    '   \\/  \\/      ',
    '    \\  /       ',
]

TREE_TRUNK = [
    '      |||      ',
    '      |||      ',
    '      |||      ',
]

FLOWER_SMALL = [' (*) ', '  |  ', ' /|\\ ']
FLOWER_TINY = [' @ ', ' | ']


class Particle:
    """Generic particle for rain/snow/leaves."""
    __slots__ = ('x', 'y', 'vx', 'vy', 'char', 'color', 'life',
                 'phase', 'freq', 'amp', 'frame')

    def __init__(self, x, y, vx, vy, char, color, life=-1):
        self.x = float(x)
        self.y = float(y)
        self.vx = vx
        self.vy = vy
        self.char = char
        self.color = color
        self.life = life
        self.phase = random.uniform(0, 6.28)
        self.freq = random.uniform(0.04, 0.12)
        self.amp = random.uniform(1.0, 3.0)
        self.frame = 0


class Cloud:
    __slots__ = ('x', 'y', 'vx', 'shape')

    def __init__(self, x, y):
        self.x = float(x)
        self.y = y
        self.vx = random.uniform(-0.08, -0.03)
        shapes = [['(~)'], ['(~~~)'], ['.--~~--.', "'~~~~~~'"]]
        self.shape = random.choice(shapes)


class Creature:
    """Butterfly or bird."""
    __slots__ = ('x', 'y', 'vx', 'kind', 'frame_idx', 'frame', 'phase')

    def __init__(self, x, y, kind='butterfly'):
        self.x = float(x)
        self.y = float(y)
        self.vx = random.choice([-0.3, 0.3])
        self.kind = kind
        self.frame_idx = 0
        self.frame = 0
        self.phase = random.uniform(0, 6.28)


class Firefly:
    __slots__ = ('x', 'y', 'cycle_start', 'flash_times', 'cycle_len')

    def __init__(self, x, y):
        self.x = x
        self.y = y
        self.cycle_len = random.uniform(15, 22)
        self.flash_times = sorted([random.uniform(0, self.cycle_len)
                                   for _ in range(2)])
        self.cycle_start = time.monotonic() + random.uniform(-5, 5)

    def visible(self, now):
        elapsed = (now - self.cycle_start) % self.cycle_len
        for ft in self.flash_times:
            if ft <= elapsed <= ft + 0.5:
                return True
        return False


def main(stdscr):
    curses.curs_set(0)
    stdscr.timeout(FRAME_MS)
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_GREEN, -1)     # tree/flowers
    curses.init_pair(2, curses.COLOR_RED, -1)        # autumn leaves
    curses.init_pair(3, curses.COLOR_YELLOW, -1)     # firefly/sun
    curses.init_pair(4, curses.COLOR_WHITE, -1)      # snow/clouds
    curses.init_pair(5, curses.COLOR_CYAN, -1)       # rain/sky
    curses.init_pair(6, curses.COLOR_MAGENTA, -1)    # butterfly

    h, w = stdscr.getmaxyx()
    ground = h - 3
    tree_x = w // 3
    season_idx = 2  # start with autumn (most visual)
    season = SEASONS[season_idx]

    particles: list[Particle] = []
    clouds: list[Cloud] = []
    creatures: list[Creature] = []
    fireflies: list[Firefly] = []

    # Init clouds
    for _ in range(3):
        clouds.append(Cloud(random.randint(0, w), random.randint(1, 4)))

    # Init flowers
    flower_xs = [w * 2 // 3, w * 2 // 3 + 8, w * 3 // 4,
                 w // 6, w // 8, w * 5 // 6]

    frame = 0

    while True:
        key = stdscr.getch()
        if key in (ord('q'), ord('Q'), 27, 32):  # q/esc/space
            return
        if key in (ord('s'), ord('S')):
            season_idx = (season_idx + 1) % 4
            season = SEASONS[season_idx]
            particles.clear()
            creatures.clear()
            fireflies.clear()

        frame += 1
        now = time.monotonic()
        wind = 0.5 * math.sin(frame * 0.008)

        # --- Spawn season-specific particles ---
        if season == 'autumn' and random.random() < 0.08 and len(particles) < 25:
            canopy = TREE_CANOPY_AUTUMN
            lx = tree_x + random.randint(-6, 6)
            ly = ground - len(TREE_TRUNK) - len(canopy) + random.randint(0, 3)
            ch = random.choice([',', "'", '~', '*'])
            particles.append(Particle(lx, ly, 0, 0.2, ch, 2))

        if season == 'winter' and random.random() < 0.12 and len(particles) < 25:
            particles.append(Particle(
                random.randint(0, w), random.randint(-5, -1),
                0, random.uniform(0.06, 0.18),
                random.choice(['.', '*']), 4))

        if season == 'spring' and random.random() < 0.03 and len(particles) < 15:
            particles.append(Particle(
                random.randint(0, w), random.randint(-5, -1),
                random.uniform(0.1, 0.2), random.uniform(0.3, 0.8),
                '|', 5))

        if season == 'autumn' and random.random() < 0.02 and len(particles) < 30:
            particles.append(Particle(
                random.randint(0, w), random.randint(-5, -1),
                random.uniform(0.1, 0.2), random.uniform(0.4, 1.0),
                '\\', 5))

        # Creatures
        if season == 'spring' and len(creatures) < 2 and random.random() < 0.005:
            creatures.append(Creature(
                random.randint(5, w - 10), random.randint(3, ground - 5),
                'butterfly'))
        if season in ('spring', 'summer') and random.random() < 0.003:
            creatures.append(Creature(-3, random.randint(1, 4), 'bird'))

        # Fireflies (summer)
        if season == 'summer' and len(fireflies) < 12 and random.random() < 0.01:
            fireflies.append(Firefly(
                random.randint(5, w - 5),
                random.randint(ground // 2, ground - 2)))

        # --- Update ---
        alive = []
        for p in particles:
            p.frame += 1
            if p.char in [',', "'", '~', '*'] and p.color == 2:
                # Leaf physics
                p.vy = 0.22 + 0.06 * math.sin(p.frame * 0.08)
                p.vx = p.amp * math.sin(p.frame * p.freq + p.phase) * 0.2 + wind * 0.1
                if p.frame % random.randint(3, 7) == 0:
                    p.char = random.choice([',', "'", '~', '*'])
            elif p.char in ['.', '*'] and p.color == 4:
                # Snow
                vx = p.amp * math.sin(p.frame * p.freq + p.phase) * 0.12
                p.x += vx
            else:
                # Rain
                p.vy += 0.04
            p.x += p.vx
            p.y += p.vy
            ix, iy = int(p.x), int(p.y)
            if 0 <= ix < w and iy < ground:
                alive.append(p)
        particles = alive

        # Update clouds
        for cl in clouds:
            cl.x += cl.vx
        clouds = [c for c in clouds if c.x > -20]
        if random.random() < 0.005 and len(clouds) < 5:
            clouds.append(Cloud(w + 5, random.randint(1, 4)))

        # Update creatures
        alive_c = []
        for cr in creatures:
            cr.frame += 1
            cr.x += cr.vx
            if cr.kind == 'butterfly':
                cr.y += 0.1 * math.sin(cr.frame * 0.05)
                if cr.frame % 3 == 0:
                    cr.frame_idx = (cr.frame_idx + 1) % 4
                if cr.x < 2 or cr.x > w - 5:
                    cr.vx = -cr.vx
            else:
                if cr.frame % 3 == 0:
                    cr.frame_idx = (cr.frame_idx + 1) % 2
            if -5 < cr.x < w + 5:
                alive_c.append(cr)
        creatures = alive_c

        # --- Draw ---
        stdscr.erase()

        # Clouds
        for cl in clouds:
            for di, line in enumerate(cl.shape):
                r = cl.y + di
                for j, ch in enumerate(line):
                    cc = int(cl.x) + j
                    if ch != ' ' and 0 <= r < h and 0 <= cc < w:
                        try:
                            stdscr.addch(r, cc, ch, curses.color_pair(4) | curses.A_BOLD)
                        except curses.error:
                            pass

        # Tree
        if season == 'autumn':
            canopy = TREE_CANOPY_AUTUMN
        elif season == 'winter':
            canopy = TREE_CANOPY_BARE
        else:
            canopy = TREE_CANOPY_FULL

        canopy_top = ground - len(TREE_TRUNK) - len(canopy)
        for i, line in enumerate(canopy):
            r = canopy_top + i
            cx = tree_x - len(line) // 2
            for j, ch in enumerate(line):
                cc = cx + j
                if ch != ' ' and 0 <= r < h and 0 <= cc < w:
                    if season == 'autumn':
                        col = curses.color_pair(2) if ch in 'o.' else curses.color_pair(3)
                    elif season == 'winter':
                        col = curses.color_pair(5)
                    else:
                        col = curses.color_pair(1) | curses.A_BOLD
                    try:
                        stdscr.addch(r, cc, ch, col)
                    except curses.error:
                        pass

        trunk_top = canopy_top + len(canopy)
        for i, line in enumerate(TREE_TRUNK):
            r = trunk_top + i
            cx = tree_x - len(line) // 2
            for j, ch in enumerate(line):
                cc = cx + j
                if ch != ' ' and 0 <= r < h and 0 <= cc < w:
                    try:
                        stdscr.addch(r, cc, ch, curses.color_pair(3) | curses.A_DIM)
                    except curses.error:
                        pass

        # Flowers (spring/summer only)
        if season in ('spring', 'summer'):
            for fx in flower_xs:
                if 0 <= fx < w - 5:
                    for i, line in enumerate(FLOWER_SMALL):
                        r = ground - len(FLOWER_SMALL) + i
                        cx = fx
                        for j, ch in enumerate(line):
                            cc = cx + j
                            if ch != ' ' and 0 <= r < h and 0 <= cc < w:
                                col = curses.color_pair(6) if ch in '()*' else curses.color_pair(1)
                                try:
                                    stdscr.addch(r, cc, ch, col)
                                except curses.error:
                                    pass

        # Ground
        for c in range(w):
            try:
                stdscr.addch(ground, c, '_', curses.A_DIM)
            except curses.error:
                pass

        # Particles
        for p in particles:
            ix, iy = int(p.x), int(p.y)
            if 0 <= iy < h and 0 <= ix < w:
                try:
                    attr = curses.color_pair(p.color)
                    if p.color in (2, 4):
                        attr |= curses.A_BOLD
                    stdscr.addch(iy, ix, p.char, attr)
                except curses.error:
                    pass

        # Creatures
        for cr in creatures:
            ix, iy = int(cr.x), int(cr.y)
            if cr.kind == 'butterfly':
                bch = ['><', '||', '><', '\\/'][cr.frame_idx]
                for j, ch in enumerate(bch):
                    cc = ix + j
                    if 0 <= iy < h and 0 <= cc < w:
                        try:
                            stdscr.addch(iy, cc, ch,
                                         curses.color_pair(6) | curses.A_BOLD)
                        except curses.error:
                            pass
            else:
                # Bird
                flap = ['v', '~'][cr.frame_idx]
                if 0 <= iy < h and 0 <= ix < w:
                    try:
                        stdscr.addch(iy, ix, flap, curses.color_pair(4))
                    except curses.error:
                        pass

        # Fireflies
        if season == 'summer':
            for ff in fireflies:
                if ff.visible(now) and 0 <= ff.y < h and 0 <= ff.x < w:
                    try:
                        stdscr.addch(ff.y, ff.x, '*',
                                     curses.color_pair(3) | curses.A_BOLD)
                    except curses.error:
                        pass

        # Status
        status = f' {season.capitalize()} Garden · s=season · q=quit '
        try:
            stdscr.addstr(h - 1, 0, status[:w-1], curses.A_DIM)
        except curses.error:
            pass

        stdscr.refresh()


if __name__ == '__main__':
    curses.wrapper(main)
