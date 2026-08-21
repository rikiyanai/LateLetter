# LateLetter Demo Script
## §24 Step 11a Part B — Emotional Arc Verification

Complete arc demo from cold start in ≤15 minutes.
Each section is one §6.9 moment, observable in the terminal or browser.

---

## Setup (one-time, ~1 min)

```bash
cd /path/to/LateLetter
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
```

---

## Moment 1 — The Waiting
**§6.9 criterion:** The garden before any letter arrives. Must feel like a place worth
returning to — weather moves, a creature visits, a plant sways. The ambient experience
IS the experience.

**Terminal:**
```bash
python3 demo_recipient.py --arc waiting --season autumn
```

**Browser:**
```bash
python3 demo_recipient.py --arc waiting --season autumn --browser
# Open URL, drag bundle file onto page
```

**What to observe (2 min):**
- Watch rain/leaves fall without pressing anything
- Does a butterfly or bird pass through?
- Does the garden feel like a place, or a loading screen?
- Is there any UI element shouting "nothing is here"?

**Pass criterion:** After 2 minutes you want to come back tomorrow.
**Fail mode:** Garden feels like a screensaver. You close it.

**Field note template:**
> _Moment 1 — [PASS/FAIL]:_ What worked: … What felt off: … Adjusted: …

---

## Moment 2 — The Delivery
**§6.9 criterion:** The letter-bird's appearance must feel like an event. A beat before
the recipient acts. Garden dims, anticipation before text appears. Letter feels like it
came from far away.

**Terminal:**
```bash
python3 demo_recipient.py --arc delivery
# Passphrase: "biscuit" (any passphrase works in dev mode)
```

**Browser:**
```bash
python3 demo_recipient.py --arc delivery --season spring --browser
```

**What to observe:**
- Watch from launch: does the bird arrive before you press anything?
- Press `e` to unlock — watch the garden dim
- Does the 1.5s verification spinner create weight?
- Read the letter — does it feel like it came from somewhere?

**Pass criterion:** The pacing creates occasion; the letter has weight.
**Fail mode:** Bird spawns → `e` pressed → overlay appears. Feels like an alert.

**Field note template:**
> _Moment 2 — [PASS/FAIL]:_ What worked: … What felt off: … Adjusted: …

---

## Moment 3 — The Animal Trust Arc
**§6.9 criterion:** Each tier transition perceptible and earned. Tier 0 skittish → tier 1
keeps distance → tier 2 approaches (feedable) → tier 3 bonded, stays.

Run all four tiers in sequence (use `Shift+A` shortcut in browser to cycle):

**Tier 0 — first glimpse (waiting arc, rabbit triggered):**
```bash
python3 demo_recipient.py --arc waiting
# Rabbit peeks from right edge after first visit
```

**Tier 1:**
```bash
python3 demo_recipient.py --arc trust1
```

**Tier 2:**
```bash
python3 demo_recipient.py --arc trust2
# Press 'f' to feed the rabbit
```

**Tier 3 (bonded):**
```bash
python3 demo_recipient.py --arc trust3
```

**Browser (all tiers):**
```bash
python3 demo_recipient.py --arc trust3 --browser
# Use Shift+A to cycle all 16 animal states (4 animals × 4 tiers)
```

**What to observe:**
- Is each tier visually distinct from the last?
- Does tier 3 feel like something the garden chose to give?
- No numeric progress bars anywhere?

**Pass criterion:** Relationship deepening is perceptible without explanation.
**Fail mode:** Tiers look nearly identical. The animal presence goes unnoticed.

**Field note template:**
> _Moment 3 — [PASS/FAIL]:_ What worked: … What felt off: … Adjusted: …

---

## Moment 4 — Post-Completion
**§6.9 criterion:** When the delivery mission is complete, the garden marks it without
a "thank you" screen. Memorial flower grows, bird stays permanently. Garden has changed
— but hasn't ended.

**Terminal:**
```bash
python3 demo_recipient.py --arc postcomplete
```

**Browser:**
```bash
python3 demo_recipient.py --arc postcomplete --browser
```

**What to observe:**
- Open the garden. Is the memorial flower `✿` visible in magenta?
- Is a bird perched permanently (not the letter-bird animation)?
- Open the archive (`letters` button) — is the footer "All letters delivered. This garden is yours."?
- Does the garden feel like a memorial — quiet, present, complete?

**Pass criterion:** The moment lands. Garden has clearly changed. It hasn't ended.
**Fail mode:** Post-complete garden looks nearly identical to normal. Moment passes unnoticed.

**Field note template:**
> _Moment 4 — [PASS/FAIL]:_ What worked: … What felt off: … Adjusted: …

---

## Moment 5 — Item Discovery
**§6.9 criterion:** When a triggered item appears, it must feel discovered, not delivered.
Item present in garden scene. Memory overlay reads like a note left in the soil — personal,
unhurried, surprising. Not a push notification.

**Terminal:**
```bash
python3 demo_recipient.py --arc item
# Press 'i' to examine — memory overlay appears
```

**Browser:**
```bash
python3 demo_recipient.py --arc item --season winter --browser
```

**What to observe:**
- Is `i · examine` visible in the status bar (terminal) or HUD (browser)?
- Press `i` — does the memory overlay feel like reading a handwritten note?
- Read the sentiment text aloud. Does it sound like the author speaking to the recipient?
- Is the item rendered in the garden scene itself?

**Pass criterion:** Reading the sentiment aloud feels personal and unhurried.
**Fail mode:** Memory overlay text is generic or announcement-style. Feels like a feature.

**Field note template:**
> _Moment 5 — [PASS/FAIL]:_ What worked: … What felt off: … Adjusted: …

---

## Full Arc Run (≤15 min)

Run all five moments in sequence:

```bash
# 1. Waiting (2 min observation)
python3 demo_recipient.py --arc waiting --season autumn

# 2. Delivery
python3 demo_recipient.py --arc delivery

# 3. Trust progression (spot check tier 2)
python3 demo_recipient.py --arc trust2

# 4. Post-completion
python3 demo_recipient.py --arc postcomplete

# 5. Item discovery
python3 demo_recipient.py --arc item
```

Or generate all browser fixtures at once:
```bash
python3 demo_recipient.py --arc all --browser
```

---

## Author Flow Demo (Part C, separate)

```bash
python3 demo_author.py
# Intended to produce demo_output.lateletter in ≤60s
```

Current audit note (2026-04-27): `demo_author.py` currently writes `bundle.to_dict()` directly and does not compute the bundle checksum first. Do not use its output as proof of a valid export or terminal-recipient-ready handoff until that path is fixed in code.
Deferred until checksum/export wiring is fixed:
- Terminal validation of `demo_output.lateletter`
- Browser validation of `demo_output.lateletter` as a canonical export artifact

---

## Ship Gate

All five moments must receive explicit PASS from a human observer before proceeding to
step 13 (encryption). Document field notes above. If any moment FAILS, file a bug and
fix before re-running this script.

**Status:** [ ] Moment 1  [ ] Moment 2  [ ] Moment 3  [ ] Moment 4  [ ] Moment 5
