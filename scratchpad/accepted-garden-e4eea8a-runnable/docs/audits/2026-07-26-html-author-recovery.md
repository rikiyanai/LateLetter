# HTML author/editor recovery audit — 2026-07-26

**Task:** LL-AUTHOR-RECOVERY-20260726-02 · audit only, no product change.
**Repository state:** `main` at `b274797`, checkout carrying the integrated
PreText typography change to `viewer-bnw.html` (not touched by this audit).

**Inputs.** 22 screenshots and `capture-receipt.json` saved by the cancelled
pane `%72` under `docs/visual-review/2026-07-26/author-recovery/`, read only;
git history; the live viewer; the Python author modules; `docs/SPEC.md`,
`docs/GARDEN_PARITY.md`, `docs/FAILURE_LOG.md`.

**Method.** Every claim below is anchored to a commit, a file and line, or a
named screenshot. Where the receipt records a click sequence, the sequence is
quoted rather than paraphrased. No claim rests on recollection or on prose in
an earlier audit.

---

## 1. The correction, stated first

Two different things have been called "the HTML author," and conflating them
produced both the belief that an editor was deleted and the belief that no
editor ever existed. Neither is true.

| Term | What it actually refers to | Ever existed in the browser? |
|---|---|---|
| **Letter-author flow** — intake, Q&A, draft, review, seal, export/append | `src/lateletter/*.py`, reached by `lateletter --write` | **No. Never. Not in any commit.** |
| **Garden placement/diagnostic editor** — place object at kind/catalog/x/y, move, rotate, transplant, undo, journal | `#garden-controls` in `viewer-bnw.html` | **Yes — and it still exists today**, behind `?garden_debug=1` |

So the accurate sentence is: *the browser has never had a letter-author flow,
and it has continuously had a Garden placement editor since `ff13aee`, which
was progressively hidden rather than deleted.* The phrase "in some ways there
was an editor" is correct, and the thing it points at is the Garden panel.

The claim **"no editor existed"** is unsupported and this audit does not make
it. Commit `4cdebbb` calls the panel an "editor panel" and an "authoring
panel" in its own message; `viewer-bnw.html:1419` names a set
`unavailableWithoutEditor`. The codebase has used the word "editor" for this
surface throughout.

---

## 2. Full inventory of browser author/editor-like capability

Chronological. All dates from `git log --date=short`.

### 2.1 `ff13aee` — 2026-07-21 — "feat: transfer browser garden to canonical runtime"

Introduced the editor surface itself:

- the `#garden-controls` aside, and
- an unconditional HUD entry point, `mk('garden controls', …)`, appended in
  `showGarden()` for **every** reader including sealed-letter recipients.

Established by `git log -S"mk('garden controls'" -- viewer-bnw.html`, which
returns exactly `ff13aee` and `f3a8383` — introduction and removal.

### 2.2 `526ab9e` — 2026-07-21 — terminal garden interaction parity

The state preserved at `archive/deleted-browser-garden-526ab9e/` and captured
as **surface D**. The panel at this revision offered *pan left*, *pan right*,
*journal*, *undo*, **place plant**, *dwell*, *pause motion*, *back*, plus a
scrolling object list of 22 fixtures — visible in
`D_526ab9e_deleted_browser_garden__D2_standalone_garden_with_action_drawer.png`,
which reports "Garden at 0,0; 4 animals, 8 collectibles, 22 fixtures, 13
plants."

Placement at this stage took **no parameters**. `viewer-bnw.html:2909-2910` of
that revision:

```js
else if(action==='place'){
  args={object_kind:'plant',catalog_id:'lavender',x:10,y:10};
}
```

One button, one hardcoded lavender at (10,10). The screenshot's label reads
`[place plant]`, which corroborates the source: the parameterised form did not
exist yet.

The receipt also records that this build needed passphrase `garden` and that
`garden-biscuit-2026` was rejected — the archived bundle predates the current
demo passphrase. Console showed only the dev-fixture checksum warning.

### 2.3 `520f27b` — 2026-07-21 — "feat: replace browser garden with canonical renderer"

**What it removed.** 1,512 deletions against 796 insertions across 14 files, of
which `viewer-bnw.html` accounts for the bulk. Nine renderer classes present at
`526ab9e` are absent at `520f27b`, each confirmed by counting `class <Name>` on
both sides:

