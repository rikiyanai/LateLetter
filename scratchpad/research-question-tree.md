# LateLetter — stage cut confirmation + proposed question tree

Read-only research. Nothing in the repository was modified.
Verified branch at start: `restore/pre-jul19-viewer` @ `d770454c5b9e665881030b4be301907aa0662d9d`.

Sources read:
- `/Users/r/Projects/LateLetter/author.html` (774 lines, seven `<section class="stage">`)
- `scratchpad/spec-authoring-questionnaire.md` §4.1, §4.2, §4.6, §4.7
- `scratchpad/audit-author-lane.md` (element inventory)
- `/Users/r/Projects/LateLetter/docs/SPEC.md` §5.1, §5.2, §5.3, §5.4, §5.6, §9.1

---

# PART A — The stage cut

## A.0 Verdict in one line

**Confirm the substance of the cut, reject the count.** The MVP should present **five counted
stages plus one uncounted door**, not six counted stages. Three changes to the proposal:
demote `resume` out of the progress rail, move the passphrase hint from `people` to `export`,
and **dissolve** `questions` into the `letters` stage rather than hiding it entirely.

| # | stage | proposal (§4.1) | **my recommendation** | change |
|---|---|---|---|---|
| — | `resume` | KEEP as stage 1 | **KEEP, but UNCOUNTED** — a door, not a step | demoted |
| 1 | `people` | KEEP, re-scoped | **KEEP, re-scoped further** — hint moves out, timezone moves out | trimmed |
| — | `questions` | HIDE | **DISSOLVE INTO `letters`** — the stage dies, the questions ship | changed |
| 2 | `letters` | KEEP — the spine | **KEEP — the spine, now carrying the prompt drawer** | grown |
| 3 | `gift` | REPLACE `garden` | **KEEP as proposed** | — |
| 4 | `review` | KEEP | **KEEP** — and do not merge with export | — |
| 5 | `export` | KEEP | **KEEP** — now also owns the hint | grown |

Counted length the author sees: **5**. Stages that actually demand input: **3** (`people`,
`letters`, `export`), with `gift` passable in one click and `review` asking nothing.

## A.1 Rationale, per stage

**`resume` — demote out of the rail.**
It asks nothing. Counting it tells a returning author "you are 1 of 6" before they have entered
a single character, and it spends a rail slot on a screen they will see every session. It stays
first-class (SPEC §5.6 requires it; it is the only place `GET /api/author/session` becomes
visible) — it is simply a full-page interstitial *before* the rail appears. Perceived flow
length drops from 6 to 5 at zero functional cost. Reversible: no markup change, just
`MVP_STAGES` membership plus a separate render path.

**`people` — keep, trim to four questions.**
This stage is the right opener: naming the two people is what makes the thing real, and
`author_name` is required by `#preview-from` before the letters stage can render its preview
truthfully. But it currently carries two fields that do not belong to it:

- *`#f-hint` moves to `export`.* Asking "the passphrase reminder they will see" before a
  passphrase exists makes the author invent a cue for a secret they have not chosen. §4.1
  already concedes the awkwardness — it has to special-case echoing the stage-2 hint into
  `#f-reminder-check` at stage 7. Put them side by side and `#f-reminder-check` becomes a live
  echo instead of a cross-stage patch. **This contradicts SPEC §5.1's stated ordering**
  ("shown immediately after the passphrase is confirmed during intake… ensures the warning
  fires even if the author loses capacity"), so it is an operator decision, not a free move.
  My argument for overriding: an author who loses capacity before export has no passphrase
  either, so there is nothing for a hint to point at; §5.6 hands the passphrase to a steward,
  and the steward should write the hint too.
- *`#f-timezone` stops being a required select.* Auto-detect from
  `Intl.DateTimeFormat().resolvedOptions().timeZone` and render it on the `letters` stage as a
  one-line confirmable sentence beside the date field, where it is the only place it means
  anything. A required dropdown on the second screen of a letter-writing app is pure
  drop-off. No schema change — `author_timezone` is still emitted.

**`questions` — dissolve, do not merely hide.**
Hiding the *stage* is correct and I agree with the reasoning (empty container, no catalog,
tree under re-research, FL:13160). But the conclusion "the MVP has no questions" is the wrong
one to draw from it. A questionnaire with no questions is a form, and the single largest
drop-off risk in this whole product is an author facing an empty `#f-letter-body` textarea.

Two independent reasons the stage shape was wrong anyway:

1. **SPEC §5.3 puts the Q&A *inside a message*, not in a global stage.** "LLM generates an
   opening question relevant to this specific message (e.g., for '30th birthday'…)". A global
   `#question-list` card set answered once, before any letter exists, is not what the spec
   describes and cannot become it later without being thrown away.
2. **A prompt that is answered into its own box needs somewhere to store the answer.** A
   prompt that seeds the letter body needs nothing. The second shape is free; the first is a
   schema change for no gain.

So: `#question-list` and `#btn-add-question` stay dark, the `questions` section stays in the
markup untouched (per the hiding rule), and the tree in Part B ships as an inline drawer beside
the body textarea on the `letters` stage. Cost: one collapsible panel. Benefit: the product
does the thing its own name promises.

**`letters` — keep as one stage. Do not split.**
There is a tempting split (a letter *list* stage, then a *write* stage). Reject it: the tab
strip already is the list, and splitting puts a stage boundary in the middle of the only task
that matters. The stage grows instead — shape chooser, prompt drawer, timezone confirm line —
and that growth is the right place for it, because it is the one stage an author will spend
real time on and will return to across sessions.

**`gift` — keep as proposed, with one requirement.**
It is 50% of the operator's own MVP scope definition, so it cannot be buried inside `review`.
But it must be passable in a single click with "not this time" as the default, and the rail
must not mark it unsatisfied when skipped. If the operator later wants four counted stages, the
correct merge is `gift` into `review` as an optional card — *not* dropping it.

**`review` and `export` — keep separate. Do not merge.**
The merge is tempting (review asks nothing; export is the gate). Reject it for two reasons.
The passphrase field must not be on screen while the author is still editing letters, and
"read it back" is the moment the thing becomes final — putting a password box next to it rushes
the one screen that should be slow.

## A.2 What genuinely cannot be deferred

Everything that a `.lateletter` file cannot be produced without, and nothing else:
`author_name`, `recipient_name`, one letter with a date and a non-blank body, a passphrase, a
hint (UI-required by SPEC §5.1), and `garden_beats: {author_timezone, beats: []}` — which the
author never sees. That is six required answers total. The tree in Part B keeps it at six.

## A.3 Drop-off note

Every stage boundary loses people, but stages that *ask nothing* are cheap (a click) and stages
that ask a lot are expensive. The proposal's six-stage flow has two ask-nothing stages counted
in the rail (`resume`, `review`), which inflates the perceived length by a third for no
information gained. Demoting `resume` removes half of that inflation; `review` has to stay
counted because it is where errors surface.

---

# PART B — The question tree

## B.1 What the outside research actually says

### B.1.1 Ethical wills / legacy letters — the established genre

The genre has a stable shape, and it is a *sequence*, not a checklist. Across Barry K. Baines
(*Ethical Wills: Putting Your Values on Paper*; *The Ethical Will Writing Guide Workbook* —
designed to produce a draft in about an hour), the Jewish Community Foundation LA workbook, and
Trust & Will's guide, the order is consistently:

> greeting → why I am writing → **two or three stories** → the values behind those stories →
> blessings and hopes → gratitude, apology, forgiveness.

Two things in that order matter and are usually got wrong in software: **story comes before
value** (the value is derived from the story, not asserted), and the hard material —
apology and forgiveness — sits **at the end but not last**; the blessing does not come after it.
The genre's own writing advice: *"Write as if you are speaking to one person at the kitchen
table. Use short sentences where the emotion is strong. Keep the language specific."*

### B.1.2 Dignity Therapy (Chochinov) — the strongest artifact in the corpus

Harvey Max Chochinov's Dignity Therapy is a randomised-trial-tested palliative intervention
built from interviews with people living with advanced illness. It uses nine questions and
produces a **"generativity document"** the patient keeps or gives away — structurally the same
object LateLetter produces. The protocol, in order:

1. "Tell me a little bit about your life history; particularly the parts that you either
   remember most or think are the most important?"
2. "When did you feel most alive?"
3. "Are there specific things that you would want your family to know about you, and are there
   particular things you would want them to remember?"
4. "What are the most important roles you have played in life (family roles, vocational roles,
   community-service roles, etc.)? Why were they so important to you and what do you think you
   accomplished in these roles?"
