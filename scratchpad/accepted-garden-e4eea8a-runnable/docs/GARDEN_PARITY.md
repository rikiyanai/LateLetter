# Garden feature-gap and renderer parity

Verified 2026-07-22 against the normal checksummed, HMAC-authenticated,
encrypted v2 synthetic bundle in `sealed_demo.lateletter`, using the public
demo passphrase `garden-biscuit-2026`.

The controlling finding remains:

> The original Garden was a renderer-backed recipient gift loop, not the
> standalone, author-directed cozy garden promised by §7.8. Terminal and HTML
> letter parity did not establish full Garden parity. The implementation now
> shares canonical world semantics and substantially closes the objective
> feature gaps, but it must not be called “full,” “parity,” or
> “production-ready” until every §7.8.13 gate—including the required human
> gates—passes.

## Feature table

| §7.8 system | Terminal state | HTML state | Same canonical state? | §7.8.13 result |
|---|---|---|---|---|
| Authentication, checksum, and real decryption | HMAC/checksum gate, bounded PBKDF2, AES-GCM; strict raw schema; fixed pre-auth preview; secret-bound receipt/world namespace | Matching v1/v2 HMAC profiles, bounded WebCrypto KDF, AES-GCM; same strict raw schema; epoch-fenced transactional unlock; bfcache plaintext/runtime purge | Yes | Shared nine-boundary adversarial vectors, cancellation regression, production path, and history-restore boundary verified locally |
| Author questions → draft → seal → export/append | Accessible and curses author paths complete; v2 APPEND decrypts and ID-safely merges the prior program | Recipient only | One canonical bundle writer/program schema | Gate 8 PASS by scripted no-JSON author flow and trace tests |
| Author conditions, schedules, recurrence, missed events, and world changes | Encrypted program; fixed-point evaluation; DST gap/fold; visible bounded summaries; conditional letter presentation | Matching parser/evaluator/materializer and visible persisted summary/presented-letter state | Yes—cross-runtime state/effects/trace vectors | Gates 8 and 9 PASS |
| Deterministic world and persistence | Immutable `WorldState`, reducer, pause-aware elapsed clock, separately projected civil observation time, event trace, canonical JSON; bounded 512 command/trace/visit/offline/occurrence histories, aggregate totals, and 128 undo records | Byte-conformant JS world, reducer, both clock fields, trace, persistence with identical bounds/totals; fixed localhost-only review time suppresses world/read/first-run persistence and freezes presentation frames | Yes—golden replay plus 700-command and multi-year restart stress compare exact bytes | Core parity implemented; fixed-time standalone and authenticated receipt resets verified |
| Glance / tend / dwell without a bundle | Standalone Garden, object/action navigation, full care verbs, 30-second dwell and real idle ticks | Standalone entry, semantic controls, real visible live loop, explicit dwell; authenticated schedules re-evaluate during live time | Yes | Gate 3 BLOCKED on required human usefulness observation |
| Touch / mouse / keyboard / terminal input | All canonical commands have discoverable terminal keys/actions | Native controls derive touch/mouse; keyboard bindings route to the same command bytes | Yes at adapter/reducer level | Gate 2 PARTIAL until every visible action is physically traversed in every modality |
| Plant care and persistent topology | Water/prune/train/rest/transplant; stable organ IDs; seven named fixed-point maturity stages with gradual geometry; undo; curated starter plants begin established but not fully mature | Same topology/care reducer, stage semantics, interpolated organ geometry, and starter ages | Yes—every stage/restart projection matches exactly | Gate 4 PASS |
| Placement, movement, rotation, and undo | Camera-centered copy/place, move, rotate, transplant, undo | Reader chooses kind, catalog, x/y; move/rotate/undo use canonical validation | Yes | Included in Gate 2 observation work |
| Functional fixtures and connected footprints | State machines and verbs change linked UI, plants, water/resources, inventory/collectibles, or animal memory/routines; full footprints and all 16 masks render | Same linked canonical effects, projected state, footprints, masks, and actions | Yes—every verb/restart effect matches exact bytes | Gate 5 PASS by exhaustive terminal/browser renderer evidence; Gate 6 portability evidence remains partial |
| Collectibles, inventory, and journal | Persistent collect/examine/inventory/journal and authored memories; scrollable inventory/journal/missed-summary panel | Same state and complete journal; browser object-list/action-card surface withdrawn after visual rejection | Partial | Secondary-action keyboard/screen-reader replacement remains open; rejected labels must not return |
| Deterministic animal AI | Four species; safety-first priority, personality/needs, bounded episodic memory, weather/season utility, deterministic validated locomotion/routines, hysteresis, four bond tiers, authored choreography | Same decisions/movement/state; reason, score, context, tier, intent, personality, and memory are visible and semantically described | Yes—decision, position, projection, and restart bytes match | Gate 7 PASS |
| Scene changes and memorial | Weather/palette/story/ambience tokens, bounded absence text, lasting memorial | Same semantic scene, absence, and memorial state | Yes | Gate 13 PASS; emotional sign-off remains Gate 14 |
| Camera, parallax, responsive hit testing, reduced motion | Canonical content-centered camera, per-object depth, and partial row diffs | Same canonical camera, legacy corner-camera migration through `pan`, per-object depth, projection-owned hotspots transformed through the presentation profile/packing offset, measured glyph geometry, saved pause and presentation-only reduced motion | Yes | Gate 10 PARTIAL: reference-device p95 measurements remain |
| Rich presentation reconstruction after `520f27b` regression | Portable atlas glyph projection remains deliberately compact; the same curated starter world contains 10 fixtures, 8 plants, 4 animals, and 3 collectibles | Responsive 4–22-row read-only compositor with bounded LOD, deterministic independent-unit no-overlap packing, per-cell plant motion, complete animal intent families and four visible projected bond tiers, distinct canonical-species silhouettes at every density, semantic collectibles, continuous cover, civil-time/season palettes, dense storybook night sky, differentiated ambient life, semantic-surface weather reactions, exact-ID focus/click/feed effects, and memorial art without an unprojected animal | Yes—presentation consumes the same projection and never owns gameplay/target/persistence state | Machine-addressable completion-audit corrections pass locally; operator visual acceptance, physical-device touch, and the supported screenshot matrix remain open |
| Versioned Unicode/ASCII atlas | Python consumes and validates the canonical atlas manifest, semantic tokens, graphemes, and safe profiles | Browser imports that same manifest directly | Yes—no duplicate glyph owner | Gate 6 PARTIAL: supported screenshot matrix remains |
| Privacy-preserving sky | Shared 24-star JSON catalog, author-region/storybook projection | Imports the same JSON catalog; explicit coarse reader opt-in, denial/fallback, and forget | Yes—12 trusted Alt/Az fixtures within 0.25° | Gate 11 PASS |
| Accessibility | Line-readable state, ordinary-text help, journal/inventory/absence/memorial | Bounded Garden summary/inventory label, semantic per-object descriptions, named action/status region, focusable controls, 44px targets, reduced motion, and theme/HUD normal-text tokens at ≥4.5:1 computed contrast | Same projected facts/actions | Gate 12 PARTIAL: 390×844 and fresh 1280×720 browser layouts passed geometry/overflow/target diagnostics; VoiceOver/NVDA, no-color, physical-device touch, and actual 200% human runs remain |
| Deterministic replay, absence, and ethics | Rollback clamp; 1/7/30/365-day aggregate return; exhaustive manipulative-copy rejection | Matching replay/absence state and parser restrictions | Yes | Gate 13 PASS |
| Normal sealed production bundle | Wrong-pass rejection, exact fictional letter, authored bench/rabbit/plant/keepsake/third-return arc, live dwell | Same exact letter and authored world; transactional unlock; first-click delivery and mobile-width dwell verified | Yes locally | Gate 1 PARTIAL until the pushed Pages deployment is re-run end to end |

## Current gate summary

| Result | Gates |
|---|---|
| **PASS** | 4 Plant stability; 5 Layout safety; 7 Animal behavior; 8 Author control; 9 Temporal correctness; 11 Sky accuracy/privacy; 13 Absence/ethics |
| **PARTIAL** | 1 Published production reachability; 2 physical input traversal; 6 atlas screenshot portability; 10 reference-device performance; 12 assistive-technology observation |
| **BLOCKED on mandatory human evidence** | 3 Standalone value; 14 Human acceptance |

Machine-readable evidence is in `tests/garden_acceptance/gate_matrix.json`.
The direct terminal/browser run is recorded in
`docs/GARDEN_QA_2026-07-21.md`.

Tracked artifacts contain fictional demo copy only. The prior Chloe message
and passphrase remain compromised and are intentionally not reused. A real
Chloe bundle requires newly approved personal wording and a new passphrase.

The table claims **semantic/state parity**, not identical pictures. Terminal is
the portable cell renderer; HTML may provide richer disposable presentation.
Neither renderer may invent positions, growth, actions, animal decisions,
schedules, camera state, persistence, or authored outcomes. The product must
still not be described as a “full,” “standalone parity,” or production Garden
until every §7.8.13 human gate passes on a normal sealed production bundle.