`GardenEngine`, `GardenVisualState`, `GardenDOM`, `ScreenBuffer`,
`BackgroundLayer`, `PlantLayer`, `CreatureLayer`, `ParticleLayer`,
`SpecialLayer` — plus `RNG` and `Particle` as recorded in the failure log's
ambient-birds entry.

**What it did not remove.** The editor. `grep -c "garden-controls"` returns
**6 at `526ab9e` and 6 at `520f27b`** — unchanged across the commit. Placement,
undo, journal, the object list and the action drawer all survived intact. This
commit replaced the *presentation* layer and left the *authoring* layer alone.

This is the single most-conflated fact in the prior audits: `520f27b` is
repeatedly cited as the commit that "deleted the browser Garden," and the
ambient-bird and five-layer losses genuinely do trace to it — but no editor
capability was lost there.

### 2.4 `7133771` — 2026-07-21 — secure Garden author and recipient flows

Upgraded placement from one hardcoded button to a real parameterised form.
`git log -S"place here" -- viewer-bnw.html` returns exactly this commit. The
form is the one still present today at `viewer-bnw.html:441-446`:

```html
<label for="garden-place-kind">place</label>
<select id="garden-place-kind"><option value="plant"><option value="fixture"></select>
<label for="garden-place-catalog">catalog</label>
<input id="garden-place-catalog" value="lavender">
<label for="garden-place-x">x</label><input id="garden-place-x" type="number" value="10">
<label for="garden-place-y">y</label><input id="garden-place-y" type="number" value="10">
<button data-garden-action="place">place here</button>
```

This is the high-water mark of browser authoring: kind selector, free-text
catalog id, integer coordinates, dispatched through the canonical runtime at
`viewer-bnw.html:2141-2145`. It matches the `docs/GARDEN_PARITY.md` row
"Reader chooses kind, catalog, x/y; move/rotate/undo use canonical validation."

### 2.5 `4cdebbb` — 2026-07-22 — "fix: frame garden camera on content, gate editor panel, restore to-chloe route"

The whole viewer change is **one line**:

```diff
-  document.getElementById('garden-controls').classList.toggle('open',name==='garden');
+  document.getElementById('garden-controls').classList.toggle('open',name==='garden'&&standaloneMode);
```

It restricted only the **auto-open on entering the garden screen**. The HUD
button from §2.1 was untouched, so a sealed-letter recipient could still open
the panel by clicking it. The commit message's claim that the panel "opens only
in standalone mode" overstates what the diff does — a discrepancy worth
recording, because later reasoning inherited the message rather than the diff.

### 2.6 `f3a8383` — 2026-07-26 — "fix: make the justified letter body actually render"

This commit's subject describes letter typography. It also changed **623 lines
of `viewer-bnw.html`** and is where the browser editor actually became
unreachable. `git log -S` places all three of the following in exactly this
commit, with zero occurrences at `f3a8383~1`:

- `GARDEN_DEBUG_REQUESTED` — `viewer-bnw.html:518`,
  `new URLSearchParams(location.search).get('garden_debug')==='1'`
- `gardenControlsEnabled()` — `viewer-bnw.html:591-594`,
  `Boolean(GARDEN_DEBUG_REQUESTED&&(standaloneMode||isDevFixture))`
- `unavailableWithoutEditor` — `viewer-bnw.html:1419`,
  `new Set(['move','rotate','transplant','open_journal'])`

It also renamed the HUD entry point from `garden controls` to
`garden diagnostics` (`viewer-bnw.html:1468`) and made it conditional on
`gardenControlsEnabled()` (`viewer-bnw.html:1467`).

**Finding.** A change of product-visible authority — removing the last
recipient-reachable route to the Garden editor — sits inside a commit whose
message discusses only text layout. Nothing in the message, and nothing in
`docs/FAILURE_LOG.md`, records it. Anyone reconstructing the editor's fate from
commit subjects will conclude it vanished at `520f27b`, which is wrong by five
commits and five days.

### 2.7 Current state — `HEAD` = `b274797` plus the checkout's typography change

