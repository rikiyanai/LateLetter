"""Layer 2 — Particles: rain, snow, falling leaves, splashes, lightning.

Implements the shared Particle type and single-loop particle system from
§7.2. Per-type physics (gravity, wind, drift) are dispatched by the
particle's `kind` field. Collision with plant surfaces triggers splashes
(rain) or accumulation (snow).

Lightning is managed as a separate bolt system within the layer since
it is not a particle per se but a multi-segment screen effect.
"""
from __future__ import annotations

import math
import random

from .screen_buffer import ScreenBuffer
from .state import GardenState

# ── Constants ───────────────────────────────────────────────────────

LEAF_CHARS = [',', "'", '~', '*']

# Rain (calibrated for 50ms frame time; prototype was 40ms)
RAIN_GRAVITY = 0.08
RAIN_VX_BASE = 0.15
RAIN_VY_RANGE = (0.5, 1.4)
MAX_RAIN = 60
RAIN_SPAWN_RATE = 0.25  # per frame probability
RAIN_WIND_FACTOR = 0.3  # wind influence on drop drift
RAIN_FRAG_COUNT = 3     # fragments per plant collision
FRAG_DAMPING = 0.32     # velocity damping on reflection

# Snow (calibrated for 50ms; prototype was 60ms)
SNOW_VY_RANGE = (0.08, 0.20)
MAX_SNOW = 25
SNOW_SPAWN_RATE = 0.12
MAX_SNOW_DEPTH = 3

# Leaves (calibrated for 50ms; prototype was 40ms)
MAX_LEAVES = 25
LEAF_SPAWN_RATE = 0.08

# Lightning
BOLT_DURATION_FRAMES = 12  # ~0.6s at 50ms
BOLT_CHANCE_PER_FRAME = 0.003  # during rain


# ── Particle ────────────────────────────────────────────────────────

class Particle:
    """Shared particle type per §7.2 spec.

    Extended with phase/freq/amp for sine-wave effects (snow drift,
    leaf oscillation) and age for frame-based physics.
    """

    __slots__ = ('x', 'y', 'vx', 'vy', 'char', 'color', 'lifetime',
                 'kind', 'phase', 'freq', 'amp', 'age')

    def __init__(self, x: float, y: float, vx: float, vy: float,
                 char: str, color: str, lifetime: int = -1,
                 kind: str = 'generic') -> None:
        self.x = x
        self.y = y
        self.vx = vx
        self.vy = vy
        self.char = char
        self.color = color
        self.lifetime = lifetime  # -1 = infinite (killed by bounds)
        self.kind = kind
        self.phase = 0.0
        self.freq = 0.0
        self.amp = 0.0
        self.age = 0


# ── Particle factories ─────────────────────────────────────────────

def _make_rain(rng: random.Random, width: int) -> Particle:
    p = Particle(
        x=float(rng.randint(0, max(0, width - 1))),
        y=float(rng.randint(-10, -1)),
        vx=max(0.0, RAIN_VX_BASE + rng.gauss(0, 0.08)),
        vy=rng.uniform(*RAIN_VY_RANGE),
        char='|', color='cyan',
        kind='rain',
    )
    p.amp = p.vx  # store base drift for wind modulation
    return p


def _make_snow(rng: random.Random, width: int) -> Particle:
    p = Particle(
        x=float(rng.randint(0, max(0, width - 1))),
        y=float(rng.randint(-6, -1)),
        vx=0.0,
        vy=rng.uniform(*SNOW_VY_RANGE),
        char=rng.choice(['.', '*']),
        color='bright_white',
        kind='snow',
    )
    p.phase = rng.uniform(0, 6.28)
    p.freq = rng.uniform(0.03, 0.08)
    p.amp = rng.uniform(0.8, 2.5)
    return p


