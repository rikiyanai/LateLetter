# LateLetter Failure Log

Check this file before making fixes. Add a short entry for each user-visible bug, spec contradiction, security flaw, or failed implementation attempt, including the outcome.

## 2026-07-21

### A plaintext personal letter and its passphrase were committed beside the encrypted bundle
- Symptom: `letters/letter_source.example.json` is tracked by an explicit `.gitignore` exception even though it now contains a personal letter body and the passphrase used to seal it. Commit `ba8f62a` exposes both in its diff and history.
- Impact: The published `.lateletter` files use real passphrase-derived encryption, but confidentiality is defeated because the plaintext and passphrase are available from Git history. Deleting only the current source file or changing repository visibility does not erase existing copies or history.
- Root cause: A safe-to-track example path was reused for a real letter source, while `.gitignore` continued to exempt that exact path.
- Resolution: Treated the passphrase and old outputs as compromised. Preserved the personal source and affected bundles under ignored local-only filenames in `letters/`, replaced the tracked example with synthetic content, deleted the old GitHub repository, and recreated it from a clean root commit that has no reference to the exposed history. No personal bundle was republished.
- Status: Fixed in replacement repository; author must choose new copy and a new passphrase before publishing a personal letter

### The deployed sealed bundles contain user-rejected message copy
- Symptom: A decrypt-and-hash comparison confirms that `sealed_demo.lateletter` and `public_letters/to-chloe.lateletter` contain exactly the current body and label from `letters/letter_source.example.json`; the user has rejected that message copy as wrong.
- Impact: Both the demo path and the recipient-specific URL deliver the wrong letter after successful unlock.
- Root cause: The personal source was edited in the tracked example file and then used as the input for both output bundles without a final copy-approval gate.
- Resolution: Removed `public_letters/to-chloe.lateletter` from the replacement history and regenerated `sealed_demo.lateletter` plus `public_letters/to-a-friend.lateletter` from synthetic example text. The rejected personal message is not present in either published/demo path.
- Status: Fixed for current repository; corrected personal letter intentionally not published yet

### AI-authored commits bypassed the incomplete profile hook and created contributor attribution
- Symptom: The global `commit-msg` hook blocked only `Co-authored-by: ...Claude` trailers. Commits `fd7e008`, `ee5a072`, and `103d26b` instead use `Claude <noreply@anthropic.com>` as both primary author and committer, and GitHub now lists `claude` with three contributions to the private repository.
- Impact: The repository contributor surface attributes commits to Claude despite the user's authorship policy.
- Resolution: Expanded `/Users/r/.git-hooks/commit-msg` to reject Claude, Codex, or agent identities in author/committer metadata, authorship trailers, and AI session metadata, and added a matching `prepare-commit-msg` gate so `git commit --no-verify` does not bypass the policy. Verified that normal human-authored commits pass and all prohibited forms fail. Also pinned the global Git identity to `RIKI YANAI HERNANDEZ <33168192+rikiyanai@users.noreply.github.com>` with `user.useConfigOnly=true` so Git no longer falls back to the anonymous local-machine identity.
- Replacement outcome: Deleted the old GitHub repository and its AI-authored refs, and recreated `rikiyanai/lateletter` from a clean root commit authored and committed by the user's verified GitHub identity. Registered a dedicated SSH signing key and enabled signed commits globally.
- Remaining remote-policy blocker: GitHub returned HTTP 403 when adding a ruleset to the replacement private repository: `Upgrade to GitHub Pro or make this repository public to enable this feature.` The repository remains private; local hooks and signing are active, but GitHub-hosted enforcement cannot be enabled on the current plan.
- Status: Replacement/history fixed; private-repository ruleset blocked by GitHub plan

### Personal repositories cannot use GitHub's direct commit-metadata restriction rules
- Symptom: GitHub returned HTTP 422 `Invalid rule 'commit_author_email_pattern'` for both the full AI-attribution pattern and GitHub's minimal documented example on a personal public repository.
- Impact: The desired server-side author/committer/message regex cannot be attached directly to these personal-account repositories.
- Resolution: Added `.github/workflows/block-ai-attribution.yml`, which audits commit author, committer, attribution trailers, and AI session metadata on every push and pull request. Added an active `Block AI attribution` ruleset requiring its `AI attribution policy` status on the default branch across all 13 repositories that were public at intake; all 12 active repositories passed and the thirteenth remains archived with the policy installed.
- Private-repository limitation: GitHub Actions refused to start on the replacement private LateLetter repository because of an account billing/spending-limit restriction, and GitHub Free rejected a required-signatures ruleset with HTTP 403. A dedicated GitHub SSH signing key is registered, global Git commits are signed by default, and the local author/trailer hooks remain mandatory. The audit workflow skips private repositories until Actions billing is available.
- Status: Fixed with workflow-required enforcement on public repositories; GitHub-hosted enforcement on private LateLetter requires GitHub Pro or public visibility

### Encryption and sealing language does not communicate the actual privacy boundary
- Symptom: README, CLI, viewer, and commit copy use both “encrypted” and “sealed” without clearly separating the encrypted output bundle from the plaintext authoring source and plaintext metadata.
- Impact: The language can create false confidence that a password protects the letter even when a tracked source file or history exposes the message and passphrase.
- Resolution: Changed recipient-facing demo and README copy to “passcode-locked,” documented the plaintext source boundary, and fixed the browser memory modal to render the already-decrypted gift sentiment instead of the stale `[encrypted — decryption in step 13]` placeholder.
- Status: Fixed for the browser and publishing workflow; terminal-only Phase 3 placeholders remain internal implementation debt

## 2026-07-18

### GitHub Pages was disabled and the mixed-case repository name kept the intended URL broken
- Symptom: `https://rikiworld.com/` returned 200, while both `https://rikiworld.com/lateletter/` and `https://rikiworld.com/LateLetter/` returned 404. The latest deploy run (June 12, run 27386698312) failed in `actions/configure-pages@v5`, and the Pages API returned 404 for the repository.
- Impact: The browser viewer was unavailable at its public project URL even though the deployment workflow still existed.
- Root cause: Pages had been disabled after the successful April deployments. The repository was still named `LateLetter`, so an inherited project-site route would be `/LateLetter`, not the intended lowercase `/lateletter`. The prior artifact-level `_site/lateletter` mirror did not control the repository-derived project path.
- Resolution: Removed the obsolete nested artifact mirror, renamed the repository to `lateletter`, and re-enabled Pages with GitHub Actions as the build source. Commit `262050d` deployed successfully in run `29631258927`; `https://rikiworld.com/lateletter/` returned 200 after deployment.
- Status: Fixed and live

## 2026-04-27

### Execution canon overstated author workflow completion
- Symptom: `docs/SPEC.md` step 6 marked the offline author workflow complete, but the live `lateletter --write` path still stops after intake and prints "Message list and Q&A session coming in the next integration step."
- Impact: The canonical execution order claimed end-to-end author readiness that the shipped CLI does not provide. Future planning could incorrectly treat author integration as closed.
- Resolution: Downgraded the execution-sequence status in `docs/SPEC.md`, added an explicit "end-to-end integration not done" checklist item, and added an audit note to the release-acceptance section.
- Status: Fixed in spec/docs