5. "What are your most important accomplishments, and what do you feel most proud of?"
6. "What have you learned about life that you would want to pass along to others?"
7. "What advice or words of guidance would you wish to pass along to your [son, daughter,
   husband, wife, parents, other(s)]?"
8. "What are your hopes and dreams for your loved ones?"
9. "Are there words or perhaps even instructions you would like to offer your family?" —
   closing with **"Are there other things that you would like included?"**

Three design lessons LateLetter should steal outright:
- **Q2 is the best single question in the entire corpus** (see B.4).
- Q9's closer exists because the protocol *knows* it will have missed the thing that mattered.
  Every letter should end with that offer.
- The protocol never asks about death. Not once. It asks about life and lets the context do
  the rest.

### B.1.3 Stanford Letter Project — the seven tasks of life review

Stanford Medicine's Letter Project (Friends and Family Letter template) sequences life review
into seven tasks, and the sequence is the best-ordered one available because it climbs:

1. Acknowledge the important people in your life
2. Remember treasured moments
3. Apologize to those you love if you hurt them
4. Forgive those who love you if they have hurt you
5. Express gratitude for the love and care you received
6. Tell your friends and family how much you love them
7. Take a moment to say goodbye

Easy → heavy → warm → close. Tasks 3 and 4 are deliberately in the middle. LateLetter's drawer
bands (B.3) follow this shape.

### B.1.4 Byock's Four Things

Ira Byock (*The Four Things That Matter Most*), from 25+ years of palliative practice: four
sentences, eleven words — **"Please forgive me," "I forgive you," "Thank you," "I love you."**
His finding is that patients who reached positive life closure were the ones not afraid to say
these. This is the highest-density thing in the literature and belongs in LateLetter twice:
as an opt-in prompt band, and as a quiet, non-scoring readback at `review`.

### B.1.5 The curated life-question genre (StoryWorth, guided journals)

StoryWorth's ~13 categories (childhood, education, parenthood, family and home, love and
friendship, work life, hobbies, travel, traditions, spirituality, military, thought-provoking,
challenges) and the *Dad, I Want to Hear Your Story* style journals share one operating
principle, and StoryWorth states it explicitly:

> Rewrite *"How did you decide when to change jobs?"* as
> *"How did you decide when to leave your job in city government?"*

**Specificity is what converts a question into an answer.** A generic question gets a shrug;
a question that names the actual thing gets a story. Their sequencing is easy → deep by
category (childhood and family first, "reflections and wisdom" and "legacy and perspective"
last), one question per week — i.e. the genre solves pacing with *time*, which LateLetter
cannot do, so it must solve it with *bands* instead.

The strongest individual questions in that corpus, for our purposes:
"What do you hope your children remember about their childhood?" · "Did your parents have any
sayings or expressions you still use?" · "Who in your family made you laugh the most?" ·
"What do you wish you had known sooner?" — note that all four are about the *ordinary*, not the
momentous.

**Direct consequence for LateLetter:** we know `recipient_name`. Every prompt must interpolate
it. That is the specificity lesson, and it is free.

### B.1.6 Milestone-letter practice

Guidance for parents writing letters to children for future milestones converges on a concrete
starting set — **three to five letters: one joyful milestone (graduation), one relationship
milestone (a wedding or partnership), and one "hard day" letter** for heartbreak, anxiety, or
feeling lost. Plus two craft rules:

- *Values, not control.* "Instead of 'Always do X,' aim for 'Here's what I hope you remember.'"
- *For the hard-day letter, tell what actually helped you — not how heroic you were.*

The **hard-day letter is the one nobody thinks to write and the one that gets used most.** It is
the strongest argument for a letter-shape chooser (B.3, item L0).

### B.1.7 Grief and bereavement literature

- **Continuing bonds** (Klass, Silverman & Nickman, *Continuing Bonds: New Understandings of
  Grief*, 1996): the bereaved need the relationship to *continue*, not to close. Letters
  structured purely as a farewell work against the mechanism that actually helps.
- **Childhood bereavement research**: children want to be told, and adults' reluctance to speak
  about death is itself the barrier. A letter that is coy about why it exists fails the child.
- **Anticipatory-bereavement practice** (Eluna's "Give Your Child Permission to be Happy"):
  tell them, in writing, to laugh and play and love without guilt — that the way to honour you
  is to live well. Survivor testimony repeatedly names *permission* as the thing they needed
  most and did not receive.

## B.2 The biggest thing missing from typical legacy letters

**Permission.** The genre's templates are near-universally about transmission — values, wisdom,
stories, advice, blessing. Almost none of them ask the writer to *release* the reader. Nobody is
prompted to write "you are allowed to be happy", "you are allowed to be angry at me", "you are
allowed to stop reading these", "you are allowed to love someone else". The bereavement
literature says those sentences are the load-bearing ones; the ethical-will literature does not
ask for them. That gap is a product opportunity and it is Band D below.

A close second, and the same failure in a different coat: **legacy letters are abstract.** They
give values and advice because that is what the dying want to hand over — but what the bereaved
treasure is the ordinary and sensory: how you made coffee, what you hummed, what you were like
on a Sunday. A letter of pure values is a letter about the writer's ideas; a letter with one
Sunday in it is a letter with the writer in it. Band A forces at least one.

## B.3 The proposed tree

**Legend**
`[R]` required · `[O]` optional
`META` → becomes a bundle/draft field · `SEED` → becomes letter body content, stored nowhere on
its own · `SHOW` → the app tells, it does not ask
`⚠` emotionally heavy: never first in a panel, never the last thing on screen, always opt-in
`※` needs a schema change (itemised in B.5)

---

### Door — `resume` (uncounted). Asks nothing.

---

### Stage 1 — `people` — "Who these are for" — 4 questions

Rationale: naming the two people is what makes the file real, and `author_name` is needed
before the letters preview can be truthful. Trimmed to four so the second screen is not a form.

| id | wording | kind | req |
|---|---|---|---|
| P1 | **"What do they call you?"**<br>note: *"This is how you are named at the top of every letter. 'Dad' is as good an answer as your name."* | META `author_name` | [R] |
| P2 | **"And who are you to them?"**<br>placeholder: *their mother · their oldest friend · their grandfather* | META `author_relationship` ※ | [O] |
| P3 | **"Who are you writing to?"**<br>note: *"Used here to keep the letters straight, and to name the file you save."* | META `recipient_name` ※ | [R] |
| P4 | **"Who are they to you?"**<br>placeholder: *daughter · oldest friend* | META `recipient_relationship` ※ | [O] |

**Moved off this stage:** `#f-hint` → stage 5. `#f-timezone` → shown on stage 2 as a confirm
line. `#f-seed` → hidden, constant (as §4.2.3 already specifies).

**Deliberately rejected here:** "In three words, what are they like?" — warm, cheap, and has
nowhere to go without a storage key. Discipline: do not ask what cannot be kept.

---

### Stage 2 — `letters` — "The letters" — 4 metadata + 23 prompts

Rationale: the spine. Every prompt below is a **SEED** — clicking it inserts text into
`#f-letter-body` and the prompt disappears. Nothing is stored as its own answer, so the entire
drawer is **zero schema change**.

#### 2a — the shape chooser (offered only when a letter's body is empty)

Rationale: from milestone-letter practice (B.1.6). Four shapes instead of a blank page. The
choice is not persisted — it only appears while the body is empty, so reopening a written
letter never re-asks.

| id | wording | kind | req |
|---|---|---|---|
| L0 | **"What kind of letter is this?"**<br>· **a good day** — *"a day I know is coming, and I want to be there for it"*<br>· **a hard day** — *"the day something goes wrong and I am not there"*<br>· **an ordinary day** — *"no occasion. Just so there is one more."*<br>· **the first one** — *"the letter they open before any other"* | SEED (routes the drawer) | [O] |

#### 2b — the three fields

| id | wording | kind | req |
|---|---|---|---|
| L1 | **"When should they be able to open this?"**<br>note: *"This date is not encrypted. Anyone holding the file can see a letter exists for this day — but not a word of it."*<br>confirm line: *"Dates are read in Asia/Tokyo. change"* | META `messages[].date` + `author_timezone` | [R] |
| L2 | **"What should this one be called in their list?"**<br>placeholder: *On your wedding day*<br>note: *"Sealed with the letter. They will not see it until they can open it."* | META `messages[].label` | [O] |
| L3 | **"What do you want to say to {recipient}?"** | **BODY** `messages[].body` | [R] |

*On the hard-day letter having no natural date* — TBD dates are outside MVP scope and the schema
cannot express one. Do not add a schema field; add a sentence:
> **"A hard day has no date. Give it one anyway — pick a day early enough that it is already
> waiting when they need it."**

#### 2c — Band A · grounding (always shown, low intensity, 3 prompts)

Rationale: SPEC §5.3's own selector calls for "2-3 low-intensity universal questions before
introducing more specific prompts". A2 and A3 are where the abstraction failure (B.2) is
answered.

| id | wording | ⚠ | req |
|---|---|---|---|
| A1 | **"Tell {recipient} about a day with them you would live again."**<br><sub>adapted from Chochinov Q2 + Stanford task 2, pinned to the recipient</sub> | | [O] |
| A2 | if `recipient_relationship` reads as a child: **"What did they do, when they were small, that you have never told them about?"**<br>otherwise: **"What is something they did that you have never told them you noticed?"** | | [O] |
| A3 | **"What is something ordinary about you that you would not want them to forget — the way you made coffee, a song you hummed, what you were like on a Sunday?"** | | [O] |

A2's branch is a two-way string check on one optional field. No schema change; if
`recipient_relationship` is blank, use the second wording.

#### 2d — Band B · this letter's own occasion (10 prompts, routed by L0)

| id | shape | wording | ⚠ | req |
|---|---|---|---|---|
| B1 | good day | **"What do you hope they are feeling today?"** | | [O] |
| B2 | good day | **"What do you want them to know that they will be too happy to ask?"** | | [O] |
| B3 | good day | **"Who else should be in the room, and what would you say about them?"** | ⚠ | [O] |
| B4 | hard day | **"Write the first sentence they need to read. Not advice — just the sentence."** | | [O] |
| B5 | hard day | **"Tell them about a time you were where they are now. What actually helped — not what you wish had helped."** | | [O] |
| B6 | hard day | **"What are they allowed to do today that they think they are not allowed to do?"** | | [O] |
| B7 | ordinary | **"What would you be saying to them right now, if this were an ordinary afternoon?"** | | [O] |
| B8 | ordinary | **"Tell them something small and true that has nothing to do with any of this."** | | [O] |
| B9 | first one | **"Say why there are letters."** | ⚠ | [O] |
| B10 | first one | **"Tell them how to use these — all at once, one at a time, or never. Whatever you actually mean."** | | [O] |

B9 is the childhood-bereavement finding (B.1.7): a letter that is coy about why it exists fails
the reader. It is heavy, so it is opt-in and never the first card.

#### 2e — Band C · the four hard ones (opt-in panel, 4 prompts)

Panel label: **"the four hard ones"**
Panel note: *"Palliative-care doctors find these are the four things people most regret not
saying. Open them when you want them, not before."*
Placement rule: this panel is **collapsed by default**, sits below Bands A and B, and is never
the last thing on the screen — Band E always follows it.

| id | wording | ⚠ | req |
|---|---|---|---|
| C1 | **"What are you thanking them for? Be specific — 'thank you for everything' is the sentence people remember as meaning nothing."** | ⚠ | [O] |
| C2 | **"What do you want to be forgiven for?"** | ⚠ | [O] |
| C3 | **"What do you want to forgive them for — and can you say it without making it a debt?"** | ⚠ | [O] |
| C4 | **"Say 'I love you' in your own words, in a way only you would say it."** | ⚠ | [O] |

#### 2f — Band D · permission (opt-in panel, 5 prompts) — the band the genre is missing

Panel label: **"the ones nobody writes"**
Panel note: *"People who have lost someone say these are the sentences they most needed and
almost never got."*

| id | wording | ⚠ | req |
|---|---|---|---|
| D1 | **"Tell them they are allowed to be happy. Say what living well would look like to you, so that it does not sound like a rule."** | ⚠ | [O] |
| D2 | **"Tell them they are allowed to be angry at you."** | ⚠ | [O] |
| D3 | **"Tell them they are allowed to stop reading these."** | ⚠ | [O] |
| D4 | shown when `recipient_relationship` reads as a partner: **"Tell them they are allowed to love someone else."** | ⚠ | [O] |
| D5 | **"Is there anything you would not want them to do — and are you willing to say it is theirs to decide?"** | ⚠ | [O] |

D5 encodes the "values, not control" rule (B.1.6) into the question itself rather than into a
tooltip nobody reads.

#### 2g — Band E · the closer (1 prompt, last on every letter)

| id | wording | ⚠ | req |
|---|---|---|---|
| E1 | **"Is there anything else you want in this letter?"** | | [O] |

Straight from the Dignity Therapy closer. It exists because any set protocol will miss the
thing that mattered. It must be the last prompt offered on every letter, in every shape.

---

### Stage 3 — `gift` — "Something to leave for them" — 6 questions

Rationale: 50% of MVP scope by the operator's own definition, so it stays counted — but it must
be passable in one click and must never mark the rail unsatisfied when skipped. Every question
maps to the one `garden_beats` beat of §4.6. **No question here touches a garden feature that
does not exist.**

| id | wording | kind | req |
|---|---|---|---|
| G1 | **"Do you want to leave one thing in the garden for them?"** — default **"not this time"**<br>note: *"The garden is there either way. This only adds one small thing that appears on a day you choose."* | META (gates the beat) | [R] |
| G2 | **"Which one?"** — a coffee mug · an ice cream cone · a mixtape · a popsicle<br>note: *"None of these are grand. That is the point — pick the one that would make them laugh, or the one that is already yours."* | META `entities[].catalog_id` | [R] if G1 |
| G3 | **"What day should it be there?"** | META `schedule.start` | [R] if G1 |
| G4 | **"Every year on this day?"**<br>note: *"Forever, unless they stop opening the garden."* | META `recurrence.intentional_unbounded` | [O] |
| G5 | **"Which letter should it hand them?"** — select over the letters written in stage 2 | META `letter.present` → `MESSAGE_<n>` | [R] if G1 |
| G6 | **"Where should it sit?"** — on the path · by the bench · somewhere in the garden<br>note: *"Roughly there. The garden picks the exact spot."* | META placement hint | [O] |

**Copy requirement, not a question** (`schedule.missed: deliver_on_next_visit` is hardcoded and
the author will wonder): *"If they do not open the garden that day, it waits for them."*

**Deliberately rejected here:** anything about plants, weather, seasons, animals, a second gift,
or a coordinate. Not built, not accepted, or actively unsafe (`authored` placement can validate
at export and throw at the recipient — §2.10). G6's note is worded loosely on purpose because a
missing anchor degrades silently to random placement (FL:1034, still OPEN) — the copy must not
promise a place the renderer cannot guarantee.

---

### Stage 4 — `review` — "Read it back" — asks nothing, shows three things

| id | what it shows | kind |
|---|---|---|
| V1 | one line per letter: *"MESSAGE 1 — 14 Jun 2032 — 'On your wedding day' — 412 words"* | SHOW |
| V2 | **"Some people want to check they said the four things. Look?"** — behind one click, phrased as absence and never as failure: *"nothing here yet about forgiveness — that is a fine choice, and it is also easy to forget."* | SHOW |
| V3 | **"These dates are visible to anyone holding the file: …"** — restate the plaintext-date fact once, at the end, where it is actionable | SHOW |

V2 is a client-side scan of letter bodies the browser already holds. **It must never be
transmitted, never stored, and never block export.** It is Byock's four things (B.1.4) offered
as a mirror, not a grade. If it cannot be built without feeling like scoring, cut it — the risk
of making a dying author feel marked is larger than the benefit.

---

### Stage 5 — `export` — "Lock it" — 3 questions

| id | wording | kind | req |
|---|---|---|---|
| X1 | **passphrase**, twice.<br>note: *"Four unrelated words beats one clever word. At least 12 characters."* | **never stored** — read at submit time only | [R] |
| X2 | **"What should the reminder say?"** *(moved here from `people`)*<br>note: *"They may not think about this for years. Write the cue you would give if you could only say one sentence. Never the passphrase itself — this line sits outside the lock."*<br>placeholder: *the road behind grandma's house* | META `passphrase_hint` | [R] (UI, per SPEC §5.1) |
| X3 | **"Is there someone who will make sure they get this?"** — name, and how to reach them<br>note: *"Their name goes in the note beside the file, so whoever finds it knows who to ask."* | META `steward_name` / `steward_contact` ※ | [O] |

**X3 is the highest-value deferred field in the whole SPEC** — a bundle nobody delivers is a
bundle that failed — but it needs a schema change *and* handoff-README work (SPEC §15.1). If it
cannot ship in the MVP, replace it with a sentence that costs nothing and stores nothing:
> **"Tell one person this file exists."**

**Not a question, but required** (SPEC §5.4 steps 6-7, absent from `author.html` today): the
passphrase-loss warning and the backup guidance, rendered after a successful export, before the
existing closing line.

**Omitted on purpose:** the notification email. The `notification` key exists in the schema and
needs no change, but the delivery does not exist — it requires the author or a steward to run
`notify.py` under cron. Asking for it in the MVP would be a promise the product cannot keep.

## B.4 The single strongest question found

> **"When did you feel most alive?"** — Dignity Therapy Question Protocol, Q2 (Chochinov).

Six words. It is not about death, so a person too tired or too frightened to face the topic can
still answer it. It produces a *scene* rather than a sentiment, which is exactly the failure
mode (B.2) that legacy letters otherwise fall into. And it can be answered in one line and still
have given something real — which is the property that matters most for an author who may not
get a second sitting. LateLetter's A1 is this question, aimed at the recipient.

## B.5 Schema changes — 6 items, explicitly flagged

| # | item | status | recommendation |
|---|---|---|---|
| 1 | `recipient_name` | **already decided** — FL:13133, spec §4.2.2 | required by P3; ship |
| 2 | `recipient_relationship` | **already decided** — same | ship; also gates A2/D4 wording |
| 3 | `author_relationship` | **already decided** — same | ship |
| 4 | `steward_name` / `steward_contact` | **NEW** — SPEC §5.1 has it, the flat draft does not; also touches the handoff README (§15.1) | highest-value of the three new ones; if it slips, use the no-storage sentence |
| 5 | `key_dates` | **NEW** — SPEC §5.1 and §9.1 have it | **defer.** Would pre-fill letter and gift dates, which is genuinely nice, but it is a convenience and nothing in the tree requires it |
| 6 | `memory_tags` | **NEW** — SPEC §5.1 and §9.1 have it | **reject for MVP.** Only pays off with an LLM prompt selector, which is outside scope |

Items 1-3 are one operator decision already taken. Of the three new ones I recommend **only #4**
be considered, and only if it is cheap.

**Explicitly needing NO schema change:** the entire prompt drawer (Bands A-E) — every prompt is
a seed that writes into `messages[].body` and is never stored on its own; the shape chooser
(never persisted; only shown while the body is empty); the timezone confirm line
(`author_timezone` already exists); the four-things readback at review (client-side only); every
gift question (all map into the existing `garden_beats` beat of §4.6).

## B.6 Counts and the one-sitting check

| | count |
|---|---|
| total questions asked of the author | **40** |
| — metadata questions | 17 |
| — letter-body prompts (seeds) | 23 |
| required | **6** (author name, recipient name, letter date, letter body, passphrase, hint) |
| optional | 34 |
| marked ⚠ heavy | 13 — all opt-in, all mid-panel, none first or last |
| needing a schema change | **6** (3 already decided) |

**One sitting:** the required path is six answers and one prompt. An author who wants nothing
else can go door → `people` (2 fields) → `letters` (date + body) → skip gift → review → export
in well under ten minutes plus however long they want to write. Every band beyond Band A is
behind a click. That is the shape the product needs: short by default, deep on request.

---

## Sources

- [Barry K. Baines — *The Ethical Will Writing Guide Workbook*](https://www.amazon.com/Ethical-Will-Writing-Guide-Workbook/dp/0967679419) and [*Ethical Wills: Putting Your Values on Paper*](https://www.amazon.com/Ethical-Wills-Putting-Values-Paper/dp/0738210552)
- [Jewish Community Foundation LA — *Your Legacy Letter: An Ethical Will Workbook* (PDF)](https://www.jewishfoundationla.org/wp-content/uploads/2022/07/JCF_EthicalWillWorkbook_2022_FILLABLE.pdf)
- [Trust & Will — Legacy Letter Writing Guide](https://trustandwill.com/learn/legacy-letter-writing-guide)
- [Utah Hospice — Legacy Letters (end-of-life glossary)](https://utahhospice.org/end-of-life-and-hospice-care-glossary/legacy-letters/)
- [Evaheld — Ethical Will Template: Free Examples and Structure](https://evaheld.com/blog/ethical-will-template)
- [Stanford Medicine Letter Project — Friends and Family Letter / seven tasks of life review](https://med.stanford.edu/letter/friendsandfamily.html)
- [Dignity Therapy at End-of-Life — Canadian Virtual Hospice / dignityincare.ca](https://dignityincare.ca/en/dignity-therapy-at-end-of-life.html)
- [Chochinov et al. — Dignity Therapy (American Journal of Psychiatry Residents' Journal)](https://www.psychiatryonline.org/doi/10.1176/appi.ajp-rj.2018.130803)
- [Enhancing legacy in palliative care: RCT study protocol for Dignity Therapy (PMC)](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC4578680/)
- [Ira Byock — *The Four Things That Matter Most*](https://www.simonandschuster.net/books/The-Four-Things-That-Matter-Most-10th-Anniversary-Edition/Ira-Byock/9780743258609)
- [StoryWorth — guide to Storyworth's questions](https://welcome.storyworth.com/blog/a-complete-guide-to-storyworths-questions)
- [Remento — 48 Storyworth sample questions by category](https://www.remento.co/journal/storyworth-sample-questions)
- [Funeral.com — Legacy Projects: Writing Letters to Your Children for Future Milestones](https://funeral.com/blogs/the-journal/legacy-projects-writing-letters-to-your-children-for-future-milestones)
- [Klass, Silverman & Nickman — Continuing Bonds (overview)](https://en.wikipedia.org/wiki/Continuing_bonds)
- [What Bereaved Children Want to Know About Death and Grief — *Journal of Child and Family Studies*](https://link.springer.com/article/10.1007/s10826-023-02694-x)
- ["What do we tell the children?": Understanding childhood grief (PMC)](https://pmc.ncbi.nlm.nih.gov/articles/PMC1071311/)
- [Eluna — Give Your Child Permission to be Happy: Anticipatory Bereavement Tools](https://elunanetwork.org/resources/give-your-child-permission-to-be-happy-anticipatory-bereavement-tools/)
