---
title: "feat: Viewer dev QA tools + pretext typography improvements"
type: feat
status: active
date: 2026-04-21
---

# Viewer dev QA tools + pretext typography improvements

## Overview

Five parallel improvements to `viewer-bnw.html`:

1. **Dev keybindings** — runtime cycling of seasons, weather, and garden state
2. **Dev console logging** — structured `[dev]` state dumps on demand and key events
3. **Rabbit carrot feed animation** — ASCII art carrot (`"` + `\/`) briefly appears at rabbit position when `f` is pressed
4. **Color/background modes** — four B&W testing modes cycled with a dev key
5. **Pretext full utilization** — justified letter body text via segment-level span rendering; reading progress; cache clearing on letter close

All dev features are gated behind `isDevFixture` (already available) — no additional URL param needed.

---

## Problem Frame

The viewer has three gaps:

**Dev gap:** No way to test seasonal states, weather, or color modes at runtime. Diagnosing the HTML grid-fidelity issue (TODO 10e) requires rapid iteration, but currently forces page reload + clock/URL editing to switch seasons. No console instrumentation means grid metrics, particle counts, and animal state are invisible during QA.

**Animation gap:** Feeding the rabbit has no visual response — the trust tier increments silently. A brief ASCII carrot feels handmade and earned; it also gives visual confirmation that `f` did something.

**Typography gap:** `renderBody()` calls `prepareWithSegments()` — which does full segment-level measurement — then discards all segment data and only uses `line.text`. This wastes pretext's core value proposition. Each line renders as a `div.textContent` string, which means justified text is impossible (CSS justify can't expand already-split lines). The letter body should look typeset, not plain.

---

## Requirements Trace

- R1. Dev keys must not collide with existing bindings: `e i l f p q j k Shift+A`
- R2. Dev features gate on `isDevFixture === true` only — no new URL param needed
- R3. Season cycling must call `garden._reset()` so the garden immediately re-renders
- R4. Carrot art uses grid coordinates (row/col → `row * CH`, `col * CW` pixels), not arbitrary pixels
- R5. Color mode 3 (B&W except animations) must not require a full renderer refactor — use ScreenBuffer cell tagging
- R6. Justified text must fall back gracefully (last line stays left, empty text stays left)
- R7. Pretext segment cache (`_prepared`) must be cleared when closing a letter to avoid stale layout

---

## Scope Boundaries

- No canvas layer — garden stays DOM-based
- No new external dependencies beyond pretext (already imported)
- Carrot animation is overlay divs on `#g`, not a new ScreenBuffer layer
- Dev keybindings are runtime-only — no persistence, no URL encoding of dev state
- No per-word hover/selection highlight (deferred to post-v1)

### Deferred to Separate Tasks

- Per-word tap-to-highlight in letter body: post-v1
- Bidi/RTL text rendering in letter body: post-v1
- Paragraph drop cap: post-v1

---

## Context & Research

### Relevant Code and Patterns

**Pretext API (used)**
- `prepareWithSegments(text, font, opts)` — returns `{widths[], lineEndFitAdvances[], kinds[], segments[], …}`
- `layoutWithLines(prepared, maxWidth, lineHeight)` — returns `{lineCount, height, lines[]}` where each `line` has `{text, width, start: {segmentIndex, graphemeIndex}, end: {segmentIndex, graphemeIndex}}`

**Pretext API (unused)**
- `clearCache()` — clears canvas measurement caches; call on letter close
- `walkLineRanges(prepared, maxWidth, onLine)` — non-materializing pass; good for line count
- `prepared.segments[i]` — segment text string
- `prepared.widths[i]` — segment width in px (canvas-measured)
- `prepared.kinds[i]` — `'text' | 'space' | 'preserved-space' | 'hard-break'`

**Key gap:** `renderBody()` at `viewer-bnw.html:1474` calls `prepareWithSegments` but only reads `line.text`, ignoring widths, kinds, and segment indices. Justified rendering requires iterating `prepared.segments[startIdx..endIdx]` with their widths.

**Garden engine**
- `getSeason()` at line ~973 — now checks `?season=` URL param; needs `_devSeason` variable override
- `garden._reset()` at line ~1009 — reinitializes `GardenState`, `PlantLayer`, `ParticleLayer`, `CreatureLayer`; call after `_devSeason` changes
- `GardenState` constructor at ~1012 — takes `cols, rows, seed, season`
- `CW, CH` globals — character cell dimensions; `CW * col`, `CH * row` = pixel position
- `CreatureLayer` — draws animal at home position; home row is computed from `GardenState.groundRow`

