# Recipient Garden current review package

Captured: 2026-08-10 JST / 2026-08-09 UTC

Status: CANDIDATE-ONLY, PARTIAL evidence; operator visual acceptance not granted

Map: `Wayfinder map: the whole recipient Garden, nested under product E2E (2026-08-10)`

Child: `Wayfinder child: capture the current whole-Garden acceptance surface (2026-08-10)`

## Exact capture state

- Commit: `63edfb532ef38dfbc9ec895bb01f03f2b63bdddc`
- Worktree: dirty before and during capture; full porcelain state is embedded in `receipt.json`.
- Bundle: temporary version-2 `.lateletter`, written outside the worktree by `lateletter.author_service.write_bundle_file`.
- Bundle SHA-256: `6dd138661daf11d4afab7abc7e9552e5b97e3a6f64000dad4555ea391de52a99`.
- Bundle content: one due encrypted letter, canonical encrypted Garden program, no authored events, no animals.
- Product route: visible file upload → visible passphrase form → archive/reading → Garden. The passphrase is intentionally absent from the receipt.
- Viewports: desktop 1400x950, desktop resize 1000x700, mobile/touch 390x844.
- Canonical provenance: generated fresh world, generator/composition version 5, one rose, six fixtures, no animals, no collectibles.

The localhost `window.__gardenReview` accessor was used only to read canonical camera, focus, provenance and fixture state after ordinary product actions. It dispatched no commands and changed no state.

## What the package demonstrates

| Surface | Desktop | Mobile | Result |
|---|---|---|---|
| Authenticated sealed bundle | visible upload + unlock | visible upload + unlock | reached |
| Archive and due letter | captured | captured | reached |
| Live Garden motion | 10/10 distinct DOM samples | 10/10 distinct DOM samples | stale “mobile motionless” note falsified for this state |
| Pan | keyboard `d,d,s`: camera `[83,55]→[85,75]` | touch drag: `[83,55]→[102,55]` | canonical camera changed |
| Primary interaction | pointer opened mailbox | touch opened mailbox | fixture count/state changed |
| Keyboard focus + Enter | mailbox→planter, then tend | same automation at mobile viewport | canonical focus and fixture state changed |
| Resize | 1400x950→1000x700 | native 390x844 capture | composition repainted without page/runtime errors |
| Persistence | camera + mailbox/planter state survived reopen | same | authenticated persistence demonstrated |
| Journal/inventory | `j` caused no visible screen/control change | same | dispatch exists; product surface is absent |
| Season/weather change | not run | not run | no ordinary recipient control exists; current summer-evening state only |

The desktop session emitted one generic resource-404 console line while the response ledger recorded no non-favicon bad response. Mobile recorded no console/page/response errors. Treat the desktop line as a disclosed diagnostic, not as acceptance evidence.

## Current mismatches exposed by the package

1. **Journal and inventory are still invisible.** Before and after `j`, the active-screen set is empty and the only visible HUD control is `letters`. No journal or inventory view appears.
2. **Projection opportunities have no product control.** The Lantern exposes `Light the lantern` as a canonical opportunity, but no opportunity button appears; the only HUD control remains `letters`.
3. **Two painted objects have no primary action.** The pond and the rose expose neither a primary action nor an opportunity. A finger can act on the mailbox but cannot act on those objects.
4. **The accepted-versus-candidate picture is mixed.** The paint manifest contains 15 unique accepted asset IDs and six review-candidate IDs. This captured seed visibly uses three candidates: `fixture.stepping_stones_five`, `fixture.planter_three`, and `fixture.pond_compact`. Their implementation does not grant operator acceptance.
5. **The review-verdict composition note is stale.** It describes a current two-plant/five-fixture starter; canonical provenance in both captures is one plant/six fixtures.
6. **The default world cannot exercise animal or collectible verbs.** It has zero animals and zero collectibles, so feed/play/collect and their persistence remain unproven by this package.
7. **Weather/season transitions remain uncaptured.** The product offers no ordinary recipient control to force a transition, and this bounded run saw only summer evening.
8. **The tracked demo remains unusable for this route.** README's documented `garden` password fails the tracked v2 bundle's HMAC. This package therefore used a temporary canonical-service bundle and does not close the known-password demo child.

## Artifact guide

For each viewport:

- `01-authenticated-initial.png` — initial current Garden.
- `02-archive.png` — authenticated archive through the visible letters control.
- `03-reading.png` — due letter through the archive.
- `04-primary-interaction.png` — after mailbox pointer/touch action.
- `05-pan.png` — after canonical keyboard/touch pan.
- `06-keyboard-focus-enter.png` — after spatial focus and primary action.
- `07-journal-key.png` — diagnostic still showing no visible journal transition.
- `09-reopen.png` — reopened authenticated world with persisted state.
- Desktop additionally has `08-resize-1000x700.png`.
- `*-session.webm` — full headed-equivalent browser session recording at exact viewport dimensions and 25 fps.
- `receipt.json` — hashes, dirty state, source refs, bundle lineage, canonical before/after state and accepted/candidate registers.

Two earlier harness failures are preserved in sibling directories
`garden-acceptance-2026-08-10-attempt-01-failed` and
`garden-acceptance-2026-08-10-attempt-02-failed`. They used a Playwright role
locator that excluded the otherwise visible letters button; the final package
uses the concrete visible HUD button and does not bypass product navigation.

## Frontier enabled by this package

The interaction child is now sharp enough for operator vocabulary decisions:

- whether canonical opportunities become beside-object controls;
- how journal/inventory become visible without a generic action sheet;
- whether pond/plant receive a primary action or are explicitly non-interactive;
- which touch-visible control treatment is acceptable.

The six seeded variants still require a dedicated multi-seed operator review. This package exposes only three of them and cannot grant a verdict. Product E2E remains open until an approved author path produces the same sealed artifact used by the accepted recipient journey.
