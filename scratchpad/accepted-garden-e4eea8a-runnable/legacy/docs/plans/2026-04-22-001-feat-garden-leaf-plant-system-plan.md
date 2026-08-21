---
title: "feat: Garden leaf system — particle physics, taxonomy, and spec"
type: feat
status: active
date: 2026-04-24
origin: docs/brainstorms/2026-04-24-garden-leaf-plant-system-requirements.md
---

# feat: Garden leaf system — particle physics, taxonomy, and spec

## Overview

Seven code changes to `viewer-bnw.html` and seven spec edits to `docs/SPEC.md` that implement
the decisions made for gaps G1–G8 and G10–G12 from the April 2026 spec audit. The changes
improve the autumn leaf particle system (rotation, 40-frame ground rest, sky spawn, density
scaling, vx clamping), fix the pine evergreen taxonomy bug, extend the deciduous plant and
colour palette, and align the spec with actual implementation behaviour.

## Problem Frame

The garden is the emotional centrepiece of LateLetter — a grief space. The spec audit
(2026-04-22) identified 12 gaps where the implementation and spec diverged or were
underspecified. This plan covers the six code-bearing gaps (G1–G6 minus G7, plus G8)
and the five spec-only gaps (G2 partial, G7–G12). Together they make the autumn season
feel alive (leaves tumble, drift, and rest) and correct (pines don't shed; density scales
with canopy size). (See origin: `docs/brainstorms/2026-04-24-garden-leaf-plant-system-requirements.md`)

## Requirements Trace