| Surface | Screenshot | Editor reachable? |
|---|---|---|
| Standalone garden, default | `E_current_live_viewer__E2_standalone_garden_default.png` | **No.** Only "Choose a detail, or take a slow look around." and `[take a closer look]`. No controls button anywhere. |
| Standalone garden, `?garden_debug=1` | `F_..._F1_standalone_with_diagnostics_button.png` | Yes — a `[garden diagnostics]` button appears. |
| Diagnostics panel open | `F_..._F2_garden_diagnostic_panel_open.png` | Full editor: pan ×4, frame garden, journal, undo, **place `[plant ▾]` catalog `[lavender]` x `[10]` y `[10]` → `[place here]`**, dwell 30 seconds, pause motion, back, plus optional-sky region controls. |
| Sealed recipient, unlocked | `E_..._E3b_sealed_after_unlock.png`, `E4`, `E5` | No. Recipient path is welcome → garden → open letters → passphrase → inbox → reading. |

The panel is `hidden` in markup (`viewer-bnw.html:426`) rather than removed, so
its inputs remain in the DOM at all times. This produces a live coupling worth
flagging: `canonicalActionRequest` reads the editor's coordinate field when
moving a fixture —

```js
if(action==='move')return{intent:'move_fixture',args:{
  x:Number(document.getElementById('garden-place-x').value),   // viewer-bnw.html:1147
```

— which is precisely why `move` sits in `unavailableWithoutEditor`. The
recipient HUD must suppress `move`, because with the panel hidden the action
would silently take its destination from an invisible input holding a default
of 10. The suppression is a correct guard around an incorrect dependency.

### 2.8 Older preserved surfaces (A, B, C) — no editor at all

- **A** `dumpster/cleanup-2026-04-20/viewer.html`, 1,360 lines. Grep for
  authoring markers finds none; `hud-author` is a byline
  ("planted for you by …") and every `place*` hit is the layout generator's
  local `placed[]` array (lines 537-608). Recipient-only.
- **B** `archive/legacy-garden-7b9389d/viewer-bnw.html` — the orphan snapshot
  without companion files. The receipt records a 404 console error; the demo
  click cannot proceed. Not usable as evidence of capability.
- **C** `archive/legacy-repo-7b9389d/` — the same snapshot as a runnable
  sanitized repository. `C2`–`C5` show demo garden, sealed prompt, unlock, and
  archive. No authoring surface in any frame.

### 2.9 What the browser can write today

For the record, the browser is not read-only — it just cannot author a letter:

- Canonical world mutations (tend, feed, play, collect, place, move) dispatch
  through `dispatchGardenUi` (`viewer-bnw.html:1130`) into
  `web/garden-runtime.mjs`, which persists to browser storage
  (`garden-runtime.mjs:177` `persist()`, keyed at `:106` `storageKey`).
- `saveToText()` (`viewer-bnw.html:1994`) exports a **plain-text** copy of one
  letter. It does not write a bundle.
- Sky-region preference writes to `localStorage` (`viewer-bnw.html:2164`).

No code path in any commit writes a `.lateletter` bundle from the browser.

---

## 3. What is missing: the HTML letter-author end-to-end

Verified absent, not merely unobserved. Across the entire history,
`git log --all -S<term> -- viewer-bnw.html` returns **zero** commits for each
of `seal_bundle`, `s-author`, `compose`, `author-form`, `btn-seal`,
`new letter`, `write a letter`; and `git log --all -S'id="s-author"'` over all
paths returns nothing.

`docs/SPEC.md §13.2` defines the browser channel as a static artifact rooted at
`viewer-bnw.html` where "the recipient opens the deployed page …, drops or
selects their `.lateletter` file, enters the passphrase, and reads their
letters." Authoring is not part of the channel's definition.
`docs/GARDEN_PARITY.md` records the same row as "Recipient only."

The missing end-to-end, stated concretely, is every step the terminal owner
performs that has no browser counterpart:

1. **Intake** — author identity, recipient identity, relationship, key dates,
   shared tags; steward designation and wishes. (`intake.py`, `intake_tui.py`,
   `intake_accessible.py`)
2. **Question selection and Q&A** — `question_selector.py`, `qa_loop.py`.
3. **Draft and review** — `draft_editor.py`; revise before sealing.
4. **Scheduling and conditions** — when each letter becomes due; recurrence,
   missed-occurrence policy, DST handling.
