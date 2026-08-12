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


def _exposed_object_art_point(page, object_id: str) -> dict[str, float]:
    """Visible accepted-art pixel of one object, away from its anchor target."""
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
    assert page.evaluate(
        "p => window.__gardenReview.objectAtPixels(p.x, p.y)", point,
    ) == object_id, "visible rose art did not resolve to its projected identity"
    return point


def _activate_garden_object(page, object_id: str, *, touch: bool) -> None:
    """Activate accepted object art away from its invisible anchor target."""
    point = _exposed_object_art_point(page, object_id)
    x, y = point["x"], point["y"]
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


def _empty_garden_row_x(page, y: float, near_x: float) -> float:
    """Empty Garden ground on ONE unchanging row, nearest a wanted x.

    A pan drag has to keep its vertical delta at zero to make the horizontal
    world edge the only clamp under test, so both ends of the gesture must sit
    on the same row -- and both must resolve to no canonical object, because a
    gesture the world edge fully absorbs never crosses the movement threshold
    and therefore releases as an ordinary click.
    """
    x = page.evaluate(
        """([row, wanted]) => {
          const garden = document.querySelector('#g');
          for (let offset = 0; offset <= 600; offset += 4) {
            for (const x of offset ? [wanted + offset, wanted - offset] : [wanted]) {
              if (x < 8 || x > innerWidth - 8) continue;
              const element = document.elementFromPoint(x, row);
              if (element && (element === garden || element.closest('#g') === garden) &&
                  window.__gardenReview.objectAtPixels(x, row) === null) return x;
            }
          }
          return null;
        }""",
        [y, near_x],
    )
    assert x is not None, f"no empty Garden ground exists on row {y}"
    return x


def _wait_drag_settled(page) -> None:
    """Wait for the gesture to finish, not merely for its first camera commit.

    The canonical camera moves on the first mid-gesture commit, so a state
    sample taken right after the release can read a half-finished gesture. The
    cleared session-only custom property is the falsifiable signal that the
    release settled onto a canonical cell and the residue transform is gone.
    """
    page.wait_for_function(
        "() => !document.getElementById('g').style.getPropertyValue('--garden-drag-x')"
    )


def _wait_camera_quiescent(page) -> list[int]:
    """The canonical camera once it has stopped moving.

    Drag pans are dispatched off the pointer thread through a serialized queue,
    so 'the camera differs from before' can be satisfied by a still-draining
    queue rather than by new input. Every clause that must attribute a change
    to input therefore starts from a camera that has demonstrably stopped.
    """
    previous = None
    for _ in range(50):
        current = page.evaluate("window.__gardenReview.camera()")
        if current is not None and current == previous:
            return current
        previous = current
        page.wait_for_timeout(100)
    raise AssertionError("the canonical camera never stopped moving")


def _mouse_drag(page, start: dict[str, float], end: dict[str, float], *, steps: int = 10) -> None:
    page.mouse.move(start["x"], start["y"])
    page.mouse.down()
    page.mouse.move(end["x"], end["y"], steps=steps)
    page.mouse.up()
    _wait_drag_settled(page)


def _wait_art_rect_quiescent(page, object_id: str) -> dict[str, float]:
    """One object's art rectangle once the painted frame has stopped changing.

    The review accessor reports geometry off the LAST PAINTED FRAME, and the
    canonical camera reaches its new value before the repaint that follows it
    lands. Reading a rectangle the instant a camera wait returns therefore hands
    back the previous frame's geometry -- measured here as a whole 54-column
    error -- so every pixel measurement waits for the paint, not the command.
    """
    previous = None
    for _ in range(50):
        current = page.evaluate(
            "id => window.__gardenReview.objectArtRectPixels(id)", object_id,
        )
        if current is not None and current == previous:
            return current
        previous = current
        page.wait_for_timeout(150)
    raise AssertionError(f"the painted art rectangle for {object_id} never settled")