def _make_leaf(rng: random.Random, x: float, y: float) -> Particle:
    p = Particle(
        x=x, y=y,
        vx=0.0,
        vy=rng.uniform(0.15, 0.35),
        char=rng.choice(LEAF_CHARS),
        color=rng.choice(['red', 'yellow', 'bright_yellow', 'brown']),
        kind='leaf',
    )
    p.phase = rng.uniform(0, 6.28)
    p.freq = rng.uniform(0.04, 0.12)
    p.amp = rng.uniform(1.0, 3.5)
    return p


def _make_splashes(rng: random.Random, x: float,
                   ground_y: int) -> list[Particle]:
    """Multi-particle splash fan on ground hit (3-5 particles)."""
    count = rng.randint(3, 5)
    result: list[Particle] = []
    for _ in range(count):
        drift = rng.choice([-1, 1]) * rng.uniform(0.4, 2.0)
        life = rng.randint(3, 8)
        result.append(Particle(
            x=x, y=float(ground_y),
            vx=drift, vy=0.0,
            char="'", color='white',
            lifetime=life, kind='splash',
        ))
    return result


def _make_fragments(rng: random.Random, x: float, y: float,
                    vx: float, vy: float) -> list[Particle]:
    """Reflection fragments on plant collision (3 per hit)."""
    result: list[Particle] = []
    for _ in range(RAIN_FRAG_COUNT):
        fvx = -vx * FRAG_DAMPING + rng.uniform(-0.5, 0.5)
        fvy = -abs(vy) * FRAG_DAMPING
        life = rng.randint(3, 8)
        result.append(Particle(
            x=x, y=y, vx=fvx, vy=fvy,
            char='*', color='cyan',
            lifetime=life, kind='fragment',
        ))
    return result


# ── Per-type physics ────────────────────────────────────────────────

def _physics_rain(p: Particle, state: GardenState) -> None:
    p.vy += RAIN_GRAVITY
    p.vx = p.amp + state.wind * RAIN_WIND_FACTOR
    p.char = '\\' if abs(p.vx) > 0.15 else '|'


def _physics_snow(p: Particle, state: GardenState) -> None:
    p.vx = p.amp * math.sin(p.age * p.freq + p.phase) * 0.15


