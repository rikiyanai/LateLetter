"""Terminal glyph projection for canonical plant species.

No layout, growth, randomness, collision, or persistence is owned here.
"""

from __future__ import annotations


_PLANT_SYMBOLS = {
    "oak": "♣",
    "pine": "▲",
    "willow": "♠",
    "rose": "✿",
    "hydrangea": "*",
    "ivy": "~",
    "wisteria": "w",
    "meadow_grass": "'",
    "lavender": ":",
    "rosemary": ";",
    "tulip": "Y",
    "sunflower": "O",
    "water_lily": "o",
}


def plant_symbol(species_id: str) -> str:
    return _PLANT_SYMBOLS.get(species_id, "*")
