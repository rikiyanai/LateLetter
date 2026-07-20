# Stone Story RPG — ASCII animation research for garden creatures
2026-07-19 · Precursor research for the sprite/creature-pose work
(highest-wins item 6). Stone Story RPG (Gabriel Santos / standardcombo,
Martian Rex, 2014–2023) is the closest 2-D ASCII-animation prior art to
lateletter's garden.

## Headline finding

There is **no magic tool**. Per the creator's Road-to-the-IGF interview:
"No special tools were used." All 16,000+ frames were typed in a plain
text editor into `.txt` files, frames stacked vertically "similar to a
sprite sheet", imported into Unity, rendered with custom shaders.
Process: references → concept → a **primary keyframe** (neutral pose) →
size/composition test in situ → plan animations → keyframes → tween by
**copy-paste-and-nudge** → polish. "1–2 keyframes are generally enough
for rough animations."

Key sources:
- Official tutorial: https://stonestoryrpg.com/ascii_tutorial.html
  (+ stream VODs: youtu.be/o5v-NS9o4yc, youtu.be/h6a2BKPHPqA — part 2
  demos the live animation workflow incl. "subtractive animation")
- Road to the IGF interview (gamedeveloper.com), Top Shelf Gaming and
  indiegraze interviews, Stonescript manual
  (stonestoryrpg.com/stonescript/manual.html), official FAQ.

## Techniques to adopt for garden creatures (2–6 rows tall)

1. **Author frames in .txt, stacked vertically, one file per creature.**
   Parse at build/load time. Don't build an editor.
2. **Primary keyframe first** — the neutral idle; every other frame is a
   copy-modify of it, which keeps silhouette/volume consistent.
3. **1–2 keyframes per action**; a readable loop is 3–5 frames, not 12.
4. **Tween by nudging characters**, never redrawing — untouched glyphs
   stay rock-still, and that stillness is what makes ASCII motion clean.
5. **Glyph substitution = sub-cell animation** (the highest-value trick
   at our creature sizes): blink `o`→`-`→`o`, breathing back `_`→`-`→`~`,
   ear twitch `/`→`|`. A whole expression is a one-char edit (`o o`,
   `. .`, `- -` asleep, `^ ^` content).
6. **Subtractive animation** for dissipating motion: delete glyphs
   across frames (dust puff after a rabbit hop, ripples, takeoff).
   Combat-style smears/impacts stay out — wrong register for a garden.
7. **Hold frames with irregular timing.** Stone Story ticks at 30/s but
   holds art frames for many ticks. At our ~20 fps: idle art at 2–5 fps
   with randomized blink intervals reads alive; only hops/flaps approach
   tick rate.
8. **Two motion layers**: pose frames on the grid + whole-sprite easing
   (Stone Story renders grid-fixed glyphs inside sprites that translate
   at pixel resolution). Our delivery overlay already does this
   (CSS-transform approach + char frames); creatures can too.
9. **Transparency character** in authored art (Stonescript uses `#`) to
   distinguish "draws blank" from "garden shows through" — needed once
   creatures overlap plants.
10. **Ink-density ramp = value scale**: background sparse (`.` `'` `-`),
    midground medium (`:` `=` `+`), focal creatures densest — never a
    dense glyph in a background layer. Dither midtones with glyph pairs.
11. **Ground shadows** (`_` or `.`) one row under a creature anchor it;
    removing the shadow mid-hop gives free "air time."
12. **Consistent glyph vocabulary** scene-wide (one meaning per glyph
    family). Stone Story's coherence comes from this symbolic
    consistency more than any single technique — matches our existing
    conventions (`~` soft/water, `"`/`;` grass, `><` birds).
13. **Below ~4 rows, skip inbetweens entirely** — full pose redraws at
    2–3 rows flicker rather than animate; rely on glyph substitution and
    position moves only.

## Register notes (ambient garden vs combat game)

Adopt the authoring pipeline wholesale; reject the combat energy:
long holds and slow eases instead of snap timing, no impact frames, few
long-lived ambient particles instead of sprays, mostly-static camera
with at most 1–3 slow parallax rows, outline-style art over heavy
`@#%` fill (which also keeps small creatures legible).

## Concrete next step for item 6

Add `ascii-animations/creatures/*.frames.txt` authored in the Stone
Story format (frames stacked vertically, `---` delimiter, `#` for
transparent cells), a tiny parser in the viewer, and re-author the four
animals' tier poses as: primary keyframe + blink/breath substitutions +
one action extreme each (cat stretch, rabbit hop, turtle head-out, bird
hop-turn). The asciicker-y9-2 sprite-asciification pipeline (FL-4547)
can bootstrap silhouettes from reference sprites where hand-drawing
stalls.
