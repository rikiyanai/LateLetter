"""One exported artifact traverses the browser author and recipient products.

This is the successor to the deleted mechanics-first Garden browser harness.
It proves product lineage only: author controls create one file, then ordinary
recipient controls open that exact file on desktop and touch-mobile Chromium.
Garden appearance and interaction acceptance remain separate operator gates.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import struct
import threading
from datetime import date
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from lateletter.author_web import create_author_server
from lateletter.bundle import Bundle
from lateletter.sealed import open_message, verify_bundle_hmac
from lateletter.session_store import SessionStore
from lateletter.garden.world.generation import generate_initial_world
from lateletter.garden.world.provenance import composition_acceptance, world_census


playwright_api = pytest.importorskip(
    "playwright.sync_api",
    reason="playwright is not installed in this interpreter",
)

ROOT = Path(__file__).resolve().parents[1]
PASSPHRASE = "1234"
LETTER_LABEL = "The yellow kitchen"
LETTER_BODY = "Dear Mara,\n\nThe yellow kitchen.\n\nLove, Riki"
LETTER_ROWS = LETTER_BODY.split("\n")
STARTER_FIXTURE_CATALOGS = {
    "bench", "mailbox", "stepping_stones", "planter", "lantern", "pond",
}
_PAINT_AUTHORITY = json.loads(
    (ROOT / "web/garden-accepted-paint.v1.json").read_text(encoding="utf-8")
)
ACCEPTED_FULL_GARDEN_PAINT = (
    set(_PAINT_AUTHORITY["accepted_assets"])
    | set(_PAINT_AUTHORITY["accepted_legacy_art"])
    | set(_PAINT_AUTHORITY["review_candidate_assets"])
    | set(_PAINT_AUTHORITY["accepted_recipes"])
)


class _QuietStaticHandler(SimpleHTTPRequestHandler):
    def log_message(self, _format: str, *_args) -> None:
        """The test asserts browser failures directly; suppress HTTP chatter."""


@contextlib.contextmanager
def _product_servers(tmp_path: Path):
    author = create_author_server(
        session_store=SessionStore(base_dir=tmp_path / "author-session"),
        static_root=ROOT,
    )
    static_handler = partial(_QuietStaticHandler, directory=str(ROOT))
    recipient = ThreadingHTTPServer(("127.0.0.1", 0), static_handler)
    author_thread = threading.Thread(target=author.serve_forever, daemon=True)
    recipient_thread = threading.Thread(target=recipient.serve_forever, daemon=True)
    author_thread.start()
    recipient_thread.start()
    try:
        author_host, author_port = author.server_address[:2]
        recipient_host, recipient_port = recipient.server_address[:2]
        yield (
            f"http://{author_host}:{author_port}",
            f"http://{recipient_host}:{recipient_port}",
        )
    finally:
        author.shutdown()
        recipient.shutdown()
        author.server_close()
        recipient.server_close()
        author_thread.join(timeout=5)
        recipient_thread.join(timeout=5)


def _watch_browser(page) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    bad_responses: list[str] = []
    page.on("pageerror", lambda error: errors.append(f"pageerror: {error}"))
    page.on(
        "console",
        lambda message: errors.append(f"console.{message.type}: {message.text}")
        if message.type == "error"
        and "favicon.ico" not in ((message.location or {}).get("url", "") + message.text)
        else None,
    )
    page.on(
        "response",
        lambda response: bad_responses.append(
            f"HTTP {response.status}: {response.url}",
        )
        if response.status >= 400 and "favicon.ico" not in response.url
        else None,
    )
    return errors, bad_responses


def _png_dimensions(path: Path) -> tuple[int, int]:
    payload = path.read_bytes()
    assert payload.startswith(b"\x89PNG\r\n\x1a\n")
    return struct.unpack(">II", payload[16:24])


def _activate_real_pointer(page, locator, *, touch: bool) -> None:
    """Activate a product control by CSS-pixel coordinates, never Locator.click."""
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


def _drag_garden(page, *, touch: bool) -> None:
    """Pan through a real mouse/pointer or native CDP touch sequence."""
    before = page.evaluate("window.__gardenReview.camera()")
    gesture = page.evaluate(
        """() => {
          const garden = document.querySelector('#g');
          const exposed = (x, y) => {
            const element = document.elementFromPoint(x, y);
            return Boolean(
              element && element.closest('#g') === garden
              && !element.closest('button, #garden-journal')
            );
          };
          const deltas = [[-80, 0], [80, 0], [0, -80], [0, 80]];
          for (let y = 50; y < innerHeight - 50; y += 40) {
            for (let x = 50; x < innerWidth - 50; x += 40) {
              for (const [dx, dy] of deltas) {
                if (exposed(x, y) && exposed(x + dx, y + dy))
                  return {start: [x, y], end: [x + dx, y + dy]};
              }
            }
          }
          return null;
        }"""
    )
    assert gesture is not None, "no exposed Garden surface could receive a drag"
    start_x, start_y = gesture["start"]
    end_x, end_y = gesture["end"]
    if touch:
        cdp = page.context.new_cdp_session(page)
        cdp.send("Input.dispatchTouchEvent", {
            "type": "touchStart",
            "touchPoints": [{"x": start_x, "y": start_y}],
        })
        for step in range(1, 5):
            cdp.send("Input.dispatchTouchEvent", {
                "type": "touchMove",
                "touchPoints": [{
                    "x": start_x + (end_x - start_x) * step / 4,
                    "y": start_y + (end_y - start_y) * step / 4,
                }],
            })
        cdp.send("Input.dispatchTouchEvent", {
            "type": "touchEnd", "touchPoints": [],
        })
    else:
        page.mouse.move(start_x, start_y)
        page.mouse.down()
        page.mouse.move(end_x, end_y, steps=5)
        page.mouse.up()
    page.wait_for_function(
        "before => JSON.stringify(window.__gardenReview.camera()) !== JSON.stringify(before)",
        arg=before,
    )


def _keyboard_focus_object(page, object_id: str) -> None:
    """Frame an object through the recipient's real keyboard navigation."""
    object_count = len(page.evaluate("window.__gardenReview.state().objects"))
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


