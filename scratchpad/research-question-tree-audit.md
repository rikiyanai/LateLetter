# Recovered research question tree — audit and operator redline

Date: 2026-08-10

Status: research pass complete; no question row is canonical until operator approval

Parent: `Wayfinder map: the whole web product, authoring through recipient (2026-08-05)`

Child: `Wayfinder child: recover and audit the research question tree (2026-08-10)`

## Recovery receipt

- Recovered artifact: `scratchpad/research-question-tree.md`
- Length: 533 lines
- SHA-256: `68311dbebaa1e7db60f91bb848300180fd34fa4583ed77d645e0d7e5dcb0ea48`
- Actual scope: 40 author questions, not 513 questions. The 40 comprise 17 metadata/control questions and 23 optional letter-body prompt seeds.
- Comparison corpus: 131 prototype prompts: 30 in `question_bank_seed.v0.json` plus 101 in `question_bank_domain_pools.v0.json`. Both banks identify themselves as prototype/draft material and provide no item-level citations.

## Audit rules

`KEEP` means the row is recommended for operator approval, not already approved. `REDLINE` means keep the product need but change the requirement, wording, gate, or destination. `HOLD` means an operator/schema decision is still required. Intensity uses the prototype scale: 0 operational, 1 gentle, 2 reflective, 3 emotionally heavy.

The 131-bank crosswalk establishes overlap only. A prototype prompt does not inherit clinical or template lineage merely because it resembles a sourced row. Conversely, the recovered wording is an adaptation, not a verbatim clinical protocol.

Current canon overrides the recovered proposal in four places:

1. Undated letters are valid draft state and must survive reload; they are visibly excluded from export rather than rejected.
2. Authored gifts are uncapped, with one gift per beat; the proposal's single-gift framing is stale.
3. The four offered gift assets are genuinely accepted paint authorities, but composition/placement is not granted by art acceptance.
4. `author_service.py` remains the sole bundle constructor; UI rows target draft state or the service's `garden_beats` adapter, never a browser-owned bundle schema.

## Forty-row audit

