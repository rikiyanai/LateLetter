"""Falling leaf physics prototype — from research.

Damped sine-wave oscillation model for leaf tumbling.
Based on analysis of terminal animation techniques.
Reference timing: 33ms frame rate (~30 FPS).

Usage: python3 ascii-animations/nature/leaf-physics.py
"""
import math
import random
import time


class FallingLeaf:
    """A single leaf particle with oscillating horizontal drift."""

    def __init__(self, x, y):
        self.x = float(x)
        self.y = float(y)
        self.vx = 0.0
        self.vy = 0.3  # base fall speed (chars/frame)
        self.phase = random.uniform(0, 2 * math.pi)
        self.freq = random.uniform(0.05, 0.15)
        self.amplitude = random.uniform(1.0, 3.0)
        self.char_cycle = [',', '.', '~', '*', '>', '<']
        self.char_idx = 0
        self.tumble_rate = random.randint(3, 8)
        self.frame = 0
        self.wind = 0.0

    def update(self, wind=0.0):
        self.frame += 1
        self.wind = wind

        # Vertical: constant fall + slight variation
        self.vy = 0.3 + 0.1 * math.sin(self.frame * 0.1)
        self.y += self.vy

        # Horizontal: sine wave oscillation + wind
        self.vx = self.amplitude * math.sin(
            self.frame * self.freq + self.phase
        )
        self.x += self.vx * 0.3 + self.wind * 0.1

        # Tumble: cycle through characters
        if self.frame % self.tumble_rate == 0:
            self.char_idx = (self.char_idx + 1) % len(self.char_cycle)

    @property
    def char(self):
        return self.char_cycle[self.char_idx]

    @property
    def pos(self):
        return (int(self.x), int(self.y))


class Firefly:
    """Real flash patterns based on Photinus species research.

    Photinus brimleyi:    2 flashes in 20s cycle (slow, sporadic)
    Photinus macdermotti: 4 flashes in 14.5s cycle (active)
    Photinus carolinus:   synchronous rapid flashes (dramatic)
    """

    def __init__(self, x, y, pattern='brimleyi'):
        self.x = x
        self.y = y
        self.char = ' '
        self.visible = False

        if pattern == 'brimleyi':
            self.cycle_length = 20.0
            self.flash_times = [5.0, 15.0]
        elif pattern == 'macdermotti':
            self.cycle_length = 14.5
            self.flash_times = [3.0, 5.0, 10.0, 12.5]
        elif pattern == 'carolinus':
            self.cycle_length = 15.0
            self.flash_times = [i * 0.5 for i in range(14)]
        else:
            self.cycle_length = random.uniform(15, 25)
            self.flash_times = sorted(
                [random.uniform(0, self.cycle_length) for _ in range(2)]
            )

        self.flash_duration = 0.5
        self.cycle_start = time.monotonic() + random.uniform(-3, 3)

    def update(self, current_time):
        elapsed = (current_time - self.cycle_start) % self.cycle_length
        self.char = ' '
        self.visible = False

        for flash_time in self.flash_times:
            if flash_time <= elapsed <= flash_time + self.flash_duration:
                mid = flash_time + self.flash_duration / 2
                if elapsed < mid:
                    self.char = '.'  # ramping up
                else:
                    self.char = '*'  # peak
                self.visible = True
                break


def wind_update(frame):
    """Global wind: slow sine base + occasional gusts."""
    base = 0.5 * math.sin(frame * 0.01)
    gust = 0.0
    if random.random() < 0.02:
        gust = random.uniform(1.0, 3.0) * random.choice([-1, 1])
    return base + gust


def branch_sway(base_x, depth, time_val, wind_strength=1.0):
    """Sine-based branch oscillation for willow trees.

    depth: distance from trunk (0=trunk, higher=tip)
    Returns: new x position (int)
    """
    amplitude = depth * 0.3 * wind_strength
    freq = 0.05 + depth * 0.01
    phase = depth * 0.3
    offset = amplitude * math.sin(time_val * freq + phase)
    return int(base_x + offset)


# ── Demo ─────────────────────────────────────────────────────
if __name__ == '__main__':
    import shutil
    import sys

    cols = shutil.get_terminal_size().columns
    rows = shutil.get_terminal_size().lines - 2
    ground = rows - 1

    # Spawn leaves from "tree canopy" area
    leaves = []
    tree_x = cols // 2
    canopy_width = 12

    print('\033[?25l\033[2J', end='')  # hide cursor, clear
    try:
        frame = 0
        while True:
            frame += 1
            w = wind_update(frame)

            # Spawn new leaf occasionally
            if random.random() < 0.15 and len(leaves) < 30:
                lx = tree_x + random.randint(-canopy_width, canopy_width)
                leaves.append(FallingLeaf(lx, 2))

            # Update and render
            buf = [[' '] * cols for _ in range(rows)]

            # Simple tree
            for r in range(3, 8):
                for c in range(tree_x - 6, tree_x + 7):
                    if 0 <= c < cols:
                        buf[r][c] = '#'
            for r in range(8, ground):
                if 0 <= tree_x < cols:
                    buf[r][tree_x] = '|'

            # Ground
            for c in range(cols):
                buf[ground][c] = '_'

            # Update leaves
            alive = []
            for leaf in leaves:
                leaf.update(w)
                x, y = leaf.pos
                if 0 <= x < cols and 0 <= y < ground:
                    buf[y][x] = leaf.char
                    alive.append(leaf)
                elif y >= ground and 0 <= x < cols:
                    buf[ground][x] = leaf.char  # leaf rests on ground
            leaves = alive

            # Render
            sys.stdout.write('\033[H')
            for row in buf:
                sys.stdout.write(''.join(row) + '\n')
            sys.stdout.flush()
            time.sleep(0.05)

    except KeyboardInterrupt:
        pass
    finally:
        print('\033[?25h', end='')  # show cursor