def _canonical_state(page) -> dict[str, object]:
    return json.loads(page.evaluate("window.__gardenReview.canonicalStateJson()"))


def _persisted_state_subset(state: dict[str, object]) -> dict[str, object]:
    program = state["program_state"]
    return {
        "plants": state["plants"],
        "fixtures": state["fixtures"],
        "journal": state["journal"],
        "inventory": state["inventory"],
        # These are canonical UI fields in the current product contract. They
        # persist; only the DOM/modal presentation around them is session-only.
        "ui": state["ui"],
        "program_entities": program.get("entities", {}),
        "applied_occurrences": program.get("applied_occurrences", []),
        "completed_events": program.get("completed_events", []),
    }


def _indexeddb_values(page) -> list[object]:
    return page.evaluate(
        """async () => {
          const database = await new Promise((resolve, reject) => {
            const request = indexedDB.open('LateLetter', 1);
            request.onsuccess = () => resolve(request.result);
            request.onerror = () => reject(request.error);
          });
          const values = await new Promise((resolve, reject) => {
            const transaction = database.transaction('kv', 'readonly');
            const request = transaction.objectStore('kv').getAll();
            request.onsuccess = () => resolve(request.result);
            request.onerror = () => reject(request.error);
          });
          database.close();
          return values;
        }"""
    )


def _upload_unlock_and_return_to_garden(page, artifact: Path, origin: str) -> None:
    if page.url == "about:blank":
        page.goto(f"{origin}/viewer-bnw.html?garden_debug=1", wait_until="networkidle")
    page.locator("#file-input").set_input_files(str(artifact))
    page.locator("#hud.vis").wait_for(state="visible")
    page.get_by_role("button", name="open letters").click()
    page.locator("#s-passphrase.active").wait_for(state="visible")
    page.locator("#pp-input").fill(PASSPHRASE)
    page.locator("#btn-unlock").click()
    page.locator("#s-archive.active").wait_for(state="visible")
    page.locator("#btn-arc-back").click()
    page.locator("#hud.vis").wait_for(state="visible")


def _export_once_through_author(
    page, origin: str, tmp_path: Path, *, scheduled_gift: bool = False,
) -> Path:
    page.goto(f"{origin}/", wait_until="networkidle")
    page.locator("#btn-start-fresh").click()
    page.locator('section[data-stage="people"]').wait_for(state="visible")
    page.locator("#f-author-name").fill("Riki")
    page.locator("#f-recipient-name").fill("Mara")
    page.locator("#f-timezone").select_option("UTC")
    page.locator("#f-hint").fill("the room with the yellow table")
    page.locator("#btn-next").click()
    page.locator('section[data-stage="letters"]').wait_for(state="visible")
    page.locator("#f-letter-date").fill(date.today().isoformat())
    page.locator("#f-letter-label").fill(LETTER_LABEL)
    page.locator("#f-letter-body").fill(LETTER_BODY)
    page.locator("#btn-next").click()
    page.locator('section[data-stage="gifts"]').wait_for(state="visible")
    if scheduled_gift:
        page.locator("#btn-add-gift").click()
        page.locator(".gift-card select").nth(0).select_option("fixture.coffee_mug")
        page.locator('.gift-card input[type="date"]').fill(
            date.today().isoformat()
        )
        page.locator(".gift-card select").nth(1).select_option(index=1)
    page.locator("#btn-next").click()
    page.locator('section[data-stage="review"]').wait_for(state="visible")
    page.locator("#btn-validate").click()
    page.locator("#validate-state").filter(has_text="1 letter ready").wait_for()
    page.locator("#btn-next").click()
    page.locator('section[data-stage="export"]').wait_for(state="visible")
    page.locator("#pp-new").fill(PASSPHRASE)
    page.locator("#pp-confirm").fill(PASSPHRASE)
    with page.expect_download() as download_info:
        page.locator("#btn-export").click()
    download = download_info.value
    artifact = tmp_path / download.suggested_filename
    download.save_as(artifact)
    return artifact


