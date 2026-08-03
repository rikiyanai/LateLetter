"""The review invariant, executed end to end in a real browser.

Why this file exists
--------------------
Every previous attempt at this proved a mechanism and reported a product path.
A guard was written, a unit test exercised the guard, and the report said the
review surface enforced it -- while the surface itself had never been opened.

So nothing here imports the guard, the runtime, or any module.  It starts a
server, drives Google Chrome at ``viewer-bnw.html``, seeds the browser's own
IndexedDB with a world a review must not see, and then asks the page what it is
showing.  If the invariant is broken, this fails; if the invariant holds only in
Node, this fails too.

The invariant
-------------
    A visual-review entry point must prove it generated the exact current
    starter composition in this process, before persistence or projection, and
    must refuse everything else.

What this file does NOT claim
-----------------------------
It is not visual acceptance.  It cannot be.  It checks the things a machine can
check -- provenance, absence of the rejected action chrome, no console errors,
the picture being painted at all -- and every question of whether the Garden
looks right, feels alive, or is dense enough remains an operator judgement made
by watching the real moving product.  A run of this file with no failures is a
precondition for that review, never a substitute for it.
"""

from __future__ import annotations

import contextlib
import hashlib
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
sys.path.insert(0, str(ROOT / "src"))

DESKTOP = (1600, 1000)
MOBILE = (390, 844)

# The standalone Garden's world identity and the key its runtime stores under,
# both duplicated from the product on purpose: if either changes, the seeding
# below silently stops seeding anything, and a test that seeds nothing would
# quietly stop testing the thing it exists for.
STANDALONE_WORLD_ID = "standalone:local"
STORAGE_KEY = f"lateletter_garden_world_v1_{STANDALONE_WORLD_ID}"

# The review surface is gated on localhost AND an explicit review time. The
# viewer accepts only a strict ISO-8601 instant here and treats anything else as
# "no review time", which silently means "the product path" -- so this literal is
# asserted to actually engage review mode by the first test below, rather than
# trusted. A malformed value here would turn every review assertion into an
# assertion about the product.
REVIEW_QUERY = "garden_debug=1&garden_review_time=2026-06-01T12:00:00Z"
PRODUCT_QUERY = "garden_debug=1"


def _free_port() -> int:
    """Ask the OS for a port nobody is using, and let go of it immediately."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@contextlib.contextmanager
def _static_server():
    """Serve the repository over HTTP for the duration of one test.

    The viewer is an ES module and fetches sibling files, so ``file://`` will
    not do -- the browser refuses cross-origin module imports from it.
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


def _restored_world_document() -> str:
    """A stored world in the condition the browser one was actually found in.

    Current shape, and no content stamps at all -- which is what a world written
    before version stamping looks like, and what the reviewed 13/22/4/8 world
    was.  Built through the real generator so the document is valid rather than
    hand-approximated, then stripped of exactly the fields that make a world
    able to say where it came from.
    """
    from lateletter.garden.world.generation import generate_initial_world

    document = generate_initial_world(STANDALONE_WORLD_ID, "restored-seed").to_dict()
    document["generator_version"] = None
    document["composition_version"] = None
    document["composition_fingerprint"] = None
    # A marker no generated world would ever produce, so the assertions below can
    # tell "the seeded world is on screen" from "a fresh world happens to look
    # similar".
    document["seed"] = "SEEDED-BY-THE-REVIEW-E2E-TEST"
    return json.dumps(document)