| ID | Recommendation | Req. | Intensity | Gate / condition | Destination | Source lineage | 131-bank crosswalk | Redline or acceptance note |
|---|---|---:|---:|---|---|---|---|---|
| P1 | KEEP | required | 0 | always | draft `author_name`; plaintext bundle header through service | SPEC intake/product requirement | none; metadata, not prompt content | Keep wording. |
| P2 | KEEP | optional | 0 | always | draft `author_relationship`; personalization only | SPEC intake + operator decision to extend draft identity | none | Do not add it to the sealed bundle merely because the UI asks it. |
| P3 | KEEP | required | 0 | always | draft `recipient_name`; file/UI personalization | SPEC intake + operator decision to extend draft identity | none | Storage is draft-owned unless a separate bundle-field decision says otherwise. |
| P4 | KEEP | optional | 0 | always | draft `recipient_relationship`; routes A2/D4 | SPEC intake + operator decision to extend draft identity | none | Free text must not alone trigger D4; require explicit opt-in too. |
| L0 | KEEP | optional | 0 | only while body is empty | transient drawer route; no persisted answer | milestone-letter/editorial synthesis | occasion pools overlap only | It may preselect prompts; it must not become a hidden content owner or erase text on reload. |
| L1 | REDLINE | conditional | 0 | required only for inclusion in export | draft date may be blank; only dated rows enter service `messages[]`; timezone goes to `garden_beats.author_timezone` | SPEC §5.2 + locked undated-letter FL decision | none | Replace `[R]` with “optional while drafting; required to ship this letter.” Show and repeat exclusion before/after export. |
| L2 | KEEP | optional | 0 | per letter | draft label, then encrypted `messages[].label` | SPEC message slot | none | Blank label is allowed by service. |
| L3 | REDLINE | conditional | 1 | may be blank in an unfinished draft; nonblank for export inclusion | draft body, then encrypted `messages[].body` | SPEC message creation | none | Replace unconditional `[R]` with “required to ship this letter”; autosave partial work. |
| A1 | KEEP | optional | 1 | always shown | inserts seed into current letter body | Dignity Therapy life-history/“most alive” line + Stanford treasured-moments task; recipient-pinned adaptation | near: `u-017`, `u-029`, `occ-bdy-004`, `rel-chl-001`, `rel-fnd-006` | Strong source and concrete scene; keep as first grounding seed. |
| A2 | KEEP | optional | 1 | child wording only when relationship says child; generic wording otherwise | body seed | editorial synthesis around unnoticed particulars | near: `u-005`, `u-007`, `rel-chl-004` | Keep generic fallback; never infer parenthood from recipient name. |
| A3 | KEEP | optional | 1 | always shown | body seed | editorial synthesis; ordinary-detail correction to abstract life review | near: `u-001`, `u-002`, `u-028`, `u-029` | Keep; it supplies embodied detail missing from most of the bank. |
| B1 | KEEP | optional | 1 | good-day route | body seed | milestone-letter synthesis | near: `u-019`, `u-023`, birthday/graduation hope pools | Keep. |
| B2 | KEEP | optional | 1 | good-day route | body seed | editorial candidate only | no close prototype | Keep as candidate; it needs copy review because “too happy to ask” presumes an emotional state. |
| B3 | HOLD | optional | 3 | good-day route + explicit heavy opt-in | body seed | editorial candidate only | no close prototype | Third-party/room framing may create pressure or disclose others; hold for operator wording verdict. |
| B4 | KEEP | optional | 1 | hard-day route | body seed | bereavement/milestone synthesis | near: `u-020`, `u-021`, `occ-wnu-001`, `occ-wnu-003` | Keep; concrete and non-prescriptive. |
| B5 | KEEP | optional | 2 | hard-day route | body seed | life-review/milestone synthesis | near: `u-004`, `u-011`, `u-024`, `u-026`, `u-027`, `occ-wnu-005` | Keep. |
| B6 | KEEP | optional | 2 | hard-day route | body seed | permission/bereavement synthesis | near: `occ-wnu-004`, `hvy-prm-002`, `hvy-prm-004` | Keep, but never surface before lower-intensity prompts. |
| B7 | KEEP | optional | 1 | ordinary-day route | body seed | ordinary-day editorial synthesis | near: `occ-dth-006` | Keep. |
| B8 | KEEP | optional | 1 | ordinary-day route | body seed | editorial candidate only | no close prototype | Keep; intentionally resists making every letter about illness/death. |
| B9 | KEEP | optional | 3 | first-letter route + explicit heavy opt-in | body seed | bereavement-literature synthesis | no close prototype | Keep heavy and never first/last; avoid coyness about why the letters exist. |
| B10 | KEEP | optional | 2 | first-letter route | body seed | milestone-letter/editorial synthesis | no close prototype | Keep; recipient autonomy is part of the product contract. |
| C1 | REDLINE | optional | 3 | collapsed heavy panel after gentle prompts | body seed | Byock gratitude phrase + Stanford gratitude task | near: `u-015` | Keep the specific-gratitude ask; delete the shaming clause that says a generic thank-you “means nothing.” |
| C2 | KEEP | optional | 3 | collapsed heavy panel | body seed | Byock “please forgive me” + Stanford apology task | near: `hvy-apl-001..005`, `u-025` | Keep opt-in; never imply forgiveness is owed. |
| C3 | REDLINE | optional | 3 | collapsed heavy panel | body seed | Byock “I forgive you” + Stanford forgiveness task | no direct prototype; `occ-wdg-006` is thematic only | Ask whether there is anything they *want* to release or forgive; explicitly allow “nothing.” Do not make forgiveness a duty. |
| C4 | KEEP | optional | 3 | collapsed heavy panel | body seed | Byock love phrase + Stanford love task | near: `u-006`, `u-009`, `u-014`, relationship love pools | Keep. |
| D1 | REDLINE | optional | 3 | separate collapsed permission panel | body seed | bereavement/editorial synthesis | near: `rel-prt-009`, `hvy-prm-001`, `hvy-prm-002` | Keep the permission; remove any wording that defines “living well” as an expectation. |
| D2 | KEEP | optional | 3 | permission panel | body seed | bereavement/editorial synthesis | no close prototype | Keep only as explicit opt-in. |
| D3 | KEEP | optional | 3 | permission panel | body seed | bereavement/editorial synthesis | no close prototype | Keep; it protects recipient autonomy. |
| D4 | REDLINE | optional | 3 | partner relationship **and** explicit after-death/permission opt-in | body seed | bereavement/editorial synthesis | near: `rel-prt-009`, `hvy-prm-002` | Relationship text alone is an unsafe gate. Add explicit context confirmation. |
| D5 | REDLINE | optional | 3 | permission panel | body seed | values-not-control editorial synthesis | no close prototype | Shorten and remove the double-bind; candidate: “Is there a wish you want to name while leaving the choice with them?” |
| E1 | KEEP | optional | 1 | always last | body seed | Dignity Therapy closing invitation | near: `u-030`, `u-016` | Keep last in every route. |
| G1 | REDLINE | optional | 0 | always skippable; default no | gates zero or more `garden_beats` | operator MVP scope | none | Replace “one thing” with repeatable “schedule a gift”; gifts are uncapped, one gift per beat. Never block the rail when skipped. |
| G2 | KEEP | conditional | 0 | required per gift beat | `garden_beats.entities[].catalog_id` | accepted-art authority | none | The four choices are source-backed grants: `coffee_mug`, `ice_cream_cone`, `mixtape`, `popsicle`. Derive, do not copy, the accepted set. |
| G3 | KEEP | conditional | 0 | required per gift beat | beat `schedule.start` | Garden-program grammar | none | Include timezone explicitly. |
| G4 | REDLINE | optional | 0 | per gift beat | full `schedule.recurrence` object | Garden-program grammar | none | A boolean alone is not the destination. Yearly means `{frequency: yearly, intentional_unbounded: true}` plus canonical defaults. |
| G5 | KEEP | conditional | 0 | required per gift beat | `letter.present.letter_id` via service `MESSAGE_n` substitution | author-service adapter | none | Only dated/exportable letters may appear in this selector. |
| G6 | HOLD | optional | 0 | per gift beat | no approved authoring destination yet | editorial/product candidate only | none | `placement_hint` is legacy-v1 language, not the v2 beat contract. Hide this row until a canonical stable-position policy exists. |
| X1 | HOLD | required | 0 | stage remains coupled to X2; never autosaved | separate passphrase argument to export service | SPEC crypto/export flow + operator decision 2026-08-10 | none | Minimum resolved: REDLINE “at least 12” to a blocking 4-character floor; strength feedback is advisory above it. The row remains held only because passphrase/hint stage placement is the next operator decision. |
| X2 | HOLD | required | 0 | exact stage remains operator decision | draft `passphrase_hint`, then plaintext bundle header | SPEC §5.1 | none | Required status is clear; placement conflicts. SPEC requires the warning immediately after passphrase confirmation during intake, while the recovered tree moves hint to export. |
| X3 | HOLD | optional | 0 | only if schema/handoff owner is approved | draft steward fields and handoff README; not bundle metadata by default | SPEC intake/handoff | none | Decide whether to store `steward_name/contact`; otherwise show “Tell one person this file exists” without collecting data. |

