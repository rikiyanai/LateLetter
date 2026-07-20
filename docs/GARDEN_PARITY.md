# Garden Runtime Parity

Verified 2026-07-21 against the repository's real sealed synthetic demo with
passcode `garden`. This table is deliberately bounded: “Full” means the named
recipient-visible behavior was exercised in both implementations. It does not
claim completion of the broader planned standalone-garden release contract or
substitute for deployment and human acceptance.

| Recipient-visible contract | Terminal | HTML | Parity | Verification |
|---|---|---|---|---|
| Canonical bundle load and checksum gate | Canonical reader blocks damaged bundles | File, demo, and public-letter loaders block damaged bundles | Full | Valid and deliberately corrupted sealed bundles were exercised in both channels. |
| HMAC passcode gate | Canonical HMAC verifier | WebCrypto HMAC verifier | Full | Correct passcode accepted; wrong passcode rejected without content disclosure. |
| Real letter decryption | PBKDF2-SHA256/AES-256-GCM | Matching WebCrypto derivation/decryption | Full | Exact synthetic label and body rendered in both channels. |
| Real gift-memory decryption | Canonical gift decryptor | Matching per-gift WebCrypto decryptor | Full | Exact Clover, coffee-mug, and pressed-flower sentiments decrypt from the generated artifacts. |
| Discoverable garden actions after authentication | Status bar shows compact `e`, `i`, `f`, and `l` actions together | Visible `letters`, `examine memories`, and `feed rabbit` buttons plus `i`/`f` shortcuts | Full for implemented actions | Terminal 80×24 interaction and desktop HTML pointer/keyboard interaction passed. |
| Pointer/touch access | Not applicable to terminal | Core actions are real buttons invoking the same handlers as keyboard shortcuts | Full for HTML | Safari responsive mode at 375×812 exposed both actions; pointer taps opened memory and advanced animal trust. |
| Triggered memory archive | Every triggered gift type is selectable, including authored animal names | Every discovered gift is selectable | Full | Both archives showed Clover and the coffee mug before the letter, then the pressed flower after reading. |
| Direct garden-memory action | `i` opens one memory or a selection list | `i` or the visible examine button opens one memory or focuses the archive memory choices | Full | Keyboard and pointer paths exercised against the same sealed content. |
| Animal feeding/trust | `f` persists feed actions and applies shared tier thresholds | `f` and the visible feed button persist the same thresholds | Full for trust state | Three pointer taps visibly changed the rabbit from wild to curious; terminal feed action remained visible alongside other controls. |
| Date, visit, and post-letter triggers | All three trigger types; post-completion releases remaining gifts | All three trigger types; post-completion releases remaining gifts | Full | Demo uses visit-triggered rabbit, date-triggered mug, and post-letter pressed flower. |
| Read receipts and reread | Recipient-private JSON state | IndexedDB with localStorage fallback | Full contract | Storage mechanisms intentionally differ; message/gift outcomes match. |
| Delivery animation | Letter bird, or bonded animal | Letter bird, or bonded animal | Full contract | Same semantic delivery rule; renderer-specific animation is expected. |
| Post-completion memorial | Memorial state and all-gift release | Memorial state and all-gift release | Functional parity | All-gift release was exercised; emotional/visual human sign-off remains open. |
| Weather and particle breadth | Clouds, lightning, splashes, and the terminal weather set | Browser rain, snow, leaves, resting leaves, and accumulation | Partial | Visual breadth still differs and requires comparative human review. |
| Full standalone cozy-garden / authored-world contract | Not implemented | Not implemented | Open | The planned contract requires tending, placement/undo, journal/collections, a shared world model, richer animal AI, author programming, deterministic sky, accessibility, and acceptance gates beyond this fix. |
| Published production reachability | Local sealed artifact is ready | Tracked `sealed_demo.lateletter` and `public_letters/to-a-friend.lateletter` contain the three synthetic gifts | Awaiting deployment | Repository artifacts pass checksum/HMAC/decrypt verification. The live URL remains old until this change is merged to the protected default branch and Pages deploys it. |

The safe-content boundary is unchanged: only fictional demo text and fictional
gift sentiments are tracked. The compromised personal message and passphrase
remain unpublished.
