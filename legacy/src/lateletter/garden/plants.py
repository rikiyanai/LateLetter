"""Layer 1 — Plants: procedural generators, layout, wind sway, collision map.

All plant generators produce a dict with:
  type   – plant kind name
  rows   – list of (dy, dx, text, color) tuples
           dy = rows above ground (1 = just above ground)
           dx = col offset from plant center x
  width  – horizontal span
  height – vertical span

Plant collision data is registered into GardenState after placement so
particle layers can use it for snow accumulation, rain splashes, and
leaf detachment.
"""
from __future__ import annotations

import math
import random

from .screen_buffer import ScreenBuffer
from .state import GardenState


# ── Plant generators (verbatim from original garden.py) ──────────────

def _pine(rng: random.Random) -> dict:
    h = rng.randint(8, 16)
    levels = h - 2
    rows = [(1, 0, '|', 'brown'), (2, 0, '|', 'brown')]
    for lv in range(levels):
        dy = 3 + lv
        w = lv
        if lv == levels - 1:
            rows.append((dy, 0, '^', 'bright_green'))
        else:
            tip = '^' if lv % 2 else '*'
            s = '/' * (w + 1) + tip + '\\' * (w + 1)
            color = 'bright_green' if lv >= levels // 2 else 'green'
            rows.append((dy, -(w + 1), s, color))
    return {'type': 'pine', 'rows': rows, 'width': levels * 2 + 2, 'height': h + 1}