def _physics_leaf(p: Particle, state: GardenState) -> None:
    p.vy = 0.25 + 0.08 * math.sin(p.age * 0.08)
    p.vx = p.amp * math.sin(p.age * p.freq + p.phase) * 0.25 + \
        state.wind * 0.15
    # Tumble char rotation
    if p.age % 5 == 0:
        p.char = LEAF_CHARS[p.age // 5 % len(LEAF_CHARS)]


def _physics_splash(p: Particle, state: GardenState) -> None:
    # Char aging: ' → . → ·
    if p.lifetime <= 2:
        p.char = '\u00b7'  # ·
    elif p.lifetime <= 4:
        p.char = '.'


def _physics_fragment(p: Particle, state: GardenState) -> None:
    p.vy += RAIN_GRAVITY * 0.5
    # Char aging: * → . → ·
    if p.lifetime <= 2:
        p.char = '\u00b7'  # ·
    elif p.lifetime <= 4:
        p.char = '.'


_PHYSICS = {
    'rain': _physics_rain,
    'snow': _physics_snow,
    'leaf': _physics_leaf,
    'splash': _physics_splash,
    'fragment': _physics_fragment,
}


# ── Lightning bolt system ───────────────────────────────────────────

class BoltSegment:
    __slots__ = ('row', 'col')

    def __init__(self, row: int, col: int) -> None:
        self.row = row
        self.col = col


class Lightning:
    __slots__ = ('segments', 'birth_frame', 'duration')

    def __init__(self, segments: list[BoltSegment], birth_frame: int) -> None:
        self.segments = segments
        self.birth_frame = birth_frame
        self.duration = BOLT_DURATION_FRAMES


def _make_bolt(rng: random.Random, state: GardenState) -> Lightning:
    """Generate a jagged bolt from top to ground with one fork."""
    segs: list[BoltSegment] = []
    w, ground_y = state.width, state.ground_y
    col = rng.randint(w // 6, w * 5 // 6)
    for row in range(ground_y):
        segs.append(BoltSegment(row, col))
        col += rng.choice([-2, -1, -1, 0, 0, 0, 0, 1, 1, 2])
        col = max(1, min(w - 2, col))

    # One fork from 1/3 down the bolt
    if len(segs) > 5:
        fork_start = segs[len(segs) // 3]
        fr, fc = fork_start.row, fork_start.col
        direction = rng.choice([-3, 3])
        for _ in range(rng.randint(3, 8)):
            fr += 1
            fc += direction + rng.choice([-1, 0, 0, 1])
            fc = max(1, min(w - 2, fc))
            if fr >= ground_y:
                break
            segs.append(BoltSegment(fr, fc))

    return Lightning(segs, state.frame)


# ── Cloud system ────────────────────────────────────────────────────

class Cloud:
    __slots__ = ('x', 'y', 'vx', 'shape')

    def __init__(self, rng: random.Random, x: float, y: int) -> None:
        self.x = x
        self.y = y
        self.vx = rng.uniform(-0.06, -0.02)
        shapes = [['(~)'], ['(~~~)'], ['.--~~--.', "'~~~~~~'"]]
        self.shape = rng.choice(shapes)

    @property
    def width(self) -> int:
        return max(len(line) for line in self.shape)


# ── Particle layer ──────────────────────────────────────────────────

# Season → active weather types
_SEASON_WEATHER: dict[str, set[str]] = {
    'spring': {'rain_light', 'cloud'},
    'summer': {'cloud'},
    'autumn': {'rain', 'leaf', 'lightning', 'cloud'},
    'winter': {'snow', 'cloud'},
}


class ParticleLayer:
    """Layer 2: particle system with spawn/update/kill loop.

    Manages particles, lightning bolts, clouds, and snow accumulation.
    Season controls which weather types are active.
    Update cadence: 40-80ms (fast).
    """

    update_interval_ms = 50

    def __init__(self) -> None:
        self.particles: list[Particle] = []
        self.bolts: list[Lightning] = []
        self.clouds: list[Cloud] = []
        self.snow_depth: dict[int, int] = {}
        self._rng = random.Random()

    def update(self, state: GardenState) -> None:
        self._rng.seed(None)  # use system entropy for spawning
        weather = _SEASON_WEATHER.get(state.season, set())

        # Spawn
        self._spawn_weather(state, weather)
        self._spawn_clouds(state, weather)

        # Update particles with per-type physics and collision
        alive: list[Particle] = []
        new_particles: list[Particle] = []
        for p in self.particles:
            p.age += 1
            # Per-type physics
            phys = _PHYSICS.get(p.kind)
            if phys:
                phys(p, state)
            # Apply velocity
            p.x += p.vx
            p.y += p.vy
            # Lifetime
            if p.lifetime > 0:
                p.lifetime -= 1
                if p.lifetime == 0:
                    continue

            ix, iy = int(p.x), int(p.y)

            # Collision and bounds
            if p.kind == 'rain':
                hit_plant = (iy, ix) in state.collision_map
                hit_ground = iy >= state.ground_y
                if hit_plant:
                    new_particles.extend(
                        _make_fragments(self._rng, p.x, p.y,
                                        p.vx, p.vy))
                    continue
                if hit_ground:
                    new_particles.extend(
                        _make_splashes(self._rng, p.x,
                                       state.ground_y))
                    continue
            elif p.kind == 'snow':
                depth = self.snow_depth.get(ix, 0)
                effective_ground = state.ground_y - depth
                hit_plant = (iy, ix) in state.collision_map
                hit_ground = iy >= effective_ground
                if hit_plant or hit_ground:
                    if 0 <= ix < state.width and depth < MAX_SNOW_DEPTH:
                        self.snow_depth[ix] = depth + 1
                    continue
            elif p.kind == 'leaf':
                if iy >= state.ground_y:
                    continue  # leaf settles
            elif p.kind in ('splash', 'fragment'):
                pass  # killed by lifetime only

            # Bounds check (keep if on screen)
            if 0 <= ix < state.width and -10 <= iy < state.height:
                alive.append(p)

        alive.extend(new_particles)
        self.particles = alive

        # Update lightning
        self.bolts = [b for b in self.bolts
                      if state.frame - b.birth_frame < b.duration]

        # Update clouds
        for cl in self.clouds:
            cl.x += cl.vx
        self.clouds = [c for c in self.clouds if c.x > -(c.width + 5)]

    def _spawn_weather(self, state: GardenState,
                       weather: set[str]) -> None:
        rng = self._rng
        rain_count = sum(1 for p in self.particles if p.kind == 'rain')
        snow_count = sum(1 for p in self.particles if p.kind == 'snow')
        leaf_count = sum(1 for p in self.particles if p.kind == 'leaf')

        # Rain (heavy in autumn, light in spring)
        if 'rain' in weather:
            if rng.random() < RAIN_SPAWN_RATE and rain_count < MAX_RAIN:
                self.particles.append(_make_rain(rng, state.width))
        elif 'rain_light' in weather:
            if rng.random() < RAIN_SPAWN_RATE * 0.3 and rain_count < 15:
                self.particles.append(_make_rain(rng, state.width))

        # Snow
        if 'snow' in weather:
            if rng.random() < SNOW_SPAWN_RATE and snow_count < MAX_SNOW:
                self.particles.append(_make_snow(rng, state.width))

        # Leaves (from canopy cells)
        if 'leaf' in weather and state.canopy_cells:
            if rng.random() < LEAF_SPAWN_RATE and leaf_count < MAX_LEAVES:
                cell = rng.choice(list(state.canopy_cells))
                self.particles.append(
                    _make_leaf(rng, float(cell[1]), float(cell[0])))

        # Lightning (during rain)
        if 'lightning' in weather and rain_count > 10:
            if rng.random() < BOLT_CHANCE_PER_FRAME:
                self.bolts.append(_make_bolt(rng, state))
                state.flash_frames = 2

    def _spawn_clouds(self, state: GardenState,
                      weather: set[str]) -> None:
        if 'cloud' not in weather:
            return
        rng = self._rng
        if rng.random() < 0.004 and len(self.clouds) < 5:
            self.clouds.append(
                Cloud(rng, float(state.width + 5), rng.randint(1, 3)))

    def render(self, buf: ScreenBuffer, state: GardenState) -> None:
        # Snow accumulation (drawn on ground)
        for col, depth in self.snow_depth.items():
            for d in range(min(depth, MAX_SNOW_DEPTH)):
                row = state.ground_y - d
                if 0 <= row < state.height and 0 <= col < state.width:
                    ch = '*' if (col + d) % 3 == 0 else '.'
                    buf.put(row, col, ch, 'bright_white')

        # Clouds (behind particles)
        for cl in self.clouds:
            for di, line in enumerate(cl.shape):
                row = cl.y + di
                for j, ch in enumerate(line):
                    col = int(cl.x) + j
                    if ch != ' ' and 0 <= row < state.height and \
                            0 <= col < state.width:
                        buf.put(row, col, ch, 'bright_white')

        # Particles
        for p in self.particles:
            ix, iy = int(p.x), int(p.y)
            if 0 <= iy < state.height and 0 <= ix < state.width:
                buf.put(iy, ix, p.char, p.color)

        # Lightning bolts
        for bolt in self.bolts:
            age_frames = state.frame - bolt.birth_frame
            frac = age_frames / bolt.duration
            if frac < 0.2:
                ch, color = '#', 'bright_yellow'
            elif frac < 0.5:
                ch, color = '+', 'yellow'
            else:
                ch, color = '*', 'white'
            for seg in bolt.segments:
                if 0 <= seg.row < state.height and \
                        0 <= seg.col < state.width:
                    buf.put(seg.row, seg.col, ch, color)

    def on_resize(self, state: GardenState) -> None:
        self.particles.clear()
        self.bolts.clear()
        self.clouds.clear()
        self.snow_depth.clear()
