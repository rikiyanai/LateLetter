"""Recipient letter typography, exercised through the real browser flow."""

from __future__ import annotations

import contextlib
import sys
from pathlib import Path

import pytest


playwright_api = pytest.importorskip(
    "playwright.sync_api",
    reason="playwright is not installed in this interpreter",
)

sys.path.insert(0, str(Path(__file__).parent))
from test_garden_interaction_browser import _static_server, _watch


PRODUCT_QUERY = "garden_debug=1"


@contextlib.contextmanager
def _chrome(_origin: str, *, viewport: tuple[int, int]):
    """Own the typography browser fixture; never revive the deleted harness."""
    with playwright_api.sync_playwright() as driver:
        try:
            browser = driver.chromium.launch(channel="chrome")
        except Exception as failure:  # pragma: no cover - environment dependent
            pytest.skip(f"system Google Chrome is unavailable: {failure}")
        context = browser.new_context(
            viewport={"width": viewport[0], "height": viewport[1]},
            has_touch=viewport[0] <= 500,
            is_mobile=viewport[0] <= 500,
        )
        page = context.new_page()
        errors = _watch(page)
        try:
            yield page, errors
        finally:
            context.close()
            browser.close()


def _open_demo_letter(page, origin: str) -> None:
    page.goto(
        f"{origin}/viewer-bnw.html?{PRODUCT_QUERY}", wait_until="networkidle"
    )
    page.locator("#btn-demo").click()
    page.locator("#hud.vis").wait_for(state="visible", timeout=15_000)
    page.get_by_role("button", name="open letters").click()
    page.locator("#pp-input").fill("dev fixture accepts any phrase")
    page.locator("#btn-unlock").click()
    page.locator("#s-archive.active").wait_for(state="visible", timeout=15_000)
    page.locator("#arc-content button").first.click()
    page.locator("#s-reading.active").wait_for(state="visible", timeout=15_000)


def _painted_letter_metrics(page) -> dict:
    return page.locator("#letter-body").evaluate(
        """el => {
            const cs = getComputedStyle(el);
            const scrim = el.closest('.scrim');
            const scrimStyle = getComputedStyle(scrim);
            const scrimRect = scrim.getBoundingClientRect();
            const contentRight = el.getBoundingClientRect().right
              - (parseFloat(cs.paddingRight) || 0);
            const rows = [...el.querySelectorAll('.ll')];
            return {
              fontSize: parseFloat(cs.fontSize),
              lineHeight: parseFloat(cs.lineHeight),
              fallback: el.classList.contains('fallback'),
              blankHeights: rows
                .filter(row => row.textContent === '')
                .map(row => row.getBoundingClientRect().height),
              justifiedRightGaps: rows
                .filter(row => row.classList.contains('ll-j'))
                .map(row => contentRight
                  - row.lastElementChild.getBoundingClientRect().right),
              scrim: {
                background: scrimStyle.backgroundColor,
                backdropFilter: scrimStyle.backdropFilter
                  || scrimStyle.webkitBackdropFilter,
                boxShadow: scrimStyle.boxShadow,
                overflowY: scrimStyle.overflowY,
                rect: {
                  left: scrimRect.left,
                  top: scrimRect.top,
                  right: scrimRect.right,
                  bottom: scrimRect.bottom,
                },
                viewport: {
                  width: innerWidth,
                  height: innerHeight,
                },
              },
            };
        }"""
    )


def test_letter_typography_uses_the_painted_metrics_at_desktop_and_phone_widths():
    """Responsive CSS, PreText measurement, and painted rows remain one truth."""
    with _static_server() as origin:
        measurements = []
        for viewport in ((1280, 800), (390, 844)):
            with _chrome(origin, viewport=viewport) as (page, errors):
                _open_demo_letter(page, origin)
                measurements.append(_painted_letter_metrics(page))
            assert errors == []

    desktop, phone = measurements
    assert desktop["fontSize"] == 13
    assert phone["fontSize"] == 12

    for measurement in measurements:
        assert not measurement["fallback"]
        assert len(measurement["blankHeights"]) == 4
        assert all(
            abs(height - measurement["lineHeight"]) < 0.5
            for height in measurement["blankHeights"]
        )
        assert measurement["justifiedRightGaps"]
        assert all(
            abs(gap) < 0.5 for gap in measurement["justifiedRightGaps"]
        )

        # The reading surface is a soft veil over the living Garden, not an
        # opaque full-screen panel. Keep paint and geometry in the real route.
        scrim = measurement["scrim"]
        assert "0.96" in scrim["background"]
        assert scrim["backdropFilter"] == "blur(18px) contrast(0.9)"
        assert "38px 24px" in scrim["boxShadow"]
        assert "0.82" in scrim["boxShadow"]
        assert scrim["overflowY"] == "visible"
        assert scrim["rect"]["left"] > 0
        assert scrim["rect"]["right"] < scrim["viewport"]["width"]
        assert scrim["rect"]["bottom"] < scrim["viewport"]["height"]