def _open_exact_artifact_as_recipient(
    browser,
    *,
    origin: str,
    artifact: Path,
    expected_sha256: str,
    viewport: tuple[int, int],
    touch: bool,
    expected_fingerprint: str,
    expected_position: tuple[int, int],
    expected_camera: tuple[int, int],
    composition_verdict: str,
    capture_path: Path,
) -> dict[str, object]:
    context = browser.new_context(
        viewport={"width": viewport[0], "height": viewport[1]},
        has_touch=touch,
        is_mobile=touch,
        reduced_motion="reduce",
    )
    page = context.new_page()
    page.set_default_timeout(30_000)
    errors, bad_responses = _watch_browser(page)
    try:
        page.goto(
            f"{origin}/viewer-bnw.html?garden_debug=1",
            wait_until="networkidle",
        )
        stored_records = page.evaluate(
            """async () => {
              const database = await new Promise((resolve, reject) => {
                const request = indexedDB.open('LateLetter', 1);
                request.onsuccess = () => resolve(request.result);
                request.onerror = () => reject(request.error);
              });
              const count = await new Promise((resolve, reject) => {
                const transaction = database.transaction('kv', 'readonly');
                const request = transaction.objectStore('kv').count();
                request.onsuccess = () => resolve(request.result);
                request.onerror = () => reject(request.error);
              });
              database.close();
              return count;
            }"""
        )
        assert stored_records == 0, "recipient context did not start with clean storage"
        assert hashlib.sha256(artifact.read_bytes()).hexdigest() == expected_sha256
        page.locator("#file-input").set_input_files(str(artifact))

        page.locator("#hud.vis").wait_for(state="visible")
        page.locator("#g div").first.wait_for(state="attached")
        assert "planted for you by Riki" in page.locator("#hud-author").inner_text()
        assert page.locator("#g").inner_text().strip()

        page.get_by_role("button", name="open letters").click()
        page.locator("#s-passphrase.active").wait_for(state="visible")
        page.locator("#pp-input").fill(PASSPHRASE)
        page.locator("#btn-unlock").click()
        page.locator("#s-archive.active").wait_for(state="visible")

        # Capture the authenticated fresh composition before reading the due
        # letter can enable story-complete presentation.
        page.locator("#btn-arc-back").click()
        page.locator("#hud.vis").wait_for(state="visible")
        provenance = page.evaluate("window.__gardenReview.provenance()")
        positions = page.evaluate("window.__gardenReview.positions()")
        camera = page.evaluate("window.__gardenReview.camera()")
        assert provenance["load_origin"] == "generated"
        assert provenance["world_origin"]["census"] == {
            "plants": 1, "fixtures": 6, "animals": 0, "collectibles": 0,
        }
        assert provenance["world_origin"]["composition_fingerprint"] == expected_fingerprint
        assert len(positions) == 7
        authenticated_state = json.loads(page.evaluate(
            "window.__gardenReview.canonicalStateJson()"
        ))
        plant_id = authenticated_state["plants"][0]["plant_id"]
        flower_source = f"plant.{authenticated_state['plants'][0]['species_id']}"
        plant_position = next(
            item["position"] for item in positions if item["id"] == plant_id
        )
        assert tuple(plant_position) == expected_position
        assert tuple(camera) == expected_camera
        visible_paint = page.evaluate("window.__gardenReview.visiblePaint()")
        canonical_ids = {item["id"] for item in positions}
        assert set(visible_paint["object_ids"]) <= canonical_ids, visible_paint
        assert set(visible_paint["source_ids"]) <= ACCEPTED_FULL_GARDEN_PAINT, visible_paint
        source_ids = set(visible_paint["source_ids"])
        assert "recipe.ground.cover" not in source_ids, visible_paint
        assert "recipe.vegetation.plant_paint" not in source_ids, visible_paint
        assert not any("ambient" in source or "weather" in source for source in source_ids)
        if viewport[0] >= 1000:
            assert flower_source in source_ids, visible_paint
            assert any(source.startswith("fixture.pond") for source in source_ids)
            assert any(source.startswith("fixture.stepping_stones") for source in source_ids)
        page.screenshot(path=str(capture_path))
        assert _png_dimensions(capture_path) == viewport

        # These are real coordinate-driven pointer routes. The flower is acted on
        # through its ink; no object-name/action label is painted over the
        # Garden. Canonical bytes prove the gesture reached the world.
        initial_state = json.loads(page.evaluate(
            "window.__gardenReview.canonicalStateJson()"
        ))
        plant_id = initial_state["plants"][0]["plant_id"]
        _keyboard_focus_object(page, plant_id)
        page.wait_for_function(
            "source => window.__gardenReview.visiblePaint().source_ids.includes(source)",
            arg=flower_source,
        )
        assert page.locator("#garden-context-actions").count() == 0
        control_capture = capture_path.with_name(
            f"{capture_path.stem}-controls{capture_path.suffix}"
        )
        page.screenshot(path=str(control_capture))
        assert _png_dimensions(control_capture) == viewport
        _activate_garden_object(page, plant_id, touch=touch)
        tended = json.loads(page.evaluate(
            "window.__gardenReview.canonicalStateJson()"
        ))
        assert tended["plants"][0]["tended_count"] == (
            initial_state["plants"][0]["tended_count"] + 1
        )
        assert len(tended["journal"]) == len(initial_state["journal"]) + 1

        assert page.locator(
            '#hud-actions [data-garden-command="open_journal"]'
        ).count() == 0
        assert page.locator(
            '#hud-actions [data-garden-command="pause_motion"]'
        ).count() == 0
        mailbox_id = next(
            fixture["fixture_id"] for fixture in tended["fixtures"]
            if fixture["catalog_id"] == "mailbox"
        )
        _activate_garden_object(page, mailbox_id, touch=touch)
        page.locator("#garden-journal").wait_for(state="visible")
        assert page.locator("#garden-journal-list li").count() >= 1
        _activate_real_pointer(
            page, page.locator("#garden-journal-close"), touch=touch,
        )
        page.locator("#garden-journal").wait_for(state="hidden")

        final_interaction_state = json.loads(page.evaluate(
            "window.__gardenReview.canonicalStateJson()"
        ))
        assert final_interaction_state["ui"]["motion_paused"] is False

        letters_control = page.locator("#hud-btns button").filter(has_text="letters")
        assert letters_control.count() == 1
        assert letters_control.inner_text().strip() == "letters"
        letters_control.click()
        page.locator("#s-archive.active").wait_for(state="visible")

        due = page.locator("#arc-content .inbox-btn.unread")
        assert due.count() == 1
        assert due.inner_text() == LETTER_LABEL
        due.click()
        page.locator("#s-reading.active").wait_for(state="visible")
        page.locator("#letter-body .ll").first.wait_for(state="attached")
        assert page.locator("#s-reading .btn").first.evaluate(
            "button => getComputedStyle(button).webkitTapHighlightColor"
        ) == "rgba(0, 0, 0, 0)"
        assert page.locator("#lm-label").inner_text() == LETTER_LABEL
        painted_rows = page.locator("#letter-body .ll").all_text_contents()
        assert painted_rows == LETTER_ROWS
        assert "\n".join(painted_rows) == LETTER_BODY
        reading_capture = capture_path.with_name(
            f"{capture_path.stem}-reading{capture_path.suffix}"
        )
        page.screenshot(path=str(reading_capture))
        assert _png_dimensions(reading_capture) == viewport

        page.locator("#btn-all").click()
        page.locator("#s-archive.active").wait_for(state="visible")
        assert page.locator("#arc-content .inbox-btn.read").inner_text() == LETTER_LABEL
        page.locator("#btn-arc-back").click()
        page.locator("#hud.vis").wait_for(state="visible")

        return {
            "viewport": viewport,
            "touch": touch,
            "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
            "painted_rows": painted_rows,
            "errors": errors,
            "bad_responses": bad_responses,
            "census": provenance["world_origin"]["census"],
            "composition_fingerprint": expected_fingerprint,
            "composition_verdict": composition_verdict,
            "flower_position": expected_position,
            "capture": capture_path,
            "control_capture": control_capture,
            "reading_capture": reading_capture,
            "pointer_modality": "touch" if touch else "mouse",
            "journal_entries": len(final_interaction_state["journal"]),
            "tended_count": final_interaction_state["plants"][0]["tended_count"],
            "motion_paused": final_interaction_state["ui"]["motion_paused"],
        }
    finally:
        context.close()


