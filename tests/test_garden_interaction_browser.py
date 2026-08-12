"""Durable real-browser successor for Garden gates 2 and 12.

The deleted mechanics harness must not return. This test drives the ordinary
viewer at desktop, 390px touch, 320px CSS width, and an actual 200% CDP page
scale. Product actions use coordinate mouse/touch input or real keyboard input;
Locator.click is reserved for entering the standalone setup route.
"""

from __future__ import annotations

import contextlib
import json
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


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@contextlib.contextmanager
def _static_server():
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
        else:  # pragma: no cover
            raise RuntimeError("the static server never came up")
        yield f"http://127.0.0.1:{port}"
    finally:
        process.terminate()
        process.wait(timeout=10)


def _watch(page) -> list[str]:
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(f"pageerror: {error}"))
    page.on(
        "console",
        lambda message: errors.append(f"console.{message.type}: {message.text}")
        if message.type == "error"
        and "favicon.ico" not in ((message.location or {}).get("url", "") + message.text)
        else None,
    )
    return errors


def _open_standalone(page, origin: str) -> None:
    page.goto(f"{origin}/viewer-bnw.html?garden_debug=1", wait_until="networkidle")
    page.locator("#btn-standalone").click()
    page.locator("#hud.vis").wait_for(state="visible")
    page.locator("#g .garden-lattice-row").first.wait_for(state="attached")


def _state(page) -> dict[str, object]:
    return json.loads(page.evaluate("window.__gardenReview.canonicalStateJson()"))


def _coordinate_activate(page, locator, *, touch: bool) -> None:
    locator.wait_for(state="visible")
    box = None
    for _ in range(10):
        box = locator.bounding_box()
        if box is not None:
            break
        page.wait_for_timeout(50)
    assert box is not None
    x = box["x"] + box["width"] / 2
    y = box["y"] + box["height"] / 2
    if touch:
        page.touchscreen.tap(x, y)
    else:
        page.mouse.click(x, y)


def _activate_garden_object(page, object_id: str, *, touch: bool) -> None:
    """Activate accepted object art away from its invisible anchor target."""
    page.wait_for_function(
        "id => window.__gardenReview.objectRectPixels(id) !== null && "
        "window.__gardenReview.objectArtRectPixels(id) !== null", arg=object_id,
    )
    point = page.evaluate(
        """id => {
          const hotspot = window.__gardenReview.objectRectPixels(id);
          const art = window.__gardenReview.objectArtRectPixels(id);
          if (!hotspot || !art) return null;
          const width = Math.max(44, hotspot.width);
          const height = Math.max(44, hotspot.height);
          const expanded = {
            left: hotspot.x - (width - hotspot.width) / 2,
            right: hotspot.x + hotspot.width + (width - hotspot.width) / 2,
            top: hotspot.y - (height - hotspot.height) / 2,
            bottom: hotspot.y + hotspot.height + (height - hotspot.height) / 2,
          };
          const xs = [.08, .25, .5, .75, .92].map(f => art.x + art.width * f);
          const ys = [.08, .25, .5, .75, .92].map(f => art.y + art.height * f);
          const garden = document.querySelector('#g');
          for (const y of ys) for (const x of xs) {
            const outsideAnchor = x < expanded.left || x >= expanded.right ||
              y < expanded.top || y >= expanded.bottom;
            const element = document.elementFromPoint(x, y);
            if (outsideAnchor && x >= 0 && y >= 0 && x < innerWidth && y < innerHeight &&
                element && (element === garden || element.closest('#g') === garden)) {
              return {x, y};
            }
          }
          return null;
        }""",
        object_id,
    )
    assert point is not None, "no exposed rose-art point exists outside its anchor target"
    x, y = point["x"], point["y"]
    assert page.evaluate(
        "p => window.__gardenReview.objectAtPixels(p.x, p.y)", point,
    ) == object_id, "visible rose art did not resolve to its projected identity"
    if touch:
        page.touchscreen.tap(x, y)
    else:
        page.mouse.click(x, y)


