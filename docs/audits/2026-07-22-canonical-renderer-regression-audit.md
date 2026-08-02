# Canonical browser Garden regression audit — 2026-07-22

## Scope and rules

This audit compares the last pre-removal browser Garden at `526ab9e` with the
replacement introduced by `520f27b`, every Garden-related change on the local
line through `d9e14bf`, and the remote-only changes discovered on 2026-07-22.
No branch or worktree was created or checked out. No `git restore` or checkout
operation was used. Personal letter plaintext and quarantined bundles were not
opened or decrypted.

## Exact history

| Commit/ref | What happened | Product consequence |
|---|---|---|
| `526ab9e` | Last parent before renderer replacement. Browser still contained `GardenVisualState`, `BackgroundLayer`, `PlantLayer`, `ParticleLayer`, `CreatureLayer`, `SpecialLayer`, `GardenDOM`, and `GardenEngine`. | Rich Garden presentation remained visible, but it duplicated generation, collision, animation, and hit-test ownership beside the canonical world. |
| `520f27b` | `viewer-bnw.html`: 93 insertions, 1,464 deletions. Added `web/garden-renderer.mjs`, atlas and sky adapters, and terminal renderer work. | Correctly removed duplicate world ownership; incorrectly removed the historical presentation implementation before its replacement existed. This history fact is not an operator-acceptance claim. |
| `f7ce660` | Corrected demo animal references. | No restoration of visual layers. |
| `7133771` | Added 5,535 lines and removed 634 across canonical world, authoring, materialization, runtime, renderers, and tests. | Canonical semantics became substantially more complete; browser presentation remained sparse and control-heavy. |
| `9ac1827` | Added the synthetic `/to-chloe → to-a-friend` route alias. | Created the separate recipient-route defect; no Garden visual repair. |
| `d9e14bf` | Recorded deployment/billing/branch state. | Local `main` at audit start. |
| remote `4cdebbb` | Centered newly generated camera state and gated the semantic panel, but also restored a `to-chloe.lateletter` bundle without the required local copy-approval process. | Camera/panel ideas are valuable and must be implemented manually; the bundle must not be imported or decrypted. |
| remote `ca39436` | Adjusted tests for the remote camera/route changes. | Proxy coverage only; no rich presentation. |
| remote `700c854` | Merged the two remote commits into GitHub `main`. | Remote and local `main` diverged while this audit was running. |
| remote `7b9389d` (`legacy-garden`) | Unrelated root snapshot containing a pre-rewrite working tree plus a plaintext passphrase-bearing source and two related sealed bundles. | Do not merge or copy wholesale. Preserve only its one unique safe code artifact, then delete the contaminated branch after local acceptance. |

## Deleted presentation inventory

| Deleted feature | Pre-removal owner | Canonical data that must now drive it |
|---|---|---|
| Day, evening, and night palettes | `C`, `NIGHT_PALETTE`, `_applyNightPalette`, `GardenDOM.setGroundBg` | `projection.scene.palette`, `story_time`, `weather`, and canonical sky resolution |
| Deterministic stars and moon phases | `BackgroundLayer`, `MOON_ART`, `_moonPhase` | Canonical star catalog, sky mode, effective time, and coarse privacy-preserving location |
| Pine, oak, bush, flowers, grass, mushrooms, ferns, willow and seasonal weighting | Local plant generators and `genLayout` | Canonical plant species, stable positions, visible topology, maturity stages, and atlas presentation profile |
| Autumn recoloring, winter ground cover, spring/summer vegetation | `applyAutumn`, `SEASON_W`, `PlantLayer` | Canonical season/scene plus atlas palette tokens |
| Wind sway, canopy shimmer, hover rustle | `PlantLayer`, `rustleChar`, cursor state | Effective time, presentation-only wind phase, canonical organ cells, actual pointer location |
| Rain, snow accumulation, leaf fall, fragments and splashes | `ParticleLayer` | Canonical weather/season, object render cells, and presentation-only bounded particles |
| Click leaf/needle bursts | `ParticleLayer.spawnAt` and renderer-local collision map | Canonical raster hit target and selected projection object |
| Butterflies and fireflies | `CreatureLayer` | Canonical season/time and bounded one-cell presentation-only ambient actors |
| Multi-line cat/bird/rabbit/turtle art and tier poses | `_ANIMAL_ART`, `_ANIMAL_POSE_ART`, `CreatureLayer` | Canonical species, bond tier, intent, choreography, personality, memory, and position |
| Feeding reactions and footprints | `_ANIMAL_FEED_GLYPHS`, `_ANIMAL_FOOTPRINTS` | Accepted canonical feed/play command trace and current animal projection |
| Letterbird and bonded delivery choreography | `_LETTERBIRD_FRAMES`, `_ANIMAL_DELIVERY_FRAMES` | Canonical atlas delivery frames already retained |
| Post-completion special tree/perch composition | `SpecialLayer` | Canonical memorial/post-completion scene state |
| Colored cell DOM and partial updates | `ScreenBuffer`, `GardenDOM` | Canonical projection plus renderer-local presentation buffer only |
| Responsive inverse hit testing | `GardenEngine` | Canonical camera/depth transform and projection-owned hotspots |