def _oak(rng: random.Random) -> dict:
    h = rng.randint(8, 14)
    trunk_h = max(2, h // 3)
    ch = rng.choice(['@', 'o', '0', '&'])
    rows = [(i, 0, '|', 'brown') for i in range(1, trunk_h + 1)]
    canopy_rows = h - trunk_h
    radius = canopy_rows // 2 + 1
    for lv in range(canopy_rows + 2):
        dy = trunk_h + lv + 1
        t = (lv / (canopy_rows + 1)) * 2 - 1
        w = max(0, int(round(radius * math.sqrt(max(0, 1 - t * t)))))
        if w == 0:
            continue
        color = 'bright_green' if 0 < lv <= canopy_rows else 'green'
        rows.append((dy, -w, ch * (w * 2 + 1), color))
    return {'type': 'oak', 'rows': rows, 'width': radius * 2 + 3, 'height': h + 3}


def _bush(rng: random.Random) -> dict:
    w = rng.randint(2, 4)
    ch = rng.choice(['~', 'u', 'w', 'v'])
    return {
        'type': 'bush',
        'rows': [
            (2, -(w + 1), '(' + ch * (w * 2 + 1) + ')', 'bright_green'),
            (1, -w, '{' + ch * (w * 2 - 1) + '}', 'green'),
        ],
        'width': w * 2 + 4, 'height': 2,
    }


def _flower(rng: random.Random) -> dict:
    species = rng.choice(['daisy', 'tulip', 'sunflower', 'wildflower', 'rose'])
    stem_h = rng.randint(2, 5)
    rows = [(i, 0, '|', 'green') for i in range(1, stem_h + 1)]

    if stem_h >= 2:
        leaf_y = rng.randint(1, stem_h - 1)
        side = rng.choice(['left', 'right', 'both', 'none', 'none'])
        if side in ('left', 'both'):
            rows.append((leaf_y, -1, '\\', 'green'))
        if side in ('right', 'both'):
            rows.append((leaf_y, 1, '/', 'green'))

    bh = stem_h + 1
    if species == 'daisy':
        c = rng.choice(['white', 'bright_white', 'cyan', 'bright_cyan'])
        rows += [(bh + 1, -1, '\\*/', c), (bh, -1, '-O-', 'bright_yellow')]
        w = 3
    elif species == 'tulip':
        c = rng.choice(['red', 'magenta', 'bright_magenta', 'bright_red'])
        rows += [(bh + 1, -1, '(")', c), (bh, -1, '|"|', c)]
        w = 3
    elif species == 'sunflower':
        rows += [(bh + 1, -2, '\\{O}/', 'bright_yellow'), (bh, -1, '{#}', 'yellow')]
        w = 5
    elif species == 'wildflower':
        c = rng.choice(['magenta', 'bright_magenta', 'cyan', 'bright_cyan', 'bright_white'])
        rows += [(bh + 1, 0, '*', c), (bh, -1, '>*<', c)]
        w = 3
    else:  # rose
        c = rng.choice(['red', 'bright_magenta', 'bright_red'])
        rows += [(bh + 1, -1, '@@@', c), (bh, -1, '(@)', c)]
        w = 3

    return {'type': 'flower', 'species': species, 'rows': rows,
            'width': w, 'height': bh + 2}


def _grass(rng: random.Random) -> dict:
    h = rng.randint(2, 4)
    tip = rng.choice(['/', '\\', '`', "'"])
    rows = [(h, 0, tip, 'bright_green')] + \
           [(i, 0, '|', 'green') for i in range(1, h)]
    return {'type': 'grass', 'rows': rows, 'width': 1, 'height': h}


def _mushroom(rng: random.Random) -> dict:
    w = rng.randint(1, 2)
    c = rng.choice(['red', 'bright_red', 'yellow', 'bright_white', 'magenta'])
    return {
        'type': 'mushroom',
        'rows': [(2, -w, '(' + '~' * (w * 2) + ')', c), (1, 0, '|', 'white')],
        'width': w * 2 + 2, 'height': 2,
    }


def _fern(rng: random.Random) -> dict:
    h = rng.randint(2, 4)
    rows = [(h + 1, 0, '*', 'bright_green')]
    for i in range(1, h + 1):
        rows.append((i, 0, '|', 'green'))
        lc = 'bright_green' if i % 2 else 'green'
        rows += [(i, -1, '*' if i % 2 else ',', lc),
                 (i, 1, '*' if i % 2 else ',', lc)]
    return {'type': 'fern', 'rows': rows, 'width': 3, 'height': h + 1}


# ── Seasonal foliage ──────────────────────────────────────────────

_AUTUMN_COLORS = ['yellow', 'bright_yellow', 'red', 'brown']

_DECIDUOUS = frozenset({'oak', 'bush'})


def _apply_autumn_colors(plant: dict, rng: random.Random) -> None:
    """Swap green canopy colors to varied autumn tones on deciduous plants."""
    if plant['type'] not in _DECIDUOUS:
        return
    plant['rows'] = [
        (dy, dx, text, rng.choice(_AUTUMN_COLORS)
         if color in ('bright_green', 'green') else color)
        for dy, dx, text, color in plant['rows']
    ]


# ── Weights and registry ────────────────────────────────────────────

DEFAULT_WEIGHTS = {
    'pine': 8, 'oak': 8, 'bush': 8, 'flower': 18,
    'grass': 12, 'mushroom': 3, 'fern': 7,
}

_MAKERS = {
    'pine': _pine, 'oak': _oak, 'bush': _bush, 'flower': _flower,
    'grass': _grass, 'mushroom': _mushroom, 'fern': _fern,
}


def make_plant(rng: random.Random, ptype: str | None = None,
               weights: dict[str, int] | None = None,
               season: str | None = None) -> dict:
    if ptype is None:
        w = weights or DEFAULT_WEIGHTS
        types, wts = zip(*w.items())
        ptype = rng.choices(types, weights=wts, k=1)[0]
    plant = _MAKERS[ptype](rng)
    if season == 'autumn':
        _apply_autumn_colors(plant, rng)
    return plant


# ── Layout ──────────────────────────────────────────────────────────

def generate_layout(width: int, height: int, seed: int,
                    weights: dict[str, int] | None = None,
                    season: str | None = None,
                    ) -> list[dict]:
    """Place plants across the garden. Returns placed plant descriptors."""
    rng = random.Random(seed)
    ground_y = height - 3
    placed: list[dict] = []
    occupied: list[tuple[int, int]] = []

    for _ in range(width * 3):
        p = make_plant(rng, weights=weights, season=season)
        half = p['width'] // 2 + 2
        if width < half * 2 + 4:
            continue
        x = rng.randint(half + 1, width - half - 2)
        xmin = x - half - 1
        xmax = x + half + 1
        if any(xmin < ox and xmax > om for om, ox in occupied):
            continue
        occupied.append((xmin, xmax))
        placed.append({'plant': p, 'x': x, 'ground_y': ground_y})

    return placed


# ── Collision map builder ───────────────────────────────────────────

_CANOPY_TYPES = frozenset({'pine', 'oak'})


def build_collision_map(placed: list[dict]) -> tuple[
    set[tuple[int, int]],   # collision_map: all occupied cells
    dict[int, int],          # top_surfaces: col -> min row
    set[tuple[int, int]],   # canopy_cells: leaf detachment points
]:
    """Compute collision surfaces from placed plants."""
    collision: set[tuple[int, int]] = set()
    top: dict[int, int] = {}
    canopy: set[tuple[int, int]] = set()

    for pd in placed:
        px, gy = pd['x'], pd['ground_y']
        ptype = pd['plant']['type']
        is_canopy_type = ptype in _CANOPY_TYPES

        for dy, dx, text, _color in pd['plant']['rows']:
            row = gy - dy
            for i, ch in enumerate(text):
                if ch == ' ':
                    continue
                col = px + dx + i
                cell = (row, col)
                collision.add(cell)
                if col not in top or row < top[col]:
                    top[col] = row
                if is_canopy_type and dy >= 3:  # canopy rows (above trunk)
                    canopy.add(cell)

    return collision, top, canopy


# ── Plant layer ─────────────────────────────────────────────────────

_SWAY_TYPES = frozenset({'flower', 'grass', 'fern'})


class PlantLayer:
    """Layer 1: procedurally placed plants with wind sway.

    Update cadence: 300-500ms (sway animation).
    """

    update_interval_ms = 300

    def __init__(self) -> None:
        self._placed: list[dict] = []

    @property
    def placed(self) -> list[dict]:
        return self._placed

    def regenerate(self, state: GardenState,
                   weights: dict[str, int] | None = None) -> None:
        """(Re)generate plant layout from seed and register collision data."""
        self._placed = generate_layout(
            state.width, state.height, state.seed, weights,
            season=state.season)
        cmap, top, canopy = build_collision_map(self._placed)
        state.collision_map = cmap
        state.top_surfaces = top
        state.canopy_cells = canopy

    def update(self, state: GardenState) -> None:
        pass  # sway is computed at render time from frame + wind

    def render(self, buf: ScreenBuffer, state: GardenState) -> None:
        frame = state.frame
        for pd in self._placed:
            px, gy = pd['x'], pd['ground_y']
            ptype = pd['plant']['type']
            sway = 0
            if ptype in _SWAY_TYPES:
                sway = int(math.sin(frame * 0.06 + px * 0.4) * 0.7)
            for dy, dx, text, color in pd['plant']['rows']:
                row = gy - dy
                col = px + dx + (sway if dy >= 2 else 0)
                buf.put_str(row, col, text, color)

    def on_resize(self, state: GardenState) -> None:
        pass  # regeneration with seasonal weights handled by GardenRenderer
