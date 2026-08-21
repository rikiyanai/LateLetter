"""Pure season mapping with an injected month; no system-clock ownership."""

from __future__ import annotations


SEASONS = ("spring", "summer", "autumn", "winter")
_MONTH_TO_SEASON = {
    12: "winter", 1: "winter", 2: "winter",
    3: "spring", 4: "spring", 5: "spring",
    6: "summer", 7: "summer", 8: "summer",
    9: "autumn", 10: "autumn", 11: "autumn",
}


def season_for_month(month: int) -> str:
    try:
        return _MONTH_TO_SEASON[int(month)]
    except (KeyError, ValueError) as exc:
        raise ValueError("month must be in 1..12") from exc