5. **Garden program authoring** — the timeline editor at `author.py:1096`
   `_run_garden_timeline_editor`, with preview at `author.py:986`
   `_preview_author_timeline`.
6. **Seal** — passphrase confirmation, PBKDF2 + AES-GCM per message and gift,
   bundle HMAC, checksum. (`sealed.py`, `author.py:124`
   `_confirm_export_passphrase`)
7. **Export / append** — canonical bundle writer, v2 APPEND merge onto an
   existing bundle, with backups (`author.py:1223` `_backup_v1_bundle`,
   `:1233` `_backup_append_bundle`).
8. **Session persistence and resumption** — `session_store.py`,
   `session_resumer.py`; a dying author must be able to stop and resume.

Steps 1-4 and 6-8 have **no browser representation of any kind**. Step 5 is the
only one with a browser cousin, and the cousin is not the same thing: the
`#garden-controls` panel edits *live world state in the recipient's storage*,
whereas `_run_garden_timeline_editor` authors *a sealed program that travels
inside the bundle*. They operate on different objects at different times for
different people. Treating the panel as "the browser half of authoring" is the
category error that produced this audit.

---

## 4. Proposed canonical browser author boundary

One boundary, stated so that no surface is ambiguous:

> **The browser is a recipient runtime. It may mutate the recipient's own
> living Garden, and it may never originate, seal, or amend a bundle.
> Everything that travels inside a `.lateletter` file is authored by the Python
> owner and by nothing else.**

Three consequences, each of which removes a currently mixed authority:

**(a) The Garden placement panel is recipient tending, not authoring.**
Renaming it was the right instinct; the vocabulary should now be carried
through. It edits the recipient's world after delivery. Every remaining
occurrence of "author"/"editor" attached to it — `unavailableWithoutEditor`,
the `GARDEN_PARITY` phrase "Reader chooses kind, catalog, x/y", the `4cdebbb`
message — should be restated as tending vocabulary. The word *editor* should be
reserved for the terminal timeline editor.

**(b) The `?garden_debug=1` gate must be either promoted or retired — not
left as-is.** `SPEC §13.5` is explicit: "A feature exercised only by
`Shift+…`, a fixture-only shortcut, **URL seeding**, console mutation, or an
empty-HMAC bundle is not recipient-reachable and cannot satisfy §7.8.13."
Placement today is reachable only by URL seeding, so by the project's own rule
it currently counts as nothing. Two honest dispositions:

- *Promote:* placement becomes a normal standalone-garden control with a
  visible entry point, no URL flag, and the `#garden-place-*` inputs move out
  of a hidden aside so `move` stops reading invisible state
  (`viewer-bnw.html:1147`); `unavailableWithoutEditor` then shrinks to
  `open_journal` or empties.
- *Retire:* the panel is acknowledged as a QA harness under §13.5, and
  `move`/`rotate`/`transplant` are dropped from the projection's advertised
  action list for the browser so the projection stops offering actions the
  product cannot reach.

Leaving it gated is the status quo that generated the confusion: a real,
maintained, canonical-dispatch editor that no user can find.

**(c) The terminal Python owner keeps sole bundle authority, explicitly.**
Not by default or by omission — by a stated rule, so that a future browser
feature cannot quietly acquire half of it. The owner is `lateletter --write`
(`cli.py:5`, `:29`) over `author.py`, `intake*.py`, `qa_loop.py`,
`question_selector.py`, `draft_editor.py`, `session_store.py`,
`session_resumer.py`, `steward.py`, `sealed.py`, `bundle.py`.

If browser authoring is ever wanted, the only boundary that does not create
mixed authority is a **separate artifact**: a distinct author-only page that is
never delivered to recipients, is never referenced by `viewer-bnw.html`, is
excluded from `scripts/prepare_pages_site.py`, and reuses the same canonical
schema by producing byte-identical bundles. Adding an author mode *inside*
`viewer-bnw.html` would put sealing keys and recipient decryption in one
document and is rejected here on that ground alone.

---

## 5. Implementable staged flow

Each stage is independently deliverable and independently reversible. No stage
begins before the operator accepts the previous one.

**Stage 0 — vocabulary and record (docs only).**
Restate the panel as recipient tending everywhere it is described; add a
failure-log entry recording that `f3a8383` hid the editor and that `520f27b`
did not remove it. *Exit:* no document claims the editor was deleted at
`520f27b`, and none claims no editor existed.

