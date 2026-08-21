"""Privacy-preserving bright-star projection for the garden sky.

The sidereal-time and horizon-coordinate equations follow the U.S. Naval
Observatory Astronomical Applications Department formulas:
https://aa.usno.navy.mil/faq/GAST and https://aa.usno.navy.mil/faq/alt_az

UTC is used as the documented UT1/TT approximation suitable for this artistic
bright-star layer.  This is not a navigation or observatory-grade library.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from importlib.resources import files
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence


CATALOG_VERSION = "bright-stars-1"
SKY_MODES = frozenset({
    "reader_live", "author_fixed", "author_clock", "story_event",
    "storybook_fallback",
})


def _quantize(value: float, grid: float) -> int:
    scaled = value / grid
    return math.floor(scaled + 0.5) if scaled >= 0 else math.ceil(scaled - 0.5)


@dataclass(frozen=True)
class CoarseLocation:
    """Persistable coarse coordinates; raw geolocation is never retained."""

    latitude_cell: int
    longitude_cell: int
    grid_degrees: int = 1

    def __post_init__(self) -> None:
        if any(
            isinstance(value, bool) or not isinstance(value, int)
            for value in (self.latitude_cell, self.longitude_cell, self.grid_degrees)
        ):
            raise ValueError("coarse location cells and grid must be integers")
        if self.grid_degrees != 1:
            raise ValueError("garden sky v1 uses a fixed one-degree grid")
        if not -90 <= self.latitude_cell <= 90:
            raise ValueError("latitude cell must be between -90 and 90")
        if not -180 <= self.longitude_cell < 180:
            raise ValueError("longitude cell must be between -180 and 179")

    @classmethod
    def from_raw(cls, latitude: float, longitude: float) -> "CoarseLocation":
        """Quantize immediately; the returned object has no raw-coordinate fields."""
        if not math.isfinite(latitude) or not math.isfinite(longitude):
            raise ValueError("location must be finite")
        if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
            raise ValueError("location is outside Earth coordinate bounds")
        lat_cell = max(-90, min(90, _quantize(latitude, 1.0)))
        normalized = ((longitude + 180.0) % 360.0) - 180.0
        lon_cell = _quantize(normalized, 1.0)
        if lon_cell == 180:
            lon_cell = -180
        return cls(lat_cell, lon_cell)

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "CoarseLocation":
        if set(raw) != {"latitude_cell", "longitude_cell", "grid_degrees"}:
            raise ValueError("coarse location contains unknown or raw coordinate fields")
        values = (
            raw["latitude_cell"], raw["longitude_cell"], raw["grid_degrees"],
        )
        if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
            raise ValueError("coarse location cells and grid must be integers")
        return cls(*values)

    def to_mapping(self) -> dict[str, int]:
        return {
            "latitude_cell": self.latitude_cell,
            "longitude_cell": self.longitude_cell,
            "grid_degrees": self.grid_degrees,
        }

    @property
    def latitude_degrees(self) -> float:
        return float(self.latitude_cell * self.grid_degrees)

    @property
    def longitude_degrees(self) -> float:
        return float(self.longitude_cell * self.grid_degrees)


@dataclass(frozen=True)
class SkyResolution:
    mode: str
    location: CoarseLocation | None
    label: str
    is_astronomical: bool


def resolve_sky_mode(requested_mode: str, *,
                     reader_location: CoarseLocation | None = None,
                     author_location: CoarseLocation | None = None) -> SkyResolution:
    """Resolve a requested sky without ever requiring recipient location."""
    if requested_mode not in SKY_MODES:
        raise ValueError(f"unsupported sky mode {requested_mode!r}")
    if requested_mode == "storybook_fallback":
        return SkyResolution("storybook_fallback", None, "storybook sky", False)
    if requested_mode == "reader_live" and reader_location is not None:
        return SkyResolution(requested_mode, reader_location, "your local sky", True)
    if requested_mode in {"author_fixed", "author_clock", "story_event"} and author_location is not None:
        return SkyResolution(requested_mode, author_location, "authored story sky", True)
    fallback = author_location if requested_mode == "reader_live" else None
    if fallback is not None:
        return SkyResolution("author_fixed", fallback, "authored story sky", True)
    return SkyResolution("storybook_fallback", None, "storybook sky", False)


def julian_date(when: datetime) -> float:
    if when.tzinfo is None or when.utcoffset() is None:
        raise ValueError("astronomy timestamps must be timezone-aware")
    utc = when.astimezone(timezone.utc)
    return utc.timestamp() / 86_400.0 + 2_440_587.5


def greenwich_apparent_sidereal_time(when: datetime) -> float:
    """Return approximate GAST in hours using the published USNO equations."""
    jd = julian_date(when)
    jd0 = math.floor(jd - 0.5) + 0.5
    hours = (jd - jd0) * 24.0
    d_tt = jd - 2_451_545.0
    d_ut = jd0 - 2_451_545.0
    t = d_tt / 36_525.0
    gmst = (6.697375 + 0.065709824279 * d_ut + 1.0027379 * hours
            + 0.0000258 * t * t) % 24.0

    omega = math.radians(125.04 - 0.052954 * d_tt)
    mean_sun_longitude = math.radians(280.47 + 0.98565 * d_tt)
    obliquity = math.radians(23.4393 - 0.0000004 * d_tt)
    delta_psi_hours = (-0.000319 * math.sin(omega)
                       - 0.000024 * math.sin(2.0 * mean_sun_longitude))
    equation_of_equinoxes = delta_psi_hours * math.cos(obliquity)
    return (gmst + equation_of_equinoxes) % 24.0


def alt_az_from_gast(*, gast_hours: float, right_ascension_hours: float,
                     declination_degrees: float, latitude_degrees: float,
                     longitude_degrees: float) -> tuple[float, float]:
    """Convert RA/Dec to altitude/azimuth via the USNO horizon formulas."""
    if not 0.0 <= right_ascension_hours < 24.0:
        raise ValueError("right ascension must be in [0, 24) hours")
    if not -90.0 <= declination_degrees <= 90.0:
        raise ValueError("declination must be in [-90, 90] degrees")
    if not -90.0 <= latitude_degrees <= 90.0:
        raise ValueError("latitude must be in [-90, 90] degrees")
    if not -180.0 <= longitude_degrees <= 180.0:
        raise ValueError("longitude must be in [-180, 180] degrees")

    lha_degrees = ((gast_hours - right_ascension_hours) * 15.0
                   + longitude_degrees)
    lha = math.radians(lha_degrees)
    declination = math.radians(declination_degrees)
    latitude = math.radians(latitude_degrees)
    sin_altitude = (math.cos(lha) * math.cos(declination) * math.cos(latitude)
                    + math.sin(declination) * math.sin(latitude))
    altitude = math.degrees(math.asin(max(-1.0, min(1.0, sin_altitude))))

    numerator = -math.sin(lha)
    denominator = (math.tan(declination) * math.cos(latitude)
                   - math.sin(latitude) * math.cos(lha))
    azimuth = math.degrees(math.atan2(numerator, denominator)) % 360.0
    return altitude, azimuth


def ra_dec_to_alt_az(*, when: datetime, location: CoarseLocation,
                     right_ascension_hours: float,
                     declination_degrees: float) -> tuple[float, float]:
    return alt_az_from_gast(
        gast_hours=greenwich_apparent_sidereal_time(when),
        right_ascension_hours=right_ascension_hours,
        declination_degrees=declination_degrees,
        latitude_degrees=location.latitude_degrees,
        longitude_degrees=location.longitude_degrees,
    )


def load_bright_star_catalog(path: Path | None = None) -> dict[str, Any]:
    target = path or Path(str(files(__package__).joinpath("data/bright-stars.v1.json")))
    with target.open(encoding="utf-8") as handle:
        raw = json.load(handle)
    if raw.get("version") != 1 or raw.get("id") != CATALOG_VERSION:
        raise ValueError(f"expected star catalog {CATALOG_VERSION}")
    stars = raw.get("stars")
    if not isinstance(stars, list) or not stars:
        raise ValueError("bright-star catalog has no stars")
    seen: set[str] = set()
    for index, star in enumerate(stars):
        if not isinstance(star, Mapping):
            raise ValueError(f"stars[{index}] must be an object")
        if set(star) != {"id", "hr", "name", "ra_hours", "dec_degrees", "visual_magnitude"}:
            raise ValueError(f"stars[{index}] has unexpected fields")
        star_id = star["id"]
        if not isinstance(star_id, str) or star_id in seen:
            raise ValueError(f"stars[{index}] has invalid or duplicate id")
        seen.add(star_id)
        if not 0 <= float(star["ra_hours"]) < 24:
            raise ValueError(f"stars[{index}] right ascension is invalid")
        if not -90 <= float(star["dec_degrees"]) <= 90:
            raise ValueError(f"stars[{index}] declination is invalid")
    return json.loads(json.dumps(raw, ensure_ascii=False))


def visible_stars(when: datetime, location: CoarseLocation,
                  stars: Sequence[Mapping[str, Any]] | None = None) -> tuple[dict[str, Any], ...]:
    catalog_stars = stars if stars is not None else load_bright_star_catalog()["stars"]
    visible: list[dict[str, Any]] = []
    for star in catalog_stars:
        altitude, azimuth = ra_dec_to_alt_az(
            when=when, location=location,
            right_ascension_hours=float(star["ra_hours"]),
            declination_degrees=float(star["dec_degrees"]),
        )
        if altitude >= 0.0:
            visible.append({
                **dict(star), "altitude_degrees": altitude,
                "azimuth_degrees": azimuth,
            })
    visible.sort(key=lambda item: (float(item["visual_magnitude"]), item["id"]))
    return tuple(visible)