### Demo author harness writes an invalid recipient artifact
- Symptom: `demo_author.py` claimed to produce a ready-to-open `.lateletter` bundle, but it wrote `bundle.to_dict()` directly with `checksum=""` instead of using `write_bundle()`. Verified on 2026-04-27: generated bundle loaded structurally but `verify_checksum()` returned `False`.
- Impact: The demo script cannot be used as proof of the export path or as a valid terminal recipient fixture. It also overstates Part C of the execution plan.
- Resolution: Logged as an open code bug; downgraded the Part C completion claim in `docs/SPEC.md` and annotated the demo docs so they no longer treat the script as proof of a valid export artifact.
- Status: Open — code fix pending; spec/docs corrected

### Browser viewer lacks the required launch-time checksum gate
- Symptom: `viewer-bnw.html` loads bundle JSON by shape/version only and never recomputes the bundle checksum before proceeding, despite the spec requiring a launch-time corruption check in both delivery channels.
- Impact: Browser-mode execution can present corrupted bundles as normal, so the implementation does not yet satisfy the canon's cross-channel integrity and acceptance requirements.
- Resolution: Implemented a browser-side checksum verifier over the canonical visible payload, added damaged-file state gating to suppress unlock/archive access when checksum validation fails, and kept local dev fixtures usable when they omit a checksum. Browser corruption parity is now wired in code, pending human QA.
- Status: Implemented (unproven)

### Browser reader depended on CDN text layout with no fallback
- Symptom: `viewer-bnw.html` imported `pretext` directly from jsDelivr at module top level. If the CDN was blocked, offline, or slow, the entire browser viewer failed before the garden or reading UI could initialize.
- Impact: A recipient could lose the whole browser experience because a text-layout helper failed to load.
- Resolution: Replaced the hard import with lazy initialization and a browser-native text fallback. The viewer now keeps working even when `pretext` fails, with simpler letter layout rather than total failure.
- Status: Fixed

### Browser memory labels were too generic
- Symptom: Discovered gifts in the browser archive were rendered as generic labels like "a memory" or "a note" regardless of whether the gift was a rabbit, a plate of food, or a plant.
- Impact: The memory layer felt abstract and interchangeable instead of specific and discovered.
- Resolution: Gift labels are now derived from `animal_name` / `catalog_id` / gift type so the archive and memory modal name the actual remembered thing.
- Status: Fixed

### Browser garden boot failed on undefined pine collision state
- Symptom: Live browser QA on 2026-04-27 opened `viewer-bnw.html` into the error screen instead of the garden. Console showed `ReferenceError: pine is not defined` from `PlantLayer.regenerate()`.
- Impact: The browser garden failed during startup, so none of the new animal behavior or ambient-bird work could be exercised.
- Resolution: Restored `pine` to the `buildCollision(...)` destructuring in `PlantLayer.regenerate()` so `state.pineCells` is populated from the returned collision data. Re-ran live QA after the fix; the garden now boots and the dev animal-cycle / reaction checks execute normally.
- Status: Fixed

### GitHub Pages workflow published only site root, leaving `/lateletter` 404
- Symptom: `https://rikiworld.com/` was live through GitHub Pages, but `https://rikiworld.com/lateletter` and `/lateletter/index.html` returned GitHub Pages 404s on 2026-04-27.
- Impact: The deployed viewer only worked at the domain root. The intended `/lateletter` URL was broken even though Actions deploy itself was succeeding.
- Resolution: Updated `.github/workflows/deploy.yml` so the Pages artifact now publishes both the root site (`_site/index.html`) and a mirrored `_site/lateletter/index.html` plus matching `test_fixture.lateletter`.
- Status: Superseded on 2026-07-18 — the nested artifact did not control the repository-derived project URL; see the current Pages entry above

## 2026-04-18

### Repo bootstrap
- Symptom: The repo had no failure log despite a workspace rule requiring it to be checked before fixes.
- Impact: Future work could skip the required review step or lose context about prior failures.
- Resolution: Created this file at the repo root and established it as the canonical pre-fix review log.
- Status: Fixed

### SPEC integrity and consistency review
- Symptom: `docs/SPEC.md` allowed unauthenticated delivery-state claims, left bundle-HMAC derivation underspecified, conflicted on session wiping vs steward recovery, left external-editor plaintext handling undefined, overpromised curses accessibility, and drifted between canonical schema sections.
- Impact: High risk of implementing the wrong trust model and shipping incompatible behavior.
- Resolution: Patched `docs/SPEC.md` to require authenticated unlock before announcing due letters, added `bundle_auth_salt`, reconciled wipe semantics with unfinished-note retention, constrained external-editor drafts to managed storage, added an accessible non-curses path, and aligned milestone/schema language.
- Status: Fixed in spec

### SPEC plan lacked explicit research gates
- Symptom: Research-heavy work in the milestone plan was mixed directly into implementation phases, especially for question-bank design, ASCII animation design, and security/industry-practice decisions.
- Impact: The project could start implementation before the content, UX, and security assumptions were validated.
- Resolution: Added explicit research sub-phases to `docs/SPEC.md` for question-bank design, encryption/privacy industry practices, LLM prompt/evaluation design, and ASCII animation prototyping.
- Status: Fixed in spec

### Canon doc inventory audit
- Symptom: There was a risk of spec drift if additional loose markdown docs existed outside the canonical spec/log pair.
- Impact: Non-canonical docs would create conflicting requirements and stale planning artifacts.
- Resolution: Audited the repo markdown inventory. Only `docs/SPEC.md` and `docs/FAILURE_LOG.md` exist, so no archive or doc consolidation work was needed.
- Status: No action needed

### Phase ordering ambiguity
- Symptom: The milestone section could be read as if any research item mentioned early should also become an early implementation phase, creating confusion about why ASCII animation research was not in the first few phases.
- Impact: Planning could drift away from the intended capability-first order.
- Resolution: Clarified in `docs/SPEC.md` that phase numbering reflects implementation priority and critical path, while limited research spikes can happen earlier without changing the canonical phase order.
- Status: Fixed in spec

### SPEC lacked a release contract
- Symptom: The spec described the product well but still left shipping-critical decisions open, especially platform target, packaging, compatibility policy, failure-mode behavior, and release acceptance criteria.
- Impact: The project could be "implemented" without being releasable to a non-technical recipient.
- Resolution: Added release-profile, compatibility, failure-mode, acceptance-criteria, test-matrix, and security-review sections to `docs/SPEC.md`, and resolved the blocking open questions those sections depended on.
- Status: Fixed in spec

### Future portability ideas were not task-shaped
- Symptom: Browser/static-site and scheduled-email ideas existed only as broad future vision notes, not as scoped future work with ordering and constraints.
- Impact: Good portability directions could be forgotten, or worse, treated as equal-priority with the current shipping path.
- Resolution: Reworked the future-portability section to prioritize a browser viewer first, hosted HTML delivery second, and scheduled email last, and added explicit post-v1 phases for each.
- Status: Fixed in spec

### Unified execution sequence was missing
- Symptom: The spec had phases, gates, and post-v1 work, but no single canonical ordered task list that collapsed them into one execution sequence.
- Impact: Different readers could interpret the roadmap differently, especially around what could run in parallel versus what was actually on the critical path.
- Resolution: Added a bottom-of-spec "Unified Sequence of Tasks" section that flattens all phases into one sequential action list and labels parallelizable work inline.
- Status: Fixed in spec

