# LateLetter product implementation status — 2026-07-26

This is an evidence audit of the dirty local checkout at `main` / `b274797`.
It is not a completion or acceptance report. Nothing in this report authorizes
a commit, push, deploy, deletion, or real personal letter.

> **Successor note — 2026-08-10:** This dated audit remains historical evidence.
> Its missing-browser-module finding is resolved in the current checkout:
> `web/author-app.mjs` now drives the operator-approved five-stage questionnaire
> through `author_service.py`, and focused Chromium E2E exports and opens a real
> bundle. Dedicated corpus/API tests also exist. Recipient-viewer traversal,
> phone and assistive-technology review, append-later, handoff shipping, Garden
> capture verdicts and whole-product operator acceptance remain open.

## Executive truth

LateLetter is intended to let an author create encrypted, scheduled letters
that a recipient receives as one `.lateletter` file. The recipient opens the
file in an HTML viewer, enters a separately shared passphrase, lives with a
persistent Garden, and reads letters as they become available.

The current checkout does **not** provide that complete HTML product:

- The recipient HTML can load, authenticate, decrypt, schedule, display, and
  persist a bundle.
- The recipient letter body uses the vendored PreText library again, including
  measured wrapping, justification, and visible blank paragraph rows.
- The canonical Garden world, reducer, persistence, programs, actions, and
  most presentation systems exist.
- The Garden's current visual composition is still rejected and has no
  operator-approved motion package.
- The separate author page is an inert HTML shell. Its only application module,
  `web/author-app.mjs`, does not exist, so all seven stages remain hidden.
- The Python author service and loopback HTTP adapter work internally, but
  there is no usable HTML author flow over them.
- The Garden is **not rendered by PreText**. `CanonicalGardenRenderer` paints
  the two-dimensional scene. PreText supplies the letter line breaker and a
  measured character-cell geometry path. A literal requirement that the whole
  Garden be implemented “in PreText” is not satisfied.

The product is therefore **not ready for a real friend letter**.

## Where the latest work left off

- Git: `main` at `b274797`, equal to `origin/main`, with a large dirty
  worktree. No new commit, push, or deploy was made during this audit.
- Vendored PreText is tracked in history (`baa7dde`) and is reachable from the
  current recipient bundle.
- The complete test run reached 633 Python passes and the four browser Garden
  adapter files reached 93 passes before a later disputed starter-catalog
  mutation. The exact current source state is red: 628 Python passes / 5
  failures and 82 browser Garden passes / 11 failures. The focused author
  service/command adapter run remains 26/26.
- The saved Garden stills are diagnostic, not accepted:
  - `root-after/garden-regression-final-desktop-motion-900x912.jpg`
  - `root-after/garden-regression-final-narrow-motion-390x844.jpg`
- The saved author checkpoint proves the current user-visible break:
  - `root-after/author-partial-shell-missing-module-900x912.jpg`
- A synthetic recipient letter was opened through the real reader and its
  PreText body was inspected:
  - `root-after/letter-narrow-reading-after-fresh-origin.png`
- Pages packaging succeeds and intentionally excludes `author.html` and
  `web/author-app.mjs`.

## Product surfaces and ownership verdict

