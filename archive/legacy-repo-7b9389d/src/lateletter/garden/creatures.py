"""Layer 3 — Creatures: butterflies, ambient birds, fireflies.

Each creature type has independent movement AI. Creatures spawn and
despawn at screen edges. Procedural variety is seed-driven per §7.1.

Butterfly: ><, ||, \\/ frame cycle; wanders left-right with sine-wave
           vertical drift and occasional up-dip.
Bird:      Single-char v/~ silhouettes flying across sky.
Firefly:   */· blink on/off with Photinus-style flash patterns.
"""
from __future__ import annotations

import math
import random
import time as _time

from .screen_buffer import ScreenBuffer
from .state import GardenState

# ── Butterfly ───────────────────────────────────────────────────────

BUTTERFLY_FRAMES = ['><', '||', '><', '\\/']


class Butterfly:
    __slots__ = ('x', 'y', 'vx', 'target_x', 'frame_idx', 'flap_rate',
                 'age', 'dip_timer', 'dipping', 'color')

    def __init__(self, rng: random.Random, x: float, y: float) -> None:
        self.x = x
        self.y = y
        self.vx = rng.choice([-0.3, 0.3])
        self.target_x = x + rng.randint(-15, 15)
        self.frame_idx = rng.randint(0, 3)
        self.flap_rate = rng.randint(3, 5)  # scaled for 50ms frames
        self.age = 0
        self.dip_timer = rng.randint(20, 60)
        self.dipping = 0
        self.color = rng.choice(['magenta', 'bright_magenta',
                                 'cyan', 'bright_cyan'])

    def update(self, state: GardenState) -> bool:
        """Update position. Returns False if should be removed."""
        self.age += 1
        # Flap
        if self.age % self.flap_rate == 0:
            self.frame_idx = (self.frame_idx + 1) % 4
        # Horizontal target-seeking
        if abs(self.x - self.target_x) < 2:
            self.target_x = self.x + random.randint(-20, 20)
            self.vx = 0.25 if self.target_x > self.x else -0.25
        self.x += self.vx
        # Up-dip
        self.dip_timer -= 1
        if self.dip_timer <= 0:
            self.dipping = random.randint(4, 8)
            self.dip_timer = random.randint(25, 70)
        if self.dipping > 0:
            self.y += -0.25 if self.dipping > 3 else 0.25
            self.dipping -= 1
        # Gentle bob
        self.y += 0.06 * math.sin(self.age * 0.05)
        # Bounds
        self.x = max(2, min(state.width - 4, self.x))
        self.y = max(2, min(state.ground_y - 3, self.y))
        return True

    def render(self, buf: ScreenBuffer) -> None:
        ix, iy = int(self.x), int(self.y)
        frame_str = BUTTERFLY_FRAMES[self.frame_idx]
        for j, ch in enumerate(frame_str):
            buf.put(iy, ix + j, ch, self.color)


# ── Ambient bird ────────────────────────────────────────────────────

class AmbientBird:
    __slots__ = ('x', 'y', 'vx', 'flap_idx', 'flap_rate', 'age', 'char')

    def __init__(self, rng: random.Random, x: float, y: float,
                 vx: float) -> None:
        self.x = x
        self.y = y
        self.vx = vx
        self.flap_idx = rng.randint(0, 1)
        self.flap_rate = rng.randint(3, 5)
        self.age = rng.randint(0, 10)
        self.char = rng.choice(['v', '~', '^'])

    def update(self, state: GardenState) -> bool:
        """Update position. Returns False if off screen."""
        self.age += 1
        self.x += self.vx
        # Slight vertical wobble
        self.y += 0.03 * math.sin(self.age * 0.08)
        # Flap
        if self.age % self.flap_rate == 0:
            self.flap_idx = (self.flap_idx + 1) % 2
            self.char = ['v', '~'][self.flap_idx]
        return -3 < self.x < state.width + 3

    def render(self, buf: ScreenBuffer) -> None:
        ix, iy = int(self.x), int(self.y)
        buf.put(iy, ix, self.char, 'white')


# ── Firefly ─────────────────────────────────────────────────────────

_PATTERNS = {
    'brimleyi':    (20.0, [5.0, 15.0]),
    'macdermotti': (14.5, [3.0, 5.0, 10.0, 12.5]),
    'carolinus':   (15.0, [i * 0.5 for i in range(13)]),
}