def _empty_garden_ground_point(page) -> dict[str, float]:
    """Find visible lower-Garden paint that resolves to no canonical object."""
    point = page.evaluate(
        """() => {
          const garden = document.querySelector('#g');
          const rect = garden.getBoundingClientRect();
          for (let y = rect.top + rect.height * .55; y < rect.bottom - 8; y += 12) {
            for (let x = rect.left + 8; x < rect.right - 8; x += 12) {
              const element = document.elementFromPoint(x, y);
              if (element && (element === garden || element.closest('#g') === garden) &&
                  window.__gardenReview.objectAtPixels(x, y) === null) return {x, y};
            }
          }
          return null;
        }"""
    )
    assert point is not None, "no visible empty Garden ground point exists"
    return point


def _keyboard_focus_object(page, object_id: str, *, object_count: int) -> None:
    """Reach one canonical object through the product's real ring navigation."""
    for _ in range(object_count + 1):
        previous = page.evaluate("window.__gardenReview.focus()?.id ?? null")
        page.keyboard.press("]")
        page.wait_for_function(
            "before => (window.__gardenReview.focus()?.id ?? null) !== before",
            arg=previous,
        )
        if page.evaluate("window.__gardenReview.focus()?.id") == object_id:
            page.wait_for_function(
                """id => {
                  const target = window.__gardenReview.positions().find(item => item.id === id);
                  return target &&
                    JSON.stringify(window.__gardenReview.camera()) ===
                      JSON.stringify(target.position) &&
                    window.__gardenReview.objectRectPixels(id) !== null &&
                    window.__gardenReview.objectArtRectPixels(id) !== null;
                }""",
                arg=object_id,
            )
            return
    raise AssertionError(f"keyboard ring never reached {object_id}")


def _assert_touch_floor_and_css_fit(page, selector: str, width: int) -> None:
    rectangles = page.locator(selector).evaluate_all(
        "nodes => nodes.filter(node => getComputedStyle(node).display !== 'none').map(node => {"
        " const r=node.getBoundingClientRect();"
        " return {left:r.left,right:r.right,width:r.width,height:r.height}; })"
    )
    assert rectangles
    for rect in rectangles:
        assert rect["width"] >= 44 and rect["height"] >= 44, rect
        assert rect["left"] >= -0.5 and rect["right"] <= width + 0.5, rect