## Regressions visible in the 2026-07-22 screenshot

- The world is generated in positive coordinates up to `120×80`, while the
  camera defaults to `[0,0]`; the renderer treats the camera as the viewport
  center, leaving most objects below/right of the viewport.
- The dotted line is the replacement renderer's hard-coded horizon.
- Plants initially expose only one visible organ, so a one-cell topology
  renderer produces isolated punctuation rather than a garden composition.
- `showScreen('garden')` forces the full semantic object list open.
- Object-list focus changes `focus_id` but does not frame the selected object.
- The browser provides left/right pan controls but no up/down or frame-content
  control.
- Automated tests assert transforms, byte parity, glyph presence, masks, and
  accessible prose. They do not compare an operator-accepted Garden baseline
  with the new visual surface.

## Ownership rule for the repair

The archive is historical feature/component evidence only, not a whole-scene
quality baseline. Production keeps
one authoritative world in `web/garden-world.mjs` / Python world modules and
one browser presentation owner in `web/garden-renderer.mjs`. Cosmetic wind,
particles, hover response, and animation frames may be renderer-local because
they cannot change commands, world state, schedules, persistence, hit targets,
or authored outcomes.

## Orphan branch value and safety audit

The `legacy-garden` root snapshot contains 89 paths. Every path also exists in
the in-lineage pre-removal tree at `526ab9e`; its two question-bank paths and
all but six differing blobs remain reachable from current `main` history. Of
the six unique blobs, only the older `viewer-bnw.html` is safe, unique code.
The unique plaintext source, two related bundles, and passcode-bearing README
remain excluded. The exact safe viewer is preserved with its source blob ID
under `archive/legacy-garden-7b9389d/`.

After operator clarification that “legacy” means the complete runnable
codebase state rather than the unique viewer alone, a sanitized full snapshot
is also preserved under `archive/legacy-repo-7b9389d/`: 85 paths match the
orphan commit byte-for-byte, while three explicitly synthetic compatible v1
artifacts replace the excluded source/bundles and archive-owned provenance
documents the boundary. The orphan branch is still never merged.

## Manual reconstruction result

The repair did not restore or import the old `GardenEngine`. The rejected
`GROUND_DEPTH_SCALE`/bottom-strip owner was deleted before its replacement. It
rebuilt the following as disposable projection layers inside the sole current
renderer:

- day/evening/night and seasonal palettes, a responsive 4–22-row garden band, the
  canonical privacy-preserving sky, and phase-aware moon art;
- colored multi-line plant silhouettes selected by canonical species and
  maturity, overlaid with canonical visible topology;
- multi-line fixtures while repainting every projection-owned footprint cell;
- four multi-line animal species driven by canonical bond tier marks, intent,
  choreography and memory, including absence footprints and exact-ID feed feedback;
- collectibles, butterflies/fireflies, rain, snow accumulation,
  autumn leaves, hover motion and object-sensitive click fragments;
- memorial composition, per-object depth, projection-hotspot hit testing,
  partial row updates, and presentation-only reduced motion.

