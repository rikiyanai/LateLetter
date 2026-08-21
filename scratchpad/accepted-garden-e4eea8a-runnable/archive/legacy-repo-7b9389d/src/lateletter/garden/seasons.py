"""Season detection and configuration per §7.4.

Derives season from system date (or CLI override). Each season controls:
  - plant type weights
  - active animations
  - color palette
  - creature spawn rates
  - weather intensity
"""
from __future__ import annotations

import datetime

from .plants import DEFAULT_WEIGHTS

# ── Season from date ────────────────────────────────────────────────

SEASONS = ('spring', 'summer', 'autumn', 'winter')

_MONTH_TO_SEASON = {
    12: 'winter', 1: 'winter', 2: 'winter',
    3: 'spring', 4: 'spring', 5: 'spring',
    6: 'summer', 7: 'summer', 8: 'summer',
    9: 'autumn', 10: 'autumn', 11: 'autumn',
}


def detect_season() -> str:
    """Return current season based on system date."""
    return _MONTH_TO_SEASON[datetime.date.today().month]


# ── Seasonal plant weights (§7.4) ──────────────────────────────────

SEASON_WEIGHTS: dict[str, dict[str, int]] = {
    'spring': {
        'pine': 5, 'oak': 6, 'bush': 6, 'flower': 25,
        'grass': 15, 'mushroom': 3, 'fern': 8,
    },
    'summer': DEFAULT_WEIGHTS,  # full palette
    'autumn': {
        'pine': 8, 'oak': 10, 'bush': 6, 'flower': 10,
        'grass': 10, 'mushroom': 5, 'fern': 5,
    },
    'winter': {
        'pine': 15, 'oak': 10, 'bush': 4, 'flower': 3,
        'grass': 5, 'mushroom': 1, 'fern': 3,
    },
}


def get_weights(season: str) -> dict[str, int]:
    """Return plant type weights for a season."""
    return SEASON_WEIGHTS.get(season, DEFAULT_WEIGHTS)