### Leaf Particle System (G1–G5)
- R1. G1 — Leaf chars rotate `\`→`-`→`/` (loop) every 8 frames via `rotPhase` field
- R2. G2 — Leaf `vx` is clamped to ±0.8 after wind accumulation each tick
- R3. G3 — 30% of leaf spawns originate from sky (rows 0–2); 70% from `canopyCells`
- R4. G4 — Leaf cap is `Math.max(0, Math.min(60, Math.floor(canopyCells.size / 3)))`
- R5. G5 — Leaves that reach `groundY` transition to `leaf-rest` kind (char `-`, 40-frame rest, then abrupt removal)

### Taxonomy (G6, G8)
- R6. G6 — `LEAF_CANOPY = new Set(['oak', 'willow'])` drives leaf spawn; pine removed from that path; `DECIDUOUS` extended to include willow
- R7. G8 — `orange: '#a06420'` added to palette `C`; `'orange'` added to `AUTUMN_COLS`

### Spec (Track A)
- R8. Track A — docs/SPEC.md §7.1/§7.2/§7.3/§7.3.1/§7.4 updated to match reality and locked decisions

## Scope Boundaries

- No new plant generator functions — willow does not get a `pWillow` renderer in this plan
- No changes to rain, snow, frag, or splash particle behaviour
- No changes to creature, background, or special layer logic
- No changes to the letter reading screen or first-run banner
- No new key bindings or dev overlay changes

### Deferred to Separate Tasks

- `pWillow` plant generator + `MAKERS`/`SEASON_W` entries: separate feat task once willow is designed
- G7 foliage char vocabulary is spec-only in this plan; enforcing it in code is deferred
- G9 layout algorithm tuning: spec documentation only, no algorithm change

## Context & Research

### Relevant Code and Patterns

- `viewer-bnw.html:688–694` — `Particle` constructor (add `rotPhase: 0` here)
- `viewer-bnw.html:700–749` — `ParticleLayer.update` — the per-tick loop with kind branches
- `viewer-bnw.html:731–736` — leaf update branch (current target for G1/G2/G5 changes)
- `viewer-bnw.html:766–789` — `_spawn` function (leaf block at 783–788 — G3/G4 target)
- `viewer-bnw.html:805–816` — `render` (static `p.ch` via `putAnim` — no rotation logic yet)
- `viewer-bnw.html:561` — `AUTUMN_COLS` constant (G8 target)
- `viewer-bnw.html:562` — `DECIDUOUS` constant (G6 target)
- `viewer-bnw.html:597` — `CANOPY` constant and `buildCollision` (G6 target — add `LEAF_CANOPY`)
- `viewer-bnw.html:598–614` — `buildCollision` — the `isC && dy>=3` check at line 609 drives `canopyCells`
- `viewer-bnw.html:357–381` — palette `C` object (G8 target — add `orange`)
- `viewer-bnw.html:787` — leaf spawn colour: currently hardcoded `['yellow','bright_yellow','red','brown']` — should become `AUTUMN_COLS` after G8 so the addition propagates automatically
- `docs/SPEC.md:756–848` — §7.1 through §7.4 (Track A targets)

### Institutional Learnings

- No `docs/solutions/` KB exists yet; all decisions are in the origin brainstorm document
- Spec §7.1 already describes rotation and sky-spawn in prose — the implementation just doesn't match; Track A corrects the prose to match the locked decisions, not the other way round
- Per-layer cadence values in §7.2 describe the TUI design intent, not the browser viewer; do not conflate them when updating that section

### External References

None required — pure vanilla JS, no external dependencies, all patterns are internal.

## Key Technical Decisions

- **Mutate, don't replace, for leaf-rest:** When a leaf reaches `groundY`, mutate `p.kind`, `p.vx`, `p.vy`, `p.ch`, `p.age`, `p.maxAge` in place and push to `alive` — avoids a constructor call and keeps the particle in the same render pass
- **`rotPhase` as a plain integer field:** Add to the `Particle` constructor with value `0`; the rotation increment belongs in the leaf update branch, not in the constructor or render pass
- **`LEAF_CANOPY` defined adjacent to `CANOPY`:** Declare `const LEAF_CANOPY = new Set(['oak', 'willow'])` immediately after `CANOPY` at line 597; change `buildCollision`'s `isC` check to use `LEAF_CANOPY`; `CANOPY` stays intact for snow accumulation (`topSurfaces` path is unchanged)
- **Leaf colour references `AUTUMN_COLS`:** Change the hardcoded colour array in `_spawn` to `rng.choice(AUTUMN_COLS)` so G8's orange addition propagates to leaf spawn automatically
- **Sky-spawn vx seed is wider:** Canopy-spawned leaves use `uniform(-0.2, 0.2)`; sky-spawned leaves use `uniform(-0.3, 0.3)` to imply slightly more mid-drift character per the requirements doc
- **Cap formula removes outer `canopyCells.size > 0` guard:** The `Math.max(0, …)` formula already produces `cap=0` for empty canopy, making the guard redundant; removing it simplifies the spawn condition to `leafCount < leafCap`

## Open Questions

### Resolved During Planning

- **Does willow need a renderer?** No — deferred. `LEAF_CANOPY` and `DECIDUOUS` can reference `'willow'` safely; the set membership check in `buildCollision` simply never finds a willow plant until one is added.
- **Does `leaf-rest` need a new kind check in `render`?** No — `render` calls `buf.putAnim(p.y|0, p.x|0, p.ch, p.color)` for all particles; since `p.ch` is set to `-` on transition, the rest char renders automatically.
- **Should sky-spawn have a fallback for empty-canopy gardens?** No — `leafCap = 0` when `canopyCells.size === 0`, so `leafCount < leafCap` is always false and the spawn block never runs. A "sky-spawn when canopy empty" fallback would be dead code — do not include it.
- **`@ ` overlap in G7 char table (rose/foliage):** Grandfathered — `@` is intentionally shared between deciduous foliage fill and flower clusters; the "should not mix roles" rule applies to new plant types only. Existing rose code is correct.

### Deferred to Implementation

- Exact line offsets for edits: the research scan found approximate lines (688, 731, 783, etc.); implementer should confirm current line numbers before each edit
- Whether `rotPhase` increment uses `state.frame` or `p.age`: use `p.age % 8 === 0` — it is equivalent to `frame % 8 === 0` and avoids threading `state.frame` into the branch

## High-Level Technical Design

> *This illustrates the intended approach and is directional guidance for review, not implementation specification. The implementing agent should treat it as context, not code to reproduce.*

**Leaf particle state machine:**

```
SPAWNED (leaf)
  ↓ each tick: vx += wind*0.04; vx clamped ±0.8
  ↓            vy += 0.04
  ↓            rotPhase increments every 8 frames; ch = ['\\','-','/'][rotPhase]
  ↓ if y >= groundY:
RESTING (leaf-rest)   kind='leaf-rest', vx=0, vy=0, ch='-', age=0, maxAge=41
  ↓ each tick: age++ (universal, line 705 — do NOT add in leaf-rest branch)
  ↓ if age >= maxAge (41):
REMOVED  // effective rest = 40 frames (age 1..40); maxAge=41 corrects off-by-one
```

**`buildCollision` LEAF_CANOPY split:**

```
CANOPY = new Set(['pine', 'oak'])     // retained for snow accumulation
LEAF_CANOPY = new Set(['oak', 'willow'])  // new — drives canopyCells for leaf spawn

buildCollision:
  // topSurfaces (snow) is built UNCONDITIONALLY for every plant cell — no CANOPY gate
  if(top[c]===undefined||row<top[c]) top[c]=row;   // line 608, unchanged

  // canopyCells now gated by LEAF_CANOPY, not CANOPY
  isLeafC = LEAF_CANOPY.has(type)     // NEW: was isC = CANOPY.has(type)
  if isLeafC && dy >= 3: can.add(key)
```

> Note: the old `isC = CANOPY.has(type)` only ever gated `can.add` — it never gated `topSurfaces`. Do **not** introduce an `isSnowC` variable: `topSurfaces` runs unconditionally and must remain so. Simply rename `isC` → `isLeafC` and change its set reference from `CANOPY` to `LEAF_CANOPY`.

**Leaf spawn decision in `_spawn`:**

```
leafCap = max(0, min(60, floor(canopyCells.size / 3)))
if season === 'autumn' && leafCount < leafCap:
  // When canopyCells is empty, leafCap === 0 → this block never runs.
  // No sky-spawn fallback for empty-canopy gardens needed or reachable.
  doSky = (random() < 0.3)            // 30% sky, 70% canopy
  x, y = sky origin (col random, row 0–2)  OR  canopy cell pick
  spawn Particle('leaf', x, y, vx, vy, ch, color, 150)