### Remaining spec weak spots after ship-contract pass
- Symptom: A few release-relevant details were still underspecified: exact terminal size requirements, the editorial approval workflow for the offline question bank, and browser-viewer receipt storage semantics.
- Impact: Those omissions would create implementation drift in UI constraints, content quality control, and post-v1 portability behavior.
- Resolution: Patched `docs/SPEC.md` with concrete minimum terminal dimensions, a stricter question-bank editorial workflow, and explicit browser-viewer local receipt-storage rules.
- Status: Fixed in spec

### Phase 1 question-bank research sub-phase lacked validated framework anchors
- Symptom: The Phase 1 research sub-phase in `docs/SPEC.md` was a three-line placeholder specifying "research questionnaire-writing practices" and "produce a reviewed bank outline" without naming validated frameworks, empirical evidence, category structure, editorial principles, or study materials.
- Impact: Without anchored sources, the offline question bank could be built from generic "reflective writing" assumptions rather than empirically validated end-of-life communication practice, producing prompts that feel hollow, culturally presumptuous, or inadvertently harmful to a terminally ill author.
- Resolution: Completed the research pass and updated `docs/SPEC.md` Phase 1 with: five validated framework anchors (Dignity Therapy with Lancet Oncology RCT evidence, ethical will/tzavaah tradition, Ariadne Labs SICG, The Conversation Project Starter Kit, VitalTalk/CAPC); a 16-domain category structure synthesized across all five frameworks; nine editorial principles derived from research (extending §5.3); a research deliverable specification (decision memo with sample questions, intensity tags, and rejection examples before bank construction begins); and a curated study-material list with buy/free/borrow guidance. All prices and URLs are labeled as requiring in-session verification.
- Status: Fixed in spec

## 2026-04-24