| Owner / artifact | Actual responsibility | Verdict | Evidence |
|---|---|---|---|
| `viewer-bnw.html` | Recipient file loading, authentication, Garden host, archive, reading | **KEEP / REPAIR IN PLACE** | It is the only live recipient surface and completes the synthetic recipient flow. Do not add author mode to it. |
| `web/garden-world.mjs` | Browser canonical world/reducer/projection | **KEEP / RECONCILE** | Real semantic owner, but its starter declarations changed during a disputed read-only audit and require cross-runtime conformance. |
| `web/garden-runtime.mjs` | Browser persistence, command serialization, program execution | **KEEP** | Covered by combined browser tests and recipient flow. |
| `web/garden-renderer.mjs` | Live HTML Garden art, layout, weather, animation, hit regions | **REBUILD IN PLACE** | It is the one live presentation owner, but the operator rejected its composition. Replacing it must not leave a second renderer alive. |
| `web/vendor/pretext/**` | Offline measured text layout | **KEEP** | Tracked vendored library; recipient letter rendering uses it. |
| `author.html` | Intended separate author-only shell | **REBUILD / COMPLETE** | Seven stages exist in markup but none can become visible without the missing module. |
| `web/author-app.mjs` | Intended author browser controller | **MISSING** | Referenced by `author.html` and static allow-list; absent on disk; HTTP 404. |
| `src/lateletter/author_service.py` | Canonical draft validation, bundle construction, sealing orchestration, round-trip | **KEEP** | Service tests and a real loopback API export/decrypt probe passed. |
| `src/lateletter/author_web.py` | Loopback-only author API/static adapter | **KEEP / TEST MORE** | Real API probe passed; dedicated HTTP contract coverage is still missing. |
| `make_letter.py` and terminal author modules | Private adapter and existing author semantics | **KEEP BUT DEFER AS PRODUCT SURFACE** | They remain semantic/back-end support; terminal UX is not an acceptance surface until HTML is complete. |
| `#garden-controls` in `viewer-bnw.html` | Recipient-world placement/diagnostic panel | **DECISION REQUIRED** | It existed since `ff13aee`, was not deleted by `520f27b`, and is now hidden behind `?garden_debug=1`. It edits recipient state, not bundle authoring. |
| `ascii-animations/**` | Visual-language prototypes | **REFERENCE ONLY** | Runnable prototypes for birds, butterflies, fireflies, rain, snow, clouds, leaves, and letter delivery; not the live HTML Garden. |
| `archive/**` | Preserved historical implementations and evidence | **ARCHIVE-ONLY** | Do not ship or count as current implementation. The old working bird vocabulary is recoverable here. |
| `dumpster/**` | Deleted/obsolete historical material | **ARCHIVE-ONLY** | Not a live owner and must not be reintroduced wholesale. |

No further deletion is supported by the evidence at this point. The broken
author shell and rejected renderer are current ownership locations to repair,
not parallel owners to replace while leaving them alive.

## Intended author flow

The complete author experience should be a separate local HTML application:

1. Start a new draft or resume the locally stored draft.
2. Enter author name/relationship, recipient name/relationship, timezone,
   passphrase hint, and Garden seed.
3. Answer, skip, or add guided questions.
4. Add one or more letters.
5. For each letter, choose the readable date, recipient-visible label, and
   body.
6. See the body through the same vendored PreText measurement/line-breaking
   path the recipient will use.
7. Choose the authored Garden contents and relationship animal.
8. Optionally author the Garden timeline/program: scheduled changes,
   conditions, recurrence, letter presentation, and story events.
9. Review the complete draft and resolve validation errors.
10. Enter and confirm the passphrase only at export time.
11. Send the draft to the loopback Python service; receive canonical sealed
    `.lateletter` bytes.
12. Download the file and separately share its passphrase.
13. Resume later without the passphrase ever being persisted.
14. Append new letters to an existing bundle with the specified backup and
    migration behavior.

### What exists for authors

- Python intake, question selection, Q&A, draft editing, session resumption,
  bundle, sealing, Garden program, scheduling, and append-related modules.
- A canonical `author_service.py` with validation and export.
- A loopback `author_web.py` API with session, validate, and export endpoints.
- An author HTML shell containing the intended seven visual stages.

### What is missing or broken for authors

- `web/author-app.mjs` does not exist.
- No author stage is visible or interactive.
- No HTML autosave/resume flow has run.
- No author PreText preview has run.
- No visual Garden author preview has run.
- No browser validation or download has run.
- No exported browser-authored bundle has been opened in the recipient viewer.
- Append is not represented in the current author HTML shell.
- Dedicated HTTP-layer automated coverage is missing.
- `SessionStore` attempts to chmod an unowned parent when given some explicit
  test directories.

