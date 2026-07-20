# Garden Feature-Gap and Renderer Parity

Verified 2026-07-21 against the normal, checksummed, HMAC-authenticated,
encrypted v2 synthetic bundle in `sealed_demo.lateletter` with passcode
`garden`. “Renderer parity” below means that terminal and HTML consume the
same canonical world state, evaluator, materialization receipts, event trace,
and semantic commands. It does **not** mean that the full §7.8 product contract
or its human acceptance gates have passed.

The specification finding remains controlling:

> The existing Garden began as a renderer-backed recipient gift loop, not the
> standalone, author-directed cozy garden promised by §7.8. Shared runtime
> ownership is now implemented, but the product must not be described as a
> “full,” “standalone,” or “parity” Garden until every §7.8.13 gate passes a
> normal sealed production bundle in every supported modality.

## Feature parity

| §7.8 contract | Terminal | HTML | Renderer parity | Release state |
|---|---|---|---|---|
| One authoritative deterministic world | Canonical immutable `WorldState`, reducer, persistence, clock, and projection | Byte-conformant JS model, reducer, persistence, clock, and projection | **Yes** — golden command replay and authored materialization compare exact canonical bytes | Automated core complete |
| Authentication, checksum, and real decryption | Canonical checksum/HMAC gate and AES-GCM message/program open | Matching checksum, WebCrypto HMAC, AES-GCM message/program open | **Yes** | Production-path pass |
| Semantic input vocabulary | All 15 commands route through the terminal adapter | Touch, mouse, and browser-keyboard adapters emit the same command bytes | **Yes at adapter/reducer level** | **Partial Gate 2** — every visible action has not been traversed in every modality |
| Standalone glance/tend/dwell entry | Garden works without a bundle; object/action help, care, arrangement, journal, pause | Visible standalone entry, object list, care, arrangement, journal, dwell/pause | **Functional parity** | **Blocked Gate 3** — human usefulness observation is mandatory |
| Plant care and stable growth topology | Persistent rooted topology; inspect, water, prune/train/transplant semantics; offline growth | Same stable IDs/topology hashes and care reducer | **Yes for canonical semantics** | Gate 4 pass; richer authored bounds/visual-stage observation remain open |
| Placement, movement, and undo | Place plant/fixture, move fixture, undo | Visible place/move/undo controls using the same reducer | **Yes** | Production-path subset observed |
| Fixtures and connected tiles | Versioned catalog and all 16 masks for five connected families | Same canonical fixtures and masks | **Yes for data/state** | **Partial** — several promised direct fixture verbs remain inspect-only and screenshot portability is open |
| Collectibles, inventory, and journal | Stable collectibles, collect state, inventory, automatic journal | Same; accessible object list and visible journal | **Yes** | Production v2 keepsake collected in both-runtime verification |
| Deterministic animal AI and bonding | Four species, persistent personality/memory/needs, utility choice, hysteresis, choreography lock, varied bonding | Shared animal state/interactions and authored materialization | **State parity; presentation partial** | **Partial Gate 7** — distinct four-tier repertoires and memory-driven live choices are incomplete |
| Encrypted author programming | v2 program decrypt, schedule expansion, evaluator, materializer, re-evaluation after actions | Same program schema/evaluator/schedules/materializer and in-session re-evaluation | **Yes for runtime** | **Partial Gate 8** — full no-JSON interactive author arc has not passed end to end |
| Conditions, recurrence, missed events, rollback | Priority/exclusivity, once/recurring, DST gap/fold, bounded catch-up, three missed policies | Matching evaluator and schedule vectors | **Yes** | Gate 9 pass |
| Shared camera/world coordinates and reduced motion | Canonical camera projected to terminal cells; pause command | Same fixed-point camera; visible pan and persistent pause/reduced-motion control | **Canonical parity** | **Partial Gate 10** — long rendered pans and p95 budgets remain open |
| Versioned Unicode/ASCII atlas | `ascii-safe` and `unicode-cell-safe` profiles | `browser-font-locked`/rich profiles with fallbacks | **Manifest parity** | **Partial Gate 6** — supported screenshot matrix for tofu/overlap/jitter is absent |
| Astronomical, privacy-preserving sky | Coarse-location and labeled fallback contracts exist | Live viewer still uses its artistic renderer sky; no complete shared star projection path | **No** | **Partial Gate 11** — only 2/12 trusted vectors and no live activation/privacy browser run |
| Accessibility and target size | Full semantic command help and line-readable state | Focusable object list/action sheet, scene summary, persistent pause, 44px controls, narrow layout | **Semantic parity** | **Partial Gate 12** — VoiceOver/NVDA, no-color, and 200% zoom observation remain open |
| Deterministic replay and humane absence | Clock rollback clamps; 1/7/30/365-day absence loses nothing; bounded summaries | Matching clock/replay state and persistence | **Yes** | Gate 13 pass; deterministic replay covered |
| Production bundle | v2 program materializes authored bench, rabbit, keepsake, and letter state | Same visible objects and exact decrypted letter | **Yes locally** | **Partial Gate 1** — third-return plant arc and published deployment still need completion observation |
| Human emotional/standalone acceptance | Not signed off | Not signed off | Not applicable | **Blocked Gates 3 and 14** |

## Current §7.8.13 gate result

| Result | Gates |
|---|---|
| **PASS** | 4 Plant stability; 5 Layout safety; 9 Temporal correctness; 13 Absence/ethics |
| **PARTIAL** | 1 Production reachability; 2 Input parity; 6 Atlas portability; 7 Animal behavior; 8 Author control; 10 Parallax/performance; 11 Sky accuracy/privacy; 12 Accessibility |
| **BLOCKED on required human evidence** | 3 Standalone value; 14 Human acceptance |

Machine-readable evidence is in
`tests/garden_acceptance/gate_matrix.json`; print it with
`PYTHONPATH=src python3 -m tests.garden_acceptance.report`. The direct terminal
and browser observations are recorded in `docs/GARDEN_QA_2026-07-21.md`.

The safe-content boundary is unchanged: tracked artifacts contain fictional
demo text only. The compromised personal letter and passphrase remain
unpublished.