def test_garden_controls_cover_required_browser_inputs_and_viewports():
    error_streams: list[list[str]] = []
    with _static_server() as origin, playwright_api.sync_playwright() as driver:
        try:
            browser = driver.chromium.launch(channel="chrome")
        except Exception as failure:  # pragma: no cover - environment dependent
            pytest.skip(f"system Google Chrome is unavailable: {failure}")
        try:
            desktop_context = browser.new_context(
                viewport={"width": 1600, "height": 1000},
            )
            desktop = desktop_context.new_page()
            desktop.set_default_timeout(30_000)
            error_streams.append(_watch(desktop))
            _open_standalone(desktop, origin)
            assert desktop.locator("#garden-context-actions").count() == 0

            # The accepted Garden is a static picture: no autonomous repaint
            # may mutate its visible bytes.
            live_frames: set[str] = set()
            for _ in range(8):
                live_frames.add(desktop.locator("#g").inner_text())
                desktop.wait_for_timeout(125)
            assert len(live_frames) == 1, "ordinary Garden presentation animated"

            initial = _state(desktop)
            home_camera = initial["ui"]["camera"]
            plant_id = initial["plants"][0]["plant_id"]
            mailbox_id = next(
                fixture["fixture_id"] for fixture in initial["fixtures"]
                if fixture["catalog_id"] == "mailbox"
            )
            pond_id = next(
                fixture["fixture_id"] for fixture in initial["fixtures"]
                if fixture["catalog_id"] == "pond"
            )

            assert desktop.locator(
                '#hud-actions [data-garden-command="open_journal"]'
            ).count() == 0
            assert desktop.locator(
                '#hud-actions [data-garden-command="pause_motion"]'
            ).count() == 0

            # The rose is an interaction in the picture, not a permanently
            # painted object-name/action label. A real coordinate click both
            # tends the canonical plant and reports outside the picture.
            _keyboard_focus_object(
                desktop,
                plant_id,
                object_count=len(desktop.evaluate("window.__gardenReview.state().objects")),
            )
            tended_before = _state(desktop)["plants"][0]["tended_count"]
            _activate_garden_object(desktop, plant_id, touch=False)
            desktop.wait_for_function(
                "before => JSON.parse(window.__gardenReview.canonicalStateJson()).plants[0].tended_count > before",
                arg=tended_before,
            )
            desktop.locator("#garden-status").wait_for(state="visible")
            assert "tend" in desktop.locator("#garden-status").inner_text().lower()

            # Keyboard focus, primary interaction, tend and pan
            # all traverse the document's recorded keyboard routes.
            tended_before = _state(desktop)["plants"][0]["tended_count"]
            desktop.keyboard.press("Enter")
            desktop.wait_for_function(
                "before => JSON.parse(window.__gardenReview.canonicalStateJson()).plants[0].tended_count > before",
                arg=tended_before,
            )
            tended_before = _state(desktop)["plants"][0]["tended_count"]
            desktop.keyboard.press("t")
            desktop.wait_for_function(
                "before => JSON.parse(window.__gardenReview.canonicalStateJson()).plants[0].tended_count > before",
                arg=tended_before,
            )
            before_global_keys = desktop.evaluate(
                "window.__gardenReview.canonicalStateJson()"
            )
            desktop.keyboard.press("Space")
            desktop.keyboard.press("j")
            assert desktop.evaluate(
                "window.__gardenReview.canonicalStateJson()"
            ) == before_global_keys

            # Journal has no HUD label. Once tending creates content, the
            # canonical mailbox becomes its direct picture-owned entrance.
            _activate_garden_object(desktop, mailbox_id, touch=False)
            desktop.locator("#garden-journal").wait_for(state="visible")
            desktop.evaluate(
                """() => {
                    window.__gardenStableJournal = {
                        close: document.querySelector('#garden-journal-close'),
                        entry: document.querySelector('#garden-journal-list > li'),
                    };
                    window.__gardenStableJournal.close.focus();
                }"""
            )
            desktop.wait_for_timeout(1_250)
            assert desktop.evaluate(
                """() => {
                    const saved = window.__gardenStableJournal;
                    return saved.close === document.querySelector('#garden-journal-close')
                        && saved.entry === document.querySelector('#garden-journal-list > li')
                        && document.activeElement === saved.close;
                }"""
            )
            desktop.keyboard.press("Escape")
            desktop.locator("#garden-journal").wait_for(state="hidden")
            camera = desktop.evaluate("window.__gardenReview.camera()")
            desktop.keyboard.press("Shift+ArrowRight")
            desktop.wait_for_function(
                "before => JSON.stringify(window.__gardenReview.camera()) !== JSON.stringify(before)",
                arg=camera,
            )

            # The operator's residual drag defect, pinned through the full
            # pointer -> canonical camera -> compositor -> pixel-layout path.
            # The accepted contract (batch operator decision item 8) is that a
            # drag settles onto a canonical cell camera position and that pan
            # passes through mouse and keyboard with IDENTICAL state
            # transitions and identical presentation: reaching camera [47,40]
            # by a settled pointer drag must paint every object at exactly the
            # pixel position the keyboard route paints it. (Per-step painted
            # displacement legitimately varies with the viewport fit, so the
            # law is same-camera/same-picture, not same-pixels-per-step.)
            desktop.keyboard.press("Home")
            desktop.wait_for_function(
                "home => JSON.stringify(window.__gardenReview.camera()) === JSON.stringify(home)",
                arg=home_camera,
            )
            for _ in range(13):
                desktop.keyboard.press("Shift+ArrowLeft")
            desktop.wait_for_function(
                "() => JSON.stringify(window.__gardenReview.camera()) === '[47,40]'"
            )
            keyboard_rects = {
                object_id: desktop.evaluate(
                    "id => window.__gardenReview.objectArtRectPixels(id).x", object_id
                )
                for object_id in (plant_id, pond_id)
            }
            desktop.keyboard.press("Shift+ArrowLeft")
            desktop.wait_for_function(
                "() => JSON.stringify(window.__gardenReview.camera()) === '[46,40]'"
            )

            drag_start = _empty_garden_ground_point(desktop)
            desktop.mouse.move(drag_start["x"], drag_start["y"])
            desktop.mouse.down()
            desktop.mouse.move(drag_start["x"] - 8, drag_start["y"])
            desktop.mouse.up()
            desktop.wait_for_function(
                "() => JSON.stringify(window.__gardenReview.camera()) === '[47,40]'"
            )
            # The session-only gesture residue must be fully settled before
            # sampling pixel rects: the cleared custom property is the
            # falsifiable signal that the commit landed.
            desktop.wait_for_function(
                "() => !document.getElementById('g').style"
                ".getPropertyValue('--garden-drag-x')"
            )
            pointer_rects = {
                object_id: desktop.evaluate(
                    "id => window.__gardenReview.objectArtRectPixels(id).x", object_id
                )
                for object_id in (plant_id, pond_id)
            }
            for object_id in (plant_id, pond_id):
                assert pointer_rects[object_id] == pytest.approx(
                    keyboard_rects[object_id], abs=0.5
                ), {
                    "object_id": object_id,
                    "keyboard_x": keyboard_rects[object_id],
                    "pointer_x": pointer_rects[object_id],
                }

            # A coordinate mouse drag pans canonically and does not rely on a
            # locator-generated click event.
            camera = desktop.evaluate("window.__gardenReview.camera()")
            desktop.mouse.move(240, 760)
            desktop.mouse.down()
            desktop.mouse.move(140, 760, steps=5)
            desktop.mouse.up()
            desktop.wait_for_function(
                "before => JSON.stringify(window.__gardenReview.camera()) !== JSON.stringify(before)",
                arg=camera,
            )

            # Recommendation 20: after a real drag, Home returns to canonical
            # home. Empty-ground double-click is an independent label-free
            # route to that exact camera.
            desktop.keyboard.press("Home")
            desktop.wait_for_function(
                "home => JSON.stringify(window.__gardenReview.camera()) === JSON.stringify(home)",
                arg=home_camera,
            )
            desktop.keyboard.press("Shift+ArrowRight")
            desktop.wait_for_function(
                "home => JSON.stringify(window.__gardenReview.camera()) !== JSON.stringify(home)",
                arg=home_camera,
            )
            empty_ground = _empty_garden_ground_point(desktop)
            desktop.mouse.dblclick(empty_ground["x"], empty_ground["y"])
            desktop.wait_for_function(
                "home => JSON.stringify(window.__gardenReview.camera()) === JSON.stringify(home)",
                arg=home_camera,
            )

            # CDP page scale is the browser's actual visual zoom boundary, not
            # a CSS transform. Measure the resulting CSS visual viewport and
            # activate a real control while it is at 200%.
            cdp = desktop_context.new_cdp_session(desktop)
            cdp.send("Emulation.setPageScaleFactor", {"pageScaleFactor": 2})
            zoom = desktop.evaluate(
                "() => ({scale:visualViewport.scale,width:visualViewport.width,inner:innerWidth})"
            )
            assert zoom["scale"] == pytest.approx(2, abs=0.05)
            assert zoom["width"] <= zoom["inner"] / 1.9
            _activate_garden_object(desktop, mailbox_id, touch=False)
            desktop.locator("#garden-journal").wait_for(state="visible")
            desktop.keyboard.press("Escape")
            cdp.send("Emulation.setPageScaleFactor", {"pageScaleFactor": 1})

            desktop.set_viewport_size({"width": 320, "height": 568})
            desktop.wait_for_timeout(200)
            _assert_touch_floor_and_css_fit(
                desktop,
                "#hud-btns button",
                320,
            )
            desktop_context.close()

            # A separate 390x844 mobile context supplies native CDP touch
            # events and a reduced-motion media preference. Tap and drag both
            # have to mutate the canonical world while the Garden still paints.
            touch_context = browser.new_context(
                viewport={"width": 390, "height": 844},
                has_touch=True,
                is_mobile=True,
                reduced_motion="reduce",
            )
            touch_page = touch_context.new_page()
            touch_page.set_default_timeout(30_000)
            error_streams.append(_watch(touch_page))
            _open_standalone(touch_page, origin)
            assert touch_page.evaluate("matchMedia('(prefers-reduced-motion: reduce)').matches")
            assert touch_page.locator("#g").inner_text().strip()
            touch_state = _state(touch_page)
            touch_home_camera = touch_state["ui"]["camera"]
            touch_id = touch_state["plants"][0]["plant_id"]
            # Traverse the real keyboard ring before proving the touch-only
            # action route; focus and pointer still use canonical identity.
            _keyboard_focus_object(
                touch_page,
                touch_id,
                object_count=len(touch_page.evaluate("window.__gardenReview.state().objects")),
            )
            assert touch_page.locator("#garden-context-actions").count() == 0
            _activate_garden_object(touch_page, touch_id, touch=True)
            touch_page.wait_for_function(
                "() => JSON.parse(window.__gardenReview.canonicalStateJson()).plants[0].tended_count === 1"
            )

            camera = touch_page.evaluate("window.__gardenReview.camera()")
            touch_cdp = touch_context.new_cdp_session(touch_page)
            touch_cdp.send("Input.dispatchTouchEvent", {
                "type": "touchStart", "touchPoints": [{"x": 320, "y": 700}],
            })
            for x in (300, 280, 260, 240):
                touch_cdp.send("Input.dispatchTouchEvent", {
                    "type": "touchMove", "touchPoints": [{"x": x, "y": 700}],
                })
            touch_cdp.send("Input.dispatchTouchEvent", {
                "type": "touchEnd", "touchPoints": [],
            })
            touch_page.wait_for_function(
                "before => JSON.stringify(window.__gardenReview.camera()) !== JSON.stringify(before)",
                arg=camera,
            )
            empty_ground = _empty_garden_ground_point(touch_page)
            touch_page.touchscreen.tap(empty_ground["x"], empty_ground["y"])
            touch_page.touchscreen.tap(empty_ground["x"], empty_ground["y"])
            touch_page.wait_for_function(
                "home => JSON.stringify(window.__gardenReview.camera()) === JSON.stringify(home)",
                arg=touch_home_camera,
            )
            _assert_touch_floor_and_css_fit(
                touch_page,
                "#hud-btns button",
                390,
            )
            touch_context.close()
        finally:
            browser.close()

    all_errors = [error for stream in error_streams for error in stream]
    assert all_errors == [], all_errors