def test_one_browser_author_download_reaches_desktop_and_mobile_recipients(tmp_path):
    with _product_servers(tmp_path) as (author_origin, recipient_origin):
        with playwright_api.sync_playwright() as driver:
            try:
                browser = driver.chromium.launch()
            except Exception as failure:  # pragma: no cover - environment dependent
                pytest.skip(f"installed Chromium is unavailable: {failure}")
            try:
                author_context = browser.new_context(
                    accept_downloads=True,
                    viewport={"width": 1280, "height": 900},
                )
                author_page = author_context.new_page()
                author_errors, author_bad_responses = _watch_browser(author_page)
                artifact = _export_once_through_author(
                    author_page, author_origin, tmp_path,
                )
                author_context.close()

                artifact_bytes = artifact.read_bytes()
                artifact_sha256 = hashlib.sha256(artifact_bytes).hexdigest()
                bundle = Bundle.from_dict(json.loads(artifact_bytes))
                assert verify_bundle_hmac(bundle, PASSPHRASE)
                assert open_message(PASSPHRASE, bundle.messages[0])["body"] == LETTER_BODY
                expected_world = generate_initial_world(
                    "handoff-composition-verdict", bundle.garden_seed,
                )
                assert world_census(expected_world) == {
                    "plants": 1, "fixtures": 6,
                    "animals": 0, "collectibles": 0,
                }
                expected_flower = expected_world.plants[0]
                expected_position = (
                    expected_flower.position.x, expected_flower.position.y,
                )
                expected_camera = (
                    expected_world.ui.camera.x, expected_world.ui.camera.y,
                )
                expected_fingerprint = expected_world.composition_fingerprint
                verdict = composition_acceptance(expected_world)

                results = [
                    _open_exact_artifact_as_recipient(
                        browser,
                        origin=recipient_origin,
                        artifact=artifact,
                        expected_sha256=artifact_sha256,
                        viewport=(1400, 950),
                        touch=False,
                        expected_fingerprint=expected_fingerprint,
                        expected_position=expected_position,
                        expected_camera=expected_camera,
                        composition_verdict=verdict,
                        capture_path=tmp_path / "handoff-desktop-1400x950.png",
                    ),
                    _open_exact_artifact_as_recipient(
                        browser,
                        origin=recipient_origin,
                        artifact=artifact,
                        expected_sha256=artifact_sha256,
                        viewport=(390, 844),
                        touch=True,
                        expected_fingerprint=expected_fingerprint,
                        expected_position=expected_position,
                        expected_camera=expected_camera,
                        composition_verdict=verdict,
                        capture_path=tmp_path / "handoff-mobile-390x844.png",
                    ),
                    _open_exact_artifact_as_recipient(
                        browser,
                        origin=recipient_origin,
                        artifact=artifact,
                        expected_sha256=artifact_sha256,
                        viewport=(320, 568),
                        touch=True,
                        expected_fingerprint=expected_fingerprint,
                        expected_position=expected_position,
                        expected_camera=expected_camera,
                        composition_verdict=verdict,
                        capture_path=tmp_path / "handoff-phone-320x568.png",
                    ),
                ]
            finally:
                browser.close()

    assert author_errors == []
    assert author_bad_responses == []
    assert {result["sha256"] for result in results} == {artifact_sha256}
    assert {result["viewport"] for result in results} == {
        (1400, 950), (390, 844), (320, 568),
    }
    assert {result["census"]["fixtures"] for result in results} == {6}
    assert {result["composition_fingerprint"] for result in results} == {
        expected_fingerprint,
    }
    assert {result["composition_verdict"] for result in results} == {"not_reviewed"}
    assert {result["flower_position"] for result in results} == {expected_position}
    assert all(result["capture"].is_file() for result in results)
    assert all(result["control_capture"].is_file() for result in results)
    assert all(result["reading_capture"].is_file() for result in results)
    assert all(result["painted_rows"] == LETTER_ROWS for result in results)
    assert all(result["errors"] == [] for result in results)
    assert all(result["bad_responses"] == [] for result in results)
    assert {result["pointer_modality"] for result in results} == {"mouse", "touch"}
    assert all(result["journal_entries"] >= 1 for result in results)
    assert all(result["tended_count"] == 1 for result in results)
    assert all(result["motion_paused"] is False for result in results)