**Dev key handler** — existing `keydown` listener in `wire()` at line ~1556. Currently handles `Shift+A` (dev cycle animals) — good pattern to follow.

**ScreenBuffer** — stores `(char, color)` per cell. Color is a CSS color string. Add `anim: bool` tag per cell for color mode 3.

**Color palette** — `const C = { sky, ground, …, plant_*, flash }` at line ~344. Background set via `setGroundBg()` which applies inline `background` style on `#g`. Plant row colors applied per-span in `blit()`.

**`#g > div` CSS** — `height: 15px; white-space: pre; overflow: hidden`. Span children get inline `color` style from `blit()`.

### Institutional Learnings

- TODO 10e already fixed `_measure()` to append to `#g` — the CH/CW globals are now accurate. Use them directly for carrot positioning.
- `_arcSeed()` (just added) shows the pattern for post-load state injection — follow same structure for dev key handlers.

---

## Key Technical Decisions

- **`_devSeason` variable:** `getSeason()` checks `_devSeason` first (if non-null), then URL param, then clock. `<`/`>` keys set this variable then call `garden._reset()`. Simple, no reload.

- **Dev keydown in existing listener:** Extend the `keydown` listener in `wire()` rather than adding a new listener. Gate all new dev keys with `if(!isDevFixture) return` at the top of the dev block.

