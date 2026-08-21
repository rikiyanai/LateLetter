---
title: "feat: Richer garden animals - trust behavior + ambient bird art"
type: feat
status: active
date: 2026-04-27
origin: docs/FAILURE_LOG.md [5], [7]
---

# feat: Richer garden animals - trust behavior + ambient bird art

## Overview

This plan closes the two remaining animal-side experiential gaps in the browser garden:

1. The trust-tier relationship animal exists structurally but behaves like a static sprite.
2. The ambient sky bird is still placeholder art (`v` / `~`) and reads weaker than the rest of the creature layer.

The work stays inside the existing browser garden ownership boundary in `viewer-bnw.html`. It does not introduce a second animal system, a second bird renderer, or a second delivery path.

## Problem Frame

The failure log already identifies the core issue: the garden has the data model for animal trust, delivery override, absence traces, and post-completion presence, but the lived experience between trust tiers is too similar to feel earned. In the current runtime:

- Relationship animals render from `_ANIMAL_ART[type][tier]` with no per-tier movement or pose logic.
- Feeding mostly changes counters and art, with only the rabbit getting a temporary carrot overlay.
- Ambient birds are one-character flyovers that look like a stub beside butterflies, weather, and letter delivery.

This is not a schema problem. It is an actor-behavior and presentation problem.

## Requirements Trace

- R1. Each trust tier must be perceptibly different without relying on HUD text.
- R2. Behavioral changes must be implemented on the existing relationship-animal path, not as a second overlay or duplicate renderer.
- R3. Tier progression remains cumulative (`0/3/7/14`) and must not change bundle or persistence schema.
- R4. Feed actions must get immediate visible feedback for all four animals.
- R5. Ambient bird art must be upgraded to a 2-3 char silhouette with a real flap cycle and optional flocking, while staying visually distinct from both the relationship bird and the letter-bird.
- R6. Bonded-animal delivery remains a progression override, not a new ownership path; the same animal type that lives in the garden must be the one that delivers.
- R7. Dev fixture mode must make every animal tier and ambient-bird state QA-able in one session.
- R8. No mixed ownership patches: `CreatureLayer` remains the sole owner of ambient creatures and relationship-animal runtime behavior.

## Scope Boundaries

- Browser viewer only: `viewer-bnw.html`
- No bundle schema change
- No IndexedDB schema change
- No new authoring UI
- No new garden gift type
- No expansion beyond the existing four v1 animals
- No change to the emotional meaning of post-complete

### Deferred

- Python/TUI parity for richer animal behaviors
- New ambient species beyond birds
- Sound, haptics, or notification work
- Multiple simultaneous bonded animals
- New trust tiers beyond 0-3

## Current Runtime Constraints

The existing code gives us the correct insertion points:

- `_ANIMAL_ART`, `_ANIMAL_DELIVERY_FRAMES`, and `_ANIMAL_FOOTPRINTS` already define the animal visual vocabulary.
- `animalTrustTier()` and persisted `trust_actions` already define progression thresholds.
- `CreatureLayer.render()` already owns both ambient creature render and relationship-animal render.
- `CreatureLayer.update()` already owns ambient creature motion and is the correct place to add relationship-animal state progression.
- `SpecialLayer` already handles post-complete memorial visuals and must not become a second animal runtime.

This means the correct change is a runtime actor model inside `CreatureLayer`, not a parallel DOM overlay system.

## Experience Design

### Cross-animal trust signatures

Each tier should answer a visible question:

- Tier 0 - "Will it come closer at all?"
- Tier 1 - "It visits, but on its own terms."
- Tier 2 - "It recognizes this place and reacts to me."
- Tier 3 - "It belongs here now."

The tiers should differ in stance, movement, and response timing, not just art.

### Per-animal behavior table