def test_canonical_garden_state_survives_reload_reupload_and_reauthentication(tmp_path):
    """One ordinary sealed product path persists interaction and scheduled gift state."""
    with _product_servers(tmp_path) as (author_origin, recipient_origin):
        with playwright_api.sync_playwright() as driver:
            try:
                browser = driver.chromium.launch()
            except Exception as failure:  # pragma: no cover - environment dependent
                pytest.skip(f"installed Chromium is unavailable: {failure}")
            context = browser.new_context(
                accept_downloads=True,
                viewport={"width": 1280, "height": 900},
            )
            author_page = context.new_page()
            author_errors, author_bad_responses = _watch_browser(author_page)
            artifact = _export_once_through_author(
                author_page, author_origin, tmp_path, scheduled_gift=True,
            )
            author_page.close()

            page = context.new_page()
            page.set_default_timeout(30_000)
            # The author UI fixes scheduled deliveries at 09:00 local time.
            # Open at that exact boundary so the first authenticated interval
            # crosses the browser-authored occurrence deterministically.
            page.add_init_script(
                f"Date.now = () => Date.parse('{date.today().isoformat()}T09:00:00Z');"
            )
            recipient_errors, recipient_bad_responses = _watch_browser(page)
            try:
                _upload_unlock_and_return_to_garden(page, artifact, recipient_origin)
                state = _canonical_state(page)
                assert len(state["plants"]) == 1
                assert {
                    fixture["catalog_id"] for fixture in state["fixtures"]
                } == STARTER_FIXTURE_CATALOGS | {"coffee_mug"}, state["program_state"]
                assert state["program_state"]["applied_occurrences"], (
                    "the browser-authored overdue scheduled gift did not trigger"
                )

                plant_id = state["plants"][0]["plant_id"]
                _keyboard_focus_object(page, plant_id)
                assert page.locator("#garden-context-actions").count() == 0
                _activate_garden_object(page, plant_id, touch=False)
                page.wait_for_function(
                    "() => JSON.parse(window.__gardenReview.canonicalStateJson()).plants[0].tended_count === 1"
                )
                page.wait_for_function(
                    "() => JSON.parse(window.__gardenReview.canonicalStateJson()).journal.length > 0"
                )

                camera_before = page.evaluate("window.__gardenReview.camera()")
                page.mouse.move(220, 720)
                page.mouse.down()
                page.mouse.move(120, 720, steps=5)
                page.mouse.up()
                page.wait_for_function(
                    "before => JSON.stringify(window.__gardenReview.camera()) !== JSON.stringify(before)",
                    arg=camera_before,
                )

                assert page.locator(
                    '#hud-actions [data-garden-command="pause_motion"]'
                ).count() == 0
                assert page.locator(
                    '#hud-actions [data-garden-command="open_journal"]'
                ).count() == 0
                mailbox_id = next(
                    fixture["fixture_id"] for fixture in _canonical_state(page)["fixtures"]
                    if fixture["catalog_id"] == "mailbox"
                )
                _activate_garden_object(page, mailbox_id, touch=False)
                page.locator("#garden-journal").wait_for(state="visible")

                before_reload_json = page.evaluate(
                    "window.__gardenReview.canonicalStateJson()"
                )
                before_reload = json.loads(before_reload_json)
                assert before_reload["ui"]["journal_open"] is True
                assert before_reload["ui"]["motion_paused"] is False
                assert before_reload["ui"]["camera"] != camera_before
                assert before_reload_json in _indexeddb_values(page), (
                    "the canonical state was not the exact value persisted to IndexedDB"
                )

                page.reload(wait_until="networkidle")
                # Screen/modal presentation is session state: it resets before
                # an artifact is uploaded. Canonical camera, journal-open and
                # legacy pause field remain in IndexedDB. Object-action labels have no
                # product DOM owner at all.
                assert page.locator("#s-welcome.active").is_visible()
                assert page.locator("#garden-journal").is_hidden()
                assert page.locator("#garden-context-actions").count() == 0
                assert before_reload_json in _indexeddb_values(page)

                _upload_unlock_and_return_to_garden(page, artifact, recipient_origin)
                restored = _canonical_state(page)
                assert page.evaluate(
                    "window.__gardenReview.provenance().load_origin"
                ) == "loaded"
                assert _persisted_state_subset(restored) == _persisted_state_subset(
                    before_reload
                )
                assert page.locator("#garden-journal").is_visible(), (
                    "canonical journal_open did not restore its ordinary HUD surface"
                )
                assert page.locator(
                    '#hud-actions [data-garden-command="pause_motion"]'
                ).count() == 0
            finally:
                context.close()
                browser.close()

    assert author_errors == []
    assert author_bad_responses == []
    assert recipient_errors == []
    assert recipient_bad_responses == []