def _wait_gesture_geometry_quiescent(page, object_id: str) -> dict[str, object]:
    """One object's VISIBLE art mid-gesture, sampled from a single settled frame.

    Two sources have to agree for this measurement to mean anything: the review
    accessor's computed rectangle, which belongs to the last painted frame, and
    the session-only residue transform, which is live inline style. The viewer
    lands both in the same microtask burst precisely so a presented frame never
    mixes a committed camera step with an uncorrected transform -- but a sample
    taken while the serialized pan queue is still draining reads one of each.
    So the pointer is held still and the pair is read until it repeats.
    """
    previous = None
    for _ in range(50):
        current = page.evaluate(
            """id => {
              const garden = document.getElementById('g');
              const rect = window.__gardenReview.objectArtRectPixels(id);
              if (!rect) return null;
              return {
                rect,
                residue: [
                  parseFloat(garden.style.getPropertyValue('--garden-drag-x')) || 0,
                  parseFloat(garden.style.getPropertyValue('--garden-drag-y')) || 0,
                ],
                camera: window.__gardenReview.camera(),
              };
            }""",
            object_id,
        )
        if current is not None and current == previous:
            return current
        previous = current
        page.wait_for_timeout(150)
    raise AssertionError(f"the visible art of {object_id} never settled mid-gesture")


def _pixels_per_camera_cell_x(page, *, travel: float = 200.0) -> float:
    """Measure the pointer-pixel to camera-cell pitch on the real drag route.

    One camera cell paints `xScale` columns at world depth and the viewer keeps
    that factor module-private, so the conversion is measured where it is
    actually applied: a known pointer delta in, the canonical camera delta out.
    Painted geometry is deliberately not used -- it snaps to whole character
    columns, which makes a single-cell sample read 7.8px or 15.7px for the same
    underlying pitch. Requires the camera to have room to absorb the travel.
    """
    row = _empty_garden_ground_point(page)["y"]
    start_x = _empty_garden_row_x(page, row, travel + 140)
    before = _wait_camera_quiescent(page)
    _mouse_drag(page, {"x": start_x, "y": row}, {"x": start_x - travel, "y": row})
    after = _wait_camera_quiescent(page)
    cells = after[0] - before[0]
    assert cells >= 8, {
        "before": before, "after": after, "travel": travel,
        "why": "the measuring drag did not pan far enough to divide",
    }
    return travel / cells


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
            desktop.set_default_timeout(60_000)
            error_streams.append(_watch(desktop))
            _open_standalone(desktop, origin)
            assert desktop.locator("#garden-context-actions").count() == 0

            # Operator live rejection (2026-08-13) of the 485d0be static
            # freeze: the Garden breathes by default — the pond water cycles
            # on the accepted 50ms-floor cadence. The picture must visibly
            # change over ordinary time, and the rejected fauna glyphs must
            # NOT ride back in with the ticker.
            live_frames: set[str] = set()
            for _ in range(10):
                live_frames.add(desktop.locator("#g").inner_text())
                desktop.wait_for_timeout(300)
            assert len(live_frames) > 1, "the ordinary Garden is a frozen picture"
            for glyph in ("\u22c8", "\u22ca", "\u2726", "\\v/", "_v_", "/v\\"):
                assert not any(glyph in frame for frame in live_frames), (
                    f"rejected ambient glyph {glyph!r} returned with the motion"
                )

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
            # Route identity is a CANONICAL claim: keyboard and settled drag
            # reach byte-identical camera state, proven by the two exact
            # camera waits above. Pixel-rect equality across the two routes
            # is deliberately NOT asserted: under the restored live loop
            # (operator rejection of the 485d0be static freeze, 2026-08-13)
            # canonical growth advances between samples and legitimately
            # repacks the plant, and presentation route-independence is
            # already pinned where it is owned — composePresentationFrame
            # composes twice and compares in the presentation contract.

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
            touch_page.set_default_timeout(60_000)
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