| Animal | Tier 0 - Wild | Tier 1 - Curious | Tier 2 - Familiar | Tier 3 - Bonded |
|---|---|---|---|---|
| `cat` | Peeks from right edge, appears briefly, tail flick only | Walks 3-5 cols into garden, pauses, retreats | Waits near one home lane, head-turn or tail-flick on hover/feed | Naps at home spot, slow blink, stretches before delivery days |
| `bird` | Lands at far edge or low branch for a beat, then lifts off | Short ground-hop or branch-hop between two perches | Holds a preferred perch, turns to face cursor/feed zone | Perches permanently, brief wing-ruffle, launches for delivery from perch |
| `rabbit` | Nose-twitch from edge, half-body peek | Enters garden in one shy hop, freezes if hovered | Uses two nearby flower-side spots, ear-twitch and small hop | Curls near flower bed, grooming / breathing idle, full feed reaction |
| `turtle` | Slow appearance at edge, may not fully enter before leaving | Crosses a short path to one basking rock | Always reaches the same rock and turns in place | Settles at favorite rock, tiny head-bob idle, deliberate delivery carry |

### Immediate feed feedback

Every animal gets a one-beat feed response:

- `cat`: food dish or fish-bone glyph appears at home lane; cat steps toward it
- `bird`: seed scatter glyph appears below perch; bird dips downward once
- `rabbit`: keep carrot, but tie it to actor response instead of free overlay only
- `turtle`: lettuce/leaf glyph appears by rock; turtle advances one cell and pauses

The response should be short, handmade, and grid-aligned. It should never become a floating UI effect detached from the animal actor.

### Absence evidence

`wasAbsent` remains cosmetic evidence, not a second state machine:

- Cat: pawprints
- Bird: feather or `v v` track near perch/ground
- Rabbit: paired prints near flower edge
- Turtle: dragged line / shell trail

Absence traces should coexist with the new actor behavior, not replace it.

## Ambient Bird Redesign

### Visual direction

Ambient birds should read as small distant silhouettes, not letters. The approved prototype direction already exists in `ascii-animations/creatures/anim_birds.py` and `birds-and-insects.txt`: a 2-3 char flap cycle using wing-up, level, and wing-down states.

Proposed distant silhouette cycle:

- Frame A: `\\v/`
- Frame B: `_v_`
- Frame C: `/v\\`
- Frame D: `_v_`

For smaller screens or narrow sky lanes, allow a compact 2-char variant:

- Frame A: `>-`
- Frame B: `~>`

### Motion direction

- Solo birds continue to traverse the sky.
- Low-frequency flocks of 3-5 birds may spawn in a loose V offset.
- Ambient birds stay in upper-third or upper-half sky lanes only.
- Ambient birds never carry letters and never reuse relationship-bird or delivery-bird art.

## Technical Design

### 1. Relationship animal actor state

Add one runtime actor object owned by `CreatureLayer`, for example:

```js
{
  type: 'rabbit',
  tier: 2,
  mode: 'idle' | 'approach' | 'retreat' | 'feed-react' | 'perch' | 'nap',
  pose: 'base' | 'blink' | 'turn' | 'hop' | 'sleep',
  row: 0,
  col: 0,
  targetRow: 0,
  targetCol: 0,
  facing: -1 | 1,
  timer: 0,
  hoverActive: false
}
```

This actor is derived from `state.animalData`, but it owns motion/pose timing locally. Persisted data remains unchanged.

### 2. Pose-driven art tables

Keep `_ANIMAL_ART` as the canonical base art, but introduce a pose layer instead of replacing ownership:

- `_ANIMAL_POSES[type][tier][pose]`
- Or a small `buildAnimalFrame(type, tier, pose, facing)` helper

This keeps rendering inside `CreatureLayer` while allowing:

- tail flick / blink / ear twitch
- alternate perch or nap pose
- left/right facing variants where needed

### 3. Relationship animal update loop

`CreatureLayer.update()` gains a relationship-animal branch that:

- Initializes actor position from `animalHomePos(...)`
- Picks tier-appropriate idle behaviors on timers
- Reacts to hover proximity and recent feed events
- Snaps tier 0 to edge behavior and tiers 1-3 to interior/home behavior
- Enforces one active authoritative animal actor at a time

### 4. Feed event plumbing