### [G1] Spec missing: leaf char rotation
- Symptom: §7.1 specifies a `\`→`-`→`/` rotation cycle for falling leaves. Code chooses a char once at spawn and never changes it. No frame timing for the rotation is given anywhere.
- Root cause: Spec states the intended behavior but provides no implementation detail (period in frames, sequence ordering, whether to loop or ping-pong).
- Impact: Leaves fall as static dots/commas — no visual suggestion of tumbling. Core autumn atmosphere is flat.
- Fix needed: Spec must define rotation char sequence, period (frames per step), and update rule. Code must apply it per leaf each physics tick.
- Status: Implemented (unproven) — `rotPhase` field added to `Particle`; leaf branch increments `(rotPhase+1)%3` every 8 frames, sets `p.ch=['\\','-','/'][rotPhase]`. Spec §7.1 updated. Ref: `199ed12`

### [G2] Spec/code mismatch: leaf horizontal motion
- Symptom: §7.1 says "sine-wave horizontal oscillation." Code uses `p.vx += state.wind * 0.04` — linear wind-driven drift, no sine component.
- Root cause: Spec describes desired feel without a formula. Implementation chose a simpler model.
- Impact: Leaves track wind linearly rather than drifting naturalistically side-to-side.
- Fix needed: Spec must define the oscillation formula (amplitude, frequency, phase offset per leaf). Code must implement it.
- Status: Implemented (unproven) — Decision: keep linear wind drift (not sine-wave). Added `p.vx = Math.max(-0.8, Math.min(0.8, p.vx))` clamp after wind accumulation. Spec §7.1 corrected to say "wind-driven drift with ±0.8 clamp." Ref: `199ed12`, `739d0dc`

### [G3] Leaf sky-spawn path missing from code
- Symptom: §7.1 says leaves "detach from tree canopy positions **or random sky positions**." Code only spawns leaves from `canopyCells` — no sky-spawn path exists.
- Root cause: "Or random sky positions" was never specced with a ratio or altitude range, so it was silently dropped in implementation.
- Impact: Leaves only appear where canopy cells exist. A sparse or narrow garden has almost no leaves. Sky-spawn would fill the scene.
- Fix needed: Spec must define sky-spawn fraction (e.g., 30% of leaf spawns appear at random cols, rows 0–3), altitude band, and spawn rate independently of canopy size.
- Status: Implemented (unproven) — 30% sky-spawn (rows 0–2, vx ±0.3) / 70% canopy-detach (vx ±0.2). Sky-spawn unreachable when canopyCells empty (leafCap=0). Spec §7.1 updated. Ref: `201b3f2`

### [G4] Leaf density cap is absolute, not canopy-proportional
- Symptom: Code caps leaves at 25 total regardless of how many canopy cells exist. A garden with 3 oaks and one with 10 oaks both get 25 leaves max.
- Root cause: No density spec exists — 25 was chosen arbitrarily.
- Impact: Dense autumn canopies look sparse; sparse canopies look proportionally correct by accident.
- Fix needed: Spec must define density as a ratio (e.g., one active leaf per N canopy cells, min 8, max 60). Code must derive the cap from `canopyCells.size`.
- Status: Implemented (unproven) — `leafCap = Math.max(0, Math.min(60, Math.floor(canopyCells.size / 3)))`. Cap 0 for pine-only gardens, up to 60 for dense oak canopy. Ref: `201b3f2`

### [G5] Leaf ground behavior unspecified
- Symptom: Leaves disappear instantly on reaching `groundY`. Spec says nothing about what happens on ground contact.
- Root cause: Ground behavior was never designed. Snow accumulates (`_snow` map), but leaves have no equivalent.
- Impact: Autumn floor has no leaf litter — the ground stays clean even during heavy leaf fall.
- Fix needed: Decide and spec ground behavior: (a) instant disappear (current), (b) brief rest then fade, (c) thin accumulation layer (like snow but shallower). Option (b) or (c) would dramatically improve autumn feel.
- Status: Implemented (unproven) — Option (b): leaf reaching groundY mutates to `leaf-rest` (ch=`-`, vx=0, vy=0, age reset to 0, maxAge=41 → 40 visible rest frames ≈ 2s). No accumulation. Ref: `199ed12`

### [G6] Pine sheds autumn leaves — evergreen bug
- Symptom: `CANOPY = new Set(['pine','oak'])` — pine cells are added to `canopyCells`, causing pines to shed leaves in autumn. Pines are evergreens and should not shed.
- Root cause: The CANOPY set was defined to drive snow accumulation and rain splash. Leaf spawn was later added to use the same set without considering evergreen/deciduous semantics.
- Impact: Pines visually shed leaves in autumn, contradicting natural behavior and the spec's own "warm colors, dead trees" autumn description.
- Fix needed: Leaf spawn must be gated to deciduous canopy only. Either add a `LEAF_CANOPY = new Set(['oak'])` set, or extend `DECIDUOUS` to also gate canopy-sourced leaf spawns. Spec must document the deciduous/evergreen split explicitly.
- Status: Implemented (unproven) — `LEAF_CANOPY = new Set(['oak','willow'])` added, `buildCollision` uses `isLeafC = LEAF_CANOPY.has(plant.type)` for canopyCells. Pine excluded. `CANOPY` retained for snow. Spec §7.4 taxonomy table added. Ref: `de4cf2d`, `739d0dc`

### [G7] Plant foliage visual vocabulary absent from spec
- Symptom: §7 never defines which characters represent foliage for any plant type. The entire visual language (oak uses `@o0&`, pine uses `/^\`, bush uses `~uvw`, etc.) exists only in the generator functions.
- Root cause: §7.3 describes procedural parameters but treats chars as implementation details. No visual vocabulary section exists.
- Impact: The spec cannot be used to verify visual correctness, reproduce the renderer, or extend the plant set consistently. New plant types will invent incompatible char languages.
- Fix needed: Add a visual vocabulary table to §7.3 or a new §7.3.1: plant type → canonical char set → meaning (foliage / trunk / flower-head / accent). Include color pairing conventions.
- Status: Implemented (unproven) — Foliage char vocabulary table added to §7.3 with 8 role rows (trunk, deciduous fill, conifer fill, hedge fill, fern frond, grass tip, flower head, accent/particle). `@` shared role noted. Ref: `739d0dc`

### [G8] Deciduous/evergreen plant classification undocumented
- Symptom: Code has `const DECIDUOUS = new Set(['oak','bush'])` determining which plants get autumn color resampling. This split is not mentioned anywhere in the spec.
- Root cause: §7.4 says "warm colors" for autumn but never defines which plant types participate.
- Impact: Future plant types (willow, dead tree) need to know which group they join. Without spec guidance the classification will drift inconsistently.
- Fix needed: §7.4 or §7.3 must explicitly list: evergreen (pine, fern, grass, mushroom — retain foliage), deciduous (oak, bush, willow — get autumn recolor), dead/bare (dead tree — already brown, no recolor needed).
- Status: Implemented (unproven) — Four-class taxonomy table added to §7.4 (Deciduous/Evergreen/Flowering/Dead) with LEAF_CANOPY and CANOPY columns. Code: `DECIDUOUS` extended with willow, `LEAF_CANOPY` created. Ref: `de4cf2d`, `739d0dc`

### [G9] Layout algorithm undocumented
- Symptom: `genLayout` runs `cols*3` placement attempts, uses `half=(width>>1)+2` padding, places all plants at `groundY`. None of this is in the spec.
- Root cause: §7.3 describes procedural generation philosophy but not the spatial layout algorithm.
- Impact: Target density, minimum/maximum plant count, spacing rules, and viewport-size behavior are unspecified. Cannot reason about whether a 40-col or 200-col viewport produces an appropriate scene.
- Fix needed: §7.3 needs a layout subsection: attempt count formula, per-plant spacing minimum, target density (plants per 10 cols), and behavior at narrow viewports (graceful degradation).
- Status: Implemented (unproven) — §7.3.1 "Layout algorithm" added: cols×3 attempts, ±2 padding, ~1 plant per 10–15 cols, sparse gardens at <60 cols correct by design. Ref: `739d0dc`

### [G10] Wind model undocumented
- Symptom: Code: `s.wind = 0.5 * Math.sin(s.frame * 0.008)`. Range ±0.5, period ~785 frames (~39s at 20fps). This value drives rain diagonal, rain char, leaf drift, and hover-rustle. Nothing in the spec describes the wind model.
- Root cause: Wind was implemented without spec. Effect coefficients (wind*0.3 for rain, wind*0.04 for leaves) were tuned by feel.
- Impact: Cannot reason about whether wind is too fast, too strong, or appropriately coupled to each weather effect without spec baseline values.
- Fix needed: §7 needs a wind model note: formula, range, period, and per-effect coupling coefficients.
- Status: Implemented (unproven) — §7.4 wind model paragraph added: `0.5*sin(frame*0.008)`, ±0.5 range, ~39s period, coupling table (rain 0.3, leaf 0.04, rustle). Ref: `739d0dc`

### [G11] Canopy cell threshold (dy≥3) undocumented
- Symptom: Code: `if(isC&&dy>=3) can.add(key)` — only cells 3+ rows above base are canopy. Lower trunk rows are excluded from canopy even if they have foliage chars. No spec rationale exists.
- Root cause: Tuning decision made in code. Without it, trunk cells would be leaf/snow spawn points.
- Impact: The effective canopy spawn zone is smaller than the visual canopy. Dense lower-canopy oaks have fewer leaf sources than their visual size implies.
- Fix needed: §7.2 plant collision surfaces section must document: canopy cells are defined as plant cells at `dy ≥ 3` above ground anchor, trunk cells (`dy < 3`) are excluded, rationale is preventing trunk-spawned leaves.
- Status: Implemented (unproven) — §7.2 "Canopy surface models" paragraph added: `canopyCells` (LEAF_CANOPY, dy≥3, leaf spawn) vs `topSurfaces` (all plants, snow). Threshold rationale documented. Ref: `739d0dc`

### [G12] Layer update cadence: spec vs. implementation mismatch
- Symptom: §7.2 specifies per-layer update cadences (plants: 300–500ms, particles: 40–80ms, creatures: 100–200ms). Code runs a single unified tick at ~50ms. There is no per-layer cadence.
- Root cause: The spec describes the curses TUI performance model. The browser viewer uses a unified RAF loop. The spec was not updated to reflect this.
- Impact: Future implementers may build an unnecessary per-layer cadence system, or assume the unified model is a deliberate departure from spec.
- Fix needed: §7.2 must clarify that the per-layer cadence is the curses/terminal target; the browser viewer uses a unified 50ms tick and this is intentional and correct for that platform.
- Status: Implemented (unproven) — §7.2 "Tick cadence note" added: browser viewer uses unified ~50ms RAF tick; per-layer cadences describe curses/TUI intent; both conformant. Ref: `739d0dc`

## 2026-04-22

### [1] Letter text still reads as too large / not vertically centered
- Symptom: Even after the 2026-04-21 fix to `.85rem / LH=21`, the letter body is perceived as too large relative to the UI chrome and feels mis-positioned — not centered or moved up enough relative to the garden visible behind the scrim.
- Root cause: Two separate issues conflated. (a) The pretext `LETTER_FONT` and CSS `font-size` may still differ by a rounding delta, creating slightly-too-tall lines. (b) The reading scrim uses `justify-content: center` vertically inside `#s-reading`, which centers the whole card in the viewport — on tall screens this puts the card lower than expected.
- Impact: The letter feels like a form field, not a letter held in one's hands over a garden.
- Fix needed: Confirm `LETTER_FONT` matches rendered CSS exactly; try vertically anchoring the scrim toward the upper third (`align-items: flex-start; padding-top: 10vh`) rather than pure center.
- Status: Implemented (unproven) — `#s-reading` now uses `justify-content: flex-start; padding: 10vh 2rem 2rem` to anchor scrim to upper area. `.letter-body` changed from `.85rem` to `13px` to exactly match `LETTER_FONT` constant. Pending visual QA to confirm feel.

### [2] Dev overlay keybindings not visible after Shift+G
- Symptom: After pressing Shift+G to activate the dev grid overlay, the keybinding list added to `ov.textContent` was not clearly visible to the user.
- Root cause: Likely one of: (a) text color `rgba(200,0,0,.8)` has low contrast against the dark garden background at certain color modes; (b) `ov.textContent` clobbers newlines if `white-space: pre` is not applied at render time; (c) the overlay div background-image CSS is computed once at creation using the current CW/CH — if these change after creation the grid lines mis-align but don't cause a reflow.
- Impact: Key dev tool unusable for onboarding to the key layout.
- Fix needed: Increase contrast (use a dark semi-transparent bg behind the text area), confirm `white-space: pre` renders multi-line, test at all 4 color modes.
- Status: Implemented (unproven) — `#dev-overlay` color changed to `rgba(180,0,0,1)` (fully opaque) and `text-shadow` added (`0 0 4px rgba(255,255,255,.95), 0 1px 6px rgba(255,255,255,.9)`) creating a white halo that ensures legibility against any garden background. `white-space: pre` was already in CSS.