## Prototype-corpus disposition

This is an exhaustive ID-level accounting of the 131 preserved prompts. `MERGE` means the prototype is a near-duplicate of a recovered row and should not become a second active question. `ALT` means preserve it in the prototype archive for later editorial work, but keep it out of the 40-row MVP. `HOLD` means it should not enter the active corpus without a new route/safety decision. None of these labels grants canonical approval.

| Prototype slice | MERGE into recovered row | ALT outside MVP | HOLD |
|---|---|---|---|
| universal (30) | `u-007→A2`, `u-015→C1`, `u-017→A1`, `u-021→B4`, `u-026→B5`, `u-029→A1/A3`, `u-030→E1` | `u-001→A3`, `u-002→A3`, `u-004→B5`, `u-005→A2`, `u-006→C4`, `u-008→C1`, `u-009→C4`, `u-011→B5`, `u-012→B5`, `u-014→C4`, `u-016→E1`, `u-018→A1`, `u-019→B1`, `u-020→B4`, `u-022→D1`, `u-023→B1`, `u-024→B5`, `u-025→C2`, `u-027→B5`, `u-028→A3` | `u-003`, `u-010`, `u-013` (abstract values before story) |
| birthday (10) | — | `occ-bdy-001→A2`, `occ-bdy-002→B1`, `occ-bdy-003→C4`, `occ-bdy-004→A1`, `occ-bdy-005→B1`, `occ-bdy-006→A2`, `occ-bdy-007→B5`, `occ-bdy-008→C1`, `occ-bdy-009→A1`, `occ-bdy-010→B1` | — |
| wedding (9) | — | `occ-wdg-001→B1`, `occ-wdg-002→B5/C4`, `occ-wdg-003→A2`, `occ-wdg-004→B4`, `occ-wdg-005→B5`, `occ-wdg-006→C3`, `occ-wdg-007→B1`, `occ-wdg-008→B5`, `occ-wdg-009→B5` | — |
| graduation (8) | — | `occ-grd-001→B1`, `occ-grd-002→B1`, `occ-grd-003→B5`, `occ-grd-004→C1`, `occ-grd-005→B1`, `occ-grd-006→B5`, `occ-grd-007→B5`, `occ-grd-008→B5` | — |
| after-my-death (9) | `occ-dth-006→B7`, `occ-dth-007→D1`, `occ-dth-008→D1` | `occ-dth-001→A3`, `occ-dth-002→D1`, `occ-dth-003→D1`, `occ-dth-004→C4`, `occ-dth-005→A3`, `occ-dth-009→D1` | — |
| whenever-needed (7) | `occ-wnu-001→B4`, `occ-wnu-003→B4`, `occ-wnu-004→B6`, `occ-wnu-005→B5` | `occ-wnu-002→B4`, `occ-wnu-006→B4`, `occ-wnu-007→B5` | — |
| child (10) | `rel-chl-001→A1`, `rel-chl-003→C4`, `rel-chl-004→A2` | `rel-chl-002→D1`, `rel-chl-005→A3`, `rel-chl-006→C4`, `rel-chl-007→B1`, `rel-chl-008→B5`, `rel-chl-010→A3` | `rel-chl-009` (assumes the recipient will become a parent) |
| partner (9) | `rel-prt-009→D4/D1` | `rel-prt-001→C4`, `rel-prt-002→A2`, `rel-prt-003→C4`, `rel-prt-004→A2`, `rel-prt-005→A1`, `rel-prt-006→C4`, `rel-prt-007→C1`, `rel-prt-008→C1` | — |
| friend (8) | `rel-fnd-006→A1` | `rel-fnd-001→C4`, `rel-fnd-002→A2`, `rel-fnd-003→C1`, `rel-fnd-004→A2`, `rel-fnd-005→C1`, `rel-fnd-007→D1`, `rel-fnd-008→E1` | — |
| sibling (7) | — | `rel-sib-001→A1`, `rel-sib-002→A2`, `rel-sib-003→C1`, `rel-sib-004→C4`, `rel-sib-005→B5`, `rel-sib-006→D1`, `rel-sib-007→A1` | — |
| apology (5) | `hvy-apl-001→C2`, `hvy-apl-002→C2`, `hvy-apl-003→C2`, `hvy-apl-004→C2`, `hvy-apl-005→C2` | — | — |
| regret (3) | — | `hvy-reg-001→C2`, `hvy-reg-002→C2`, `hvy-reg-003→C2` | — |
| fear (3) | — | `hvy-fer-001→B4`, `hvy-fer-002→B4`, `hvy-fer-003→B5` | — |
| spiritual (5) | — | — | `hvy-spr-001`, `hvy-spr-002`, `hvy-spr-003`, `hvy-spr-004`, `hvy-spr-005` (no approved spiritual route; faith/worldview must be explicit opt-in) |
| permission (4) | `hvy-prm-001→D1`, `hvy-prm-002→D4/D1`, `hvy-prm-003→D1`, `hvy-prm-004→B6/D1` | — | — |
| grief (4) | — | `hvy-grf-001→B5`, `hvy-grf-002→B7`, `hvy-grf-003→A3`, `hvy-grf-004→D1` | — |