def test_drag_capture_clamp_and_release_suppression_own_the_gesture():
    """Execute the three unexercised clauses of the Garden drag contract.

    Batch operator decision item 8 (2026-08-11) states four laws for pointer
    dragging: one-to-one visible movement settling onto a canonical cell,
    pointer capture retained beyond the Garden bounds, a clamp at the world
    edges, and never activating an object after a drag. Only the settle law had
    a real-browser executor; the other three were implemented in
    `viewer-bnw.html` with nothing driving them, which is exactly the shape of
    the defects this lane keeps re-introducing.

    Every verdict below is read off canonical state. The painted picture cannot
    distinguish a gesture that dispatched a command from one that did not, and
    the absence of DOM noise cannot prove the absence of an action.
    """
    errors: list[str] = []
    with _static_server() as origin, playwright_api.sync_playwright() as driver:
        try:
            browser = driver.chromium.launch(channel="chrome")
        except Exception as failure:  # pragma: no cover - environment dependent
            pytest.skip(f"system Google Chrome is unavailable: {failure}")
        try:
            context = browser.new_context(viewport={"width": 1600, "height": 1000})
            page = context.new_page()
            page.set_default_timeout(60_000)
            errors = _watch(page)
            _open_standalone(page, origin)

            initial = _state(page)
            home_camera = initial["ui"]["camera"]
            world_width = int(initial["world_width"])
            plant_id = initial["plants"][0]["plant_id"]
            object_count = len(page.evaluate("window.__gardenReview.state().objects"))
            viewport = page.evaluate("() => [innerWidth, innerHeight]")

            def go_home() -> None:
                """Return to the canonical home camera between clauses."""
                page.keyboard.press("Home")
                page.wait_for_function(
                    "home => JSON.stringify(window.__gardenReview.camera()) === "
                    "JSON.stringify(home)",
                    arg=home_camera,
                )

            # Size every gesture below in real camera cells, measured on the
            # drag route itself rather than assumed from a pixel constant.
            pitch = _pixels_per_camera_cell_x(page)

            # ── Clause: CAPTURE BEYOND BOUNDS ────────────────────────────────
            # `#g` is pinned to all four viewport edges, so a pointer cannot
            # leave its box without leaving the window. The event-stealing case
            # that actually matters is the pointer travelling OVER another
            # interactive element: without `setPointerCapture` on pointerdown
            # that element receives the pointer stream and the pan dies
            # mid-gesture. So the proof is that the canonical camera keeps
            # moving while the pointer sits on a HUD button, which is not a
            # descendant of `#g`.
            go_home()
            ground = _empty_garden_ground_point(page)
            overlay = page.evaluate(
                """() => {
                  const candidates = [...document.querySelectorAll('#hud button')]
                    .map(node => ({node, rect: node.getBoundingClientRect()}))
                    .filter(item => item.rect.width > 0 && item.rect.height > 0 &&
                      getComputedStyle(item.node).pointerEvents === 'auto' &&
                      getComputedStyle(item.node).visibility !== 'hidden')
                    .sort((left, right) => right.rect.width - left.rect.width);
                  for (const {node, rect} of candidates) {
                    const hit = document.elementFromPoint(
                      rect.x + rect.width / 2, rect.y + rect.height / 2);
                    if (hit && (hit === node || node.contains(hit)) && !hit.closest('#g')) {
                      window.__dragOverlayProbe = node;
                      return {label: (node.textContent || '').trim(), x: rect.x, y: rect.y,
                              width: rect.width, height: rect.height};
                    }
                  }
                  return null;
                }"""
            )
            assert overlay is not None, (
                "no HUD control outside #g is on screen, so pointer capture has "
                "no event thief to be proven against"
            )

            def overlay_owns(x: float, y: float) -> bool:
                return page.evaluate(
                    """p => {
                      const node = window.__dragOverlayProbe;
                      const hit = document.elementFromPoint(p.x, p.y);
                      return Boolean(hit && (hit === node || node.contains(hit)) &&
                        !hit.closest('#g'));
                    }""",
                    {"x": x, "y": y},
                )

            overlay_left = overlay["x"] + 3
            overlay_right = overlay["x"] + overlay["width"] - 3
            overlay_y = overlay["y"] + overlay["height"] / 2
            assert overlay_right - overlay_left > pitch + 2, {
                "overlay": overlay, "pitch": pitch,
                "why": "the overlay is narrower than one camera cell",
            }
            # Pressing down directly below the overlay keeps the accumulated
            # horizontal delta small, so neither sample can be sitting against
            # the world-edge clamp that the next clause tests deliberately.
            capture_start = {
                "x": _empty_garden_row_x(
                    page, ground["y"], (overlay_left + overlay_right) / 2),
                "y": ground["y"],
            }
            page.mouse.move(capture_start["x"], capture_start["y"])
            page.mouse.down()
            page.mouse.move(overlay_left, overlay_y, steps=12)
            assert overlay_owns(overlay_left, overlay_y), (
                "the pointer is not over the overlay control after moving onto it"
            )
            camera_on_overlay = _wait_camera_quiescent(page)
            page.mouse.move(overlay_right, overlay_y, steps=6)
            assert overlay_owns(overlay_right, overlay_y), (
                "the pointer left the overlay control while crossing it"
            )
            try:
                page.wait_for_function(
                    "before => window.__gardenReview.camera()[0] !== before",
                    arg=camera_on_overlay[0],
                    timeout=10_000,
                )
            except playwright_api.TimeoutError as failure:
                raise AssertionError(
                    "the pan stopped while the pointer was over "
                    f"{overlay['label']!r}: the gesture did not retain pointer "
                    "capture beyond the Garden's own hit surface"
                ) from failure
            camera_across_overlay = page.evaluate("window.__gardenReview.camera()")
            assert camera_across_overlay[0] != camera_on_overlay[0]
            assert 0 <= camera_across_overlay[0] <= world_width - 1, camera_across_overlay
            # Release back over the Garden: this clause owns capture, not the
            # question of what a release over a HUD control means.
            page.mouse.move(capture_start["x"], capture_start["y"], steps=12)
            page.mouse.up()
            _wait_drag_settled(page)

            # ── Clause: EDGE CLAMP ───────────────────────────────────────────
            # A finger delta far larger than the world can absorb must leave the
            # camera exactly AT the canonical bound, never beyond it, and must
            # not wedge the gesture: a small reverse drag still pans normally.
            go_home()
            row_y = _empty_garden_ground_point(page)["y"]

            def long_left_drag() -> list[int]:
                """Drag the world as far left as the row allows, then settle."""
                start = {"x": _empty_garden_row_x(page, row_y, viewport[0] - 100),
                         "y": row_y}
                end = {"x": _empty_garden_row_x(page, row_y, 140), "y": row_y}
                # Both ends must be empty ground: once the clamp absorbs the
                # whole delta the gesture never crosses the movement threshold,
                # so it releases as an ordinary click on whatever it lands on.
                _mouse_drag(page, start, end)
                return _wait_camera_quiescent(page)

            previous = page.evaluate("window.__gardenReview.camera()")
            edge_camera = None
            for _ in range(30):
                camera = long_left_drag()
                assert 0 <= camera[0] <= world_width - 1, {
                    "camera": camera, "world_width": world_width,
                    "why": "the drag pushed the camera outside the canonical world",
                }
                if camera == previous:
                    edge_camera = camera
                    break
                previous = camera
            assert edge_camera is not None, (
                "thirty long left drags never brought the camera to rest"
            )
            assert edge_camera[0] == world_width - 1, {
                "camera": edge_camera, "world_width": world_width,
                "why": "the drag stopped short of the canonical world edge",
            }
            for _ in range(2):
                assert long_left_drag() == edge_camera, {
                    "expected": edge_camera,
                    "why": "a further oversized drag moved the clamped camera",
                }
            reverse_start = {"x": _empty_garden_row_x(page, row_y, 300), "y": row_y}
            _mouse_drag(page, reverse_start,
                        {"x": reverse_start["x"] + 15 * pitch, "y": row_y})
            reverse_camera = _wait_camera_quiescent(page)
            assert reverse_camera[0] < edge_camera[0], {
                "before": edge_camera, "after": reverse_camera,
                "why": "the camera stayed wedged at the edge after a reverse drag",
            }
            assert reverse_camera[1] == edge_camera[1], (reverse_camera, edge_camera)

            # ── Clause: RELEASE OVER OBJECT NEVER ACTS ───────────────────────
            # The visible Garden follows the pointer one-to-one, so art pressed
            # at pointerdown is still under the pointer at pointerup: this
            # gesture releases on the flower's own ink. A pan must never also
            # perform whatever primary action sits under the finger.
            go_home()
            _keyboard_focus_object(page, plant_id, object_count=object_count)
            _wait_art_rect_quiescent(page, plant_id)
            focused_camera = page.evaluate("window.__gardenReview.camera()")
            art = _exposed_object_art_point(page, plant_id)
            before = _state(page)

            # Drag towards whichever world edge has room, so the clamp cannot
            # break the one-to-one tracking this clause depends on. The measured
            # pitch rounds up, so the room budget is taken conservatively.
            room_right = world_width - 1 - focused_camera[0]
            room_left = focused_camera[0]
            direction = -1 if room_right >= room_left else 1
            travel = min(240.0, max(room_left, room_right) * pitch * 0.8)
            assert travel > 4 * pitch, {
                "camera": focused_camera, "world_width": world_width, "pitch": pitch,
                "why": "no room exists for a drag long enough to commit a pan",
            }
            release = {"x": art["x"] + direction * travel, "y": art["y"]}
            assert 8 < release["x"] < viewport[0] - 8, release
            page.mouse.move(art["x"], art["y"])
            page.mouse.down()
            page.mouse.move(release["x"], release["y"], steps=12)
            page.wait_for_function(
                "before => window.__gardenReview.camera()[0] !== before",
                arg=focused_camera[0],
            )
            # The accessor reports COMPUTED art geometry while the live gesture
            # residue is a CSS transform on the Garden's children, so the visible
            # ink is the reported rectangle displaced by that residue. The pair
            # is read from one settled frame with the pointer already parked at
            # its release position, so what is judged here is exactly what the
            # release will land on.
            visible = _wait_gesture_geometry_quiescent(page, plant_id)
            rect, residue = visible["rect"], visible["residue"]
            inside = (
                rect["x"] + residue[0] <= release["x"] <= rect["x"] + residue[0] + rect["width"]
                and rect["y"] + residue[1] <= release["y"] <= rect["y"] + residue[1] + rect["height"]
            )
            assert inside, {
                "release": release, "measured": visible,
                "why": "the visible Garden did not track the pointer one-to-one, so "
                       "this gesture would not release on the rose's art",
            }
            hit = page.evaluate(
                "p => window.__gardenReview.objectAtPixels(p[0], p[1])",
                [release["x"] - residue[0], release["y"] - residue[1]],
            )
            assert hit == plant_id, {
                "release": release, "measured": visible, "hit": hit,
                "why": "the release point does not identify the rose, so a plain "
                       "click there would not have acted either",
            }
            page.mouse.up()
            _wait_drag_settled(page)

            after = _state(page)
            assert after["plants"] == before["plants"], {
                "before": before["plants"], "after": after["plants"],
                "why": "releasing a pan on the rose's art tended it",
            }
            assert len(after["journal"]) == len(before["journal"]), (
                "releasing a pan on the rose's art wrote a journal entry"
            )
            assert (
                [fixture["interaction_count"] for fixture in after["fixtures"]]
                == [fixture["interaction_count"] for fixture in before["fixtures"]]
            ), "releasing a pan dispatched a fixture interaction"
            assert page.evaluate(
                "window.__gardenReview.state().actions_open_for"
            ) is None
            settled = _wait_camera_quiescent(page)
            assert settled[0] != focused_camera[0], (
                "the suppressed-activation gesture never panned, so it did not "
                "exercise drag-click suppression at all"
            )
            assert 0 < settled[0] < world_width - 1, (
                f"the suppression gesture ran into the world edge clamp: {settled}"
            )

            # Contrast fixture: the SAME art point, reached by the same keyboard
            # route, does act on a plain click. Without this the clause above
            # would also pass on a point that can never be activated.
            _keyboard_focus_object(page, plant_id, object_count=object_count)
            _wait_art_rect_quiescent(page, plant_id)
            assert page.evaluate("window.__gardenReview.camera()") == focused_camera
            control = _exposed_object_art_point(page, plant_id)
            assert control["x"] == pytest.approx(art["x"], abs=0.5)
            assert control["y"] == pytest.approx(art["y"], abs=0.5)
            tended_before = _state(page)["plants"][0]["tended_count"]
            page.mouse.click(control["x"], control["y"])
            page.wait_for_function(
                "before => JSON.parse(window.__gardenReview.canonicalStateJson())"
                ".plants[0].tended_count > before",
                arg=tended_before,
            )
            context.close()
        finally:
            browser.close()

    assert errors == [], errors


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
