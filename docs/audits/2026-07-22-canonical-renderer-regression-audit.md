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
| `520f27b` | `viewer-bnw.html`: 93 insertions, 1,464 deletions. Added `web/garden-renderer.mjs`, atlas and sky adapters, and terminal renderer work. | Correctly removed duplicate world ownership; incorrectly removed the accepted visual product before its replacement existed. |
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
| Butterflies, fireflies and ambient birds | `CreatureLayer` | Canonical season/time and bounded presentation-only ambient actors |
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
  accessible prose. They do not compare the accepted old Garden with the new
  visual surface.

## Ownership rule for the repair

The archive is evidence and a presentation reference only. Production keeps
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
are deliberately excluded. The unique historical failure log is superseded by
the current log. The safe viewer is preserved with its source blob ID under
`archive/legacy-garden-7b9389d/`; the orphan branch must never be merged.

## Manual reconstruction result

The repair did not restore or import the old `GardenEngine`. It rebuilt the
following as disposable projection layers inside the sole current renderer:

- day/evening/night and seasonal palettes, a near-bottom ground plane, the
  canonical privacy-preserving sky, and phase-aware moon art;
- colored multi-line plant silhouettes selected by canonical species and
  maturity, overlaid with canonical visible topology;
- multi-line fixtures while repainting every projection-owned footprint cell;
- four multi-line animal species driven by canonical bond tier, intent,
  choreography and memory, including absence footprints and feed feedback;
- collectibles, ambient birds/butterflies/fireflies, rain, snow accumulation,
  autumn leaves, hover motion and object-sensitive click fragments;
- memorial composition, per-object depth, inverse canonical hit testing,
  partial row updates, and presentation-only reduced motion.

Canonical initial generation now centers the shared camera on fixture content
in both Python and JavaScript. A persisted pre-fix corner camera is moved only
by dispatching a canonical `pan` command. Object-list focus and the explicit
frame command also pan canonically; the renderer never substitutes a private
camera.

## Verification result

- All seven archived historical files match their source Git blob IDs.
- `python3 -m pytest -q`: 593 passed, 8 pre-existing session-healing warnings.
- `node --test tests/garden_adapters/*.mjs`: 53 passed.
- Localhost comparison rendered the archived and reconstructed surfaces in the
  in-app browser. The current surface exposed 39 canonical objects, 232
  colored spans, no forced control drawer, no fake standalone letter button,
  and zero console warnings/errors.
- Pointer control framing, object-list focus, bench inspection, and keyboard
  panning all produced accepted canonical results. The browser's requested
  narrow viewport override remained 1280 pixels internally, so this run does
  not claim new mobile visual acceptance.

The implementation regression is repaired locally. Operator visual sign-off,
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