### [3] Dev grid overlay disappears / breaks when season is cycled
- Symptom: After pressing `<`/`>` to change season, the grid overlay (if active) either disappears or the grid lines become misaligned.
- Root cause: `garden._reset()` re-runs `blit()` which syncs `_rowEls`. If row count changes the `removeChild` loop may interact unexpectedly with the overlay div. Additionally, the background-image CSS was computed from CW/CH at overlay-creation time — if `_measure()` returns different values after reset, the grid lines drift from actual character cell boundaries.
- Impact: Overlay must be re-created or its background-image must be recomputed after every reset to remain accurate.
- Fix needed: On `garden._reset()`, if `_devGridActive`, recompute the overlay's `backgroundImage` using the new CW/CH values. Alternatively, redraw the grid lines via a canvas overlay that is resized with the garden.
- Status: Implemented (unproven) — added `_refreshDevGridBg()` which recomputes `backgroundImage` from current `CW`/`CH`. Called after `garden._reset()` in season cycle (`,`/`.` keys) and after `garden.onResize()` in the window resize handler.

### [4] Animal type and trust tier not shown in dev info area
- Symptom: The HUD shows animal state text (`[f] · feed the rabbit`) but in dev mode the overlay / HUD doesn't show `rabbit/tier2` in a compact debug-readable format alongside season and color mode.
- Root cause: The dev overlay (Shift+G) only shows grid metrics and season. The `devCycleAnimal()` function updates `#hud-animal` text but not in a dev-structured format; no compact state summary exists.
- Impact: QA requires constant cross-referencing of HUD text and mental tracking of state.
- Fix needed: Add animal type + tier to dev overlay's status line: `season: spring | color: default | animal: rabbit/2`.
- Status: Implemented (unproven) — dev overlay tick now reads `s?.animalData` and appends `animal: {type}/{tier}` (or `none`) to the status line alongside season/color.

### [5] Animal interactions too thin — trust arc has no texture between tiers
- Symptom: The trust arc (4 tiers, ~14 feed actions to bond) exists in data but the experience between tiers is nearly identical. There is no behavioral change visible in the garden between, say, tier 1 and tier 2 except the art changing.
- Root cause: No per-tier behavioral variation has been designed or implemented. Tier progression is mechanical (count actions, change art), not experiential (animal does different things at different trust levels).
- Fix needed: Spec out and implement per-tier behavioral signature for each animal. E.g., rabbit at tier 1 twitches when moused over; at tier 2 hops between two columns; at tier 3 grooms itself. See SPEC §7.7 (to be written — item 13–15 of this session).
- Status: Implemented (live QA pass) — `CreatureLayer` now owns a single relationship-animal actor with tier-specific mode/pose loops for all four animals, actor-owned feed reactions, and dev-overlay behavior readouts. Verified on 2026-04-27 by cycling all 16 dev states and confirming distinct `edge / approach / patrol / settled` behavior families in the browser.

### [6] Carrot feed animation not visible
- Symptom: When feeding the rabbit (`f` key), the carrot overlay (`#carrot-anim`) does not appear visibly, or appears at the wrong position.
- Root cause (suspected): The carrot div is appended to `#g` with `position:absolute`. `#g` has `position:fixed; inset:0; overflow:hidden`. The carrot's `top` is computed as `(homeRow-2)*CH` — if `homeRow` is 0 or 1, this yields a negative `top`, placing it above the visible area. Additionally, the font size on the carrot spans (`font: 13px/15px 'Courier New'`) may not match the garden grid exactly, misaligning the carrot from the character grid.
- Impact: Core game-feel moment is invisible.
- Fix needed: (a) Clamp `top` to at least `0`. (b) Log carrot position to console on creation to diagnose. (c) Confirm `#g` is the correct parent for `position:absolute` overlays by verifying `#frb` (first-run banner uses `position:fixed`) — carrot should use `position:absolute` relative to `#g` since `#g` is `position:fixed`, making it the containing block.
- Status: Fixed differently — the rabbit-only DOM carrot overlay owner was removed. Feed visuals now run through the authoritative `CreatureLayer` actor path, with a grid-aligned rabbit feed glyph and matching actor reaction instead of a separate `#carrot-anim` overlay.

### [7] Ambient bird visual needs redesign
- Symptom: Ambient birds are single characters (`v`/`~`) that traverse the sky. This is visually underdeveloped compared to the richness of butterflies and other creatures.
- Root cause: Placeholder implementation inherited from early prototyping. The SPEC (§7.1) describes multi-char bird silhouettes with more visual presence.
- Fix needed: Design a proper 2-3 char ambient bird art (distinct from the letter-bird which is multi-line). Consider `>-`, `-<`, or simple 2-char wingbeat cycle. See bird redesign discussion in SPEC §7.7 (to be written).
- Status: Implemented (live QA pass) — ambient birds now render as multi-char flap-cycle silhouettes with optional flock spawns, plus a dev spawn hook for direct inspection. Verified on 2026-04-27 in the browser via `Shift+N` live QA screenshots.

### [8] Fireflies appear during night mode (wrong — should be dusk/evening only)
- Symptom: In `spring-night`, `summer-night`, etc., fireflies still spawn. Fireflies in nature are a dusk and early-evening phenomenon, not a late-night one.
- Root cause: The `CreatureLayer._initCreatures()` spawns fireflies for `season === 'summer'` with no time-of-day gate. The current night mode does not disable firefly spawning.
- Fix needed: Gate firefly spawning to `time === 'dusk' || time === 'evening'`. Fireflies should not appear in full night or day. This requires implementing the time-of-day dimension as a first-class state (not just a dev overlay color mode). See SPEC §7.5 and new §7.7.
- Status: Implemented (unproven) — browser viewer now has `day / evening / night` time-of-day detection (local clock, `?time=`, and dev cycle), and fireflies spawn only during `evening`.

### [9] Missing evening/dusk mode between day and night
- Symptom: The dev time-of-day cycle jumps from day directly to full night. There is no dusk/evening state where fireflies come out, the palette warms, but stars are not yet visible.
- Root cause: SPEC §7.5 defined day/dusk/night as a concept but implementation only added day and night. Evening/dusk was deferred without a concrete state machine.
- Fix needed: Add `evening` as a distinct state between day and night: fireflies active, warm sky gradient shift (amber tones), no stars or moon yet visible. See SPEC §7.7 (to be written — time-of-day state machine).
- Status: Implemented (unproven) — browser viewer now supports `evening` in the dev season/time cycle and applies a warm dusk sky gradient before full night.

### [10] Rain droplets render green — should be blue
- Symptom: Rain particles use palette color `'cyan'` which maps to `C.cyan = '#246858'` — a teal-green. On the B&W/muted garden palette, this reads as distinctly green rather than rain-blue.
- Root cause: The palette was designed for B&W aesthetics. `'cyan'` was chosen for rain early in development but was never revisited when the B&W palette was finalized.
- Fix needed: Change rain particle color from `'cyan'` to a palette entry closer to blue-gray. Add `rain: '#4a6888'` to `C` and use `'rain'` for all rain/splash/fragment particles. Exact value TBD based on visual QA against all 4 color modes.
- Status: Implemented (unproven) — `rain: '#4a6888'` added to `C`. Rain particles in `_spawn()` (spring and autumn) and frag particles in `_fragments()` now use `'rain'`. Pending visual QA against all 4 color modes to confirm exact value.

