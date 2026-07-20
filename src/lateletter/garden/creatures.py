"""Terminal glyph projection for canonical animal decisions.

Animal movement, bonding, routines, and choreography live in world.animals.
"""

from __future__ import annotations


_ANIMAL_SYMBOLS = {
    "bird": "v",
    "cat": "c",
    "rabbit": "r",
    "turtle": "t",
}


def animal_symbol(species_id: str, intent: str = "idle") -> str:
    symbol = _ANIMAL_SYMBOLS.get(species_id, "a")
    return symbol.upper() if intent in {"greet", "play", "sing"} else symbol