def test_local_fixed_time_is_an_executable_four_season_review_route():
    cases = {
        "2026-01-15T12:00:00Z": "winter",
        "2026-04-15T12:00:00Z": "spring",
        "2026-07-15T12:00:00Z": "summer",
        "2026-10-15T12:00:00Z": "autumn",
    }
    streams: list[list[str]] = []
    with _static_server() as origin, playwright_api.sync_playwright() as driver:
        try:
            browser = driver.chromium.launch(channel="chrome")
        except Exception as failure:  # pragma: no cover
            pytest.skip(f"system Google Chrome is unavailable: {failure}")
        try:
            for timestamp, expected in cases.items():
                context = browser.new_context(viewport={"width": 1280, "height": 900})
                page = context.new_page()
                streams.append(_watch(page))
                page.goto(
                    f"{origin}/viewer-bnw.html?garden_debug=1&garden_review_time={timestamp}",
                    wait_until="networkidle",
                )
                page.locator("#btn-standalone").click()
                page.locator("#hud.vis").wait_for(state="visible")
                presentation = page.evaluate("window.__gardenReview.presentation()")
                assert presentation["season"] == expected
                assert presentation["review_time"] is not None
                assert presentation["sky_label"]
                context.close()
        finally:
            browser.close()
    errors = [error for stream in streams for error in stream]
    assert errors == []