## Recipient flow end to end

The live recipient flow is:

1. Open `viewer-bnw.html`.
2. Drop/select a `.lateletter`, use a packaged public-letter route, or choose a
   trusted local demo.
3. Parse the bundle and validate its version, identity shape, signature/checksum
   boundary, and cryptographic parameters.
4. Open a non-authenticated preview Garden that contains no decrypted author
   prose or authored relationship-animal roster.
5. Choose **open letters**.
6. See the author name and unencrypted passphrase hint.
7. Enter the passphrase.
8. Verify bundle HMAC before announcing or persisting authenticated content.
9. Decrypt each message and the encrypted Garden program.
10. Adopt the authored relationship-animal roster and materialize due Garden
    events into the canonical world.
11. Show the letter archive:
    - future letters remain date-locked;
    - due letters can open;
    - previously read letters retain their label;
    - discovered memories appear separately.
12. On the first read, play a delivery scene using a tier-three bonded animal
    when available, otherwise the letter-bird atlas.
13. Render the letter body through vendored PreText, with browser-native
    wrapping only as a failure fallback.
14. Persist authenticated read receipts, Garden state, program receipts,
    inventory, journal, camera, and relationship progress under a derived
    authentication binding.
15. Return to the Garden and continue tending without punitive absence.

### Recipient verification status

- Synthetic file load, passphrase unlock, Garden, archive, delivery, and
  reading paths exist.
- The current PreText reader uses computed font and line-height values and
  preserves blank paragraph rows.
- The recipient page remains the recipient page; author code is not embedded
  into it.
- The complete flow has not been rerun from a finished HTML author export,
  because no finished HTML author exists.
- Browser/device/accessibility coverage is incomplete: no Safari, Firefox,
  physical iOS/Android, VoiceOver/NVDA, 200% zoom, or no-color acceptance.

## The Garden: actual model and asset inventory

### Canonical systems that exist

- One versioned world state and reducer.
- Viewport-independent world coordinates and a persisted camera.
- Deterministic IDs, program materialization, schedules, idempotency receipts,
  bounded traces, undo, and browser/Python persistence.
- Exact semantic commands from keyboard, pointer, touch, and terminal adapters.
- Persistent plants, fixtures, animals, collectibles, inventory, journal, and
  missed-event summaries.
- Four seasons and day/evening/night scene state.
- Optional coarse sky region, eight moon phases, and a 24-star catalog.

### Plant assets

Thirteen canonical species exist:

1. Oak
2. Pine
3. Willow
4. Rose
5. Hydrangea
6. Ivy
7. Wisteria
8. Meadow grass
9. Lavender
10. Rosemary
11. Tulip
12. Sunflower
13. Water lily

Each plant owns a persistent generated topology with stable organ IDs, one
root, stems/trunks/vines, branches, leaves, buds/blooms, birth/maturity times,
and a predetermined mature form. The seven projected stages are emergent,
sprouting, unfurling, juvenile, developing, near mature, and mature.

Implemented semantic care is observe, water, prune, train, rest, and transplant.
Plants do not die because the recipient was absent.

### Fixture assets

The catalog currently contains 28 IDs. Twenty-two are the intended functional
authorable set:

- Bench
- Fence and gate
- Sundial
- Trellis
- Birdbath
- Lantern
- Pond
- Memory mailbox
- Stepping stones
- Bridge
- Planter
- Table and chairs
- Well
- Arbor
- Wind chime
- Shed edge/tool shed
- Tool rack
- Watering can
- Compost
- Basket
- Sign
- Memorial stone

The six additional IDs are separate/legacy forms (`fence`, `gate`,
`memory_shrine`, `stepping_stone`, `table`, `chair`). They are supported
catalog records but should not be double-counted as six more product concepts.

