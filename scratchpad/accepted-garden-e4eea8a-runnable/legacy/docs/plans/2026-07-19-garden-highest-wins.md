# Garden Experience — Highest Wins First
2026-07-19 · Informed by the repo audit and by porting notes from
asciicker-y9-2 (FL-4482 static glyph-cycle foliage, glyph_fx_preview.py
blade-lean model, FL-4547 sprite asciification pipeline).

Ordered by impact on the main lateletter garden experience per unit of
effort. Items 1–2 shipped on this branch.

1. **Real passcode gate in the browser viewer** — ✅ shipped 2026-07-19.
   The product's entire promise is a sealed letter; until now the browser
   flow had no real lock (dev fixtures decoded regardless of input).
   PBKDF2-SHA256 + AES-256-GCM via WebCrypto, HMAC gate per SPEC §4,
   Python parity in `sealed.py`, authoring via `make_letter.py`.

2. **Foliage life pass (grass + ground cover + gusty wind)** — ✅ shipped
   2026-07-19. The first 5 seconds of the garden are the emotional pitch;
   static sticks read as dead. Grass is now multi-blade clumps with live
   lean (wind·1.6 + 0.1 Hz per-blade sway, upper cells lean more), tip
   glyphs cycle through fixed families (asciicker "saved static cycle" —
   shimmer without drift), tri-stop root→tip color ramp, density-bucketed
   ground cover, and wind that gusts (product of two oscillators).

3. **§6.9 emotional-arc human QA** — the spec's own ship gate: five
   moments (waiting, recognition, unlock, reading, return) verified by
   direct observation. Everything below is polish until this passes.
   Effort: an evening with `docs/DEMO_SCRIPT.md`. No code.

4. **Delivery-moment polish** — ✅ shipped 2026-07-19. Three-phase
   delivery (approach slide-in with flapping → settle dip → envelope
   glint), letter-bird fallback per SPEC §6.3 when no animal is bonded
   (previously no-animal bundles skipped the moment entirely), and only
   tier-3 bonded animals deliver.

5. **Ambient canopy shimmer** — ✅ shipped 2026-07-19. Sparse fixed
   subset (~1/8) of oak/bush/pine foliage cells rustles with wind
   intensity via the static-cycle technique, putAnim-tagged.

6. **Creature pose richness** — research done 2026-07-19: see
   `docs/research/2026-07-19-stone-story-ascii-animation.md` (Stone
   Story RPG authoring pipeline: primary keyframe + copy-nudge tweens +
   glyph-substitution micro-animation, frames in stacked .txt). Next:
   author `*.frames.txt` pose sets for the four animals; use the
   asciicker-y9-2 FL-4547 asciification pipeline to bootstrap
   silhouettes.

7. **Phone-width garden** — ✅ audited 2026-07-19 at 390×844 in
   Chromium: zero horizontal overflow, URL-letter load, passphrase
   overlay, unlock, and archive all work. No fixes needed at this width.

8. **Seasonal coherence for the new foliage** — ✅ shipped 2026-07-19.
   Autumn straw ramp + bright-yellow tips, winter gray blades with
   snow-dusted cover (`. *` in white/dim), spring flower-tip bump,
   winter flower suppression.

8b. **URL-shareable sealed letters** — ✅ shipped 2026-07-19 (user
   request): `?l=<name>` loads `public_letters/<name>.lateletter`;
   deploy generates pretty paths `/lateletter/<name>/`; bundles are
   committable to the public repo because they are truly encrypted.

9. **Retire/supersede `demo_author.py` invalid-artifact bug** (open in
   FAILURE_LOG 2026-04-27) — `make_letter.py` now produces valid,
   checksum-and-HMAC-correct bundles; fold the demo script onto it.

10. **Phase 3 crypto decision closure** — formally adopt PBKDF2 v0 or
    add an Argon2id WASM path; either way document the 20–30-year
    readability contract in SPEC §4 and remove the "pending" states.

11. **Author-mode end-to-end integration** — the CLI still stops after
    intake. Largest product gap overall, but not garden-experience
    critical; sequenced last here by garden impact, not importance.