**Stage 1 — decide the panel's disposition (one operator decision).**
Promote or retire, per §4(b). *Exit:* the decision is written down; the
`SPEC §13.5` evidence boundary is satisfied either way.

**Stage 2 — break the hidden-input coupling (viewer only).**
`canonicalActionRequest` must take its move destination from an explicit
argument rather than from `#garden-place-x`. *Exit:* `viewer-bnw.html:1147` no
longer reads DOM state that may be invisible; the `unavailableWithoutEditor`
suppression of `move` becomes a product choice rather than a safety guard.

**Stage 3 — if promoting: recipient-reachable tending.**
Visible entry point in standalone, no URL flag, keyboard reachable, labelled in
tending vocabulary. Sealed-letter recipients unchanged. *Exit:* every advertised
action is reachable without URL seeding, in a normal sealed production flow.

**Stage 4 — author boundary enforcement (tests only, no product change).**
A contract that `viewer-bnw.html` contains no bundle-writing capability: no
`seal_*`, no bundle serialisation, no author-session storage. This is the guard
that keeps §4's boundary from eroding silently, and it is cheap.

**Stage 5 — only if browser authoring is actually wanted: separate artifact.**
The author-only page described in §4(c), gated by its own review, never on the
Pages route. Not proposed as needed; recorded so that if it is ever built, it
is built at the right boundary.

---

## 6. Visual acceptance criteria

Same harness discipline as the PreText lane: real flows, painted evidence,
before and after at 1280×800 and 390×844, saved beside the existing 22 frames.

**A. Recipient path is unchanged and quiet.** Sealed demo, welcome → garden →
open letters → passphrase → inbox → reading. No controls, diagnostics, place,
move, rotate or transplant affordance appears in any frame. Compare against
`E1`–`E5` as the reference set.

**B. Standalone entry point matches the Stage 1 decision.** If promoted, a
visible control appears with no URL flag and `E2` changes accordingly; if
retired, `E2` is unchanged and `F1`/`F2` are reproducible only with the flag,
with a documented note that the panel is a §13.5 harness.

**C. Placement round-trips visibly.** Place a named catalog item at explicit
coordinates; the object appears at those coordinates in the projection, is
named in the accessible object summary, survives reload, and `undo` returns the
scene to the prior frame. Before/after frames plus the summary text.

**D. Move takes its destination from the action, not from a hidden input.**
With the panel shut, a move performed through any route lands where the action
said, not at (10,10).

**E. No mixed authority.** Nothing in the browser writes a `.lateletter`; the
Stage 4 contract runs; `scripts/prepare_pages_site.py` runs clean; no console
errors in any captured frame.

---

## 7. Remaining unknowns

1. **Whether the operator wants the placement panel at all.** §4(b) is a
   product decision this audit cannot make. Everything downstream of Stage 1
   depends on it.
2. **Why `f3a8383` carried the gating change.** The diff is unambiguous about
   *what* changed; the intent is not recorded anywhere, so whether hiding the
   editor was deliberate or incidental to a large refactor is unestablished.
3. **Whether `4cdebbb`'s message describes an intent that the one-line diff
   under-delivered**, or whether the author believed the HUD button was already
   conditional. Not determinable from the history.
4. **Behaviour of the archived surfaces beyond the captured clicks.** Surfaces
   B, C and D were exercised only along the sequences in
   `capture-receipt.json`. B is partly unusable (404). Any claim about their
   editor behaviour beyond `D2` would need new captures.
5. **Whether placement in a *sealed* world was ever exercised in production.**
   The panel was recipient-reachable between `ff13aee` and `f3a8383`, but no
   saved frame shows it opened over an authenticated bundle, so whether
   recipients ever edited a sealed garden is unknown. If any delivered bundle
   was read in that window, persisted world state may contain reader-placed
   objects.
6. **The `docs/FAILURE_LOG.md` entries this audit bears on cannot be updated
   here** — the path is forbidden to this lane. The entry *"Direct HTML review
   contradicts the claimed Garden composition…"* still attributes the loss
   solely to `520f27b`; §2.3 and §2.6 above supply the correction the root
   needs to apply.