### [11] Moon is too small; needs phase cycling
- Symptom: The moon renders as `()` — two characters — which is barely visible in the night sky. It does not cycle through phases the way the Claude Code install moon animates.
- Root cause: Placeholder implementation. A 2-char glyph at a fixed brightness is the simplest possible moon. Phase cycling was not spec'd.
- Fix needed: Implement moon as a taller ASCII art block (3-4 rows, 3-4 chars wide) that cycles through visible phases: new (absent), crescent `(`, quarter `C`, gibbous `(O`, full `O`. Phase derived from `Math.floor(Date.now() / 86400000 / 29.5) % 8` (synodic month). Current dev-mode moon should show the current phase at startup; `<`/`>` cycling could step phases for QA.
- Status: Needs design + spec (add to SPEC §7.7)

### [12] Dev keybindings missing coverage for gifts and other interactables
- Symptom: The dev overlay lists the current keybindings but has no way to trigger gift discovery, examine a gift, show the memory modal, or simulate different bundle states (all-read, post-complete, etc.).
- Root cause: The dev tool keybinding plan (2026-04-21) focused on garden visual state (seasons, animals, color modes) and missed the full interaction surface including gift discovery, archive, and bundle state simulation.
- Fix needed: Add dev bindings for: `Shift+P` post-complete toggle, `Shift+F` first-run banner re-trigger, `Shift+I` inject/cycle gift item state, `Shift+V` simulate visit (increment visitCount). Update dev overlay to show these. Reference SPEC §13.5.
- Status: Implemented (unproven) — all four keys wired in the `keydown` handler (dev fixture only). Overlay keybinding display updated with a fifth line listing the new keys.

### [13–15] Garden system architecture undocumented as a state machine; no user flow graphs per subsystem
- Symptom: The garden has multiple overlapping dimensions (season, time-of-day, animal trust, gift discovery, post-completion) each with their own state machine, but no single document describes how they compose, what triggers state transitions, or what the user experiences at each state intersection.
- Root cause: The garden grew incrementally. §7 covers animations and season mechanics but has no unified model of all dimensions and their interactions.
- Impact: Impossible to reason about gaps (fireflies at night, missing evening mode, etc.) without mentally reconstructing the full state space each time. New contributors and future QA will not be able to systematically verify all states are correct.
- Fix needed: Author `SPEC §7.7 — Garden State Machine Architecture` (written in this session — see below). Include: (a) full dimension table, (b) state machine per dimension with transitions and triggers, (c) composition rules for overlapping dimensions, (d) user flow leaf layout for each major subsystem. See SPEC §7.7.
- Status: Spec written (this session)

## 2026-04-26