@contextlib.contextmanager
def _chrome(origin: str, viewport=DESKTOP, seed_world: str | None = None):
    """Open Chrome at the viewer with an optionally pre-seeded world store.

    The world is written into the page's own IndexedDB, through the same
    database and object store the viewer uses, BEFORE the viewer's scripts run.
    That is what makes this the product path: nothing is injected into the
    runtime and no module is stubbed; storage simply already contains something.

    :param origin: base URL of the static server
    :param viewport: (width, height) in CSS pixels
    :param seed_world: a serialized world document to place in storage first
    :yields: (page, errors) -- errors accumulates console and page errors
    """
    errors: list[str] = []
    with playwright_api.sync_playwright() as driver:
        try:
            browser = driver.chromium.launch(channel="chrome")
        except Exception as failure:  # pragma: no cover - environment dependent
            pytest.skip(f"system Google Chrome is unavailable: {failure}")
        context = browser.new_context(
            viewport={"width": viewport[0], "height": viewport[1]},
            # Phone-sized viewports get a real touchscreen, so `touchscreen.
            # tap` and dispatched pointerType='touch' gestures exercise the
            # same input surface a phone presents.
            has_touch=viewport[0] <= 500,
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
            if seed_world is not None:
                # A blank same-origin document first, so IndexedDB is reachable
                # without the viewer having started.
                page.goto(f"{origin}/", wait_until="domcontentloaded")
                page.evaluate(
                    """async ({key, value}) => {
                        const db = await new Promise((resolve, reject) => {
                          const request = indexedDB.open('LateLetter', 1);
                          request.onupgradeneeded = event => {
                            const database = event.target.result;
                            if (!database.objectStoreNames.contains('kv')) {
                              database.createObjectStore('kv');
                            }
                          };
                          request.onsuccess = event => resolve(event.target.result);
                          request.onerror = event => reject(event.target.error);
                        });
                        await new Promise((resolve, reject) => {
                          const tx = db.transaction('kv', 'readwrite');
                          tx.objectStore('kv').put(value, key);
                          tx.oncomplete = resolve;
                          tx.onerror = event => reject(event.target.error);
                        });
                    }""",
                    {"key": STORAGE_KEY, "value": seed_world},
                )
            yield page, errors
        finally:
            context.close()
            browser.close()


def _enter_standalone_garden(page, origin: str, query: str) -> None:
    """Click the real visible standalone button and wait for the picture.

    `#btn-standalone` and not `#btn-demo`, deliberately. The demo button opens
    the non-persistent recipient PREVIEW world, whose loader always returns
    null, so it generates whatever is in storage and could never have shown a
    restored world in the first place -- a review passing through it would prove
    nothing about the defect. `#btn-standalone` opens `standalone:local`, the
    world that actually persists, which is where the 13/22/4/8 world lived.

    The two tests below then differ only by the review query on the URL, so what
    is being compared is the review policy itself and not two different paths.
    """
    page.goto(f"{origin}/viewer-bnw.html?{query}", wait_until="networkidle")
    page.locator("#btn-standalone").click()
    page.locator("#hud.vis").wait_for(state="visible")
    page.locator("#g .garden-lattice-row").first.wait_for(state="attached")


def _painted_glyph_count(page) -> int:
    """How much ink is actually on the screen."""
    return page.locator("#g .garden-lattice-row").evaluate_all(
        "rows => rows.reduce((total, row) => total + row.textContent.trim().length, 0)"
    )


def _stored_world(page) -> str | None:
    """Read the world document currently in the page's own storage."""
    return page.evaluate(
        """async key => {
            const db = await new Promise((resolve, reject) => {
              const request = indexedDB.open('LateLetter', 1);
              request.onupgradeneeded = event => {
                const database = event.target.result;
                if (!database.objectStoreNames.contains('kv')) {
                  database.createObjectStore('kv');
                }
              };
              request.onsuccess = event => resolve(event.target.result);
              request.onerror = event => reject(event.target.error);
            });
            return await new Promise((resolve, reject) => {
              const tx = db.transaction('kv', 'readonly');
              const read = tx.objectStore('kv').get(key);
              read.onsuccess = event => resolve(event.target.result ?? null);
              read.onerror = event => reject(event.target.error);
            });
        }""",
        STORAGE_KEY,
    )


# ---------------------------------------------------------------------------
# The invariant.
# ---------------------------------------------------------------------------


def test_the_review_surface_REFUSES_a_stored_world_and_paints_nothing():
    """Seed storage with a restored world; the review must refuse it outright.

    The strong form, and the reason this file was rewritten once. An earlier
    version asserted only that the review SHOWED a fresh picture, which held
    even with the guard deleted -- review mode had been handed an empty loader,
    so it always generated and the guard never ran. "Never looked" is not
    "proved fresh"; it is the same answer reached by not asking.

    A review now reads exactly what a recipient's browser holds and refuses it,
    so deleting the guard makes this fail. Nothing is projected, nothing is
    painted, and because a review is never given a writer, nothing is lost.
    """
    with _static_server() as origin:
        with _chrome(origin, seed_world=_restored_world_document()) as (page, errors):
            page.goto(f"{origin}/viewer-bnw.html?{REVIEW_QUERY}", wait_until="networkidle")
            page.locator("#btn-standalone").click()

            # The refusal is visible to a person, not only to a log.
            page.locator("#s-error").wait_for(state="visible", timeout=5000)
            detail = page.locator("#err-d").inner_text()
            assert "not a fresh composition" in detail, detail
            assert "predates version stamping" in detail, detail

            # Nothing was painted, and the stored world is untouched.
            assert _painted_glyph_count(page) == 0, "the refused world was painted anyway"
            assert _stored_world(page) == _restored_world_document(), (
                "the review surface overwrote the stored world"
            )
        # A refusal is an expected outcome, so it must not arrive as an
        # unhandled rejection or a console error.
        assert errors == [], f"the refusal was reported as a page error: {errors}"


def test_a_severed_paint_manifest_refuses_the_garden_and_keeps_the_letter():
    """Reopened step 1 (2026-08-04 review): absent authority refuses, never widens.

    The earlier flow started the renderer with a null authority and installed
    the manifest when the fetch landed, which meant a slow fetch briefly
    painted everything and a failed fetch painted everything permanently --
    and this suite never noticed, because its static server always served the
    file. Here the manifest request is severed at the network layer, the
    exact shape a broken deploy or CDN would produce. The garden must REFUSE:
    the region carries the refusal marker, no lattice row ever exists, and
    the letter surface still boots.
    """
    with _static_server() as origin:
        with _chrome(origin) as (page, errors):
            page.route(
                "**/garden-accepted-paint.v1.json", lambda route: route.abort()
            )
            page.goto(f"{origin}/viewer-bnw.html?{REVIEW_QUERY}", wait_until="networkidle")

            # The refusal is stamped on the garden region itself.
            page.locator(
                "#g[data-paint-refusal='authority-unavailable']"
            ).wait_for(state="attached", timeout=5000)

            # The garden was never constructed: no lattice, no ink, and no
            # review accessor -- there is nothing to review.
            assert page.locator("#g .garden-lattice-row").count() == 0, (
                "a garden painted without any paint authority"
            )
            assert _painted_glyph_count(page) == 0

            # The letter is WIRED, not merely painted: the demo letter opens
            # through the real fetch/decode/screen path and reaches its HUD.
            # (The first version of this test only looked at a pre-existing
            # button, which proves markup and nothing about wiring -- claim
            # verification, 2026-08-04.)
            page.locator("#btn-demo").click()
            page.locator("#hud.vis").wait_for(state="visible", timeout=10000)
        # The refusal is deliberate and logged as such; the aborted fetch and
        # the garden's refusal notice are the EXPECTED console traffic, and
        # anything beyond them is a defect.
        unexpected = [
            line
            for line in errors
            if "garden-accepted-paint" not in line
            and "garden painting refused" not in line
            and "[init] garden failed" not in line
            # Chrome reports the severed request itself without its URL in
            # the message text; the only aborted request in this test is the
            # manifest, so this line IS the severing being observed.
            and "Failed to load resource: net::ERR_FAILED" not in line
        ]
        assert unexpected == [], f"the refusal leaked unrelated errors: {unexpected}"


def test_a_stalled_paint_manifest_cannot_hold_the_letter_hostage():
    """A request that never resolves refuses within the bound; the letter runs.

    ADDED 2026-08-04 (claim verification, finding 1): the awaited fetch sits
    AHEAD of the letter wiring in init, so before the bound existed a hung
    manifest request -- a stalled CDN, a captive portal -- would hang the
    entire application, not just the garden. Fast failure was proved; the
    hang was not. Here the manifest request is answered with silence: the
    route neither fulfils nor aborts, the exact shape of a stalled server.
    The garden must refuse within its declared bound and the demo letter
    must then open through the real wiring.
    """
    with _static_server() as origin:
        with _chrome(origin) as (page, errors):
            # Holding the route without fulfilling or aborting leaves the
            # request pending forever, which is the point.
            page.route("**/garden-accepted-paint.v1.json", lambda route: None)
            page.goto(f"{origin}/viewer-bnw.html?{REVIEW_QUERY}", wait_until="domcontentloaded")

            # The refusal must arrive on the viewer's own clock (a 5s bound;
            # the wait here is deliberately longer so a hang fails HERE, not
            # flakily).
            page.locator(
                "#g[data-paint-refusal='authority-unavailable']"
            ).wait_for(state="attached", timeout=15000)
            assert page.locator("#g .garden-lattice-row").count() == 0
            assert _painted_glyph_count(page) == 0

            # And the letter is not hostage: the demo letter opens fully.
            page.locator("#btn-demo").click()
            page.locator("#hud.vis").wait_for(state="visible", timeout=10000)
        unexpected = [
            line
            for line in errors
            if "garden-accepted-paint" not in line
            and "garden painting refused" not in line
            and "[init] garden failed" not in line
        ]
        assert unexpected == [], f"the stall leaked unrelated errors: {unexpected}"


def test_the_review_surface_generates_and_paints_when_storage_is_empty():
    """The positive control: a review that can never run is not a review."""
    with _static_server() as origin:
        with _chrome(origin) as (page, errors):
            _enter_standalone_garden(page, origin, REVIEW_QUERY)

            provenance = page.evaluate("() => window.__gardenReview.provenance()")
            assert provenance is not None, "the review accessor was not installed"
            assert provenance["load_origin"] == "generated", provenance["load_origin"]
            assert provenance["world_origin"]["is_fresh"] is True, (
                provenance["world_origin"]["reasons"]
            )
            assert _painted_glyph_count(page) > 0, "the review painted nothing"
            # A review is given no writer, so it cannot leave a world behind for
            # the next session to inherit.
            assert _stored_world(page) is None, "the review persisted its world"
        assert errors == [], f"the review surface logged errors: {errors}"


def test_the_review_surface_shows_the_exact_current_starter_composition():
    """Not merely fresh: the declared starter, measured from the running page.

    A world can be freshly generated and still be a custom roster nobody
    declared. The census here is read out of the browser, not out of a Python
    constant, so it is the composition a reviewer would actually be looking at.
    """
    from lateletter.garden.world.generation import generate_initial_world
    from lateletter.garden.world.provenance import world_census

    expected = world_census(generate_initial_world("probe", "probe"))

    with _static_server() as origin:
        with _chrome(origin) as (page, errors):
            _enter_standalone_garden(page, origin, REVIEW_QUERY)
            origin_report = page.evaluate(
                "() => window.__gardenReview.provenance().world_origin"
            )
            assert origin_report["census"] == expected, (
                f"the review is showing {origin_report['census']}, "
                f"not the declared starter {expected}"
            )
            assert origin_report["composition_version"] is not None, (
                "the reviewed world belongs to no named composition revision"
            )
        assert errors == [], errors


def test_the_product_path_keeps_a_recipients_restored_garden():
    """The other direction, and it matters as much.

    A guard that refused everywhere would delete a recipient's garden. The
    product opens what is stored, and says plainly that it is restored rather
    than pretending it is current.
    """
    with _static_server() as origin:
        with _chrome(origin, seed_world=_restored_world_document()) as (page, errors):
            _enter_standalone_garden(page, origin, PRODUCT_QUERY)

            provenance = page.evaluate("() => window.__gardenReview.provenance()")
            assert provenance["load_origin"] == "loaded", (
                "the product regenerated over a stored world"
            )
            assert provenance["world_origin"]["is_fresh"] is False
            assert provenance["world_origin"]["label"] == "restored"
            assert _painted_glyph_count(page) > 0
        assert errors == [], errors


def test_the_reviewed_scene_holds_only_the_art_the_operator_accepted():
    """Which objects are in the reviewed picture, against the verdict register.

    Ten fixtures are accepted; no plant and no animal is.  The current starter
    places five accepted fixtures AND two plants that carry no verdict, so this
    test states that exactly, rather than passing on a vague "some accepted art
    is present" or failing forever on a gap nobody has decided yet.

    Written as an equality on both sets so it cannot drift in either direction:
    adding unreviewed art to the starter fails it, and so does an approval
    landing without the composition being reconsidered.  Neither change should
    be able to happen quietly.
    """
    import json as _json

    register = _json.loads((ROOT / "docs" / "garden-asset-acceptance.json").read_text())
    accepted = {
        row["asset_id"] for row in register["assets"]
        if row["verdict"] in {"accepted", "accepted_as_deployed"}
    }
    assert accepted == {
        "fixture.arbor", "fixture.bench", "fixture.birdbath", "fixture.bridge",
        "fixture.lantern", "fixture.mailbox", "fixture.planter", "fixture.pond",
        "fixture.stepping_stones", "fixture.trellis",
    }, "the accepted inventory changed; the reviewed composition must be revisited"

    with _static_server() as origin:
        with _chrome(origin) as (page, errors):
            _enter_standalone_garden(page, origin, REVIEW_QUERY)
            objects = page.evaluate("() => window.__gardenReview.state().objects")
            fixtures = page.evaluate("() => window.__gardenReview.state().fixtures")

            in_scene = {f"fixture.{row['catalog']}" for row in fixtures}
            assert in_scene <= accepted, (
                f"the reviewed scene places unaccepted fixtures: {sorted(in_scene - accepted)}"
            )
            assert in_scene == {
                "fixture.bench", "fixture.lantern", "fixture.mailbox",
                "fixture.planter", "fixture.stepping_stones",
            }, f"the starter fixture set changed: {sorted(in_scene)}"

            # The recorded gap. Plants are drawn by the renderer and carry no
            # per-asset verdict, so the reviewed composition is NOT one that
            # could be accepted as it stands. Stating the count keeps it from
            # growing unnoticed and keeps this file from implying otherwise.
            plants = [row for row in objects if row["id"].startswith("plant")]
            assert len(plants) == 2, (
                "the number of unaccepted plant objects in the starter changed: "
                f"{[row['id'] for row in plants]}"
            )
        assert errors == [], errors


# ---------------------------------------------------------------------------
# The rejected action chrome, at every required size.
# ---------------------------------------------------------------------------


FORBIDDEN_SELECTORS = (
    "#garden-affordances",
    "#garden-semantics",
    "#garden-object-list",
    "#garden-action-sheet",
    ".garden-opportunity",
    "#garden-invitation",
)

# Phrases from the rejected surfaces. Checked as TEXT because a rewritten
# implementation would carry new element ids while saying the same things, and
# it is the words over the picture the operator rejected.
FORBIDDEN_PHRASES = ("Click to", "More actions", "Feed the bird", "Light the lantern")


def _assert_no_action_chrome(page) -> None:
    """No labels, cards, buttons, lists or sheets over or beside the picture."""
    for selector in FORBIDDEN_SELECTORS:
        assert page.locator(selector).count() == 0, selector
    assert page.locator("#g button").count() == 0, "a button was painted in the Garden"
    text = page.locator("#g").inner_text()
    for phrase in FORBIDDEN_PHRASES:
        assert phrase not in text, f"the Garden shows {phrase!r}"


@pytest.mark.parametrize(
    "viewport",
    [DESKTOP, MOBILE, (320, 800)],
    ids=["desktop-1600x1000", "mobile-390x844", "narrow-320"],
)
def test_no_action_chrome_at_every_required_size(viewport):
    """1600x1000, 390x844 and 320 CSS pixels are all required review sizes."""
    with _static_server() as origin:
        with _chrome(origin, viewport=viewport) as (page, errors):
            _enter_standalone_garden(page, origin, REVIEW_QUERY)
            assert _painted_glyph_count(page) > 0, "the Garden painted nothing"
            _assert_no_action_chrome(page)
        assert errors == [], errors


# ---------------------------------------------------------------------------
# Picture-owned interaction, exercised only on art the operator accepted.
#
# The five fixtures in the starter are all `accepted`; the two plants are not,
# and declare no primary action, so nothing below touches them. No pose, state,
# effect or behaviour is invented anywhere in this section.
# ---------------------------------------------------------------------------


def _summary(page) -> str:
    """The accessible scene summary, which is where a dispatch shows up."""
    return page.evaluate(
        "() => document.getElementById('garden-scene-summary')?.textContent ?? ''"
    )


def _summary_changes(page, previous: str, timeout_ms: int = 4000) -> bool:
    """Wait until the summary settles to something new, or give up.

    Polling rather than sleeping is the whole point. A fixed wait read the
    PREVIOUS click's result and made four working fixtures look broken -- the
    summary updates asynchronously, so the only correct question is "has it
    changed yet", asked until it has.
    """
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        if _summary(page) != previous:
            return True
        page.wait_for_timeout(100)
    return False


def _accepted_fixture_target(page):
    """Pick an accepted fixture that declares a primary action, and its rect.

    Returns the object id, its interaction rectangle in CSS pixels, and the
    canonical primary action declaration -- read from the page, so the test
    aims at whatever the product actually projected rather than at a guess.
    """
    return page.evaluate(
        """() => {
            const review = window.__gardenReview;
            const fixture = review.state().objects.find(
              object => object.id.startsWith('fixture') && object.primary_action,
            );
            if (!fixture) return null;
            const rect = review.objectRectPixels(fixture.id);
            return rect ? {id: fixture.id, rect, primary: fixture.primary_action} : null;
        }"""
    )


def test_clicking_one_accepted_fixture_reaches_the_canonical_world():
    """The single-fixture positive control for the pointer path.

    Kept after the five-fixture test below superseded it, because it is the
    smallest thing that can fail: one click, one fixture, one canonical
    counter. If this goes red the dispatch path itself is gone, and the larger
    test's failure would be ambiguous between "dispatch is broken" and "the
    rectangles were read wrongly" -- an ambiguity that once produced four wrong
    descriptions of a defect that did not exist.

    Its earlier docstring claimed the other four fixtures did nothing. That was
    my measurement error, not the product's: see the retraction in
    docs/FAILURE_LOG.md and commit 0fb7bec.
    """
    with _static_server() as origin:
        with _chrome(origin) as (page, errors):
            _enter_standalone_garden(page, origin, REVIEW_QUERY)
            target = page.evaluate(
                """() => {
                    const review = window.__gardenReview;
                    const object = review.state().objects.find(
                      candidate => candidate.primary_action
                        && candidate.primary_action.args.fixture_action === 'walk',
                    );
                    return object
                      ? {id: object.id, rect: review.objectRectPixels(object.id)} : null;
                }"""
            )
            assert target and target["rect"], "the stepping stones were not projected"

            def count() -> int:
                rows = page.evaluate("() => window.__gardenReview.state().fixtures")
                return next(row["interaction_count"] for row in rows if row["id"] == target["id"])

            before = count()
            page.mouse.click(
                target["rect"]["x"] + target["rect"]["width"] / 2,
                target["rect"]["y"] + target["rect"]["height"] / 2,
            )
            page.wait_for_timeout(400)
            assert count() == before + 1, "no fixture click reaches the canonical world at all"
            _assert_no_action_chrome(page)
        assert errors == [], errors


def test_clicking_EVERY_accepted_fixture_reaches_the_canonical_world():
    """All five, each rectangle re-read immediately before its own click.

    The re-read is the entire correctness of this test, and getting it wrong
    produced four wrong descriptions of a defect that does not exist.

    Interacting with a fixture MOVES THE CAMERA. Reading all five rectangles up
    front and then clicking them in turn aims every click after the first at
    ground the scene has since slid out from under: the click lands on whatever
    is there now, which is usually the previously targeted object. That looks
    exactly like "clicks activate the wrong object", and it was reported as
    exactly that. Canonical state, read per click against a freshly read
    rectangle, shows all five fixtures dispatching their own action correctly.

    The signal is canonical world state, not the accessible summary: the summary
    is written only when `syncGardenControlsAvailability()` is truthy, so its
    silence means nothing either way.
    """
    with _static_server() as origin:
        with _chrome(origin) as (page, errors):
            _enter_standalone_garden(page, origin, REVIEW_QUERY)
            actions = page.evaluate(
                """() => window.__gardenReview.state().objects
                    .filter(object => object.id.startsWith('fixture') && object.primary_action)
                    .map(object => object.primary_action.args.fixture_action)"""
            )
            assert sorted(actions) == ["observe", "open", "sit", "tend", "walk"], actions

            def fixtures():
                return {
                    row["id"]: (row["interaction_count"], row["last_interaction"])
                    for row in page.evaluate("() => window.__gardenReview.state().fixtures")
                }

            for action in actions:
                target = page.evaluate(
                    """action => {
                        const review = window.__gardenReview;
                        const object = review.state().objects.find(
                          candidate => candidate.primary_action
                            && candidate.primary_action.args.fixture_action === action,
                        );
                        return object
                          ? {id: object.id, rect: review.objectRectPixels(object.id)} : null;
                    }""",
                    action,
                )
                assert target and target["rect"], f"the {action!r} fixture left the frame"

                before = fixtures()
                page.mouse.click(
                    target["rect"]["x"] + target["rect"]["width"] / 2,
                    target["rect"]["y"] + target["rect"]["height"] / 2,
                )
                landed = False
                for _ in range(30):
                    page.wait_for_timeout(100)
                    if fixtures()[target["id"]] != before[target["id"]]:
                        landed = True
                        break
                assert landed, f"clicking the {action!r} fixture changed nothing"
                assert fixtures()[target["id"]][1] == action, (
                    f"the {action!r} fixture recorded "
                    f"{fixtures()[target['id']][1]!r} instead"
                )
                _assert_no_action_chrome(page)
        assert errors == [], errors


def test_keyboard_focus_reaches_every_accepted_fixture_and_ENTER_performs_its_action():
    """The keyboard half of the review package, on the same product path.

    Goal §13 lists "keyboard focus and Enter" as its own line of the acceptance
    package, and §10 requires keyboard-complete play. Until now this file proved
    only the pointer: every interaction assertion above went through
    `page.mouse`, so a Garden whose keyboard path was wired to nothing would
    still have satisfied every assertion in this file.

    What is asserted, and why each part is needed:

    1. Focus starts as nothing. A ring that silently pre-selects an object would
       let step 2 succeed without any key ever having moved anything.
    2. `]` walks a stable ring that contains all five accepted fixtures. Read
       from canonical world state via `__gardenReview.focus()`, not from the
       picture -- a focus that moved but dispatched nothing is invisible in the
       painted text, which is exactly the adjacent-signal mistake this lane has
       made before.
    3. Enter on each focused fixture increments THAT fixture's canonical
       interaction count and records ITS action. Same signal, same tolerance
       loop as the pointer test above, so "Enter does what the click does" is a
       comparison of like with like rather than of two different observables.
    4. None of it paints action chrome, and the console stays clean.

    The keyboard reader never touches the mouse here. `activeElement` is BODY
    after the standalone button is dismissed, which is what lets the document
    level `keydown` handler see the keys at all; if that regressed to leaving
    focus on a BUTTON, `Enter` would be swallowed as native button activation
    and step 3 would fail rather than quietly test nothing.
    """
    with _static_server() as origin:
        with _chrome(origin) as (page, errors):
            _enter_standalone_garden(page, origin, REVIEW_QUERY)

            # Nobody has pressed anything yet, so nothing is focused. This also
            # pins that the ring is entered BY the key, not by page load.
            assert page.evaluate("() => window.__gardenReview.focus()") is None, (
                "something was already focused before any key was pressed"
            )

            def fixtures():
                return {
                    row["id"]: (row["interaction_count"], row["last_interaction"])
                    for row in page.evaluate("() => window.__gardenReview.state().fixtures")
                }

            # One full lap of the ring. Bounded at twice the object count so a
            # ring that never closes fails instead of looping forever.
            object_count = page.evaluate(
                "() => window.__gardenReview.state().objects.length"
            )
            reached: dict[str, str] = {}
            for _ in range(object_count * 2):
                page.keyboard.press("]")
                page.wait_for_timeout(150)
                focus = page.evaluate("() => window.__gardenReview.focus()")
                assert focus, "']' left the Garden with nothing focused"
                if focus["primary_action"]:
                    reached[focus["primary_action"]["args"]["fixture_action"]] = focus["id"]

            assert sorted(reached) == ["observe", "open", "sit", "tend", "walk"], (
                f"the keyboard ring does not reach all five accepted fixtures: {sorted(reached)}"
            )

            # Now walk the ring again and press Enter on each fixture as it is
            # reached, so the key that acts is pressed against the focus the
            # previous key actually produced -- no id is re-targeted from a
            # stale reading, which is the mistake that produced four wrong
            # descriptions of the pointer path.
            performed: dict[str, str] = {}
            for _ in range(object_count * 2):
                page.keyboard.press("]")
                page.wait_for_timeout(150)
                focus = page.evaluate("() => window.__gardenReview.focus()")
                if not focus or not focus["primary_action"]:
                    continue
                action = focus["primary_action"]["args"]["fixture_action"]
                if action in performed:
                    continue
                before = fixtures()
                page.keyboard.press("Enter")
                landed = False
                for _ in range(30):
                    page.wait_for_timeout(100)
                    if fixtures()[focus["id"]] != before[focus["id"]]:
                        landed = True
                        break
                assert landed, f"Enter on the focused {action!r} fixture changed nothing"
                count, last = fixtures()[focus["id"]]
                assert last == action, (
                    f"Enter on the {action!r} fixture recorded {last!r} instead"
                )
                assert count == before[focus["id"]][0] + 1, (
                    f"Enter on the {action!r} fixture did not increment its count once"
                )
                performed[action] = focus["id"]
                _assert_no_action_chrome(page)

            assert sorted(performed) == ["observe", "open", "sit", "tend", "walk"], (
                f"Enter did not perform every accepted fixture's action: {sorted(performed)}"
            )
            assert performed == reached, (
                "the fixture Enter acted on is not the one focus reported"
            )
        assert errors == [], errors


def test_keyboard_focus_moves_spatially():
    """Focusing 'right' should reach the object to the right, not the next id.

    CORRECTED 2026-08-03, in two halves. First the COMMAND: `move_focus` used
    to map every compass direction onto previous/next over id order; it now
    resolves them against canonical positions, identically in both engines,
    proved by `test_spatial_focus_agrees_exactly_between_the_two_engines` and
    by mutation. Then the BINDING: the browser sent the arrow keys to `pan`,
    so no direction ever reached the command from a keyboard. The key map
    recorded in the Failure Log (the execution order's recommended map) now
    binds plain arrows to spatial focus and keeps pan on Shift+Arrow and
    WASD, so navigating and panning coexist without one shadowing the other.

    Asserted against canonical positions, which is the only place 'to the right
    of' is defined -- the painted picture is a projection of them and cannot
    settle the question on its own.
    """
    with _static_server() as origin:
        with _chrome(origin) as (page, errors):
            _enter_standalone_garden(page, origin, REVIEW_QUERY)

            # Canonical positions, read once. `]` and ArrowRight are the only
            # things that touch focus below -- the harness never sets it, so
            # what is measured is the product's own navigation and not a state
            # this test arranged.
            layout = {
                item["id"]: tuple(item["position"])
                for item in page.evaluate("() => window.__gardenReview.positions()")
            }

            # Walk the ring with `]` until standing on an object that HAS a
            # right-hand neighbour, so "move right" is a question with an
            # answer. Bounded by the ring size.
            origin_id = None
            for _ in range(len(layout) + 1):
                page.keyboard.press("]")
                page.wait_for_timeout(150)
                focus = page.evaluate("() => window.__gardenReview.focus()")
                assert focus, "']' left the Garden with nothing focused"
                if any(x > layout[focus["id"]][0] for x, _ in layout.values()):
                    origin_id = focus["id"]
                    break
            assert origin_id, "no object in the starter has a right-hand neighbour"

            start_x = layout[origin_id][0]
            nearest = min(
                (item for item, (x, _) in layout.items() if x > start_x),
                key=lambda item: layout[item][0] - start_x,
            )

            page.keyboard.press("ArrowRight")
            page.wait_for_timeout(400)
            moved = page.evaluate("() => window.__gardenReview.focus()")
            assert moved, "ArrowRight left the Garden with nothing focused"
            assert moved["id"] == nearest, (
                f"ArrowRight from {origin_id} (x={start_x}) focused {moved['id']} "
                f"instead of its right-hand neighbour {nearest} "
                f"(x={layout[nearest][0]})"
            )
        assert errors == [], errors


def test_the_full_recorded_key_map_pans_and_focuses_without_shadowing():
    """Every binding in the recorded key map, exercised in real Chrome.

    ADDED 2026-08-04 (external verification, finding 4): only ArrowRight had
    browser coverage; the other three arrows, Shift+Arrow panning, a/d/w/s
    panning, and the modifier boundary were bindings in source that no test
    had ever pressed. This presses all of them. Arrows are asserted against
    the canonical spatial rule (minimise distance along the axis, then
    across it, then object id -- `spatialFocus` in web/garden-world.mjs,
    mirrored by the Python engine), a direction with no object that way must
    leave focus where it was, opposite pan keys are pressed in pairs so a
    clamped edge cannot fake a dead binding, and every pan keystroke must
    leave focus untouched -- the shadowing failure this map was designed
    against.
    """
    with _static_server() as origin:
        with _chrome(origin) as (page, errors):
            _enter_standalone_garden(page, origin, REVIEW_QUERY)

            layout = {
                item["id"]: tuple(item["position"])
                for item in page.evaluate("() => window.__gardenReview.positions()")
            }

            def focus():
                return page.evaluate("() => window.__gardenReview.focus()")

            def camera():
                return page.evaluate("() => window.__gardenReview.camera()")

            page.keyboard.press("]")
            page.wait_for_timeout(200)
            assert focus(), "']' left the Garden with nothing focused"

            # All four arrows, each proved to MOVE focus. For every
            # direction the ring (`]`) walks to an object that really has a
            # neighbour that way, so the press has a canonical answer; a
            # direction exercised only where nothing lies that way would
            # pass with a dead binding (claim verification, 2026-08-04).
            # ArrowDown gets its no-neighbour case too, from the ground row,
            # so both branches of the binding are exercised for real.
            def neighbor_of(current, axis, sign):
                origin_pos = layout[current]
                candidates = {
                    cid: pos
                    for cid, pos in layout.items()
                    if cid != current and sign * (pos[axis] - origin_pos[axis]) > 0
                }
                if not candidates:
                    return None
                return min(
                    candidates,
                    key=lambda cid: (
                        sign * (layout[cid][axis] - origin_pos[axis]),
                        abs(layout[cid][1 - axis] - origin_pos[1 - axis]),
                        cid,
                    ),
                )

            for key, axis, sign in (
                ("ArrowRight", 0, +1),
                ("ArrowDown", 1, +1),
                ("ArrowLeft", 0, -1),
                ("ArrowUp", 1, -1),
            ):
                # Walk the ring until this direction has an answer.
                expected = neighbor_of(focus()["id"], axis, sign)
                for _ in range(len(layout) + 1):
                    if expected is not None:
                        break
                    page.keyboard.press("]")
                    page.wait_for_timeout(150)
                    expected = neighbor_of(focus()["id"], axis, sign)
                assert expected is not None, (
                    f"no object anywhere has a neighbour for {key}, so the "
                    "binding cannot be proved on this starter"
                )
                current = focus()["id"]
                page.keyboard.press(key)
                page.wait_for_timeout(250)
                after = focus()
                assert after, f"{key} left the Garden with nothing focused"
                assert after["id"] == expected, (
                    f"{key} from {current} {layout[current]} focused "
                    f"{after['id']} instead of {expected} {layout[expected]}"
                )

            # The no-neighbour branch, exercised where it is REAL: every
            # fixture stands on the ground row, so from a fixture with only
            # sky-row plants above it, ArrowDown has no answer and focus
            # must hold still.
            for _ in range(len(layout) + 1):
                if neighbor_of(focus()["id"], 1, +1) is None:
                    break
                page.keyboard.press("]")
                page.wait_for_timeout(150)
            bottom = focus()["id"]
            assert neighbor_of(bottom, 1, +1) is None, (
                "no object without a downward neighbour exists, so the "
                "no-neighbour branch cannot be proved on this starter"
            )
            page.keyboard.press("ArrowDown")
            page.wait_for_timeout(250)
            assert focus()["id"] == bottom, (
                "ArrowDown moved focus although nothing lies below"
            )

            # Every pan binding, each proved INDIVIDUALLY. Opposite keys
            # alternate over a few rounds: a key that found the camera
            # clamped at an edge gets another chance after its opposite has
            # pulled the camera inward, so clamping cannot hide a dead
            # binding and a dead binding cannot hide behind its partner
            # (claim verification, 2026-08-04). No pan keystroke may touch
            # focus.
            for first, second in (
                ("Shift+ArrowLeft", "Shift+ArrowRight"),
                ("Shift+ArrowUp", "Shift+ArrowDown"),
                ("a", "d"),
                ("w", "s"),
            ):
                focused_before = focus()["id"]
                moved = {first: False, second: False}
                for _ in range(3):
                    for key in (first, second):
                        if moved[key]:
                            continue
                        camera_before = camera()
                        page.keyboard.press(key)
                        page.wait_for_timeout(250)
                        if camera() != camera_before:
                            moved[key] = True
                        assert focus()["id"] == focused_before, (
                            f"{key} changed focus; panning is shadowing "
                            "spatial navigation"
                        )
                    if all(moved.values()):
                        break
                dead = [key for key, alive in moved.items() if not alive]
                assert not dead, f"pan keys never moved the camera: {dead}"
        assert errors == [], errors


def test_five_of_the_ten_accepted_assets_never_enter_this_review_at_all():
    """Say plainly which accepted art this file does not exercise.

    Ten fixtures carry an operator verdict; the starter places five. Arbor,
    birdbath, bridge, pond and trellis are accepted drawings that appear in no
    scene here, so nothing in this file is evidence about them -- and a reader
    should not have to infer that from a passing run.

    Asserted as an exact set so it cannot drift: if the starter grows to include
    them this fails and the claim gets rewritten, and if an accepted asset is
    withdrawn it fails too.
    """
    import json as _json

    register = _json.loads((ROOT / "docs" / "garden-asset-acceptance.json").read_text())
    accepted = {
        row["asset_id"] for row in register["assets"]
        if row["verdict"] in {"accepted", "accepted_as_deployed"}
    }
    with _static_server() as origin:
        with _chrome(origin) as (page, errors):
            _enter_standalone_garden(page, origin, REVIEW_QUERY)
            in_scene = {
                f"fixture.{row['catalog']}"
                for row in page.evaluate("() => window.__gardenReview.state().fixtures")
            }
        assert errors == [], errors

    uncovered = accepted - in_scene
    assert uncovered == {
        "fixture.arbor", "fixture.birdbath", "fixture.bridge",
        "fixture.pond", "fixture.trellis",
    }, "the accepted art this review does not cover has changed"

    # WHY they are uncovered, stated rather than left to inference, and stated
    # narrowly.
    #
    # "Five accepted fixtures never enter the review" reads like a test-coverage
    # gap more testing would close. For INTERACTION it is not: these five are
    # accepted as ART and carry NO authored primary action, so placing them in a
    # scene would not make them interactable -- a click would dispatch nothing.
    # The catalog says why in its own comment: a primary action is a promise
    # about safety, not a convenience default, and every entry outside the
    # default scene keeps `primary_verb=None` until it has been through that
    # judgement.
    #
    # What this does NOT say is that their DRAWINGS are covered here. They are
    # checked at the renderer level -- `tests/garden_adapters/
    # test_garden_renderer.mjs` proves every catalog fixture gets a unique,
    # recognisable, non-placeholder picture at three densities -- and nowhere in
    # a product scene in a real browser. That remains an open gap, and it is a
    # gap in composition rather than in testing: showing them through the
    # product means putting them in a starter, which is the operator's choice.
    #
    # Which verb each should get is exactly the kind of decision the destination
    # spec reserves for the operator, so nothing here invents one. Read from the
    # catalog rather than hardcoded, so that authoring one fails this test and
    # forces the claim to be rewritten.
    from lateletter.garden.world.fixtures import FIXTURE_CATALOG

    interactable = {
        f"fixture.{catalog}"
        for catalog, definition in FIXTURE_CATALOG.items()
        if definition.primary_verb is not None
    }

    # Both implementations, not just Python. The browser reads its own
    # `FIXTURE_PRIMARY_ACTIONS`, so authoring an off-starter action there alone
    # would make a fixture interactable in the product while a Python-only
    # check went on reporting that none of them are. Asked of node rather than
    # parsed out of the file, so a rename or a reformat cannot quietly turn this
    # into a check of nothing.
    browser_interactable = {
        f"fixture.{catalog}"
        for catalog in json.loads(
            subprocess.run(
                [
                    "node", "--input-type=module", "-e",
                    "import {FIXTURE_PRIMARY_ACTIONS} from "
                    f"'{(ROOT / 'web' / 'garden-world.mjs').as_uri()}';"
                    "console.log(JSON.stringify(Object.keys(FIXTURE_PRIMARY_ACTIONS)));",
                ],
                capture_output=True, text=True, check=True, cwd=ROOT,
            ).stdout
        )
    }
    assert browser_interactable == interactable, (
        "the browser and the canonical model disagree about which fixtures have "
        f"a primary action: browser {sorted(browser_interactable)} versus "
        f"canonical {sorted(interactable)}"
    )
    assert not (uncovered & interactable), (
        "an accepted fixture outside the starter now has an authored primary "
        f"action: {sorted(uncovered & interactable)}. It is interactable and "
        "this review no longer has a reason to skip it."
    )
    assert accepted & interactable == accepted - uncovered, (
        "the five accepted fixtures this review does cover are exactly the ones "
        "with an authored primary action; that correspondence has changed"
    )


def _touch_drag(page, start_x: int, start_y: int, end_x: int, end_y: int, steps: int = 14):
    """One single-finger drag, injected through Chrome's NATIVE touch pipeline.

    CORRECTED 2026-08-04 (external verification, finding 3): the previous
    version constructed PointerEvent objects in page JavaScript and called
    `dispatchEvent`, which bypasses Chrome's input pipeline entirely -- no
    hit testing, no implicit pointer capture, no gesture arbitration, no
    slop detection, no synthesized click. That proved the handler's wiring,
    not the gesture. `Input.dispatchTouchEvent` over CDP is the browser's
    own injection path: Chrome performs the same touch-to-pointer
    translation and gesture decisions a finger on a phone produces, and the
    page cannot tell the difference.
    """
    cdp = page.context.new_cdp_session(page)
    try:
        cdp.send(
            "Input.dispatchTouchEvent",
            {"type": "touchStart", "touchPoints": [{"x": start_x, "y": start_y, "id": 1}]},
        )
        for step in range(1, steps + 1):
            cdp.send(
                "Input.dispatchTouchEvent",
                {
                    "type": "touchMove",
                    "touchPoints": [
                        {
                            "x": start_x + (end_x - start_x) * step / steps,
                            "y": start_y + (end_y - start_y) * step / steps,
                            "id": 1,
                        }
                    ],
                },
            )
        cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
    finally:
        cdp.detach()
    page.wait_for_timeout(250)


def test_touch_can_bring_an_off_screen_fixture_into_reach():
    """A phone with no keyboard must still be able to reach the whole Garden.

    CORRECTED 2026-08-03: this was a strict expected failure -- the viewer
    registered no drag handler of any kind, so the two fixtures outside the
    phone frame were unreachable by any means a touch device has.
    Single-pointer pan now dispatches the same canonical `pan` command the
    keyboard uses, and this asserts it with a REAL touch gesture. The camera
    is the signal, not the painted text: ambient motion repaints the Garden
    on its own, so text comparison would report success for a dead gesture.
    """
    with _static_server() as origin:
        with _chrome(origin, viewport=MOBILE) as (page, errors):
            _enter_standalone_garden(page, origin, PRODUCT_QUERY)
            page.wait_for_timeout(3000)

            before = page.evaluate("() => window.__gardenReview.camera()")
            assert before is not None, "the review surface exposes no camera"

            _touch_drag(page, 320, 400, 40, 400)

            assert page.evaluate("() => window.__gardenReview.camera()") != before, (
                "a full-width touch drag did not move the camera, so the "
                "fixtures outside the phone frame cannot be reached by touch"
            )
        assert errors == [], errors


def test_a_single_tap_performs_the_primary_action_on_touch():
    """One tap acts -- including on the fixtures that start off-screen.

    CORRECTED 2026-08-03: this was a strict expected failure -- at 390x844
    the stepping stones and the planter had no interaction rectangle at all,
    because they fell outside the cropped mobile width and no gesture could
    bring them in. With single-pointer touch pan, the phone can now reach
    them: this test pans the camera BY TOUCH until each of the two
    previously unreachable fixtures presents a rectangle, then taps it once
    and requires that first tap to perform the declared primary action.
    Mobile may crop peripheral scenery; it may not lose reachable
    interactions -- and now it does not.
    """
    with _static_server() as origin:
        with _chrome(origin, viewport=MOBILE) as (page, errors):
            _enter_standalone_garden(page, origin, REVIEW_QUERY)
            page.wait_for_timeout(500)

            def reachable_target(verb: str) -> dict | None:
                """The fixture declaring `verb`, with its rectangle -- or None
                while the camera has not brought it on screen."""
                return page.evaluate(
                    """(verb) => {
                        const review = window.__gardenReview;
                        const object = review.state().objects.find(
                          item => item.id.startsWith('fixture') &&
                                  item.primary_action &&
                                  item.primary_action.args?.fixture_action === verb,
                        );
                        if (!object) return null;
                        const rect = review.objectRectPixels(object.id);
                        return rect ? {id: object.id, rect} : null;
                    }""",
                    verb,
                )

            def interactions(fixture_id: str) -> int:
                rows = page.evaluate("() => window.__gardenReview.state().fixtures")
                return next(row["interaction_count"] for row in rows if row["id"] == fixture_id)

            # The two fixtures the initial frame cannot show: walk is the
            # stepping stones (world x=31, left of the start camera) and tend
            # is the planter (x=88, right of it).
            for verb, direction in (("walk", +1), ("tend", -1)):
                target = reachable_target(verb)
                for _ in range(12):
                    if target is not None:
                        break
                    # Drag a frame-width in the direction that reveals the
                    # target: content follows the finger, so dragging RIGHT
                    # (direction +1) brings the world's left side into view.
                    middle = 420
                    if direction > 0:
                        _touch_drag(page, 60, middle, 330, middle)
                    else:
                        _touch_drag(page, 330, middle, 60, middle)
                    target = reachable_target(verb)
                assert target is not None, (
                    f"panning a dozen frame-widths never gave {verb!r} an "
                    "interaction rectangle; the fixture is still unreachable"
                )

                before = interactions(target["id"])
                page.touchscreen.tap(
                    target["rect"]["x"] + target["rect"]["width"] / 2,
                    target["rect"]["y"] + target["rect"]["height"] / 2,
                )
                page.wait_for_timeout(400)
                assert interactions(target["id"]) == before + 1, (
                    f"the first tap on {verb!r} did not perform its primary action"
                )
        assert errors == [], errors


def test_a_drag_that_pans_never_performs_the_action_under_the_pointer():
    """Releasing a pan over a fixture must not act on it.

    ADDED 2026-08-04 (external verification, finding 3): the click-swallow
    handler in the viewer was exercised by no test -- deleting it left the
    whole suite intact, because no test ever generated the post-drag click
    the handler exists to suppress. A browser DOES generate one: a mouse
    drag that starts and ends inside the same element fires a click at
    button-release regardless of distance travelled. So this drags across
    the Garden with the real mouse, ends the drag ON an actionable fixture,
    proves the browser really synthesised the click (a document-level
    capture listener sees it before the viewer can stop propagation), and
    requires that the fixture's action count did NOT move. Delete the
    swallow handler and the released pan performs whatever sat under the
    pointer -- exactly the defect this pins out.
    """
    with _static_server() as origin:
        with _chrome(origin) as (page, errors):
            _enter_standalone_garden(page, origin, REVIEW_QUERY)
            page.wait_for_timeout(500)

            target = page.evaluate(
                """() => {
                    const review = window.__gardenReview;
                    for (const object of review.state().objects) {
                        if (!object.id.startsWith('fixture') || !object.primary_action) continue;
                        const rect = review.objectRectPixels(object.id);
                        if (rect) return {id: object.id, rect};
                    }
                    return null;
                }"""
            )
            assert target is not None, "no actionable fixture is on screen to drag onto"

            # The document-capture listener runs before the garden element's
            # own capture handler, so it records the synthesised click even
            # though the viewer swallows it on the way down.
            page.evaluate(
                """() => {
                    window.__clicksSeen = [];
                    document.addEventListener('click', event => {
                        window.__clicksSeen.push({x: event.clientX, y: event.clientY});
                    }, {capture: true});
                }"""
            )

            def counts() -> list:
                return page.evaluate(
                    "() => window.__gardenReview.state().fixtures"
                    ".map(row => [row.id, row.interaction_count])"
                )

            # Start the drag ON the fixture, sized to a little over ONE CELL.
            # Below a cell no pan is dispatched and the viewer rightly treats
            # the gesture as a click, which ACTS -- that is a tap with
            # jitter, not a pan. Just over a cell, one pan step fires, the
            # content follows the pointer to within a few pixels, and the
            # synthesised click at release still lands on the fixture. The
            # cell size varies with the measured font, so several sizes are
            # tried and each attempt is judged ONLY against itself: counts
            # are captured immediately before the drag, and the swallow is
            # asserted on the first attempt that really panned AND really
            # released its click on the fixture -- both verified, never
            # assumed. (Two earlier versions assumed containment and let the
            # deleted-handler mutation survive; the diagnosis is in the
            # Failure Log, 2026-08-04.)
            exercised = False
            for drag_px in (16, 20, 24, 12):
                rect = page.evaluate(
                    "(id) => window.__gardenReview.objectRectPixels(id)", target["id"]
                )
                if rect is None:
                    continue
                start_x = rect["x"] + rect["width"] / 2
                start_y = rect["y"] + rect["height"] / 2
                before_counts = counts()
                before_camera = page.evaluate("() => window.__gardenReview.camera()")
                page.evaluate("() => { window.__clicksSeen = []; }")

                page.mouse.move(start_x, start_y)
                page.mouse.down()
                page.mouse.move(start_x + drag_px, start_y, steps=4)
                page.mouse.up()
                page.wait_for_timeout(400)

                clicks = page.evaluate("() => window.__clicksSeen")
                rect_after = page.evaluate(
                    "(id) => window.__gardenReview.objectRectPixels(id)", target["id"]
                )
                camera_moved = (
                    page.evaluate("() => window.__gardenReview.camera()") != before_camera
                )
                landed = rect_after is not None and any(
                    rect_after["x"] <= click["x"] <= rect_after["x"] + rect_after["width"]
                    and rect_after["y"] <= click["y"] <= rect_after["y"] + rect_after["height"]
                    for click in clicks
                )
                if not (camera_moved and landed):
                    continue
                exercised = True
                assert counts() == before_counts, (
                    f"releasing a {drag_px}px pan over the fixture performed "
                    "its primary action instead of being swallowed"
                )
                break
            assert exercised, (
                "no drag both panned the camera and released its synthesised "
                "click on the fixture, so the swallow path was never exercised"
            )
        assert errors == [], errors


def _fixture_presentation_under_hover(page) -> tuple[set[str], set[str], set[str], str]:
    """Fixture presentation with the pointer away, over an accepted fixture, away again.

    WHY THIS SIGNAL. The first version of this compared SCREENSHOTS of a region
    around the fixture, sampled pointer-away and then pointer-over 800ms later.
    That is not a hover measurement: the Garden repaints on its own, so a
    rendering can appear during the second window purely because time passed.
    The test alternated between XFAIL and strict XPASS across runs and therefore
    established nothing -- the same mistake, measuring a signal adjacent to the
    claim, that this lane keeps making.

    `.garden-measured-layer` has neither problem. Only fixtures with measured
    atlas art reach it -- plants paint into the lattice through `raster.art` --
    and fixtures carry no ambient animation, so its markup is a still function
    of fixture presentation. Emphasis is colour, and colour is written into that
    markup as an inline `color:`, so a hover response would appear there and
    nothing else would.

    Three windows, not two, and the outer pair matters as much as the middle
    one: if the two pointer-away windows disagree, the layer is not quiet and
    any difference found in the middle window could be drift rather than hover.

    :param page: an open Garden with the review accessor available
    :returns: (markup seen before, markup seen while hovering, markup seen
        after, the CSS cursor while hovering)
    """
    target = page.evaluate(
        """() => {
            const review = window.__gardenReview;
            const object = review.state().objects.find(item => item.primary_action);
            return object
              ? {id: object.id, rect: review.objectRectPixels(object.id)} : null;
        }"""
    )
    assert target and target["rect"], "no accepted fixture was projected to hover"
    rect = target["rect"]
    read = "() => document.querySelector('.garden-measured-layer').innerHTML"

    def window() -> set[str]:
        seen = set()
        for _ in range(6):
            seen.add(hashlib.sha256(page.evaluate(read).encode("utf-8")).hexdigest())
            page.wait_for_timeout(300)
        return seen

    page.mouse.move(5, 5)
    page.wait_for_timeout(600)
    before = window()
    page.mouse.move(rect["x"] + rect["width"] / 2, rect["y"] + rect["height"] / 2)
    page.wait_for_timeout(600)
    during = window()
    cursor = page.evaluate(
        "() => getComputedStyle(document.getElementById('g')).cursor"
    )
    page.mouse.move(5, 5)
    page.wait_for_timeout(600)
    after = window()
    return before, during, after, cursor


def test_hovering_accepted_ink_changes_the_fixture_and_the_cursor():
    """The control: the hover lands, and the layer being watched does not drift.

    Two claims, both needed before the expected failure below means anything.
    If the cursor never changed, "no visual response" could mean the pointer
    never reached the object. If the measured layer changed on its own, a
    difference found while hovering could be drift rather than a response.
    """
    with _static_server() as origin:
        with _chrome(origin) as (page, errors):
            _enter_standalone_garden(page, origin, PRODUCT_QUERY)
            before, _, after, cursor = _fixture_presentation_under_hover(page)
            assert cursor == "pointer", (
                f"the cursor over accepted fixture ink is {cursor!r}, so the "
                "hover is not being received and the test below proves nothing"
            )
            assert before == after, (
                "fixture presentation changed between two pointer-away windows, "
                "so this layer is not quiet enough to attribute a change to hover"
            )
        assert errors == [], errors


def test_hovering_accepted_ink_changes_the_picture():
    """Goal §5: hovering visible object ink changes the picture, not just the cursor.

    RETRACTED DEFECT. This was recorded on 2026-08-03 as a strict expected
    failure -- "hover changes the cursor and nothing else" -- and it was my
    measurement, not the product. The test opened the viewer with
    `garden_review_time`, which deliberately FREEZES disposable presentation, so
    the renderer never repainted and the emphasis it had already computed never
    reached the DOM. On the product path the same measurement shows a distinct
    fixture presentation for as long as the pointer is over the ink, reverting
    exactly when it leaves.

    The lesson generalises past hover: the review clock is right for provenance
    questions and wrong for every question a repaint has to answer. The sky
    motion test already used the product path for that reason; hover and the
    mobile drag did not, and both said the wrong thing.
    """
    with _static_server() as origin:
        with _chrome(origin) as (page, errors):
            _enter_standalone_garden(page, origin, PRODUCT_QUERY)
            before, during, after, _ = _fixture_presentation_under_hover(page)
            assert during - before - after, (
                "every fixture presentation seen while hovering is one the "
                "Garden also paints with the pointer elsewhere, so hovering "
                "changed nothing but the cursor"
            )
        assert errors == [], errors


def test_the_44px_floor_is_applied_where_it_decides_a_click(tmp_path):
    """Probe the expanded target, do not read the raw rectangle.

    An earlier version read `objectRectPixels` -- the canonical HOTSPOT, 15x17
    CSS pixels for a one-cell fixture -- and called the floor unimplemented. Hit
    testing expands that through `expandTarget` to `MINIMUM_TARGET_PX` before
    deciding what was touched, so the rectangle it read was never the one that
    matters. The only honest measurement is a click.

    So this clicks at a point INSIDE the 44px expansion and OUTSIDE the raw
    hotspot, and requires the object to be selected anyway. If the floor were
    not applied, that point would hit nothing.
    """
    with _static_server() as origin:
        with _chrome(origin) as (page, errors):
            _enter_standalone_garden(page, origin, REVIEW_QUERY)
            target = _accepted_fixture_target(page)
            assert target is not None
            rect = target["rect"]
            assert rect["width"] < 44 or rect["height"] < 44, (
                "the raw hotspot is already 44px; this probe no longer tests expansion"
            )

            # Just outside the hotspot's top edge, still well inside a 44px box
            # centred on it. `expandTarget` grows by half on each side, so a
            # point 12px above the hotspot is covered only if the floor applies.
            probe_x = rect["x"] + rect["width"] / 2
            probe_y = rect["y"] - 12
            settled = _summary(page)
            page.mouse.click(probe_x, probe_y)
            assert _summary_changes(page, settled), (
                "a click inside the 44px expansion but outside the hotspot hit nothing, "
                "so the accessibility floor is not applied where it decides a click"
            )
        assert errors == [], errors


def _upper_half_renderings(page, *, seconds: float, until: int | None = None) -> int:
    """How many DISTINCT pictures the top half of the viewport takes over `seconds`.

    Measured in PIXELS, deliberately, after two text-based readings of the same
    question disagreed with each other:

    * `.garden-lattice-row` textContent misses the measured atlas layer entirely,
      because Contract-P assets are painted separately from the lattice, and the
      deployed legacy has no such rows at all -- so it can only ever measure the
      candidate, and only part of it.
    * `#g` innerText DOES include that layer, but at the cost of the line index
      meaning something different in each viewer: the candidate yields 378 lines
      because every measured glyph span is its own line, the legacy yields 66
      screen rows. "Row 83" is then not a row and not comparable.

    A screenshot has neither problem. The top half of the frame is sky by
    construction -- the ground sits near the bottom in both viewers -- and two
    identical pictures produce identical bytes.

    :param page: an open Garden
    :param seconds: how long to watch, sampled twice a second
    :param until: stop early once this many distinct renderings are seen
    :returns: the number of distinct renderings seen, 1 meaning nothing moved
    """
    size = page.viewport_size
    clip = {"x": 0, "y": 0, "width": size["width"], "height": size["height"] // 2}
    seen: set[str] = set()
    for _ in range(int(seconds * 2)):
        seen.add(hashlib.sha256(page.screenshot(clip=clip)).hexdigest())
        # Motion is a threshold question -- "did a second rendering ever
        # appear" -- so once it has, watching longer only spends wall time.
        if until is not None and len(seen) >= until:
            break
        page.wait_for_timeout(500)
    return len(seen)


def test_the_plain_product_url_grants_no_debug_or_review_permission():
    """No query string at all: the Garden opens, the review surface does not.

    Goal §13 requires the accepted package to carry "no debug/query-only
    permission", and §5 forbids "review/debug query parameters that revive"
    the rejected action chrome. Every other test in this file opens the viewer
    WITH `garden_debug=1`, because they need `__gardenReview` to ask the runtime
    questions -- which means, on their own, they say nothing about what a
    recipient who types the bare URL gets.

    Three things are asserted, and the first two must hold together or neither
    is worth anything:

    1. The Garden paints. If it did not, "no debug surface" would be true of a
       blank page and would prove nothing about the product.
    2. `window.__gardenReview` is not installed. The accessor is the review
       permission; its absence on the product path is the permission not being
       granted.
    3. No action chrome, and a clean console.
    """
    with _static_server() as origin:
        with _chrome(origin) as (page, errors):
            # Deliberately NOT `_enter_standalone_garden`: that helper always
            # appends a query, and a query is the thing under test.
            page.goto(f"{origin}/viewer-bnw.html", wait_until="networkidle")
            page.locator("#btn-standalone").click()
            page.locator("#hud.vis").wait_for(state="visible")
            page.locator("#g .garden-lattice-row").first.wait_for(state="attached")

            assert _painted_glyph_count(page) > 0, (
                "the plain product URL painted nothing, so the absence of a "
                "debug surface below proves nothing"
            )
            assert page.evaluate("() => typeof window.__gardenReview") == "undefined", (
                "the review accessor is installed without anyone asking for it"
            )
            _assert_no_action_chrome(page)
        assert errors == [], errors


def test_nothing_installs_a_cache_that_could_go_stale():
    """Goal §13's "no stale browser cache", asserted rather than assumed.

    Every test in this file opens a fresh Chrome context, so what it sees is
    never a cached build. That is a property of the HARNESS, and a reviewer has
    no reason to trust it about the PRODUCT: if the viewer registered a service
    worker or filled Cache Storage, a recipient could sit on an old Garden
    indefinitely while every run here looked current, and the review would be
    describing a build nobody is being served.

    Today nothing does -- there is no service worker, no cache manifest and no
    Cache-Control handling anywhere in the viewer or the site builder -- so this
    guards that rather than proving something new. Adding one later is a
    legitimate thing to do; doing it without revisiting what "fresh review"
    means is not, and this fails when it happens.
    """
    with _static_server() as origin:
        with _chrome(origin) as (page, errors):
            page.goto(f"{origin}/viewer-bnw.html", wait_until="networkidle")
            page.locator("#btn-standalone").click()
            page.locator("#hud.vis").wait_for(state="visible")
            page.wait_for_timeout(1000)

            workers = page.evaluate(
                "async () => 'serviceWorker' in navigator"
                " ? (await navigator.serviceWorker.getRegistrations())"
                ".map(entry => entry.scope) : []"
            )
            assert workers == [], f"the viewer registered a service worker: {workers}"

            stores = page.evaluate(
                "async () => 'caches' in window ? await caches.keys() : []"
            )
            assert stores == [], f"the viewer filled Cache Storage: {stores}"
        assert errors == [], errors


def test_the_deployed_legacy_sky_lives_which_is_how_the_measurement_is_known_to_work():
    """The positive control for the expected failure below.

    Without this, "nothing moves in the candidate's sky" is indistinguishable
    from "this measurement cannot see motion". Run against the accepted deployed
    baseline -- the same reading, the same window, the same threshold -- the
    legacy shows sky rows changing, because two ambient birds cross it.

    The legacy opens from `#btn-demo`; it has no standalone mode.
    """
    with _static_server() as origin:
        with _chrome(origin) as (page, errors):
            page.goto(f"{origin}/legacy/viewer-bnw.html", wait_until="networkidle")
            page.locator("#btn-demo").click()
            page.locator("#hud.vis").wait_for(state="visible")
            page.wait_for_timeout(1500)

            renderings = _upper_half_renderings(page, seconds=12)
            assert renderings > 1, (
                "the deployed legacy sky did not move either, so this measurement "
                "proves nothing about the candidate"
            )
        assert errors == [], errors


def test_the_sky_lives_too_and_not_only_two_stems():
    """Something must move above the plants, over a long enough look.

    CORRECTED 2026-08-03: this was a strict expected failure -- the top half
    of the candidate was byte-identical for twenty seconds because the sky
    held nothing that moved. The accepted legacy ambient-bird traversal is
    now ported exactly through the GardenPresentation composer, so the sky
    lives again and this asserts it plainly.

    The watch window is FORTY-FIVE seconds with an early exit, not twenty,
    because that is the recipe's own guarantee: the deployed respawn law
    waits 250 to 600 ticks (12.5 to 30 seconds at the accepted 50ms cadence)
    before the first bird, and a shorter window would fail the exact
    deployed behaviour whenever the seeded draw lands late.

    This exists because `test_the_garden_keeps_moving_without_any_input` below
    passes on a signal far weaker than the destination requires: it compares
    whole-frame text, so two alternating trunk glyphs satisfy it completely.
    The capture receipt agrees with it -- seven unique frame hashes out of ten
    -- and the video shows a Garden that is, to the eye, still. That is the same
    adjacent-signal mistake this lane has made repeatedly: measuring something
    true and adjacent to the claim, then reporting the claim.

    So this asks a question the trunk cannot answer: does any row in the UPPER
    HALF of the picture ever change? The ground sits near the bottom by
    construction, so the upper half is sky, and a bird crossing it is the
    accepted legacy recipe the goal file requires.

    Twenty seconds, not three, because traversal is slow and a short look could
    miss a bird that is genuinely there.
    """
    with _static_server() as origin:
        with _chrome(origin) as (page, errors):
            # The product query, not the review query: review deliberately
            # freezes disposable presentation motion, so asking it about motion
            # would answer a question about the freeze.
            _enter_standalone_garden(page, origin, PRODUCT_QUERY)
            page.wait_for_timeout(1500)

            renderings = _upper_half_renderings(page, seconds=45, until=2)
            assert renderings > 1, (
                "the top half of the Garden was byte-identical for forty-five "
                "seconds: nothing above the horizon moved at all, although the "
                "deployed respawn law guarantees a bird within thirty"
            )
        assert errors == [], errors


def test_the_garden_keeps_moving_without_any_input():
    """It must live on its own, not only when touched.

    Compared as painted text over real elapsed time. `garden_review_time` is
    deliberately NOT used for this one: it freezes disposable motion, which is
    exactly what is being measured.

    Polled rather than sampled twice, after this failed inside a full-suite run
    while passing on its own. It used to read the frame, wait exactly three
    seconds, and read again -- and the only motion in the candidate is the oak
    trunk and the sunflower stem alternating between '/', '\\' and '|', so two
    instants three seconds apart can land on the same phase of that sway, and
    under load they did. The claim is unchanged: the Garden changes without
    input. Only the sensitivity to WHICH two instants are compared is gone.

    That fragility is itself evidence for the expected failure above. A motion
    test is only as robust as the motion it watches, and this one watches two
    glyphs.
    """
    with _static_server() as origin:
        with _chrome(origin) as (page, errors):
            _enter_standalone_garden(page, origin, PRODUCT_QUERY)
            first = page.locator("#g").inner_text()
            moved = False
            for _ in range(20):
                page.wait_for_timeout(500)
                if page.locator("#g").inner_text() != first:
                    moved = True
                    break
            assert moved, "the Garden was motionless for ten seconds"
        assert errors == [], errors


def test_the_garden_keeps_moving_on_mobile_too():
    """Same measurement as the desktop case, at the required phone size.

    CORRECTED 2026-08-03: this was a strict expected failure -- the phone
    frame held only three static fixtures, because both animating plants fell
    outside it, and nothing else moved. The exact legacy ambient-bird
    traversal now crosses the phone sky too (below sixty columns it paints
    the deployed compact frame pair), so the mobile Garden visibly lives
    before any gesture, which is the requirement.

    The window is forty-five seconds for the same reason as the sky test:
    the deployed respawn law may wait up to thirty seconds before the first
    bird, and a shorter window would fail the exact deployed behaviour.
    """
    with _static_server() as origin:
        with _chrome(origin, viewport=MOBILE) as (page, errors):
            _enter_standalone_garden(page, origin, PRODUCT_QUERY)
            page.wait_for_timeout(1500)
            first = page.locator("#g").inner_text()
            moved = False
            for _ in range(90):
                page.wait_for_timeout(500)
                if page.locator("#g").inner_text() != first:
                    moved = True
                    break
            assert moved, (
                "the mobile Garden was motionless for forty-five seconds, "
                "although the deployed respawn law guarantees a bird within thirty"
            )
        assert errors == [], errors


def test_day_evening_and_night_are_visually_distinct():
    """Time of day must read differently. This one holds.

    Driven by `garden_review_time`, which is how the operator's own review
    query selects an instant -- so these are the same three moments a reviewer
    would look at, not a private test hook.
    """
    instants = {
        "day": "2026-07-15T12:00:00Z",
        "evening": "2026-07-15T19:30:00Z",
        "night": "2026-07-15T23:00:00Z",
    }
    seen: dict[str, str] = {}
    with _static_server() as origin:
        for name, when in instants.items():
            with _chrome(origin) as (page, errors):
                _enter_standalone_garden(page, origin, f"garden_debug=1&garden_review_time={when}")
                seen[name] = page.evaluate(
                    "() => getComputedStyle(document.documentElement)"
                    ".getPropertyValue('--bg').trim()"
                )
                assert _painted_glyph_count(page) > 0, f"{name} painted nothing"
                assert errors == [], errors
    assert len(set(seen.values())) == 3, f"time of day does not read differently: {seen}"


def test_the_four_seasons_are_visually_distinct():
    """Four seasons at the same hour must not paint the same picture.

    CORRECTED 2026-08-03: this was a strict expected failure recorded as
    "winter does not exist as a season", attributed to seasonal art carrying
    no verdict. The real defect needed no new art at all: the candidate's
    season chain read `month <= 8` with no lower bound, so January and
    February fell into SUMMER -- winter never existed on the clock path --
    and the scene-empty weather branch painted nothing in any season. Both
    are deployed laws now transcribed exactly (frozen blob 59dc49a8, lines
    1634-1637 and 1030-1056): months 12-2 are winter, winter snows
    continuously, spring carries light rain, autumn sheds leaves. Particle
    density remains the candidate's own until the full particle-system port;
    presence is the deployed law.
    """
    midday = {
        "spring": "2026-04-15T12:00:00Z",
        "summer": "2026-07-15T12:00:00Z",
        "autumn": "2026-10-15T12:00:00Z",
        "winter": "2026-01-15T12:00:00Z",
    }
    painted: dict[str, str] = {}
    with _static_server() as origin:
        for name, when in midday.items():
            with _chrome(origin) as (page, errors):
                _enter_standalone_garden(page, origin, f"garden_debug=1&garden_review_time={when}")
                painted[name] = page.locator("#g").inner_text()
                assert errors == [], errors
    assert len(set(painted.values())) == 4, (
        "seasons that paint the same picture: "
        f"{sorted(k for k in painted if list(painted.values()).count(painted[k]) > 1)}"
    )


def test_reduced_motion_still_paints_the_garden():
    """A person who cannot take motion still gets the picture."""
    with _static_server() as origin:
        with playwright_api.sync_playwright() as driver:
            try:
                browser = driver.chromium.launch(channel="chrome")
            except Exception as failure:  # pragma: no cover - environment dependent
                pytest.skip(f"system Google Chrome is unavailable: {failure}")
            context = browser.new_context(
                viewport={"width": DESKTOP[0], "height": DESKTOP[1]},
                reduced_motion="reduce",
            )
            page = context.new_page()
            errors: list[str] = []
            page.on("pageerror", lambda error: errors.append(f"pageerror: {error}"))
            try:
                _enter_standalone_garden(page, origin, REVIEW_QUERY)
                assert _painted_glyph_count(page) > 0, "reduced motion painted nothing"
                _assert_no_action_chrome(page)
            finally:
                context.close()
                browser.close()
            assert errors == [], errors


def test_no_action_chrome_survives_a_live_desktop_to_mobile_resize():
    """Resizing in one live session, not two separate loads.

    A surface can be clean on a fresh mobile load and still spawn chrome when a
    desktop session is narrowed, because that path runs different code.
    """
    with _static_server() as origin:
        with _chrome(origin, viewport=DESKTOP) as (page, errors):
            _enter_standalone_garden(page, origin, REVIEW_QUERY)
            _assert_no_action_chrome(page)
            page.set_viewport_size({"width": MOBILE[0], "height": MOBILE[1]})
            page.wait_for_timeout(400)
            assert _painted_glyph_count(page) > 0, "the Garden emptied on resize"
            _assert_no_action_chrome(page)
        assert errors == [], errors


# ---------------------------------------------------------------------------
# The AUTHENTICATED path: a real sealed bundle, unlocked with a passphrase.
#
# Everything above enters through the standalone button, which is not what the
# recipient does and not what the release gate asks about. This section seals a
# real .lateletter with the product's own code, drops it on the viewer, types
# the passphrase, and requires the Garden to appear on the other side.
# ---------------------------------------------------------------------------


def _sealed_bundle(tmp_path, passphrase: str = "correct horse"):
    """Seal a real bundle with the product's own crypto, and write it out.

    Not a fixture checked into the repository: sealing it here means the test
    exercises the same code that seals a recipient's letter, and a change to the
    envelope shows up as a failure rather than as a stale file that still opens.
    """
    from datetime import date

    from lateletter.bundle import Bundle, write_bundle
    from lateletter.sealed import seal_bundle, seal_message

    message = seal_message(
        passphrase,
        message_id="m1",
        date=date.today().isoformat(),
        label="Open today",
        body="The letter the Garden is waiting to deliver.",
    )
    bundle = Bundle(messages=[message], garden_gifts=[])
    seal_bundle(bundle, passphrase)
    path = tmp_path / "review.lateletter"
    write_bundle(bundle, path)
    return path


def _open_sealed_bundle(page, origin, bundle):
    """Drive the recipient's real flow up to the passphrase prompt.

    Loading a bundle does NOT ask for a passphrase: the Garden appears first and
    an "open letters" control is what leads to it. An earlier version of these
    tests waited for `#pp-input` straight after the drop, saw a hidden field, and
    was skipped as a broken harness -- the product was doing the right thing and
    the test was asking the wrong question.
    """
    page.goto(f"{origin}/viewer-bnw.html", wait_until="networkidle")
    page.locator("#file-input").set_input_files(str(bundle))
    page.locator("#g .garden-lattice-row").first.wait_for(state="attached", timeout=15000)
    page.get_by_role("button", name="open letters").first.click()
    page.locator("#pp-input").wait_for(state="visible", timeout=10000)


def test_a_sealed_bundle_opens_the_garden_before_asking_anything(tmp_path):
    """The Garden comes before the authentication, and leaks nothing.

    This is the first-run promise and the privacy rule in one measurement: the
    picture is painted from a real sealed bundle, and nothing the passphrase
    protects -- the label, the body -- is anywhere on the page yet.
    """
    bundle = _sealed_bundle(tmp_path)
    with _static_server() as origin:
        with _chrome(origin) as (page, errors):
            page.goto(f"{origin}/viewer-bnw.html", wait_until="networkidle")
            page.locator("#file-input").set_input_files(str(bundle))
            page.locator("#g .garden-lattice-row").first.wait_for(state="attached", timeout=15000)

            assert _painted_glyph_count(page) > 0, "a sealed bundle painted no Garden"
            body = page.locator("body").inner_text()
            assert "Open today" not in body, "the sealed label leaked before authentication"
            assert "waiting to deliver" not in body, "the sealed body leaked before authentication"
            _assert_no_action_chrome(page)
        assert errors == [], errors


def test_an_authenticated_sealed_bundle_opens_the_garden(tmp_path):
    """The recipient's actual path, end to end, through a real browser.

    Drop a sealed bundle, type the passphrase, and the Garden must be there.
    None of the standalone tests above prove this: they enter through a button
    the recipient never presses, on a world no bundle produced.
    """
    passphrase = "correct horse"
    bundle = _sealed_bundle(tmp_path, passphrase)

    with _static_server() as origin:
        with _chrome(origin) as (page, errors):
            _open_sealed_bundle(page, origin, bundle)
            page.locator("#pp-input").fill(passphrase)
            page.locator("#btn-unlock").click()
            page.wait_for_timeout(2500)

            page.locator("#g .garden-lattice-row").first.wait_for(
                state="attached", timeout=15000,
            )
            assert _painted_glyph_count(page) > 0, (
                "the authenticated Garden painted nothing"
            )
            # The passphrase was accepted: the prompt is gone and its error is
            # not showing. Asserting the letter body would test the reading
            # surface, which is a different gate from this one.
            assert not page.locator("#pp-err.on").count(), "the passphrase was refused"
            _assert_no_action_chrome(page)
        assert errors == [], errors


def test_a_wrong_passphrase_reveals_nothing_and_opens_no_garden(tmp_path):
    """Failure must not expose what success would have shown."""
    bundle = _sealed_bundle(tmp_path, "correct horse")

    with _static_server() as origin:
        with _chrome(origin) as (page, errors):
            _open_sealed_bundle(page, origin, bundle)
            page.locator("#pp-input").fill("not the passphrase")
            page.locator("#btn-unlock").click()
            page.wait_for_timeout(1500)

            body = page.locator("body").inner_text()
            assert "Open today" not in body, "a wrong passphrase leaked the letter label"
            assert "waiting to deliver" not in body, "a wrong passphrase leaked the body"
            # The Garden legitimately stays on screen -- it was already there
            # before authentication, and hiding it would punish a typo. What
            # must not happen is the letter becoming readable.
            assert page.locator("#pp-err.on").count(), "a wrong passphrase was not refused"
        assert errors == [], errors