Fixture state and affordance gates exist: gate routes depend on open state,
birdbath drinking/bathing depends on water, lantern moth affordance depends on
light, and watering depends on the can containing water. Not every promised
visual consequence is painted: the current renderer has no moth presentation.

### Relationship animals

Four canonical species exist:

- Bird
- Cat
- Rabbit
- Turtle

Each has a species-specific repertoire, fixture affinities, weather response,
personality, dwell timing, four bond tiers, memory, authored choreography lock,
and a possible relationship gift. Variety and interaction history affect
bonding; absence does not kill, sicken, shame, or permanently remove animals.

The live renderer has species-specific pose families and delivery fallbacks.
The current product requirement is one resident relationship animal in a new
personal Garden, with other species arriving through authored or earned events.

### Collectibles

Eight canonical collectible identities exist in four families:

- Plant: oak leaf, lavender sprig
- Seasonal: first snowflake, fallen acorn
- Animal trace: rabbit track, bird feather
- Authored keepsake: pressed flower, small key

The renderer now contains purpose-drawn full and compact art for these eight.
The atlas also contains seed-packet and smooth-stone assets, but they are not
canonical collectible identities and remain unsupported leftovers.

### Ambient and weather presentation

Implemented in the live HTML renderer:

- Per-cell plant sway and bounded focus/interaction response
- Relationship-animal pose animation
- Drifting clouds
- Archived multi-cell distant bird flap vocabulary
- Butterflies
- Fireflies
- Winter glints
- Rain with splashes
- Snow with ground/surface accumulation
- Autumn leaves originating from plant regions and settling
- Day/evening/night palette projection
- Stars and moon at night
- Reduced-motion suppression

Not implemented in the live HTML renderer despite prototype/spec references:

- Lightning
- Moths at a lit lantern
- A proven uninterrupted full Garden motion package
- Human-approved composition across all seasons, weather, evening, and night

### Starter-scene truth

The earlier prose claim that the implemented starter is exactly **10 fixtures,
8 plants, 4 animals, and 3 finds** was false as a claim about one clean
canonical starter.

Evidence now distinguishes three states:

1. The rejected phone capture did show a 25-record 10/8/4/3 catalog dump. That
   was rejected visual evidence, not an accepted starter definition.
2. At this audit's start, the dirty browser source declared 5 fixtures,
   8 plants, 1 cat, and 3 collectibles.
3. Python declared 5 fixtures, 5 plants, 1 cat, and 1 collectible.

During a task explicitly contracted as read-only, a concurrent writer changed
the browser source to 5/5/1/1. The lane returned a zero-edit audit and observed
the file mtime advance while it was only publishing its cancellation return;
the exact writer is unidentified. That disputed mutation has not been accepted
as a product decision.

The current failures confirm the mutation is not integrated: Python conformance
still expects bird/rabbit/turtle starter coverage, browser runtime tests expect
15 initial semantic objects but receive 12, and renderer tests lose packed
targets/hotspots needed for interaction, focus, weather, and selection.
The exact starter scene is therefore an **open ownership/conformance defect**,
not a number that can honestly be presented as finished.

The intended starter relationships expressed by current anchors include a
quiet central room (bench, path, mailbox, cat), plus water and trellis anchors
that are not all materialized by the current five-fixture starter. The Garden
cannot be called authored/composed until its chosen starter IDs and its visual
rooms agree.

## Garden visual experience: intended versus current

### Intended recipient experience

- The Garden opens as a warm, legible living place rather than a database
  projection.
- Trees occupy the sky; roots and fixtures rest on a receding ground plane.
- Plants, fixtures, collectibles, and animals are identifiable without labels.
- Related objects form readable rooms: pond/bridge/water lily, trellis/vine,
  bench/path/mailbox/animal.
- Clouds and distant birds cross the sky; plants move independently; animals
  follow routines; insects remain small ambience.
- Weather touches real surfaces without overwriting semantic art.
- A glance is rewarding without action; tending takes one or two meaningful
  actions; dwelling reveals longer interactions.