### [G13] Leaf rotation phase sync — all leaves start at rotPhase=0
- Symptom: Every leaf particle starts with `rotPhase=0` (char `\`). Leaves spawned within a few ticks of each other rotate in lockstep — all showing the same char at the same time, creating a uniform "wave" rather than a natural tumble.
- Root cause: `Particle` constructor sets `this.rotPhase=0` unconditionally. No per-leaf randomization of initial phase.
- Impact: Visual uniformity undermines the organic tumble feel. Most visible when many leaves spawn simultaneously (e.g., after season cycle to autumn).
- Fix needed: Randomize initial `rotPhase` per leaf at spawn time: `this.rotPhase = Math.floor(Math.random() * 3)` — or set it in `_spawn` when creating leaf particles. Also consider randomizing the initial char to match the phase.
- Status: Implemented (unproven) — `Particle` constructor now uses `Math.floor(Math.random()*3)` instead of `0`. Each leaf starts at a random rotation phase, breaking lockstep. Pending visual QA. Ref: `09fca8d`

### [G14] spawnAt still creates leaves on pine trees in autumn
- Symptom: Clicking a pine tree in autumn spawns autumn-coloured leaves from pine cells. `spawnAt` uses `state.collisionMap` (all plant cells) not `state.canopyCells` (LEAF_CANOPY only).
- Root cause: `spawnAt` was not updated in the LEAF_CANOPY split. The plan explicitly deferred this: "clicking a pine tree in autumn will still spawn leaves from it. This is a known gap."
- Impact: Contradicts the evergreen taxonomy — pines should not shed leaves. Cursor interaction breaks the visual rule that ambient particles follow.
- Fix needed: Gate `spawnAt` leaf creation to only fire on LEAF_CANOPY plant cells, or check plant type at the cursor position against `LEAF_CANOPY` before spawning.
- Status: Implemented (unproven) — `spawnAt` now checks `state.canopyCells` instead of `state.collisionMap`. Clicking pines no longer spawns leaves. Pending visual QA. Ref: `22aebf9`

### [G15] leafCount cap doesn't include leaf-rest particles
- Symptom: `leafCount = this._p.filter(p=>p.kind==='leaf').length` counts only falling leaves. Resting leaves (`kind==='leaf-rest'`) are excluded from the cap check. Total leaf-related particles (falling + resting) can exceed `leafCap`.
- Root cause: The filter checks `kind==='leaf'` only. When leaves transition to `leaf-rest`, they change kind and exit the count.
- Impact: At steady state with leafCap=60 and 40-frame rest, up to ~80-90 total leaf/leaf-rest particles could exist simultaneously. Unlikely to cause visible issues but represents a subtle density overshoot.
- Fix needed: Either include `leaf-rest` in the count (`p.kind==='leaf'||p.kind==='leaf-rest'`), or accept the overshoot as intentional (resting leaves are transient and low visual weight). Document the decision.
- Status: Implemented (unproven) — leafCount filter now includes `leaf-rest` particles (`p.kind==='leaf'||p.kind==='leaf-rest'`). Cap respects total leaf presence. Ref: `22aebf9`

### [G16] Leaf vy has no terminal velocity cap
- Symptom: Leaf gravity accumulates `p.vy += 0.04` per tick with no upper bound. Rain has `Math.min(p.vy+0.08, 2.2)` capping terminal velocity; leaves do not.
- Root cause: Rain had a cap from early implementation; leaves were simpler and no cap was added. The `*0.4` dampening factor on position update (`p.y += p.vy * 0.4`) slows effective movement but doesn't cap acceleration.
- Impact: In practice, leaves hit groundY before vy grows large (typical fall is 25-35 rows, ~30 ticks). A leaf at maxAge=150 that somehow stays airborne would reach vy=6.0 — but this can't happen in normal gardens. Theoretical only.
- Status: Implemented (unproven) — `p.vy=Math.min(p.vy+0.04,1.5)` caps terminal velocity at 1.5. Ref: `22aebf9`

### [G17] Autumn palette orange value may be indistinguishable from brown in B&W mode
- Symptom: `C.orange = '#a06420'` and `C.brown = '#7a5830'` — in B&W or desaturated colour modes, both map to similar gray tones. The plan noted this as a risk: "Visual QA in colour mode 3 (B&W) — if indistinguishable, note in FAILURE_LOG."
- Root cause: The hex values differ by ~38 in luminance (orange: ~100, brown: ~76 in sRGB red channel), which may not survive desaturation.
- Impact: In B&W mode, orange leaves are visually identical to brown leaves. The palette expansion provides no visible variety in that mode.
- Fix needed: Visual QA across all 4 colour modes. If indistinguishable, either adjust `#a06420` brighter or accept as an inherent limitation of the B&W palette.
- Status: Implemented (unproven) — orange brightened from `#a06420` to `#b07020` (luminance gap vs brown widened from ~16 to ~28 in grayscale). Pending QA in all 4 colour modes. Ref: `22aebf9`

### [G18] Night mode text does not invert to white-on-black
- Symptom: When night mode activates, text remains dark. Should invert to white text on black background — no surrounding box, just the text colour flip.
- Impact: Text becomes unreadable or very low-contrast at night.
- Fix needed: On night toggle, set text colour to white (or near-white) and background to black/dark. No box/border around text — purely colour inversion.
- Status: Implemented (unproven) — Added `NIGHT_PALETTE` with brighter variants for all plant/weather colors. `_applyNightPalette(on)` swaps `C` entries and sets CSS vars `--text`, `--bg`, `--scrim-bg` for UI elements. Called on `_reset()` and season cycling. Scrim backgrounds now use `var(--scrim-bg)`. `#g` background uses `var(--bg)`. `setGroundBg` reads from `C.sky`/`C.dim_green` directly (night values already applied).

### [G19] Pine trees appear inverted in night mode
- Symptom: Pine tree rendering looks inverted (possibly chars or colours are wrong) when night mode is active.
- Impact: Visual glitch breaks the garden aesthetic at night.
- Fix needed: Investigate pine rendering path in night mode; likely needs colour/char adjustment for dark background context.
- Status: Implemented (unproven) — Addressed by G18 night palette. Pine uses `bright_green` (#62923e) and `green` (#4a7030) which are now remapped to brighter variants (#78b870 / #5a9858) when night palette is active. `brown` trunk color also brightened (#a08868). Pending visual QA.

### [G20] Moon too small and lacks phase cycles
- Symptom: The moon element in night mode is too small and does not cycle through phases (new → crescent → half → full → etc.).
- Impact: Night sky feels static and the moon lacks presence.
- Fix needed: Increase moon size and implement phase cycling (tied to time or frame count).
- Status: Implemented (unproven) — Replaced 2-char `()` with `MOON_ART` array (8 phases, 3 rows each). `_moonPhase()` derives current phase from real date using synodic month (29.53 days) anchored to known new moon (2000-01-06). Phase 0 (new) renders nothing; phases 1-7 render 3-row ASCII art. Pending visual QA.

### [G21] Animals should deliver the letter (bird TUI interaction)
- Symptom: The bird/animal creature does not participate in letter delivery. The tui (bird) experience should involve the animal bringing the letter to the recipient.
- Impact: Missed emotional moment — the garden creatures feel disconnected from the letter's purpose.
- Fix needed: Design and implement letter delivery animation where the bird (tui) carries/delivers the letter. This is an interaction/animation feature, not a bug.
- Status: Implemented (unproven) — Added `_playDelivery(cb)` function using existing `_ANIMAL_DELIVERY_FRAMES` data. On first letter read (when animal is triggered), a centered overlay animates the delivery frames (12 ticks at 150ms each, ~1.8s) before fading and opening the reading screen. Uses `_deliveryPlayed` flag to show once per bundle load. Pending visual QA.

### [G22] Cannot interact with pine tree leaves via mouse
- Symptom: Clicking on pine tree foliage cells does not produce any particle interaction (no leaf burst). This is now partially expected after G14 gated `spawnAt` to `canopyCells` only — but the user expects some interaction on pines (e.g., needle particles or a rustle effect).
- Impact: Pines feel dead to interaction. Other trees respond to clicks but pines do nothing.
- Fix needed: Either add pine-specific interaction (needle drop, rustle) or add pine cells back to an interaction map distinct from leaf spawning.
- Status: Implemented (unproven) — Added pine needle rustle fallback in `spawnAt`. When no canopy cells are hit (n===0), checks `collisionMap` for pine cells (in collision but not canopy). Spawns up to 6 `frag` particles with needle-like chars (`'`, `.`, `` ` ``), bright_green/green colors, short lifespan (8-16 frames). Pines now respond to clicks without shedding deciduous leaves. Pending visual QA.

### [G23] Letter needs original citation at bottom; remove em dash
- Symptom: The letter display does not show the original citation/attribution at the bottom. Also contains an em dash that should be removed.
- Impact: Missing attribution feels incomplete; em dash is a stylistic issue.
- Fix needed: Add citation line at bottom of letter body. Find and remove the em dash from letter content/template.
- Status: Implemented (unproven) — Re-encoded `test_fixture.lateletter` ciphertext: replaced em dash at "groomed — you know" with comma, appended `\n\nBased on "Letter from Heaven" (author unknown)` as attribution. Passphrase hint changed from "our best friend" to "biscuit" for demo. Pending visual QA.

### [G24] Mobile responsiveness needs verification
- Symptom: The viewer and letter display have not been verified on mobile viewports. Layout, text sizing, touch interactions, and garden rendering may break on small screens.
- Impact: Recipients on phones may have a degraded or broken experience.
- Fix needed: Test across mobile viewports (320px–428px width). Verify: garden scales, letter is readable, touch events work for plant interaction, no horizontal overflow.
- Status: Implemented (unproven) — Added `@media (max-width: 480px)` breakpoint with: reduced scrim padding, smaller garden font (11px/13px), smaller letter body (12px), tighter button gaps, adjusted HUD position. Added `@media (max-width: 360px)` for narrowest viewports with further text size reduction. Touch events inherently supported (click handlers fire from touch). Pending visual QA on real devices.

### [G25] Night + color mode palette corruption
- Symptom: When night mode is active and user cycles color modes (Shift+B), mode 1 stashes `C.sky`/`C.dim_green` into `_savedPalette` — but night already overwrote those keys. Restoring on mode 0 clobbers the live night palette permanently.
- Root cause: `_devCycleColorMode` and `_applyNightPalette` both mutate `C` in-place with independent save/restore stashes that don't know about each other.
- Impact: Palette permanently corrupted after night + color mode cycling. Only reload recovers.
- Fix needed: Guard `_devCycleColorMode` to stash `_dayPalette` values (not current C values) when night is active.
- Status: Implemented (unproven) — Mode 1 entry now stashes `_dayPalette.sky`/`_dayPalette.dim_green` when night is active (not current C values). Restore paths (mode 1→2, mode 3→0) write back into `_dayPalette` when night is active, then re-apply night palette values to C. Pending visual QA: cycle night + all 4 color modes.

### [G26] Pine needle fallback triggers on all non-canopy plant cells
- Symptom: Clicking any plant cell that is in `collisionMap` but not `canopyCells` spawns pine needle particles — including flower stems, grass, mushroom stalks, fern fronds, bush bases, trunk segments.
- Root cause: `spawnAt` fallback uses `collisionMap \ canopyCells` as a proxy for pine cells. This set is too broad — it includes every non-canopy plant cell, not just pines.
- Impact: Clicking a daisy stem or grass blade produces pine-colored needle particles.
- Fix needed: Add a `pineCells` set in `buildCollision` tracking only pine plant cells. Use that set in the `spawnAt` fallback.
- Status: Implemented (unproven) — Added `pine` Set in `buildCollision` (isPine && dy>=3). Stored as `state.pineCells`. `spawnAt` fallback now checks `state.pineCells.has(key)` instead of `collisionMap \ canopyCells`. Pending visual QA.

### [G27] Delivery animation interval leak on navigation
- Symptom: If user navigates away during the 1.8s delivery animation (clicks back, opens archive), `clearInterval` never fires. Stale `cb()` eventually calls `showReading` on the wrong screen state.
- Root cause: `_playDelivery` stores the interval ID locally with no external cancel handle. No cleanup on screen transitions.
- Impact: Stale callback fires after animation, potentially showing reading screen over archive or garden.
- Fix needed: Store interval ID at module level, clear it on `showScreen` calls, wrap `cb()` in protection against stale invocation.
- Status: Implemented (unproven) — Module-level `_deliveryIv`/`_deliveryOv` refs. `_cancelDelivery()` clears interval + removes overlay. Called at top of `showScreen()` and at start of `_playDelivery()`. Interval body wrapped in try/catch with `_cancelDelivery()` on error. Overlay z-index raised to 12 (above screen z-index 10). Pending QA.

### [G28] Memory modal background not night-aware
- Symptom: `mem-inner` background is hardcoded `rgba(249,248,245,.94)` — bright white card renders in night mode against dark garden.
- Root cause: Missed during G18 night mode CSS var conversion.
- Impact: Visual break in night mode when opening memory modal.
- Fix needed: Convert `mem-inner` background to use a CSS var or derive from `--scrim-bg`.
- Status: Implemented (unproven) — `mem-inner` background changed from `rgba(249,248,245,.94)` to `var(--scrim-bg)`. Night palette already sets `--scrim-bg` to `rgba(11,14,22,.76)`. Pending visual QA.

### [G29] Moon phase negative modulo for pre-2000 system clocks
- Symptom: If system clock is before 2000-01-06, `days` is negative and `days % 29.53` returns negative in JS. Negative index into `MOON_ART` returns `undefined`, causing silent rendering failure.
- Root cause: JS `%` operator preserves sign of dividend. No double-modulo wrap.
- Impact: Moon invisible on pre-2000 clocks (unlikely but trivially fixable).
- Fix needed: Use `(((days % 29.53) + 29.53) % 29.53)` double-modulo pattern.
- Status: Implemented (unproven) — `_moonPhase()` now uses `((days%29.53)+29.53)%29.53` before dividing. Pending QA.

## 2026-04-21

### Letter body text still visually larger than surrounding UI
- Symptom: After 16px→15px fix, letter body still reads as larger than the rest of the UI because `.t2` (0.85rem ≈ 12.75px) is the dominant text size in menus, archive, HUD. Letter body at 15px/1rem is `.t1` scale — readable but inconsistent with the "same size as everything else" expectation.
- Impact: Visual hierarchy feels off; letter body stands out as oversized compared to all other UI text.
- Fix: `.85rem / 1.65` (matches `.t2`). Pretext constants: `13px / LH=21`.
- Status: Fixed

### Garden has too few interactive moments
- Symptom: Beyond plant click (leaf burst) and rustle-on-hover, the garden has no other discoverable interactions. Recipients exploring the space find nothing new after the first click.
- Impact: Garden feels static after initial discovery; no reason to return and explore. Undermines the "living space" intent.
- Fix planned: Plan additional interaction layer (see dev tool plan in SPEC §13.1).
- Status: Needs planning

### Dev fixture shows no animal by default — hard to test animal system
- Symptom: In dev fixture mode, animals are only visible if the bundle has a garden_gift of type 'animal' with a satisfied trigger. Most test bundles don't have this, so the entire animal system is invisible during dev.
- Root cause: No auto-init of animal state in dev fixture.
- Fix planned: In dev fixture, if no animal gift in bundle, auto-inject a cat at tier 0 (wild) so the system is always exercised.
- Status: Fix planned (part of dev tool plan)

### No way to cycle seasons in the browser viewer for QA
- Symptom: Season is derived from system date. Seeing all 4 seasonal garden states requires waiting months or manually changing the system clock.
- Fix planned: `Shift+S` keybinding in dev fixture mode cycles spring → summer → autumn → winter → spring and calls `garden.setSeason()` + `garden._reset()`.
- Status: Fix planned (part of dev tool plan)

## 2026-04-20

### Garden clicks blocked by transparent screen overlays
- Symptom: Clicking plants in the garden spawns no leaves/particles when any screen is active, even transparent ones (`#s-archive`, `#s-welcome` have `background: none` but are still hit-tested).
- Root cause: `.screen.active { pointer-events: auto }` is applied to the full-viewport wrapper (`position: fixed; inset: 0`), not just the inner card. The wrapper eats all pointer events even when visually transparent.
- Impact: Garden is never interactive when archive or welcome is shown; plant click-to-burst doesn't work during those views.
- Fix: Removed `pointer-events: auto` from `.screen.active`. Added it to `.scrim`, `.inbox`, `.welcome-inner` directly. Wrapper stays `pointer-events: none`; clicks pass through to `#g` in transparent areas.
- Follow-up: `#s-welcome.active` must keep full `pointer-events: auto` — the `dragover` handler only lives on `#drop-zone`, so any drag over the wrapper area outside the drop zone falls through to `#g` with no `preventDefault`, blocking the drop. Welcome screen doesn't need garden click-through (no bundle loaded), so full auto is correct there.
- Status: Fixed

### Letter reading card too large, obscures garden
- Symptom: The reading scrim (`width: min(680px, 96vw); max-height: 86vh`) with `align-items: stretch` fills most of the viewport, blocking the garden that is meant to show through.
- Root cause: `#s-reading` uses stretch layout rather than centered; scrim width and height are too generous.
- Impact: The garden—the emotional backdrop—is hidden while reading a letter.
- Fix: Centered reading screen (dropped stretch layout), scrim `min(520px, 88vw)` / `max-height: 72vh`, padding trimmed to `1.75rem 2rem`.
- Status: Fixed

### Letter body font size doesn't match UI
- Symptom: Body text uses `15px / 1.65` everywhere; the letter body uses hardcoded `font-size: 16px; line-height: 30px` in CSS and `'16px "Times New Roman"' / LH=30` in the pretext constants—visibly larger than all other UI text.
- Root cause: Constants set independently of the body font, never reconciled.
- Fix: `LETTER_FONT = '15px "Times New Roman", Times, serif'`, `LETTER_LH = 25`, `.letter-body { font-size: 15px; line-height: 1.65 }`.
- Status: Fixed

### pretext `prepareWithSegments` called on every resize (performance)
- Symptom: `renderBody()` is called by ResizeObserver on every width change and re-runs `prepareWithSegments` each time. `prepareWithSegments` does Unicode segmentation + Canvas measurement — the expensive phase — even though only `layoutWithLines` needs to re-run on resize.
- Root cause: No caching of the prepared object between resize calls.
- Impact: Janky resize behavior; wasted work on every window resize event. (Correctness is not broken, only performance.)
- Fix: Cache `_prepared`/`_preparedText`; `prepareWithSegments` only runs when text changes, `layoutWithLines` runs on every resize. Cache cleared in `teardownResize()` on leave.
- Status: Fixed

### Offline question-bank runtime design was underspecified
- Symptom: The spec said the offline question bank should exist and be versioned, but it did not define how universal questions and personalization should combine, where prototype questions live before the full bank ships, or what local runtime selector state is allowed to persist.
- Impact: Implementation could drift into either a flat random prompt list or an ad hoc personalization system with unstable storage and no clean path from prototype seed questions to the canonical release bank.
- Resolution: Updated `docs/SPEC.md` to define a layered offline selector (universal base set plus personalization layer), a temporary reviewed seed-bank file for the first offline vertical slice, the long-term bundled read-only canonical bank format, and optional local `selector_state.json` runtime storage under `~/.lateletter/author/`.
- Status: Fixed in spec