class Firefly:
    __slots__ = ('x', 'y', 'cycle_len', 'flash_times', 'flash_dur',
                 'cycle_start', 'drift_timer')

    def __init__(self, rng: random.Random, x: int, y: int) -> None:
        self.x = x
        self.y = y
        pattern = rng.choice(list(_PATTERNS.keys()))
        self.cycle_len, self.flash_times = _PATTERNS[pattern]
        self.flash_dur = 0.5
        self.cycle_start = _time.monotonic() + rng.uniform(-5, 5)
        self.drift_timer = 0

    def update(self, state: GardenState) -> bool:
        """Drift slowly. Returns True always (fireflies don't leave)."""
        self.drift_timer -= 1
        if self.drift_timer <= 0:
            dx = random.choice([-1, 0, 0, 0, 1])
            dy = random.choice([0, 0, 0, -1, 1])
            self.x = max(1, min(state.width - 2, self.x + dx))
            self.y = max(state.height // 3,
                         min(state.ground_y - 2, self.y + dy))
            self.drift_timer = random.randint(8, 25)
        return True

    def visible(self, now: float) -> tuple[str, str] | None:
        """Return (char, color) if flashing, None if dark."""
        elapsed = (now - self.cycle_start) % self.cycle_len
        for ft in self.flash_times:
            if ft <= elapsed <= ft + self.flash_dur:
                mid = ft + self.flash_dur / 2
                if abs(elapsed - mid) < 0.1:
                    return '*', 'bright_yellow'
                return '.', 'yellow'
        return None

    def render(self, buf: ScreenBuffer, now: float) -> None:
        vis = self.visible(now)
        if vis:
            ch, color = vis
            buf.put(self.y, self.x, ch, color)


# ── Season → active creature types ─────────────────────────────────

_SEASON_CREATURES: dict[str, set[str]] = {
    'spring':  {'butterfly', 'bird'},
    'summer':  {'bird', 'firefly'},
    'autumn':  set(),
    'winter':  set(),
}

# Max counts per type
_MAX_COUNTS = {'butterfly': 3, 'bird': 4, 'firefly': 12}

# Spawn probabilities per frame
_SPAWN_RATES = {'butterfly': 0.004, 'bird': 0.008, 'firefly': 0.008}


# ── Creature layer ──────────────────────────────────────────────────

class CreatureLayer:
    """Layer 3: creature spawning, movement AI, and rendering.

    Update cadence: 100-200ms (creatures run at ~100ms effective rate
    since movement speeds are calibrated accordingly).
    """

    update_interval_ms = 100

    def __init__(self) -> None:
        self.butterflies: list[Butterfly] = []
        self.birds: list[AmbientBird] = []
        self.fireflies: list[Firefly] = []
        self._rng = random.Random()

    def update(self, state: GardenState) -> None:
        active = _SEASON_CREATURES.get(state.season, set())
        self._rng.seed(None)
        rng = self._rng

        # Spawn
        if 'butterfly' in active:
            if rng.random() < _SPAWN_RATES['butterfly'] and \
                    len(self.butterflies) < _MAX_COUNTS['butterfly']:
                bx = rng.randint(5, state.width - 10)
                by = rng.randint(3, state.ground_y - 5)
                self.butterflies.append(Butterfly(rng, float(bx), float(by)))

        if 'bird' in active:
            if rng.random() < _SPAWN_RATES['bird'] and \
                    len(self.birds) < _MAX_COUNTS['bird']:
                direction = rng.choice([-1, 1])
                sx = -3.0 if direction > 0 else float(state.width + 3)
                sy = float(rng.randint(1, state.height // 3))
                vx = rng.uniform(0.4, 0.8) * direction
                self.birds.append(AmbientBird(rng, sx, sy, vx))

        if 'firefly' in active:
            if rng.random() < _SPAWN_RATES['firefly'] and \
                    len(self.fireflies) < _MAX_COUNTS['firefly']:
                fx = rng.randint(2, state.width - 3)
                fy = rng.randint(state.height // 3, state.ground_y - 2)
                self.fireflies.append(Firefly(rng, fx, fy))

        # Update all
        self.butterflies = [b for b in self.butterflies
                            if b.update(state)]
        self.birds = [b for b in self.birds if b.update(state)]
        for ff in self.fireflies:
            ff.update(state)

        # Cull creatures not in active season
        if 'butterfly' not in active:
            self.butterflies.clear()
        if 'bird' not in active:
            self.birds.clear()
        if 'firefly' not in active:
            self.fireflies.clear()

    def render(self, buf: ScreenBuffer, state: GardenState) -> None:
        for b in self.butterflies:
            b.render(buf)
        for b in self.birds:
            b.render(buf)
        for ff in self.fireflies:
            ff.render(buf, state.now)

    def on_resize(self, state: GardenState) -> None:
        self.butterflies.clear()
        self.birds.clear()
        self.fireflies.clear()