The initial canonical world is now a curated composition rather than a catalog
showroom: 10 starter fixtures, 8 starter plants, 4 relationship animals, and 3
collectibles. The complete catalogs remain available to placement, author
programs, reducers, both renderers, and exhaustive tests; they are simply not
all dumped into every new Garden. Starter plants begin visibly established but
retain unborn topology, so subsequent care and elapsed time still produce real
persistent growth.

Canonical initial generation now centers the shared camera on fixture content
in both Python and JavaScript. A persisted pre-fix corner camera is moved only
by dispatching a canonical `pan` command. Object-list focus and the explicit
frame command also pan canonically; the renderer never substitutes a private
camera.

## Twenty-one-finding re-verification matrix

| # | Correction in the current canonical renderer | Direct evidence |
|---|---|---|
| 1 | Deleted the rejected `GROUND_DEPTH_SCALE` projection; responsive composition uses a 4–22-row band. | Source absence assertion plus compact/medium/full layout tests. |
| 2 | The garden band expands to 42% of viewport rows (bounded at 22) and is no longer a six-row bottom strip; the storybook night sky also uses a deterministic dense field rather than three isolated points. | Direct profile/sky-density tests; repeat localhost review pending. |
| 3 | New worlds use a curated 10-fixture starter set; all 22 remain placeable and functional. | 1,000 deterministic safe-layout seeds plus exhaustive full-catalog verb tests. |
| 4 | Deterministic visual packing exhausts the presentation band and culls a unit rather than overlapping independent art; members of one projection-owned connected group move together. | Fifty-seed × desktop/narrow zero-overlap contract plus 100-seed diagnostic sweep, culling, and connected-continuity tests. |
| 5 | All thirteen canonical plant species have distinct established silhouettes and overlay projection-owned visible organ geometry. | Complete species uniqueness at compact, medium, and full density plus topology projection tests. |
| 6 | Foliage uses stable per-object, per-row, and per-cell phase cycles; focus accelerates local rustle. | A two-plant runtime sequence holds species equal, rejects synchronized frame sequences, and requires a focused-only adjacent-frame change. |
| 7 | Full-width deterministic ground cover and undergrowth reconnect the composition. | A direct empty-scene raster contract requires both horizon rows to span every column and cover to occupy at least 60% of viewport columns. |
| 8 | Butterflies, fireflies, and winter glints are recognizable bounded one-cell ambience, never roster animals; both the ordinary distant-bird path and memorial perch-bird glyph were removed to avoid impersonating relationship animals. | Direct day/night/winter ambient, ordinary no-impostor, and memorial no-impostor tests. |
| 9 | All four animal species select play/greet/rest/approach/retreat/groom/forage/perform pose families from canonical intent/choreography. | Intent-family and all-species/tier render tests. |
| 10 | Rain splashes at semantic object surfaces, snow caps empty object-surface cells, and autumn leaves originate only at projected plants before settling; ground reactions are counted separately. | Object-present/object-absent weather counters and no-overwrite assertions. |
| 11 | Hover/focus and clicks derive targets from projection-owned hotspots transformed by the same presentation profile/packing offset; feed feedback retains the exact acted-on object ID. | Real `_hoverAt`/`_burstAt` paths, missing-hotspot fail-closed, packed-hotspot selection, same-species exact-target, object-aware burst, and semantic-focus tests. |
| 12 | Collectibles use leaf, sprig, snowflake, acorn, track, feather, flower, and key tokens—never `$`. | All eight canonical identities render through compact/medium/full profiles with exact distinct glyphs and no `$`. |
| 13 | Compact/medium/full presentation LOD is selected responsively without changing world state. | Direct LOD bounds at each profile. |
| 14 | Projection separates pause-aware `effective_time` from canonical civil `observed_time`; the localhost-only review clock suppresses world and receipt persistence and freezes presentation frames. | Python/JS projection conformance, two exact standalone reloads, and an authenticated read→reload→unread receipt replay. |
| 15 | Standalone and recipient HUDs have one author line; the duplicate first-run banner is suppressed. | Viewer contract and live DOM review. |
| 16 | The initial guide explains focus; direct raster selection writes canonical `focus_id` for the already-visible clicked object, while previous/next navigation additionally frames its result through canonical `pan`; both paths mark the object and expose readable object-named actions. All day/evening/night HUD opacity tokens exceed 4.5:1. | Focus marker/navigation and computed contrast contracts plus live bird inspect/feed/play loop. |
| 17 | Raw diagnostics require both an explicit debug query and standalone/development capability; normal recipients cannot opt in. | Viewer authorization contracts plus a live localhost matrix: normal standalone absent, explicit standalone debug present, sealed recipient with the same query absent. |
| 18 | The image label is a bounded class/count summary with at most five inventory names and a remainder count; individual objects and the complete inventory are traversed through their named surfaces instead of one truncated paragraph. | Accessible-summary, large-inventory-bound, and focus-loop tests. |
| 19 | Rejected/accepted projection comments were removed; source describes only current ownership. | Source scan. |
| 20 | Parity documentation calls the presentation a reconstruction and keeps human gates open. | `docs/GARDEN_PARITY.md`. |
| 21 | Tests now exercise composition, LOD, culling, color-only repaint, focus framing, semantic bursts, weather reactions, continuous cover, differentiated ambience, no animal impostors, independent focused plant motion, exhaustive collectible profiles, bounded accessible summaries, continuity, sleep behavior, exact fixed-time reset, tier-specific animal presentation, and computed theme contrast—not only coordinates/glyph presence. | 598 Python and 87 browser-adapter tests pass; human visual approval remains intentionally unclaimed. |