- Narrow screens show a composed camera slice, not every world record packed
  into one phone viewport.

### Current visual result

- The renderer now paints ground, taller plants, multi-line fixtures and
  animals, clouds, archived birds, and weather reactions.
- DOM text changes over time, proving that a presentation loop runs.
- The desktop still remains sparse above a busy lower band.
- The narrow still remains crowded and difficult to parse.
- Several relationships do not read visually without source labels.
- No accepted GIF/WebM demonstrates continuous traversal, stable scene
  composition, interactions, delivery, and dwell.
- The operator has not approved any current Garden candidate.

Passing raster/count/uniqueness tests does not satisfy that visual gate.

## PreText boundary

What PreText currently owns:

- Offline line analysis and measurement for letter bodies.
- Recipient letter line breaking and justification.
- Blank-line preservation through generated line boxes.
- Character-cell measurement passed into the Garden renderer.

What PreText does not own:

- Garden world state
- Garden layout/composition
- Scene rasterization
- Object art
- Animation
- Weather
- Hit testing
- Animal or plant behavior

Those remain in the canonical Garden world/runtime and
`CanonicalGardenRenderer`. Therefore:

- If “use PreText for all product typography and character-grid measurement”
  is the requirement, the recipient is substantially wired and the author page
  is not.
- If “the whole two-dimensional Garden renderer must be implemented inside the
  PreText library” is the requirement, nothing current satisfies it.

## Implemented/not-implemented matrix

| Product capability | Internal code | User-visible HTML | Visual acceptance |
|---|---:|---:|---:|
| Load signed `.lateletter` | Yes | Yes | Verified synthetically |
| Passphrase/HMAC/decrypt | Yes | Yes | Verified synthetically |
| Scheduled/locked archive | Yes | Yes | Verified synthetically |
| PreText recipient reading | Yes | Yes | Verified desktop/narrow |
| Delivery animation | Yes | Yes | Not accepted as full motion package |
| Persistent Garden reducer/runtime | Yes | Yes | Internal tests pass |
| Plants/fixtures/animals/collectibles | Yes | Yes | Current composition rejected |
| Seasons/day/night/weather | Yes, except live lightning/moths | Partially reachable | Summer/day only directly reviewed |
| Recipient tending/actions | Yes | Partially reachable | Placement/editor disposition unresolved |
| HTML author intake | Back-end semantics exist | No | Broken shell |
| HTML guided Q&A | Back-end semantics exist | No | Broken shell |
| HTML letter editor | Service exists | No | Broken shell |
| Author PreText preview | Intended in shell | No | Missing module |
| HTML Garden authoring | Program service exists | No | Missing module |
| HTML autosave/resume | API exists | No | Missing module |
| HTML validation/export | API exists | No | Missing module |
| HTML append | Python path exists | No shell representation | Missing |
| Author export → recipient E2E | Service probe only | No | Not run |
| Production deployment | Existing recipient packaging only | Author excluded | No new deploy |
| Real friend test letter | Not started | Not applicable | Correctly gated |

## What must happen before a real friend letter

1. Resolve the remaining stalled author-pane ownership and identify the
   concurrent Garden writer before preserving or undoing only the exact
   disputed starter hunk.
2. Choose one canonical starter composition and add Python/browser identity
   conformance.
3. Rebuild the live Garden presentation in place until the operator approves
   desktop, phone, and uninterrupted motion across the required states.
4. Complete `web/author-app.mjs` over the existing Python author service.
5. Add missing author contract/API coverage and fix `SessionStore` ownership of
   explicit directories.
6. Run every author stage at desktop and phone sizes, saving each checkpoint.
7. Export a synthetic bundle from the HTML author and complete the unchanged
   recipient E2E with it.
8. Run the full Python, combined browser, packaging, security, and portability
   checks from the exact source state reviewed visually.
9. Obtain explicit operator approval.
10. Only then draft and export the real letter for the user's friend.
