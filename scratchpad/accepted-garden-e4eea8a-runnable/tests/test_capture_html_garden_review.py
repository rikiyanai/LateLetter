"""Contracts for the HTML Garden review-capture harness."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.capture_html_garden_review import (
    Dimensions,
    _desktop_master_command,
    _gif_command,
    artifact_paths,
    gif_loop_count_bytes,
    parse_aria_object_counts,
    validate_capture_url,
    validate_label,
)


def test_artifact_names_preserve_checkpoint_and_exact_dimensions(tmp_path):
    paths = artifact_paths(
        tmp_path,
        "14-garden-motion-candidate",
        Dimensions(1600, 1000),
        Dimensions(390, 844),
        Dimensions(960, 600),
    )

    assert paths.desktop_master.name == (
        "14-garden-motion-candidate-desktop-1600x1000.webm"
    )
    assert paths.desktop_still.name == (
        "14-garden-motion-candidate-desktop-1600x1000.png"
    )
    assert paths.mobile_master.name == (
        "14-garden-motion-candidate-mobile-390x844.webm"
    )
    assert paths.mobile_still.name == (
        "14-garden-motion-candidate-mobile-390x844.png"
    )
    assert paths.gif.name == "14-garden-motion-candidate-desktop-960x600.gif"
    assert paths.receipt.name == "14-garden-motion-candidate-receipt.json"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1600x1000", Dimensions(1600, 1000)),
        ("390x844", Dimensions(390, 844)),
    ],
)
def test_dimensions_parse_bounded_positive_viewports(text, expected):
    assert Dimensions.parse(text) == expected


@pytest.mark.parametrize("text", ["0x600", "960x0", "x600", "960", "99999x20"])
def test_dimensions_reject_invalid_or_unbounded_values(text):
    with pytest.raises(Exception):
        Dimensions.parse(text)


def test_capture_url_is_loopback_by_default_and_cannot_freeze_motion():
    assert validate_capture_url(
        "http://127.0.0.1:8770/viewer-bnw.html"
    ) == "http://127.0.0.1:8770/viewer-bnw.html"
    with pytest.raises(ValueError, match="loopback"):
        validate_capture_url("https://example.com/viewer-bnw.html")
    assert validate_capture_url(
        "https://example.com/viewer-bnw.html", allow_remote=True
    ).startswith("https://example.com/")
    with pytest.raises(ValueError, match="freezes"):
        validate_capture_url(
            "http://localhost:8770/viewer-bnw.html?garden_review_time=1"
        )


def test_label_is_filename_scoped():
    assert validate_label("14-garden-motion-candidate") == (
        "14-garden-motion-candidate"
    )
    for invalid in ("", "../escape", "has space", "/absolute", "x" * 81):
        with pytest.raises(Exception):
            validate_label(invalid)


def test_aria_counts_parse_the_real_standalone_label():
    label = (
        "storybook sky. summer day. Garden with 8 plants, 10 fixtures, "
        "4 relationship animals, 3 collectibles. Inventory: empty."
    )
    assert parse_aria_object_counts(label) == {
        "plants": 8,
        "fixtures": 10,
        "relationship_animals": 4,
        "collectibles": 3,
    }


def test_gif_loop_parser_requires_the_infinite_application_extension():
    forever = (
        b"GIF89a"
        b"\x21\xff\x0bNETSCAPE2.0"
        b"\x03\x01\x00\x00\x00"
    )
    finite = (
        b"GIF89a"
        b"\x21\xff\x0bNETSCAPE2.0"
        b"\x03\x01\x03\x00\x00"
    )

    assert gif_loop_count_bytes(forever) == 0
    assert gif_loop_count_bytes(finite) == 3
    assert gif_loop_count_bytes(b"GIF89a") is None


def test_master_command_crops_the_motion_only_tail_without_overwriting(tmp_path):
    command = _desktop_master_command(
        tmp_path / "raw.webm", tmp_path / "master.webm", 10.0
    )

    assert command[0] == "ffmpeg"
    assert "-n" in command
    assert command[command.index("-sseof") + 1] == "-10.000"
    assert command[command.index("-t") + 1] == "10.000"
    assert command[command.index("-c:v") + 1] == "libvpx-vp9"


def test_gif_command_matches_renderer_cadence_and_palette_pipeline(tmp_path):
    command = _gif_command(
        tmp_path / "master.webm",
        tmp_path / "review.gif",
        Dimensions(960, 600),
        10.0,
        10,
    )
    filters = command[command.index("-vf") + 1]

    assert "-n" in command
    assert command[command.index("-loop") + 1] == "0"
    assert "fps=10" in filters
    assert "scale=960:600:flags=lanczos" in filters
    assert "palettegen=max_colors=256:stats_mode=diff" in filters
    assert "paletteuse=dither=sierra2_4a:diff_mode=rectangle" in filters