```

## Implementation Units

- [ ] **Unit 1: Taxonomy constants and buildCollision (G6, G8)**

**Goal:** Establish correct taxonomy data and introduce `LEAF_CANOPY` so downstream units can reference it.

**Requirements:** R6, R7 (plus `spawnAt` colour alignment — extends R7)

**Dependencies:** None — this is the foundation for all other units.

**Files:**
- Modify: `viewer-bnw.html`

**Approach:**
- Add `orange: '#a06420'` to palette `C` (after `brown` entry, ~line 370)
- Add `'orange'` to `AUTUMN_COLS` array (~line 561): `['yellow', 'bright_yellow', 'orange', 'red', 'brown']`
- Add `'willow'` to `DECIDUOUS` set (~line 562)
- Add `const LEAF_CANOPY = new Set(['oak', 'willow'])` immediately after the `CANOPY` declaration (~line 597)
- In `buildCollision`, rename `isC = CANOPY.has(plant.type)` to `isLeafC = LEAF_CANOPY.has(plant.type)`; change `can.add(key)` condition from `isC && dy>=3` to `isLeafC && dy>=3`; leave the `topSurfaces` path (line 608) untouched — it has no CANOPY gate and must remain unconditional
- In `spawnAt` (~line 800), change the hardcoded colour array `['bright_green','green','bright_yellow','yellow','bright_magenta']` to `rng.choice(AUTUMN_COLS)` so cursor-triggered spawn in autumn uses the same colour pool as ambient leaf fall

**Test scenarios:**
- Happy path: In autumn with an oak garden, `state.canopyCells.size > 0` (oak produces canopy cells as before)
- G6 regression: In autumn with a pine-only garden, `state.canopyCells.size === 0` (pine no longer contributes canopy cells to leaf spawn path)
- G8 visual: autumn leaf colours include orange-toned leaves alongside yellow/red/brown
- G8 data: `C.orange` exists and `AUTUMN_COLS` has length 5
- spawnAt colour: clicking a tree in autumn spawns leaves in autumn colours (no magenta, no bright_green)

**Verification:**
- Open the viewer in a browser with dev fixture, cycle to autumn with `,.` — pine-only gardens have `canopyCells.size === 0` confirmed by Shift+D dump; gardens with oak have non-zero canopyCells

---

- [ ] **Unit 2: Leaf spawn rework (G3, G4)**

**Goal:** Replace the hardcoded cap and single-origin spawn with a dynamic cap and 70/30 canopy/sky split.

**Requirements:** R3, R4

**Dependencies:** Unit 1 (needs `LEAF_CANOPY`-driven `canopyCells` and updated `AUTUMN_COLS`)

**Files:**
- Modify: `viewer-bnw.html`

**Approach:**
- In `_spawn`, replace the leaf block (lines ~783–788):
  - Compute `leafCap = Math.max(0, Math.min(60, Math.floor(state.canopyCells.size / 3)))`
  - Compute `leafCount` by filtering `_p` for `kind === 'leaf'` (keep the existing filter pattern)
  - Replace outer guard `state.canopyCells.size > 0 && leafCount < 25` with `leafCount < leafCap`
  - Inside the spawn block: use `rng.random() < 0.3` to decide sky-spawn (30% sky, 70% canopy). No fallback for empty-canopy needed — leafCap=0 prevents entering this block when canopy is empty.
  - Sky-spawn: `x = rng.random() * state.cols`, `y = rng.randint(0, 2)`, `vx = rng.uniform(-0.3, 0.3)`, `vy = rng.uniform(0.1, 0.25)`
  - Canopy-spawn: existing `arr[…].split(',')` pick, `vx = rng.uniform(-0.2, 0.2)`, `vy = rng.uniform(0.05, 0.2)`
  - Change leaf colour source from hardcoded array to `rng.choice(AUTUMN_COLS)` so orange propagates automatically
  - `rng.randint` exists at line 446 — use it directly; no fallback needed
  - Leaf char source remains `rng.choice([',', "'", '~', '*'])` — unchanged; rotation overwrites it on the first tick
  - `maxAge` remains `150`

**Test scenarios:**
- Happy path: Autumn leaves spawn in a mixed oak/pine garden; leaves appear from both tree positions and above the treetops
- Edge case — pine-only garden: `leafCap === 0` → no leaves spawn (confirmed via count in Shift+D dump)
- Edge case — large canopy (180+ cells): cap approaches 60, not exceeding it
- Edge case — small canopy (30 cells): cap is 10, not the old hardcoded 25
- Sky-spawn frequency: over 100 ticks approximately 30% of new leaves appear at rows 0–2 (visual spot-check)
- Colour distribution: after Unit 1, orange leaves appear in the autumn population alongside other colours

**Verification:**
- In autumn with a large oak garden, leaf count stabilises at ≤60 not the old 25 cap
- Sky-spawned leaves appear to drift down from above the canopy with slightly wider horizontal drift than canopy-detached leaves

---

- [ ] **Unit 3: Leaf particle update — rotation, clamp, and ground rest (G1, G2, G5)**

**Goal:** Add `rotPhase` field to `Particle`, implement tumbling char rotation, clamp vx, and transition grounded leaves to `leaf-rest`.

**Requirements:** R1, R2, R5

**Dependencies:** Unit 1 (leaf-rest particles draw char from palette; colour is set at spawn time so no direct dependency — but Unit 1 should be in place for coherent autumn visuals)

**Files:**
- Modify: `viewer-bnw.html`

**Approach:**
- **Particle constructor** (~line 692): add `this.rotPhase = 0` as a new field (after existing fields)
- **Leaf update branch** (~lines 731–736) — make three changes in order:
  1. After `p.vx += state.wind * 0.04`, add `p.vx = Math.max(-0.8, Math.min(0.8, p.vx))` (G2)
  2. After the clamp, add rotation increment: `if(p.age % 8 === 0) p.rotPhase = (p.rotPhase + 1) % 3;` then `p.ch = ['\\', '-', '/'][p.rotPhase];` (G1)
  3. Replace the ground-check `alive.push(p)` block: if `(p.y|0) >= state.groundY`, mutate to leaf-rest instead of discarding (G5):
     ```
     p.kind = 'leaf-rest'; p.vx = 0; p.vy = 0; p.ch = '-'; p.age = 0; p.maxAge = 41;
     alive.push(p);
     ```
     maxAge=41 compensates for the universal `p.age++` at line 705: on the transition tick, age is reset to 0 and pushed; on the next tick, age becomes 1 before the leaf-rest branch runs — so the particle lives for age 1..40 = exactly 40 visible frames before removal at age=41.
- **New `leaf-rest` update branch** — add after the leaf branch (before or after frag/splash, before the closing of the loop): if `p.kind === 'leaf-rest'`, push to `alive` while `p.age < p.maxAge`, otherwise discard:
  ```
  if(p.kind === 'leaf-rest'){
    if(p.age < p.maxAge){ alive.push(p); } // no movement, just age
    continue;
  }
  ```
  **Do NOT add `p.age++` inside this branch.** The outer loop at line 705 increments `p.age` universally before any kind check — adding a second increment here halves the rest duration.
- **render** — no change needed; `putAnim` uses `p.ch` which is now mutated on each rotation tick and set to `-` on rest. `p.color` is not changed on transition — the leaf retains its autumn spawn colour at rest (yellow, orange, etc.). This is intentional.

**Test scenarios:**
- Happy path G1: Falling leaves visibly tumble — char alternates between `\`, `-`, `/` approximately every 8 frames (400ms) as they fall
- Happy path G5: Leaves reach the ground and briefly appear as `-` at the ground row before disappearing (~2 seconds)
- Happy path G2: At peak wind, leaves drift laterally but do not exit the garden horizontally before falling (no instantaneous left-edge/right-edge exits)
- Edge case G1: Char rotation stops when leaf transitions to `leaf-rest` (stays as `-`)
- Edge case G5: Resting leaves do not accumulate — after ~40 frames the ground row clears, not fills up
- Edge case G5: A leaf reaching groundY before maxAge is reached transitions correctly (leaf-rest has age=0 restart, not the leaf's age)
- Integration: Leaf-rest particles pass through `render` correctly — `-` chars appear at groundY in the autumn colour of the original leaf

**Verification:**
- In browser, autumn season, observe leaf fall: chars tumble, leaves land as `-`, then disappear after ~2s
- No horizontal leaf escapes visible even during peak wind cycles
- Ground row never fills with persistent `-` chars after a long session

---

- [ ] **Unit 4: docs/SPEC.md Track A updates (G2, G7, G9, G10, G11, G12 — spec only)**

**Goal:** Align docs/SPEC.md §7.1–§7.4 with the locked decisions from the requirements doc so the spec matches reality.

**Requirements:** R8

**Dependencies:** None — spec edits are independent of code units; may be done in any order relative to Units 1–3

**Files:**
- Modify: `docs/SPEC.md`

**Approach — seven targeted edits:**

1. **§7.1 leaf row** (~line 777): Change "sine-wave horizontal drift" to "wind-driven drift (vx accumulation, ±0.8 clamp)"; update rotation description to note `rotPhase = (rotPhase + 1) % 3` every 8 frames; note sky-spawn is 30% of spawns from rows 0–2

2. **§7.2 tick cadence** (~lines 790–809): Add a note: "The browser viewer uses a unified ~50ms RAF tick for all layers. The per-layer cadences listed in this section (plants 300–500ms, particles 40–80ms, creatures 100–200ms) describe the curses/TUI design intent; both are conformant implementations."

3. **§7.2 canopy surfaces** (~line 809): Add a paragraph distinguishing `canopyCells` (LEAF\_CANOPY plants, dy ≥ 3, drives leaf spawn) from `topSurfaces` (per-column highest cell across all plant types, drives snow accumulation). Note the two are distinct models serving different physical purposes.

4. **§7.3 foliage char vocabulary** (~line 810): Add a sub-section or table with the canonical char vocabulary (from G7 decision in the requirements doc). Note that `@` is intentionally shared between deciduous foliage fill and flower head by historical convention.

5. **§7.3.1 layout algorithm** (new sub-section after §7.3): Document `genLayout` constants — `cols*3` attempts, `±2` col padding, ~1 plant per 10–15 cols at typical widths, sparse gardens at <60 cols are correct by design.

6. **§7.4 wind model** (~line 831): Add wind formula `state.wind = 0.5 * Math.sin(state.frame * 0.008)`, range ±0.5, period ~39s, coupling coefficients (rain drift `wind*0.3`, leaf drift `wind*0.04`).

7. **§7.4 plant classification table** (~line 831): Add the four-class taxonomy table (Deciduous/Evergreen/Flowering/Dead) with autumn recolor and leaf-canopy columns from G6 decision. Note that `CANOPY` (snow) differs from `LEAF_CANOPY` (leaf spawn).

**Test scenarios:**
- Test expectation: none — spec edits carry no runtime behaviour. Verification is document quality.

**Verification:**
- Each updated section accurately reflects the locked decisions in the requirements doc
- §7.3.1 exists as a new subsection after §7.3
- No spec section still claims "sine-wave" leaf oscillation
- The taxonomy table includes all plants listed in SEASON_W plus willow/cactus/bamboo/lily/dead-tree as "planned"

## System-Wide Impact

- **Interaction graph:** `buildCollision` is called in `PlantLayer.regenerate` on season change and window resize; the LEAF_CANOPY swap changes which cells end up in `state.canopyCells` — this state is consumed by `_spawn` (affected) and by `spawnAt` (cursor-triggered spawn) which also checks `canopyCells.size > 0` and may need the same cap formula applied
- **Error propagation:** No error paths introduced; particle mutations are in-place with no async or I/O
- **State lifecycle risks:** `leaf-rest` particles have `age` reset to 0 on transition — if the outer update loop increments `age` before the kind check, the reset needs to happen carefully to avoid an off-by-one; implementer should verify increment order in the update loop
- **API surface parity:** `spawnAt` (cursor-triggered) uses `state.collisionMap` (all plant cells), not `state.canopyCells` — it is unaffected by the LEAF_CANOPY change and the cap formula change. After this plan lands, clicking a pine tree in autumn will still spawn leaves from it. This is a known gap, not in scope for this plan.
- **Integration coverage:** The leaf colour path now goes through `AUTUMN_COLS` rather than a hardcoded array — after Unit 1, both `applyAutumn` and `_spawn` reference the same colour set; adding future colours to `AUTUMN_COLS` automatically propagates to both
- **Unchanged invariants:** Rain, snow, frag, splash particle behaviour is not touched; `CANOPY` set and `topSurfaces` snow accumulation path are unchanged; the `dy >= 3` threshold is unchanged

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| `rng.randint` existence | Confirmed at line 446: `randint(a,b){ return a+Math.floor(this.random()*(b-a+1)); }` — use directly |
| `p.age` increment order | Confirmed universal at line 705 (before any kind check). **Do NOT add `p.age++` to leaf-rest branch** — double-increment halves the rest duration |
| `rotPhase` on existing (pre-fix) leaf particles would be `undefined` until respawn | Not a concern — leaf lifetime is 150 frames and the garden resets on season change; all in-flight particles are cleared on reset |
| docs/SPEC.md §7.3.1 insertion may conflict with existing §7.5 numbering | Check whether §7.4 ends cleanly before §7.5; if §7.5 exists, insert §7.3.1 as a sub-section not a top-level heading |
| Orange colour value `#a06420` may be too close to brown `#7a5830` in B&W mode | Visual QA in colour mode 3 (B&W) — if indistinguishable, note in FAILURE_LOG; colour parity in B&W is acceptable per existing palette design |

## Documentation / Operational Notes

- After this plan lands, the FAILURE_LOG entries G1–G8 should be updated to "Implemented (unproven)" status
- The orange colour `#a06420` should be visually verified in both full-colour and B&W modes before closing the gap

## Sources & References

- **Origin document:** [docs/brainstorms/2026-04-24-garden-leaf-plant-system-requirements.md](docs/brainstorms/2026-04-24-garden-leaf-plant-system-requirements.md)
- Research: `/tmp/claude-repo-research-garden-leaf.md`
- Particle system: `viewer-bnw.html:688–816`
- Taxonomy constants: `viewer-bnw.html:561–614`
- Spec sections: `docs/SPEC.md:754–848`
