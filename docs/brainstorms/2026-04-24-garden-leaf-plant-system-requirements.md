# Garden Leaf & Plant System — Requirements

**Date:** 2026-04-24
**Status:** Decisions locked + reviewed — ready for spec update + implementation planning
**Covers:** Gaps G1–G12 from docs/FAILURE_LOG.md § 2026-04-24

---

## Context

The garden in `viewer-bnw.html` uses a 5-layer compositing model (Background, Plants, Particles, Creatures, Special). A spec audit identified 12 gaps in the leaf particle system, plant taxonomy, and garden-level systems. This document records the decisions made for each gap.

---

## G1–G5: Leaf Particle System

### G1 — Leaf char rotation

**Decision:** Slow rotation, one char-step every 8 frames (400ms at 20fps).

- Sequence: `\` → `-` → `/` → `\` (loop, not ping-pong)
- Each leaf stores a `rotPhase` (0–2) that increments every 8 frames (`rotPhase = (rotPhase + 1) % 3`)
- The displayed char is `['\\','-','/'][p.rotPhase]` regardless of base spawn char
- No velocity coupling — rotation speed is fixed for all leaves
- Rationale: subtle tumbling reads as a real leaf; faster rotation looks like UI noise in a grief space

### G2 — Leaf horizontal motion

**Decision:** Keep current wind-driven linear drift. Spec §7.1 is incorrect.

- Formula: `p.vx += state.wind * 0.04` per frame (current implementation), then clamp: `p.vx = Math.max(-0.8, Math.min(0.8, p.vx))`
- §7.1 claim of "sine-wave horizontal oscillation" is wrong — update spec to say "wind-driven drift with ±0.8 clamp"
- Rationale: linear drift is simpler and correct for this context; the ±0.8 clamp prevents leaves exiting the garden immediately during peak wind without affecting the typical drift feel

### G3 — Sky spawn

**Decision:** 30% of leaf spawns originate from the sky, not from canopy cells.

- When `_spawn()` runs for a leaf: 70% of the time pick a random cell from `canopyCells`; 30% of the time spawn at a random col, row 0–2 with `vx` already seeded to `uniform(-0.3, 0.3)` and `vy` to `uniform(0.1, 0.25)` (mid-drift)
- Sky-spawned leaves are visually identical to canopy-detached leaves; they draw color from the same pool (green normally; autumn color pool during autumn season)
- If `canopyCells.size === 0`, all spawns are sky-spawns (sparse garden fallback)
- Rationale: prevents near-empty leaf fall on narrow gardens with few deciduous trees

### G4 — Density cap

**Decision:** Dynamic cap derived from canopy size.

- Formula: `cap = Math.max(0, Math.min(60, Math.floor(canopyCells.size / 3)))`
- Examples: 0 cells → cap 0 (evergreen-only garden), 30 cells → cap 10, 90 cells → cap 30, 180 cells → cap 60
- Replaces current hardcoded cap of 25
- Floor is 0, not 10 — pine-only gardens shed no leaves, as expected for evergreens
- Rationale: cap proportional to canopy size feels correct — dense oak forests shed more leaves than sparse ones

### G5 — Leaf ground behavior

**Decision:** Brief rest on groundY, then age out.

- When `p.y >= state.groundY`: zero out `p.vx` and `p.vy`, set `p.kind = 'leaf-rest'`
- Resting leaves persist for 40 frames (~2s at 20fps), then are removed
- During rest, the leaf is drawn as `-` (flat position) at `groundY`; no rotation while resting
- No accumulation — resting leaves are transient; ground never fills up
- Rationale: leaves settling briefly on the ground reads as autumn; instant disappearance feels sterile; accumulation would clutter the ground row over long sessions

---

## G6–G8: Plant Taxonomy

### G6 — Plant classification

**Decision:** Four-class taxonomy, formally defined.

| Class | Plants | Autumn recolor | Contributes to CANOPY/leaf spawn |
|---|---|---|---|
| Deciduous | oak, bush, willow | Yes — green → autumn pool | Yes |
| Evergreen | pine, fern, grass, mushroom, cactus, bamboo | No | No (pine bug fixed) |
| Flowering | daisy, tulip, sunflower, wildflower, rose, lily | No | No |
| Dead/bare | dead tree | No (already brown) | No |

- **Pine removed from `CANOPY`** — pine is evergreen and must not shed leaves
- A new `LEAF_CANOPY` set replaces `CANOPY` for leaf-spawn purposes: `new Set(['oak', 'willow'])`
- `CANOPY` (used for snow accumulation) retains pine — snow accumulates on pine needles correctly
- `DECIDUOUS` set extended to include willow: `new Set(['oak', 'bush', 'willow'])`

### G7 — Foliage char vocabulary

**Decision:** Write a canonical char vocabulary table in §7.3 of the spec.

Table to be added to spec:

| Role | Chars | Plants |
|---|---|---|
| Trunk / stem | `\|` | all |
| Deciduous foliage fill | `@ o 0 &` | oak, willow |
| Coniferous fill | `/ \ ^ *` | pine |
| Soft-edge / hedge fill | `~ u w v` | bush |
| Fern frond | `* ,` | fern |
| Grass tip | `/ \ \` ` '` | grass |
| Flower head | `O # @ ( ) "` | all flower types |
| Accent / particle | `* . , ' \`` | mushroom caps, falling leaves |

