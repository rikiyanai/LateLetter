"""The Garden's no-action-chrome rule, exercised in a real browser.

Why this file exists
--------------------
The rejected implementation painted opportunity cards, hover instructions, an
object list and a "More actions" sheet over the Garden.  Source tests then
required those unapproved controls to exist.  This test drives the localhost
review surface and asserts both sides of the operator's decision: the picture
is painted, while the rejected product UI cannot return over it.

Running it
----------
``playwright`` and system Google Chrome must already be installed; the test
skips when they are not, exactly like ``scripts/capture_html_garden_review.py``,
which shares the same requirement and the same policy of never downloading a
browser.  The project's own virtual environment does not carry ``playwright``,
so this is normally run from an interpreter that does::

    python3 -m pytest tests/test_garden_interaction_browser.py
"""

from __future__ import annotations

import contextlib
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest


playwright_api = pytest.importorskip(
    "playwright.sync_api",
    reason="playwright is not installed in this interpreter",
)

ROOT = Path(__file__).parents[1]
DESKTOP = (1600, 1000)
MOBILE = (390, 844)


def _free_port() -> int:
    """Ask the OS for a port nobody is using, and let go of it immediately."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@contextlib.contextmanager
def _static_server():
    """Serve the repository over HTTP for the duration of the test.

    The viewer is an ES module and fetches sibling files, so ``file://`` will
    not do — the browser refuses cross-origin module imports from it.
    """
    port = _free_port()
    process = subprocess.Popen(
        [sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1"],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            with socket.socket() as probe:
                if probe.connect_ex(("127.0.0.1", port)) == 0:
                    break
            time.sleep(0.05)
        else:  # pragma: no cover - only on a badly wedged machine
            raise RuntimeError("the static server never came up")
        yield f"http://127.0.0.1:{port}"
    finally:
        process.terminate()
        process.wait(timeout=10)


def test_garden_renders_no_object_action_labels_cards_or_lists():
    errors: list[str] = []
    with _static_server() as origin, playwright_api.sync_playwright() as driver:
        try:
            browser = driver.chromium.launch(channel="chrome")
        except Exception as failure:  # pragma: no cover - environment dependent
            pytest.skip(f"system Google Chrome is unavailable: {failure}")
        context = browser.new_context(
            viewport={"width": DESKTOP[0], "height": DESKTOP[1]},
        )
        page = context.new_page()
        page.on("pageerror", lambda error: errors.append(f"pageerror: {error}"))
        page.on(
            "console",
            lambda message: errors.append(f"console.{message.type}: {message.text}")
            if message.type == "error"
            and "/favicon.ico" not in (message.location or {}).get("url", "")
            else None,
        )
        try:
            # Localhost paints the tracked candidate without any permission
            # query. The public workflow still serves the legacy Garden.
            page.goto(f"{origin}/viewer-bnw.html", wait_until="networkidle")
            page.locator("#btn-demo").click()
            page.locator("#hud.vis").wait_for(state="visible")
            page.locator("#g .garden-lattice-row").first.wait_for(state="attached")

            assert page.locator("#g .garden-lattice-row").evaluate_all(
                "rows => rows.reduce((count, row) => count + row.textContent.trim().length, 0)"
            ) > 0, "localhost review must paint the Garden picture"

            forbidden = (
                "#garden-affordances",
                "#garden-semantics",
                "#garden-object-list",
                "#garden-action-sheet",
                ".garden-opportunity",
                "#garden-invitation",
            )
            for selector in forbidden:
                assert page.locator(selector).count() == 0, selector
            assert page.locator("#g button").count() == 0

            page.set_viewport_size({"width": MOBILE[0], "height": MOBILE[1]})
            page.wait_for_timeout(250)
            for selector in forbidden:
                assert page.locator(selector).count() == 0, selector
            assert page.locator("#g button").count() == 0
        finally:
            context.close()
            browser.close()

    assert errors == [], f"the localhost review surface logged errors: {errors}"
