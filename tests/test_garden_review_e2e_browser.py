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
    """The positive control, kept separate so the defect below is not vacuous.

    Stepping stones is the one fixture whose click currently reaches the world.
    Asserting it here proves the dispatch path exists and works, which is what
    makes "the other four do nothing" a defect in those four rather than a
    broken test.
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


@pytest.mark.xfail(
    strict=True,
    reason=(
        "DEFECT, characterised 2026-08-03 by observing canonical world state "
        "directly instead of any DOM summary. Clicks land on the WRONG OBJECT. "
        "Clicking the stepping stones raises stepping-stones walk_count to 1, "
        "correctly. Clicking the MAILBOX then raises stepping-stones walk_count "
        "to 2. Clicking the lantern and the bench change nothing at all. "
        "Clicking the PLANTER sets the mailbox to open:true. So a click "
        "activates a previously targeted object rather than the one under the "
        "pointer -- hit resolution is reading stale frame geometry, not queuing "
        "a dispatch. This is why three earlier descriptions were wrong: the "
        "accessible summary was reporting a real action on the wrong object, "
        "which looks exactly like a lagging report of the right one. It is also "
        "why no DOM signal could settle it -- the summary is written only when "
        "`syncGardenControlsAvailability()` is truthy, so absence of a change "
        "there is not absence of an action. Left strict: this is the most "
        "serious interaction defect on the board, and it must not be normalised."
    ),
)
def test_clicking_EVERY_accepted_fixture_reaches_the_canonical_world():
    """Each of the five, with a signal that settles before it is read.

    Two things were wrong in the first version. `interaction_count` is not the
    signal -- fixtures track different state per verb -- and a fixed 350ms wait
    read the PREVIOUS click's summary, so every fixture appeared one behind and
    four working objects looked broken.

    This waits for the accessible summary to CHANGE, then checks it names the
    action that was just dispatched. That is the product's own account of what
    it did, polled until it settles.
    """
    with _static_server() as origin:
        with _chrome(origin) as (page, errors):
            _enter_standalone_garden(page, origin, REVIEW_QUERY)
            targets = page.evaluate(
                """() => {
                    const review = window.__gardenReview;
                    return review.state().objects
                      .filter(object => object.id.startsWith('fixture') && object.primary_action)
                      .map(object => ({
                        rect: review.objectRectPixels(object.id),
                        action: object.primary_action.args.fixture_action,
                      }))
                      .filter(row => row.rect);
                }"""
            )
            assert len(targets) == 5, f"expected five clickable fixtures, got {len(targets)}"

            for target in targets:
                previous = _summary(page)
                page.mouse.click(
                    target["rect"]["x"] + target["rect"]["width"] / 2,
                    target["rect"]["y"] + target["rect"]["height"] / 2,
                )
                assert _summary_changes(page, previous), (
                    f"clicking the {target['action']!r} fixture produced no response at all"
                )
                assert _summary(page).lower().startswith(f"used {target['action']}"), (
                    f"clicking the {target['action']!r} fixture reported "
                    f"{_summary(page)[:60]!r} instead"
                )
                _assert_no_action_chrome(page)
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

    assert accepted - in_scene == {
        "fixture.arbor", "fixture.birdbath", "fixture.bridge",
        "fixture.pond", "fixture.trellis",
    }, "the accepted art this review does not cover has changed"


@pytest.mark.xfail(
    strict=True,
    reason=(
        "DEFECT, found by this test on 2026-08-03. At 390x844 two of the five "
        "accepted starter fixtures -- stepping_stones (world x=31) and planter "
        "(x=88) -- have no interaction rectangle at all: they fall outside the "
        "cropped mobile width. Mobile may crop peripheral scenery; it may not "
        "lose reachable interactions. Owned by the interaction-mask step of the "
        "operator route, which gives every interactive asset state a "
        "projection/atlas-owned mask. Left strict so it cannot be normalised "
        "into the baseline, and so that a later correction cannot land silently."
    ),
)
def test_a_single_tap_performs_the_primary_action_on_touch():
    """One tap, not a hover-equivalent first tap and a second to confirm."""
    with _static_server() as origin:
        with _chrome(origin, viewport=MOBILE) as (page, errors):
            _enter_standalone_garden(page, origin, REVIEW_QUERY)
            target = _accepted_fixture_target(page)
            assert target is not None

            def interactions() -> int:
                rows = page.evaluate("() => window.__gardenReview.state().fixtures")
                return next(row["interaction_count"] for row in rows if row["id"] == target["id"])

            before = interactions()
            page.touchscreen.tap(
                target["rect"]["x"] + target["rect"]["width"] / 2,
                target["rect"]["y"] + target["rect"]["height"] / 2,
            )
            page.wait_for_timeout(400)
            assert interactions() == before + 1, "the first tap did not act"
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


def test_the_garden_keeps_moving_without_any_input():
    """It must live on its own, not only when touched.

    Compared as painted text over real elapsed time. `garden_review_time` is
    deliberately NOT used for this one: it freezes disposable motion, which is
    exactly what is being measured.
    """
    with _static_server() as origin:
        with _chrome(origin) as (page, errors):
            _enter_standalone_garden(page, origin, PRODUCT_QUERY)
            first = page.locator("#g").inner_text()
            page.wait_for_timeout(3000)
            second = page.locator("#g").inner_text()
            assert first != second, "the Garden was motionless for three seconds"
        assert errors == [], errors


@pytest.mark.xfail(
    strict=True,
    reason=(
        "DEFECT, found by this test on 2026-08-03. At 390x844 the Garden is "
        "motionless AND nearly empty: 6 non-blank rows out of 64, 57 glyphs, and "
        "ONE unique painted-text hash across twelve samples over six seconds. "
        "Four of those six rows are sky holding one or two characters ('..', "
        "'.', '*.', '.'). Desktop over the same window paints 300 glyphs across "
        "58 rows and produces eight distinct hashes. The Garden must visibly "
        "live without input, and mobile may crop peripheral scenery but may not "
        "become a still, empty frame. Left strict so it cannot be normalised "
        "into the baseline, and so that a later correction cannot land silently."
    ),
)
def test_the_garden_keeps_moving_on_mobile_too():
    """Same measurement as the desktop case, at the required phone size."""
    with _static_server() as origin:
        with _chrome(origin, viewport=MOBILE) as (page, errors):
            _enter_standalone_garden(page, origin, PRODUCT_QUERY)
            page.wait_for_timeout(1500)
            first = page.locator("#g").inner_text()
            page.wait_for_timeout(3000)
            second = page.locator("#g").inner_text()
            assert first != second, "the mobile Garden was motionless for three seconds"
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


@pytest.mark.xfail(
    strict=True,
    reason=(
        "DEFECT, found by this test on 2026-08-03. At midday the painted text is "
        "BYTE-IDENTICAL across spring, summer and winter -- desktop hash "
        "770ad5a5d909ec70 for both spring and winter, and one shared mobile hash "
        "3ac79ca42f5e65db for all three. Only autumn differs. Time of day does "
        "read differently, but season does not, and the destination requires "
        "seasonal weighting, plant colouring, weather and ambience to visibly "
        "change across all four. Seasonal plant colouring and weather are art "
        "and recipes that carry no verdict, so nothing is invented here to make "
        "this hold. Left strict so it cannot be normalised into the baseline, "
        "and so that a later correction cannot land silently."
    ),
)
def test_the_four_seasons_are_visually_distinct():
    """Four seasons at the same hour must not paint the same picture."""
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
