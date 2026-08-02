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
        "MEASUREMENT DEFECT IN THIS TEST, corrected 2026-08-03, and left failing "
        "until it is rewritten. Clicking DOES reach the canonical world for more "
        "than stepping stones: the mailbox click produces 'Used open at Memory "
        "mailbox' in the accessible summary, with a journal entry and a focus "
        "move. Two things were wrong here. `interaction_count` is not the signal "
        "-- fixtures track different state per verb -- and the accessible summary "
        "updates asynchronously, so a 500ms wait reads the PREVIOUS click's "
        "result and every fixture looks one behind. Kept strict and failing "
        "rather than deleted, because a defect I recorded wrongly must not vanish "
        "quietly; it needs a signal that settles before it is read. The original, "
        "incorrect text follows.\n\n"
        "DEFECT, found by this test on 2026-08-03, and hidden until it was "
        "written. Only ONE of the five accepted starter fixtures responds to a "
        "click: stepping stones ('walk') raises its canonical interaction count, "
        "while mailbox ('open'), lantern ('observe'), bench ('sit') and planter "
        "('tend') all stay at zero. An earlier version of this test used "
        "`.find(...)`, exercised whichever fixture came first -- the one that "
        "works -- and reported that clicking worked. Four accepted, declared, "
        "visible objects cannot be operated by a pointer. Left strict so it "
        "cannot be normalised into the baseline, and so that a later correction "
        "cannot land silently."
    ),
)
def test_clicking_EVERY_accepted_fixture_performs_its_canonical_primary_action():
    """Each fixture in the scene, not one of them.

    Each declares a DIFFERENT primary action -- sit, open, observe, walk, tend --
    so one passing says nothing about the others. Every one is clicked here and
    its own count checked, and the set of actions reached is asserted so a
    fixture cannot quietly stop declaring one.
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
                        id: object.id,
                        rect: review.objectRectPixels(object.id),
                        primary: object.primary_action,
                      }))
                      .filter(row => row.rect);
                }"""
            )
            assert len(targets) == 5, (
                f"expected all five starter fixtures to be clickable, got {len(targets)}"
            )

            def interactions(object_id: str) -> int:
                rows = page.evaluate("() => window.__gardenReview.state().fixtures")
                return next(row["interaction_count"] for row in rows if row["id"] == object_id)

            reached = set()
            for target in targets:
                before = interactions(target["id"])
                page.mouse.click(
                    target["rect"]["x"] + target["rect"]["width"] / 2,
                    target["rect"]["y"] + target["rect"]["height"] / 2,
                )
                page.wait_for_timeout(350)
                assert interactions(target["id"]) == before + 1, (
                    f"clicking {target['primary']['label']!r} did not reach the canonical world"
                )
                reached.add(target["primary"]["args"]["fixture_action"])
                # The rejected chrome used to appear as a RESULT of interacting,
                # so it is re-checked after each one rather than once at the end.
                _assert_no_action_chrome(page)

            assert reached == {"sit", "open", "observe", "walk", "tend"}, (
                f"the five fixtures no longer declare five distinct actions: {sorted(reached)}"
            )
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


@pytest.mark.xfail(
    strict=True,
    reason=(
        "MEASUREMENT DEFECT IN THIS TEST, corrected 2026-08-03, and left failing "
        "until it is rewritten. `objectRectPixels` reports the canonical HOTSPOT, "
        "and hit testing expands that through `expandTarget` to "
        "`MINIMUM_TARGET_PX` before deciding what a pointer touched -- so the "
        "44px floor IS applied where it matters, and this test was measuring the "
        "wrong rectangle. What remains genuinely unproven is whether the EXPANDED "
        "target is reachable, which needs a hit probe rather than a rectangle "
        "read. Kept strict and failing rather than deleted, because a defect I "
        "recorded wrongly must not vanish quietly; it is superseded, not cleared. "
        "The original, incorrect text follows.\n\n"
        "DEFECT, found by this test on 2026-08-03. Every interaction rectangle "
        "the product produces is the raw cell rect -- measured at 11x13 CSS "
        "pixels for a one-cell fixture and 22x13 for a two-cell one -- against a "
        "44px floor that SPEC 7.2 already states and that MINIMUM_TARGET_PX in "
        "web/garden-geometry.mjs already defines. Nothing enlarges them. Two of "
        "the five accepted fixtures have no rectangle at all on mobile, which is "
        "the separate defect above. Owned by the interaction-mask step of the "
        "operator route; enlarging a hotspot to the floor is explicitly "
        "permitted there and requires no new art. Left strict so it cannot be "
        "normalised into the baseline, and so that a later correction cannot "
        "land silently."
    ),
)
def test_every_interactive_target_meets_the_44px_minimum():
    """A target below the floor is present but not reachable by a fingertip."""
    with _static_server() as origin:
        with _chrome(origin, viewport=MOBILE) as (page, errors):
            _enter_standalone_garden(page, origin, REVIEW_QUERY)
            rects = page.evaluate(
                """() => window.__gardenReview.state().objects
                    .filter(object => object.primary_action)
                    .map(object => ({
                      id: object.id, rect: window.__gardenReview.objectRectPixels(object.id),
                    }))"""
            )
            assert rects, "no interactive object was projected"
            for row in rects:
                assert row["rect"] is not None, f"{row['id']} has no interaction rectangle"
                assert row["rect"]["width"] >= 44 and row["rect"]["height"] >= 44, (
                    f"{row['id']} is {row['rect']['width']}x{row['rect']['height']}px"
                )
        assert errors == [], errors