- **Carrot overlay — absolutely positioned divs, not ScreenBuffer:** The carrot is a 2-row overlay (`"` line, `\/` line) placed at `left: animalCol * CW`, `top: animalRow * CH` using `position:absolute` inside `#g`. Styled orange (#FF8C00). Auto-removed after 1500ms. This avoids any ScreenBuffer changes for a pure decoration.

- **ScreenBuffer `anim` tag for color mode 3:** Add a boolean `anim` field to ScreenBuffer cells (default false). `ParticleLayer` and `CreatureLayer` set `anim=true` when writing. `BackgroundLayer` and `PlantLayer` leave it false. In `blit()`, for `_colorMode === 'bw-anim'`, override color to `'var(--text)'` unless `cell.anim === true`. This is the minimal-footprint approach — no second buffer, no layer split.

- **Color modes via CSS + JS combination:**
  - Mode 0 (default): no override
  - Mode 1 (white bg): `C.sky = '#fff'`; `C.dim_green = '#f0f0f0'` temporarily; call `garden._reset()`
  - Mode 2 (full grayscale): `#g { filter: grayscale(1) }` via `el.style.filter`
  - Mode 3 (B&W + anim color): `_colorMode = 'bw-anim'`; `blit()` uses ScreenBuffer `anim` tag
  - Mode cycling writes a `_colorMode` global; `blit()` and garden check it

- **Justified text via flex spans:** `renderBody()` is rewritten to render each non-last line as a `<div class="ll ll-j">` containing one `<span>` per segment from `prepared.segments[startIdx..endIdx]`. Spaces become `flex-grow: 1` spans (or margin on word spans). Last line and single-word lines stay left-aligned (`<div class="ll">` with plain text). This uses the `start.segmentIndex` / `end.segmentIndex` already on each `layoutWithLines` line object.

- **Reading progress:** After `layoutWithLines`, `lineCount` is available. Show a subtle `X lines` or a thin scroll-progress bar (1px, opacity 0.15) at the bottom of the letter body `<div>`. Uses `scroll` event on `#letter-body` to update.

---

## High-Level Technical Design

> *Directional guidance only — not implementation specification.*

### Color mode state machine

```
_colorMode: 0 | 1 | 2 | 3
Shift+C → (_colorMode + 1) % 4

Mode 0: no overrides
Mode 1: C.sky/'#fff', C.dim_green/'#eee', garden._reset()
Mode 2: #g.style.filter = 'grayscale(1)'
Mode 3: _colorMode flag → blit() skips anim=false cell colors
```

Mode 1 saves original palette values and restores on mode exit.

### Justified text rendering (per line)

```
layoutWithLines → {lines}
  isLastLine = (i === lines.length - 1)
  segs = prepared.segments[line.start.segmentIndex .. line.end.segmentIndex]
  kinds = prepared.kinds[same range]
  widths = prepared.widths[same range]

  if isLastLine or segs.length <= 1:
    render <div class="ll">line.text</div>   // no justify
  else:
    wordWidthSum = sum(widths where kinds[i] === 'text')
    spaceCount = count where kinds[i] === 'space'
    extraPerSpace = (maxWidth - wordWidthSum) / spaceCount
    render <div class="ll ll-j">
      for each seg: <span style="margin-right: Npx">segText</span>
    </div>
```

---

## Implementation Units

- [ ] **Unit 1: Dev keybindings — season cycling and state dump**

**Goal:** `<`/`>` keys cycle seasons at runtime; `Shift+D` dumps current state to console; `Shift+G` toggles a grid overlay showing CW/CH, cols×rows, mouse position, FPS.

**Requirements:** R1, R2, R3

**Dependencies:** None (extends existing `wire()` keydown handler)

**Files:**
- Modify: `viewer-bnw.html`

**Approach:**
- Add `let _devSeason = null` global alongside existing dev globals
- Modify `getSeason()` to check `_devSeason` first (already checks URL param second)
- In `wire()` keydown handler, add dev block: `if (!isDevFixture) return` guard
- `<` (key `','`) / `>` (key `'.'`) — advance `_devSeason` through `['spring','summer','autumn','winter']` and call `garden._reset()`; log `[dev] season → X`
- `Shift+D` — log structured state object: season, CW/CH, cols×rows, visitCount, animalType/Tier/Triggered, giftDiscovered keys, isPostComplete, dueIdxs.length, `_colorMode`
- `Shift+G` — toggle `#dev-overlay` div (created on first use) absolutely positioned over `#g`; shows: `${cols}×${rows} cells | CW=${CW.toFixed(2)} CH=${CH} | mouse(${mouseCol},${mouseRow}) | FPS: N`; update on requestAnimationFrame; also show thin 1px grid lines every 10 chars via CSS background-image gradient

**Patterns to follow:**
- Existing `Shift+A` dev handler in `wire()` keydown block
- `_devSeason` pattern mirrors `_devAnimal` (already exists)

**Test scenarios:**
- Happy path: press `>` → season advances to next; garden re-renders with new weather; console shows `[dev] season → summer`
- Wrap: press `>` four times from winter → back to spring
- `Shift+D`: console object contains all expected keys; values match global state
- Grid overlay: `Shift+G` once → overlay visible; `Shift+G` again → hidden
- Non-dev fixture: none of the above keys trigger (gated by `isDevFixture`)

**Verification:**
- Seasonal weather changes are immediately visible on `<`/`>` keypress without page reload
- Grid overlay lines visually align with character cell boundaries when zoomed to 100% and 150%

---

- [ ] **Unit 2: Dev keybindings — color/background mode cycling**

**Goal:** `Shift+B` cycles through 4 color modes; `ScreenBuffer` gains `anim` tag for mode 3.

**Requirements:** R2, R5

**Dependencies:** Unit 1 (dev keydown block established)

**Files:**
- Modify: `viewer-bnw.html`

**Approach:**
- Add `let _colorMode = 0` global
- Add `let _savedPalette = null` for mode 1 palette save/restore
- `Shift+B` handler:
  - Mode 0 → 1: save `C.sky`, `C.dim_green`; override both to near-white; call `garden._reset()`; log `[dev] color: white-bg`
  - Mode 1 → 2: restore palette; remove any filter; apply `document.getElementById('g').style.filter = 'grayscale(1) contrast(1.2)'`; log `[dev] color: full-grayscale`
  - Mode 2 → 3: remove filter; set `_colorMode = 3`; log `[dev] color: bw-anim`
  - Mode 3 → 0: set `_colorMode = 0`; restore palette; call `garden._reset()`; log `[dev] color: default`
- In `ScreenBuffer` cell structure, add `anim: false` as default field
- In `ParticleLayer.blit()` and `CreatureLayer.blit()` — set `cell.anim = true` when writing
- In `GardenDOM.blit()`, for `_colorMode === 3`, apply `color: var(--text)` to span unless `cell.anim`

**Patterns to follow:**
- `C` object palette at line ~344; `setGroundBg()` for background override pattern

**Test scenarios:**
- Mode 0 → 1: background turns white; plant colors remain; no grayscale filter
- Mode 1 → 2: CSS grayscale filter applied; all colors desaturated; background white
- Mode 2 → 3: filter removed; plant chars appear in text color; particle rain / butterfly keep original color
- Mode 3 → 0: garden returns to default cream palette
- At each mode, `Shift+D` shows correct `_colorMode` value in console

**Verification:**
- Mode 1 (white-bg) makes grid misalignment clearly visible when zoomed — this is the primary QA tool for TODO 10e browser QA pass
- Mode 3 shows colored rain/butterflies on B&W plant background without CSS filter

---

- [ ] **Unit 3: Rabbit carrot feed animation**

**Goal:** When `f` is pressed and `animalType === 'rabbit'`, briefly display ASCII carrot art at the rabbit's position in the garden.

**Requirements:** R4

**Dependencies:** Unit 1 (dev keydown established — but carrot fires from `feedAnimal()`, not a dev-only key; it shows for all users when animal is rabbit)

**Files:**
- Modify: `viewer-bnw.html`

**Approach:**
- Carrot art (2 rows):
  ```
  "      ← row 0, orange #E8780A
  \/     ← row 1, orange #E8780A
  ```
- Animal home position: `CreatureLayer` renders the animal at a fixed col derived from `GardenState`. The home column is near the right side of the garden (for tier 0 peeking) or at a fixed interior position for tiers 1-3. Read `CreatureLayer` to find the exact `homeCol` calculation — it's likely `Math.floor(cols * 0.75)` or similar. Home row is near `groundRow`.
- On `feedAnimal()` call (before or after trust increment): create a `<div id="carrot-anim">` with two child spans, positioned `left: homeCol * CW`, `top: (groundRow - 2) * CH` inside `#g` using `position:absolute`
- Style: `color: #E8780A; font: 13px/15px 'Courier New'`; `pointer-events: none`; `z-index: 5`
- Auto-remove after 1500ms via `setTimeout`; if `f` is pressed again before timeout, clear existing and restart
- This fires for all users (not dev-only) — it's a game-feel response, not a dev tool

**Patterns to follow:**
- `#frb` first-run banner — absolutely positioned div over `#g` with auto-removal pattern (line ~212)
- `_devCycleAnimal` shows how to find CreatureLayer animal home position logic

**Test scenarios:**
- Happy path (rabbit, tier < 3): press `f` → orange `"` and `\/` appear at rabbit position for 1.5s then disappear
- Rapid re-press: second `f` clears existing carrot and restarts 1.5s timer
- Non-rabbit animal: no carrot (carrot is rabbit-specific; other animals might get their own art later)
- Tier 3 (bonded): `feedAnimal()` is a no-op; no carrot shown
- Unauthenticated: `f` is blocked by existing auth guard; carrot never shows

**Verification:**
- Carrot appears at grid-aligned position (not floating in a wrong location)
- No layout reflow — overlay div doesn't affect garden grid rows

---

- [ ] **Unit 4: Pretext — justified letter body**

**Goal:** Rewrite `renderBody()` to use segment-level span rendering for justified text. Non-last lines distribute extra whitespace across inter-word gaps using pretext's measured segment widths. Last line stays left-aligned.

**Requirements:** R6, R7

**Dependencies:** None (self-contained in `renderBody()`)

**Files:**
- Modify: `viewer-bnw.html`

**Approach:**
- Extend import to include `clearCache` from pretext (already imported from same module)
- Rewrite `renderBody(text, el)`:
  - `prepareWithSegments` call unchanged (already there)
  - `layoutWithLines(prepared, w, LETTER_LH)` unchanged
  - For each line (index `i`):
    - Extract `startSeg = line.start.segmentIndex`, `endSeg = line.end.segmentIndex`
    - Get segments: `segs = prepared.segments.slice(startSeg, endSeg + 1)`, same for `widths` and `kinds`
    - `isLast = i === lines.length - 1`
    - If `isLast` or word count ≤ 1: render `<div class="ll">` with `textContent = line.text` (existing behavior)
    - Else (justified line):
      - `wordWidthSum` = sum of `widths[j]` where `kinds[j] === 'text'`
      - `spaceCount` = count of `kinds[j] === 'space'`
      - `extraPerSpace` = `(w - wordWidthSum) / spaceCount` — extra px per space
      - Render `<div class="ll ll-j" style="display:flex">` with `<span>` per segment; space segments get `style="width: ${baseSpaceWidth + extra}px; flex-shrink:0"`; word segments just have `textContent`
  - Call `clearCache()` in `teardownResize()` to free canvas measurement memory

- CSS addition: `.ll-j { display:flex; align-items:baseline; } .ll-j span { white-space:pre }`

**Note on `prepared.segments` indexing:** The `start.segmentIndex` is absolute into `prepared.segments`. A line starting at segment 5 and ending at 9 gets `prepared.segments.slice(5, 10)`. The last grapheme partial-segment case (when `endGraphemeIndex < full-segment length`) needs handling: if `endSegmentIndex === startSegmentIndex + N` and the last segment is partial, use `line.text` for the last segment rather than the full segment string.

**Patterns to follow:**
- Existing `renderBody()` at line ~1474 — preserve the `_prepared`/`_preparedText` cache check

**Test scenarios:**
- Long body text: non-last lines render justified (words spread to fill container width)
- Last line: always left-aligned regardless of length
- Single-word line (rare, very long word): falls back to non-justified `textContent` div
- Empty body: `el.replaceChildren(frag)` with zero children — no errors
- Resize: `ResizeObserver` triggers re-render; justified layout recomputes for new width
- `teardownResize()`: `clearCache()` called → canvas measurement caches freed
- Letters with paragraph breaks (blank lines): blank-line segments render as empty divs, not justify targets

**Verification:**
- Letter body text fills the full column width on non-last lines, matching the visual weight of a typeset letter
- No width overflow (words don't extend past container)
- Resize preserves justification

---

- [ ] **Unit 5: Reading progress indicator**

**Goal:** Show a subtle scroll-progress bar and line count in the letter reading view, powered by pretext's `lineCount`.

**Requirements:** None (pure enhancement)

**Dependencies:** Unit 4 (pretext segment rendering already in place; `lineCount` from `layoutWithLines`)

**Files:**
- Modify: `viewer-bnw.html`

**Approach:**
- After `layoutWithLines`, store `_lineCount = result.lineCount`
- Add a 1px `<div id="lm-progress">` at the bottom of `#s-reading` (or as a pseudo-element on `#letter-body`) with `background: var(--text); opacity: 0.15; height: 2px; transform-origin: left; transition: transform 0.1s`
- On `scroll` event of `#letter-body`: `progress = scrollTop / (scrollHeight - clientHeight)`; `progressEl.style.transform = scaleX(progress)`
- Small text element `#lm-linect` showing `${_lineCount} lines` at opacity 0.2 in the letter header — only shown if `_lineCount > 20` (short letters don't need it)
- On `teardownResize()`, reset progress bar to 0

**Patterns to follow:**
- `.lm-label` and `.lm-date` elements in `#s-reading` for typography hierarchy

**Test scenarios:**
- Short letter (<20 lines): line count label hidden; progress bar shows but barely moves
- Long letter: scrolling from top to bottom animates progress bar from 0 to 1
- Resize: progress bar position resets; line count updates to new value
- Letter close (`teardownResize()`): bar resets to zero

**Verification:**
- Progress bar is visible but not distracting — opacity 0.15 is subtle
- Line count label does not clutter the letter header for short letters

---

## System-Wide Impact

- **Interaction graph:** `garden._reset()` reinitializes all five layers plus `GardenState` — color mode 0↔1 triggers this; all other modes are post-hoc filter/color overrides
- **State lifecycle risks:** `_devSeason` must be reset to `null` if the page is reloaded or a new bundle is loaded — add reset in `loadBundle()` prologue
- **API surface parity:** `clearCache()` is a new pretext import — add to the import line at line ~332
- **Unchanged invariants:** The existing `Shift+A` dev cycle and `f` feed key behavior are preserved; carrot is additive to `feedAnimal()`
- **Integration coverage:** Color mode 3's `blit()` override must not break when `anim` field is absent on old cells — default to `false`

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| `prepared.segments` slice indices off-by-one for partial last segments | Fall back to `line.text` for any line where segment slice fails — wrap in try/catch |
| Flex span rendering breaks for CJK or Arabic text | pretext handles bidi/CJK — but justified flex may fight bidi; fall back to plain text for lines with RTL segments (check `prepared.segLevels`) |
| Carrot position wrong for different trust tiers | Read CreatureLayer home position logic before implementing; unit test by visual check at all 4 tiers with Shift+A |
| Color mode 1 palette save/restore gets out of sync if user reloads | `_colorMode` and `_savedPalette` are transient; a reload always starts fresh at mode 0 |
| `clearCache()` in `teardownResize()` too aggressive (clears shared canvas cache) | pretext `clearCache()` only clears measurement caches, not DOM — safe to call on letter close |

## Sources & References

- pretext source: `https://cdn.jsdelivr.net/npm/@chenglou/pretext@0.0.4/dist/layout.js`
- pretext API: `prepare`, `prepareWithSegments`, `layoutWithLines`, `walkLineRanges`, `clearCache`
- Current usage: `viewer-bnw.html` line ~1472–1487 (`renderBody()`)
- Color palette: `viewer-bnw.html` line ~344 (`const C = {…}`)
- Existing dev pattern: `wire()` keydown, `Shift+A` dev cycle at line ~1562