Accounting: 28 MERGE + 94 ALT + 9 HOLD = 131. The active MVP remains the redlined 40-row tree; this audit does not silently expand it with 94 alternates.

## Operator decisions required before browser implementation

These are ordered by dependency. Per the grilling workflow they should be decided one at a time.

Resolved 2026-08-10: the blocking passphrase minimum is 4 characters. Strength feedback is advisory, and the floor may be revised later through the canonical service policy.

1. Passphrase hint placement: keep SPEC intake timing, move only the hint field to export while repeating the warning earlier, or amend the SPEC completely.
2. Steward data: store optional steward name/contact in the draft and handoff package, or collect no steward data and show only the no-storage instruction.
3. Accept/redline the row recommendations, especially B3, C1, C3, D1, D4, D5 and the eight prototype-only prompts with no close bank counterpart.
4. Confirm conditional-required semantics: undated/unfinished letters stay in draft; only dated nonblank letters are service messages; gift fields are required per created beat, never for skipping gifts.
5. Decide G6 placement ownership. Until then, the browser may not ask where a gift should sit.

## Verified lineage sources

- Dignity Therapy randomized-trial protocol: `https://dignityincare.ca/wp-content/uploads/2010/05/Protocol%2006.28.2011.pdf` — the protocol contains the “most alive,” family-memory, hopes, learning/advice and final-unsaid-things prompts and requires patient-directed flexibility.
- Stanford Medicine, Who Matters Most Letter: `https://www.med.stanford.edu/letter/friendsandfamily` — seven life-review tasks covering important people, treasured moments, apology, forgiveness, gratitude, love and an optional goodbye.
- Ira Byock, *The Four Things That Matter Most*, publisher page: `https://www.simonandschuster.co.uk/books/The-Four-Things-That-Matter-Most-10th-Anniversary-Edition/Ira-Byock/9781476748535` — the four phrases are “Please forgive me,” “I forgive you,” “Thank you,” and “I love you.”

## Exit state

Recovery is complete. The research comparison and redline are complete. The passphrase-minimum contradiction is resolved at a provisional 4-character floor. Operator approval remains open, so `web/author-app.mjs` remains blocked. The next decision is passphrase/hint placement.