def test_hovering_accepted_ink_marks_it_interactive_without_saying_a_word():
    """The half that holds: the cursor tells you the ink can be touched.

    Checked separately from the picture-change half below, because they are two
    different promises and one of them is currently kept.
    """
    with _static_server() as origin:
        with _chrome(origin) as (page, errors):
            _enter_standalone_garden(page, origin, REVIEW_QUERY)
            target = _accepted_fixture_target(page)
            assert target is not None

            page.mouse.move(5, 5)
            page.wait_for_timeout(300)
            assert page.evaluate(
                "() => getComputedStyle(document.getElementById('g')).cursor"
            ) == "default"

            page.mouse.move(
                target["rect"]["x"] + target["rect"]["width"] / 2,
                target["rect"]["y"] + target["rect"]["height"] / 2,
            )
            page.wait_for_timeout(400)
            assert page.evaluate(
                "() => getComputedStyle(document.getElementById('g')).cursor"
            ) == "pointer", "hovering interactive ink did not mark it interactive"

            # And it says nothing while doing so: no tooltip, no label, no card.
            # The rejected implementation answered hover by printing an
            # instruction, which is the thing that must not come back.
            _assert_no_action_chrome(page)
            assert target["primary"]["label"] not in page.locator("#g").inner_text(), (
                "hovering printed the action label over the picture"
            )
        assert errors == [], errors


@pytest.mark.xfail(
    strict=True,
    reason=(
        "DEFECT, found by this test on 2026-08-03. Hovering an accepted "
        "fixture's ink changes the cursor to `pointer` but does not change the "
        "picture at all: the painted text is byte-identical before and after, "
        "and no element carries a hover or focus class. Measured with "
        "`garden_review_time` freezing ambient motion, so the comparison is the "
        "hover and not the weather. The destination requires hover to change "
        "the picture -- rustle, pose change, emphasis -- and forbids it saying "
        "anything; today it does neither. A pose or emphasis state is new art "
        "and needs its own verdict, so it is NOT invented here. Left strict so "
        "it cannot be normalised into the baseline, and so that a later "
        "correction cannot land silently."
    ),
)
def test_hovering_accepted_ink_changes_the_picture():
    """Hover must change the picture itself, not merely the cursor."""
    with _static_server() as origin:
        with _chrome(origin) as (page, errors):
            _enter_standalone_garden(page, origin, REVIEW_QUERY)
            target = _accepted_fixture_target(page)
            assert target is not None

            page.mouse.move(5, 5)
            page.wait_for_timeout(300)
            before = page.locator("#g").inner_text()

            page.mouse.move(
                target["rect"]["x"] + target["rect"]["width"] / 2,
                target["rect"]["y"] + target["rect"]["height"] / 2,
            )
            page.wait_for_timeout(400)
            assert page.locator("#g").inner_text() != before, (
                f"hovering {target['primary']['label']!r} changed nothing in the picture"
            )
        assert errors == [], errors


@pytest.mark.xfail(
    strict=True,
    reason=(
        "DEFECT, found by this test on 2026-08-03. The Garden picture cannot "
        "take keyboard focus at all: `#g` carries no tabindex, so it is not in "
        "the tab order, and the arrow keys pan the CAMERA rather than moving "
        "canonical focus -- the accessible summary reports 'Panned to 61,51 ... "
        "No object focused'. Enter therefore reaches no primary action and the "
        "canonical interaction count stays at zero. Keyboard-complete play is a "
        "hard accessibility requirement, and spatial focus navigation plus "
        "Enter is the stated contract. Owned by the interaction-mask step, "
        "which is where focus and hit geometry get a single owner. Left strict "
        "so it cannot be normalised into the baseline, and so that a later "
        "correction cannot land silently."
    ),
)
def test_keyboard_focus_and_enter_perform_the_same_primary_action():
    """A person who cannot use a pointer must reach the same single action."""
    with _static_server() as origin:
        with _chrome(origin) as (page, errors):
            _enter_standalone_garden(page, origin, REVIEW_QUERY)

            def totals() -> int:
                rows = page.evaluate("() => window.__gardenReview.state().fixtures")
                return sum(row["interaction_count"] for row in rows)

            before = totals()
            page.locator("#g").focus()
            for _ in range(12):
                page.keyboard.press("ArrowRight")
                page.wait_for_timeout(80)
            page.keyboard.press("Enter")
            page.wait_for_timeout(400)

            assert totals() == before + 1, (
                "keyboard focus and Enter did not reach any canonical primary action"
            )
        assert errors == [], errors


def test_the_garden_is_reachable_at_200_percent_zoom():
    """200% zoom is a required review condition, not an edge case."""
    with _static_server() as origin:
        with _chrome(origin, viewport=(800, 500)) as (page, errors):
            # A 1600x1000 layout viewed at 200% is a 800x500 CSS viewport, which
            # is what a browser zoom actually produces.
            _enter_standalone_garden(page, origin, REVIEW_QUERY)
            assert _painted_glyph_count(page) > 0, "nothing painted at 200% zoom"
            _assert_no_action_chrome(page)
            interactive = page.evaluate(
                """() => window.__gardenReview.state().objects
                    .filter(object => object.primary_action)
                    .filter(object => window.__gardenReview.objectRectPixels(object.id))
                    .length"""
            )
            assert interactive > 0, "no interactive object is reachable at 200% zoom"
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