def test_browser_append_keeps_the_old_receipt_and_old_ciphertext(tmp_path):
    with _product_servers(tmp_path) as (author_origin, recipient_origin):
        with playwright_api.sync_playwright() as driver:
            try:
                browser = driver.chromium.launch()
            except Exception as failure:  # pragma: no cover
                pytest.skip(f"installed Chromium is unavailable: {failure}")
            context = browser.new_context(
                accept_downloads=True, viewport={"width": 1280, "height": 900},
            )
            author = context.new_page()
            author_errors, author_bad_responses = _watch_browser(author)
            original_path = _export_once_through_author(author, author_origin, tmp_path)
            original = Bundle.from_dict(json.loads(original_path.read_bytes()))

            recipient = context.new_page()
            recipient_errors, recipient_bad_responses = _watch_browser(recipient)
            recipient.goto(
                f"{recipient_origin}/viewer-bnw.html?garden_debug=1",
                wait_until="networkidle",
            )
            recipient.locator("#file-input").set_input_files(str(original_path))
            recipient.get_by_role("button", name="open letters").click()
            recipient.locator("#pp-input").fill(PASSPHRASE)
            recipient.locator("#btn-unlock").click()
            recipient.locator("#s-archive.active").wait_for(state="visible")
            recipient.locator("#arc-content .inbox-btn.unread").click()
            recipient.locator("#s-reading.active").wait_for(state="visible")
            recipient.locator("#btn-all").click()
            recipient.locator("#arc-content .inbox-btn.read").wait_for(state="visible")

            author.goto(author_origin, wait_until="networkidle")
            author.locator("#append-file").set_input_files(str(original_path))
            author.locator("#append-date").fill(date.today().isoformat())
            author.locator("#append-label").fill("Still beside you")
            author.locator("#append-body").fill("Dear Mara,\n\nStill beside you.\n\nLove, Riki")
            author.locator("#append-passphrase").fill(PASSPHRASE)
            with author.expect_download() as download_info:
                author.locator("#btn-append").click()
            appended_path = tmp_path / "appended.lateletter"
            download_info.value.save_as(appended_path)
            appended = Bundle.from_dict(json.loads(appended_path.read_bytes()))
            assert appended.bundle_id == original.bundle_id
            assert appended.bundle_auth_salt == original.bundle_auth_salt
            assert appended.messages[0].to_dict() == original.messages[0].to_dict()
            assert len(appended.messages) == 2

            recipient.reload(wait_until="networkidle")
            recipient.locator("#file-input").set_input_files(str(appended_path))
            recipient.get_by_role("button", name="open letters").click()
            recipient.locator("#pp-input").fill(PASSPHRASE)
            recipient.locator("#btn-unlock").click()
            recipient.locator("#s-archive.active").wait_for(state="visible")
            assert recipient.locator("#arc-content .inbox-btn.read").count() == 1
            assert recipient.locator("#arc-content .inbox-btn.read").inner_text() == LETTER_LABEL
            assert recipient.locator("#arc-content .inbox-btn.unread").count() == 1
            assert recipient.locator("#arc-content .inbox-btn.unread").inner_text() == "Still beside you"
            context.close()
            browser.close()

    assert author_errors == []
    assert author_bad_responses == []
    assert recipient_errors == []
    assert recipient_bad_responses == []