`feedAnimal()` should stop directly owning visual effects. Instead:

- It increments trust as it does now
- It stores a short-lived feed event for `CreatureLayer`
- `CreatureLayer` consumes that event and drives both glyph spawn and actor response

This keeps behavior ownership unified and avoids DOM overlays becoming a second animation system.

### 5. Ambient bird entity upgrade

Ambient birds in `this._cr` should move from single-char entities to small multi-cell sprites:

- store `frames`, `frameIndex`, and optional `formationOffset`
- render with `putStrAnim(...)`, not `putAnim(...)`
- optionally spawn one leader plus 2-4 follower birds sharing the same velocity

### 6. Delivery integration

Bonded-animal delivery should reuse the same visual identity introduced by tier-3 idle behavior:

- same silhouette family
- same facing rules where practical
- same home/perch logic before or after delivery

The letter-bird remains fallback-only when no bonded relationship exists.

## Implementation Units

- [ ] **Unit 1: Relationship-animal actor refactor**

Goal: Move relationship-animal behavior from static render-only art lookup to a single actor state owned by `CreatureLayer`.

Files:
- Modify: `viewer-bnw.html`

Output:
- actor initialization and update path
- feed-event handoff into `CreatureLayer`
- no visual regressions for tier 0-3 static presence

- [ ] **Unit 2: Per-animal tier behaviors**

Goal: Implement one visible motion/pose signature per tier for cat, bird, rabbit, and turtle.

Rules:
- Tier changes must be visible in under 10 seconds of observation
- Tier 1 and tier 2 cannot share the same idle loop with only different art
- Tier 3 must read as settled, not just larger

- [ ] **Unit 3: Feed reaction pass**

Goal: Generalize the current rabbit-only carrot moment into animal-specific feed reactions with grid-aligned art and actor response.

Rules:
- No free-floating behavior outside the actor owner
- Glyph lifetime stays brief
- Reaction should be visible even on small/mobile viewports

- [ ] **Unit 4: Ambient bird redesign**

Goal: Replace placeholder sky birds with multi-char silhouettes and optional flocking.

Rules:
- Keep birds visually light; they are distant ambience, not featured characters
- Stay distinct from letter delivery art
- Preserve performance at the current 20fps unified loop

- [ ] **Unit 5: Dev harness and QA**

Goal: Make richer animal states easy to inspect and compare.

Changes:
- extend `Shift+A` overlay/status to include current behavior mode or pose
- add a dev-only trigger for feed reactions without mutating trust permanently in-session
- add a lightweight bird-spawn dev hook so ambient-bird art can be judged on demand

- [ ] **Unit 6: Spec + failure-log reconciliation**

Goal: After behavior is implemented and reviewed, update `docs/SPEC.md` and close FAILURE_LOG items [5] and [7] with evidence, not intent.

## Verification

### Functional checks

- `Shift+A` can still cycle all 16 animal states
- feeding still persists trust actions correctly
- tier 3 still overrides default delivery
- post-complete still renders the memorial state without duplicate animal draws
- ambient birds still despawn cleanly off-screen

### Experiential checks

- A human observer can distinguish tier 1 from tier 2 for each animal within 10 seconds
- Rabbit, cat, bird, and turtle each feel behaviorally different, not palette swaps
- Ambient birds feel intentionally designed rather than placeholder glyphs
- Bonded delivery feels like a payoff of the relationship rather than a separate minigame

### Regression checks

- no second animal draw path in `SpecialLayer`
- no DOM overlay ownership for core animal movement
- no overlap where ambient bird art is mistaken for letter-bird art

## Recommended Execution Order

1. Relationship-animal actor refactor
2. Rabbit and cat behaviors first
3. Bird and turtle behaviors next
4. Ambient bird redesign
5. Dev harness updates
6. Spec / failure-log reconciliation after visual QA

Rabbit and cat should go first because they have the clearest ground-level trust read and expose the feed-reaction architecture fastest. Ambient bird redesign should wait until the relationship-bird silhouette is locked so the two bird families do not drift together.