## Verification result

- All seven archived historical files match their source Git blob IDs.
- `python3 -m pytest -q`: 598 passed, 8 pre-existing session-healing warnings.
- `node --test tests/garden_adapters/*.mjs`: 87 passed.
- Independent generation review compared 1,000 complete Python/JavaScript
  starter worlds: all 1,000 canonical states matched exactly and all 8,000
  plants had at least four visible organs plus at least one unborn organ.
- Equal-size localhost comparison rendered the preserved historical and current
  surfaces at 1280×720. The deterministic current standalone review exposed 25
  canonical objects (8 plants, 10 fixtures, 4 animals, 3 collectibles), 23
  nonempty rows, 150 colored spans after focus, no `$`, and no diagnostics.
- Two fresh opens with `garden_review_time=2026-07-22T12:00:00Z` produced exact
  matching Garden HTML, text, and accessible labels. Review mode neither loads
  nor saves persistent world/receipt state and freezes presentation-only
  animation. A trusted-demo read followed by a fresh reload/unlock returned to
  the unread date label, proving receipt isolation through the real UI path.
- Pointer control framing, object-list focus, bench inspection, and keyboard
  panning all produced accepted canonical results. A separate CDP-backed
  layout viewport measured an actual 390×844 CSS pixels at DPR 2: the Garden
  had no horizontal overflow, the HUD remained inside a 360-pixel content
  width, and every visible focused-object control retained a 44-pixel minimum
  dimension. Pointer activation selected hydrangea and the document keyboard
  `]` binding moved hydrangea → water lily through the canonical command path.
  The same desktop pointer path selected hydrangea, then keyboard and a real HUD
  button moved focus through water lily → willow. The in-app browser
  does not expose native touch dispatch, so this is narrow-layout and
  pointer/keyboard evidence, not a physical-device touch acceptance claim.

The completion audit reopened packing, browser target ownership, and animal-tier
consumption after this table was first written. Their machine-addressable
corrections and focused regressions pass locally. Product acceptance remains
open: operator visual sign-off,
supported-device screenshots, assistive-technology observation, and published
normal-bundle replay remain acceptance gates. Nothing was promoted.

## Remote-main reconciliation

The safe archive, renderer repair, and audit commits were rebased directly onto
remote `main` without a feature branch, worktree, restore, or wholesale orphan
merge. Conflict resolution retained the bounded content-centered camera,
removed the obsolete route-alias owner, kept the Garden drawer opt-in and
closable, and removed the compromised `public_letters/to-chloe.lateletter`.
Post-rebase verification passed 593 Python tests, 53 browser adapter tests, the
release verifier, and the local Pages closure. The local server returns 200 for
the root, `to-a-friend`, and renderer module and 404 for `to-chloe`. No push or
deployment occurred; the result remains local pending operator localhost
review.