def test_tracked_sealed_demo_button_unlocks_with_the_documented_passphrase(tmp_path):
    documented_passphrase = "garden-biscuit-2026"
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert (
        "https://rikiworld.com/lateletter/to-a-friend/ "
        f"(passcode `{documented_passphrase}`)"
    ) in readme

    with _product_servers(tmp_path) as (_author_origin, recipient_origin):
        with playwright_api.sync_playwright() as driver:
            try:
                browser = driver.chromium.launch()
            except Exception as failure:  # pragma: no cover
                pytest.skip(f"installed Chromium is unavailable: {failure}")
            context = browser.new_context(
                accept_downloads=True, viewport={"width": 1280, "height": 900},
            )
            page = context.new_page()
            page.set_default_timeout(30_000)
            errors, bad_responses = _watch_browser(page)
            try:
                page.goto(
                    f"{recipient_origin}/viewer-bnw.html?garden_debug=1",
                    wait_until="networkidle",
                )
                _activate_real_pointer(
                    page, page.locator("#btn-demo-sealed"), touch=False,
                )
                page.locator("#hud.vis").wait_for(state="visible")
                _activate_real_pointer(
                    page, page.get_by_role("button", name="open letters"),
                    touch=False,
                )
                page.locator("#s-passphrase.active").wait_for(state="visible")
                page.locator("#pp-input").fill(documented_passphrase)
                _activate_real_pointer(
                    page, page.locator("#btn-unlock"), touch=False,
                )
                page.locator("#s-archive.active").wait_for(state="visible")
                assert page.locator("#arc-content .inbox-btn.unread").count() == 1
                state = _canonical_state(page)
                assert {
                    "demo-rabbit", "demo-rose", "autumn-keepsake",
                } <= set(state["program_state"]["entities"])
                assert page.evaluate(
                    "window.__gardenReview.provenance().load_origin"
                ) == "generated"
            finally:
                context.close()
                browser.close()

    assert errors == []
    assert bad_responses == []