- Future plant types must choose from this table or explicitly extend it with a new char role entry
- `@` is intentionally shared between deciduous foliage fill and flower head — historical overlap between dense foliage and dense flower clusters; existing rose code is correct
- Within a single new plant type, chars should not mix roles from unrelated rows (e.g. do not use a trunk char as a flower head)

### G8 — Autumn palette

**Decision:** Add `orange` to palette and autumn recolor pool.

- New palette entry: `orange: '#a06420'`
- Updated `AUTUMN_COLS`: `['yellow', 'bright_yellow', 'orange', 'red', 'brown']`
- `applyAutumn()` resamples deciduous green cells across all five autumn colors
- Rationale: real deciduous progression is yellow → orange → red → brown; current palette skips orange

---

## G9–G12: Garden-Level Systems

### G9 — Layout algorithm

**Decision:** Algorithm stays as-is. Document constants in spec.

- Attempt count: `cols * 3`
- Per-plant collision padding: `±2` cols beyond plant half-width
- Expected density: ~1 plant per 10–15 cols at typical viewport widths
- Sparse gardens at narrow viewports (< 60 cols) are correct by design
- No intentional clearings in v1 (deferred)
- Spec §7.3 to include a layout algorithm subsection with these constants

### G10 — Wind model

**Decision:** Document current formula in spec. No formula change.

- `state.wind = 0.5 * Math.sin(state.frame * 0.008)`
- Range: ±0.5 (dimensionless, unitless coupling factor)
- Period: ~785 frames ≈ 39 seconds at 20fps
- Effect coupling coefficients: rain drift `wind * 0.3`, leaf drift `wind * 0.04`, rustle intensity via `rustleChar`
- Moments of true calm (sin = 0) are intentional pleasant pauses
- Spec §7.4 (or a new §7.4.1) to document this

### G11 — Canopy cell threshold

**Decision:** Uniform `dy ≥ 3` threshold. Document the snow/leaf split in spec.

- `canopyCells`: plant cells where `dy ≥ 3` AND plant type in `LEAF_CANOPY` (deciduous only after G6 fix)
- `topSurfaces`: per-column topmost occupied cell across ALL plant types — used for snow accumulation
- These are two distinct models serving different physical purposes; spec §7.2 must document both
- `dy ≥ 3` rationale: excludes trunk rows (row 1–2 above base) from leaf spawn, which would look wrong

### G12 — Layer update cadence

**Decision:** Unified 50ms tick is the correct model for the browser viewer; per-layer cadence remains the TUI model.

- Spec §7.2 currently describes per-layer cadences (plants 300–500ms, particles 40–80ms, creatures 100–200ms)
- These cadences describe the **curses/terminal TUI design intent**, not the browser viewer
- The browser viewer's unified RAF loop at ~50ms (20fps) is correct for that platform
- Spec §7.2 to be updated: add a note that the curses TUI uses per-layer cadence; the browser viewer uses a unified tick; both are conformant implementations

---

## Implementation Notes

These are spec and code decisions — not implementation tasks. When this goes to planning, the implementation work falls into two tracks:

**Track A — Spec updates (no code change):**
- §7.1: correct "sine-wave" claim → "wind-driven drift with ±0.8 vx clamp"
- §7.2: document unified tick as browser-canonical; per-layer cadence as TUI-canonical
- §7.2: document `canopyCells` vs. `topSurfaces` distinction
- §7.3: add foliage char vocabulary table (G7)
- §7.3.1: add layout algorithm constants (G9)
- §7.4: add wind model formula and coupling coefficients
- §7.4 seasons: add plant classification table (G6)

**Track B — Code changes (viewer-bnw.html):**
- G1: add `rotPhase` to leaf particles; apply rotation each tick
- G2: add vx clamp after wind accumulation: `p.vx = Math.max(-0.8, Math.min(0.8, p.vx))`
- G3: split leaf spawn: 70% canopy, 30% sky
- G4: replace hardcoded `< 25` with dynamic cap formula (`Math.max(0, ...)` — floor is 0)
- G5: add `leaf-rest` kind; zero velocity on ground contact, set `p.age = 0` and `p.maxAge = 40`; update branch: increment age each frame, remove when `age >= maxAge`
- G6: fix `CANOPY` set (keep pine for snow); add `LEAF_CANOPY = new Set(['oak', 'willow'])` for leaf spawn; extend `DECIDUOUS`
- G8: add `orange` to palette `C`; add to `AUTUMN_COLS`
