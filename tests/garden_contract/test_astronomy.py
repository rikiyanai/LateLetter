from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path

import pytest

from lateletter.garden.astronomy import (
    CoarseLocation, alt_az_from_gast, greenwich_apparent_sidereal_time,
    load_bright_star_catalog, ra_dec_to_alt_az, resolve_sky_mode, visible_stars,
)


FIXTURES = Path(__file__).parent / "fixtures"


def test_location_quantizes_immediately_and_persists_no_raw_coordinates():
    location = CoarseLocation.from_raw(35.681236, 139.767125)
    assert location.to_mapping() == {
        "latitude_cell": 36, "longitude_cell": 140, "grid_degrees": 1,
    }
    assert set(location.to_mapping()) == {"latitude_cell", "longitude_cell", "grid_degrees"}
    with pytest.raises(ValueError):
        CoarseLocation.from_mapping({
            **location.to_mapping(), "raw_latitude": 35.681236,
        })


def test_location_denial_uses_labeled_storybook_fallback():
    resolution = resolve_sky_mode("reader_live")
    assert resolution.mode == "storybook_fallback"
    assert resolution.location is None
    assert resolution.label == "storybook sky"
    assert resolution.is_astronomical is False


def test_usno_cardinal_horizon_cases():
    overhead = alt_az_from_gast(
        gast_hours=10, right_ascension_hours=10, declination_degrees=0,
        latitude_degrees=0, longitude_degrees=0,
    )
    western = alt_az_from_gast(
        gast_hours=10, right_ascension_hours=4, declination_degrees=0,
        latitude_degrees=0, longitude_degrees=0,
    )
    eastern = alt_az_from_gast(
        gast_hours=10, right_ascension_hours=16, declination_degrees=0,
        latitude_degrees=0, longitude_degrees=0,
    )
    assert overhead[0] == pytest.approx(90)
    assert western == pytest.approx((0, 270), abs=1e-12)
    assert eastern == pytest.approx((0, 90), abs=1e-12)


def test_usno_datetime_conformance_vectors():
    payload = json.loads((FIXTURES / "astronomy_vectors.v1.json").read_text())
    for vector in payload["vectors"]:
        when = datetime.fromisoformat(vector["timestamp"])
        gast = greenwich_apparent_sidereal_time(when)
        location = CoarseLocation(int(vector["latitude"]), int(vector["longitude"]))
        altitude, azimuth = ra_dec_to_alt_az(
            when=when, location=location,
            right_ascension_hours=vector["ra_hours"],
            declination_degrees=vector["dec_degrees"],
        )
        assert gast == pytest.approx(vector["gast_hours"], abs=1e-10)
        assert altitude == pytest.approx(vector["altitude_degrees"], abs=1e-10)
        assert azimuth == pytest.approx(vector["azimuth_degrees"], abs=1e-10)


def test_curated_catalog_is_versioned_and_visible_projection_is_sorted():
    catalog = load_bright_star_catalog()
    assert catalog["id"] == "bright-stars-1"
    assert len(catalog["stars"]) >= 20
    visible = visible_stars(
        datetime.fromisoformat("2026-07-21T12:00:00+00:00"),
        CoarseLocation(41, -74), catalog["stars"],
    )
    assert visible
    assert all(star["altitude_degrees"] >= 0 for star in visible)
    assert [star["visual_magnitude"] for star in visible] == sorted(
        star["visual_magnitude"] for star in visible
    )