def test_final_one_artifact_traverses_author_desktop_phone_gift_and_reopen(tmp_path):
    with _product_servers(tmp_path) as (author_origin, recipient_origin):
        with playwright_api.sync_playwright() as driver:
            try:
                browser = driver.chromium.launch()
            except Exception as failure:  # pragma: no cover
                pytest.skip(f"installed Chromium is unavailable: {failure}")
            author_context = browser.new_context(
                accept_downloads=True, viewport={"width": 1400, "height": 950},
            )
            author_page = author_context.new_page()
            author_errors, author_bad_responses = _watch_browser(author_page)
            artifact = _export_once_through_author(
                author_page, author_origin, tmp_path, scheduled_gift=True,
            )
            artifact_sha = hashlib.sha256(artifact.read_bytes()).hexdigest()
            author_context.close()

            results = []
            for viewport, touch in (((1400, 950), False), ((390, 844), True)):
                context = browser.new_context(
                    viewport={"width": viewport[0], "height": viewport[1]},
                    has_touch=touch, is_mobile=touch,
                    reduced_motion="reduce" if touch else "no-preference",
                )
                page = context.new_page()
                page.set_default_timeout(30_000)
                before_gift = f"{date.today().isoformat()}T08:59:58Z"
                after_gift = f"{date.today().isoformat()}T09:00:02Z"
                page.add_init_script(
                    f"globalThis.__lateletterReviewNow=Date.parse('{before_gift}');"
                    "Date.now=()=>globalThis.__lateletterReviewNow;"
                )
                errors, bad_responses = _watch_browser(page)
                journey = ["author", "export"]

                page.goto(
                    f"{recipient_origin}/viewer-bnw.html?garden_debug=1",
                    wait_until="networkidle",
                )
                page.locator("#file-input").set_input_files(str(artifact))
                page.locator("#hud.vis").wait_for(state="visible")
                journey.append("Garden")
                page.get_by_role("button", name="open letters").click()
                page.locator("#pp-input").fill(PASSPHRASE)
                page.locator("#btn-unlock").click()
                page.locator("#s-archive.active").wait_for(state="visible")
                journey.extend(["unlock", "archive"])

                state = _canonical_state(page)
                assert hashlib.sha256(artifact.read_bytes()).hexdigest() == artifact_sha
                assert {
                    fixture["catalog_id"] for fixture in state["fixtures"]
                } == STARTER_FIXTURE_CATALOGS
                assert state["program_state"]["applied_occurrences"] == []
                unread = page.locator("#arc-content .inbox-btn.unread")
                assert unread.count() == 1 and unread.inner_text() == LETTER_LABEL
                journey.append("unread label")
                unread.click()
                page.locator("#s-reading.active").wait_for(state="visible")
                assert page.locator("#lm-label").inner_text() == LETTER_LABEL
                assert "\n".join(
                    page.locator("#letter-body .ll").all_text_contents()
                ) == LETTER_BODY
                journey.append("reading")
                page.locator("#btn-all").click()
                page.locator("#btn-arc-back").click()
                page.locator("#hud.vis").wait_for(state="visible")

                plant_id = state["plants"][0]["plant_id"]
                _keyboard_focus_object(page, plant_id)
                assert page.locator("#garden-context-actions").count() == 0
                _activate_garden_object(page, plant_id, touch=touch)
                page.wait_for_function(
                    "() => JSON.parse(window.__gardenReview.canonicalStateJson()).plants[0].tended_count === 1"
                )
                page.wait_for_function(
                    "() => JSON.parse(window.__gardenReview.canonicalStateJson()).journal.length > 0"
                )
                _drag_garden(page, touch=touch)
                journey.append("interactions")
                assert len(_canonical_state(page)["fixtures"]) == 6

                page.evaluate(
                    "timestamp => { globalThis.__lateletterReviewNow=Date.parse(timestamp); }",
                    after_gift,
                )
                assert page.locator(
                    '#hud-actions [data-garden-command="pause_motion"]'
                ).count() == 0
                assert page.locator(
                    '#hud-actions [data-garden-command="open_journal"]'
                ).count() == 0

                # With no autonomous product loop, reopening is the explicit
                # observation boundary that reconciles wall time and evaluates
                # the newly due authored occurrence.
                page.reload(wait_until="networkidle")
                page.evaluate(
                    "timestamp => { globalThis.__lateletterReviewNow=Date.parse(timestamp); }",
                    after_gift,
                )
                page.locator("#file-input").set_input_files(str(artifact))
                page.locator("#hud.vis").wait_for(state="visible")
                page.get_by_role("button", name="open letters").click()
                page.locator("#pp-input").fill(PASSPHRASE)
                page.locator("#btn-unlock").click()
                page.locator("#s-archive.active").wait_for(state="visible")
                assert page.locator(
                    "#arc-content .inbox-btn.read"
                ).inner_text() == LETTER_LABEL
                page.locator("#btn-arc-back").click()
                page.locator("#hud.vis").wait_for(state="visible")
                journey.append("reopen")

                page.wait_for_function(
                    "() => JSON.parse(window.__gardenReview.canonicalStateJson()).fixtures.length === 7"
                )
                crossed = _canonical_state(page)
                expected_observed = int(
                    page.evaluate("timestamp => Date.parse(timestamp) / 1000", after_gift)
                )
                assert crossed["last_observed_wall_time"] >= expected_observed, {
                    "expected": expected_observed,
                    "observed": crossed["last_observed_wall_time"],
                    "motion_paused": crossed["ui"]["motion_paused"],
                }
                gifted = _canonical_state(page)
                assert {
                    fixture["catalog_id"] for fixture in gifted["fixtures"]
                } == STARTER_FIXTURE_CATALOGS | {"coffee_mug"}
                assert gifted["program_state"]["applied_occurrences"]
                journey.append("gift")

                mailbox_id = next(
                    fixture["fixture_id"] for fixture in gifted["fixtures"]
                    if fixture["catalog_id"] == "mailbox"
                )
                # The earlier real drag is intentionally persistent, so the
                # mailbox may be outside the restored viewport. Frame it via
                # the product keyboard route before proving direct pointer or
                # touch activation on its actual painted art.
                _keyboard_focus_object(page, mailbox_id)
                _activate_garden_object(page, mailbox_id, touch=touch)
                page.locator("#garden-journal").wait_for(state="visible")
                before = _canonical_state(page)
                assert json.dumps(before, separators=(",", ":"), ensure_ascii=False) in (
                    value for value in _indexeddb_values(page) if isinstance(value, str)
                )
                journey.append("persistence")
                assert page.evaluate(
                    "window.__gardenReview.provenance().load_origin"
                ) == "loaded"

                results.append({
                    "viewport": viewport, "touch": touch,
                    "gift_count": len(before["fixtures"]),
                    "tended": before["plants"][0]["tended_count"],
                    "paused": before["ui"]["motion_paused"],
                    "journey": journey,
                    "errors": errors, "bad_responses": bad_responses,
                })
                context.close()
            browser.close()

    assert author_errors == []
    assert author_bad_responses == []
    assert {result["viewport"] for result in results} == {(1400, 950), (390, 844)}
    assert {result["touch"] for result in results} == {False, True}
    assert all(result["journey"] == [
        "author", "export", "Garden", "unlock", "archive", "unread label",
        "reading", "interactions", "reopen", "gift", "persistence",
    ] for result in results)
    assert all(result["gift_count"] == 7 for result in results)
    assert all(result["tended"] == 1 and not result["paused"] for result in results)
    assert all(result["errors"] == [] for result in results)
    assert all(result["bad_responses"] == [] for result in results)
