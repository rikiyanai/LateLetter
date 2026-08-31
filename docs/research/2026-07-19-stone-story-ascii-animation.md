# Stone Story RPG — ASCII animation research for garden creatures
2026-07-19 · Precursor research for the sprite/creature-pose work
(highest-wins item 6). Stone Story RPG (Gabriel Santos / standardcombo,
Martian Rex, 2014–2023) is the closest 2-D ASCII-animation prior art to
lateletter's garden.

## Headline finding

There is **no magic tool**. Per the creator's Road-to-the-IGF interview:
"No special tools were used." More than 10,000 frames were typed in a plain
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

## Direct Discord artifact intake (2026-08-21)

The saved Discord export and its local attachment directory are now a direct
source for this research. They are external reference material, not
operator-granted LateLetter runtime art:

- HTML owner: `/Users/r/Pictures/ASCIICKER Y9-2/Godot References/Discord Help/stonestory:world fountain:gamedev/Stone Story RPG - World Fountain - gamedev [463768875490869259].html`
- HTML SHA-256: `9c4728ce6679180fe1ccc6013d1972b60402eaee9b95e4444f25c726da591bc1`
- Export identity: Stone Story RPG, `gamedev` channel, 12,045 messages,
  timezone UTC-5. The HTML contains 12,033 message containers, 1,765
  attachment blocks, and 3,034 posts attributed to `standardcombo`
  (`data-user-id=294231481902039042`).
- Companion directory: the HTML's containing directory. It holds the locally
  resolved images, GIFs, video, audio, emoji, fonts, scripts, and nine `.txt`
  art sheets referenced below. The directory remains the raw-source owner;
  this note is the durable extracted result.

### Locally preserved text-art sheets

| Discord attachment | Lines | SHA-256 | What it supplies |
|---|---:|---|---|
| `Utility_Belt_UI_Mockups-0cd01fa923b6d654.txt` | 212 | `94dc8d5ba3b3b87e97525a2ca17938392db62f10aeb273729234ca22d87fc779` | interface composition variants on a fixed 70-column stage |
| `ssrpg_Factory_BG-13a447d1a3462967.txt` | 271 | `e82b15fef2b866268e634776d61be2195f9105a7dd414423d80a84ca144cb309` | repeated architectural modules, depth planes, and background variants |
| `ssrpg_Library_window-81d6cca5fd912ec4.txt` | 173 | `642551b91776599b624e27a862d126cbe98420fba9b510e06f8db6ebcd072535` | perspective window studies and repeated contour refinement |
| `ssrpg_Laboratory-d691d7c6d8512146.txt` | 106 | `1b03fdf3a5650e2b2ee035db224b6d1184317570200162210754c52cffe49bc4` | dense material/value grouping and prop silhouettes inside architecture |
| `ssrpg_Fairweather_Faire-145842e2854f617a.txt` | 229 | `4e82bbaddc6dead97842fec3cfa95f4839b377cc2254e88726da823e048f8ef9` | complete scene layout on an explicit stage boundary |
| `ssrpg_Factory_small_NPCs-aab09e196440d89d.txt` | 319 | `bba12e40450ee928755014d24a8c53eb80c57d4b2eca9915bc14436af475e0f4` | named small-character inventory followed by pose/silhouette studies |
| `ssrpg_Marionette-00de3bd0bc7dad84.txt` | 334 | `196aa1dd07d955d8b4b7bdd23aa154b01b1c77972ac1e1a461e88296da4acacf` | large character construction and successive pose variants |
| `Stream_2026_03_11-78f26b47e612174f.txt` | 643 | `71fe412b03b0fef774912d2ea98369b416b4377c2735b24aa0153e18f566061f` | art-stream task ledger plus creature, prop, and environment working studies |
| `Lunar_Guardian_ASCII_Stream-88e12347185fc315.txt` | 674 | `474577c04964f8333e0c4166ed5b1a8b47d99dfa5d3ee3f7e56a68fb56434e1e` | primary character design, named action checklist, and action-pose development |

### What the direct artifacts add

The text sheets strengthen several earlier conclusions with production
artifacts rather than secondary descriptions:

1. A `.txt` file is a working board, not merely a serialized final animation.
   It mixes task lists, named assets, primary designs, alternatives, and
   successive poses. LateLetter should preserve that authoring distinction:
   source sheets are editable evidence; parsed runtime frames are derived data.
2. Composition is tested inside an explicit stage. Several sheets use a
   70-column `#` boundary while foreground and background modules are developed
   against the final scene width. Asset quality therefore cannot be accepted
   from an isolated crop alone; the target viewport and neighboring ink are
   part of the experiment identity.
3. Reuse occurs at several scales: stable character cores across action poses,
   repeated architectural modules across depth planes, and small prop/NPC
   vocabularies across a larger scene. Copy-and-nudge is not only an
   in-betweening tactic; it is the continuity mechanism for a whole visual
   system.
4. Animation planning is action-first. `Lunar_Guardian_ASCII_Stream` records a
   named checklist (`Block`, `Punch`, `Jump`, and later actions) adjacent to the
   primary drawing. The runtime animation inventory should therefore be derived
   from semantic actions, not from an arbitrary target frame count.
5. Negative space and partial contours remain authored structure. The sheets
   repeatedly preserve gaps inside bodies, machinery, windows, and layered
   scenery instead of repairing them into closed connected outlines.
6. The companion GIF/MOV corpus is the acceptance surface for timing and
   continuity. The `.txt` sheets prove authored geometry and pose lineage, but
   do not alone prove cadence, easing, or readability in motion.

This intake also corrects the earlier `16,000+` wording. The primary-source
audit supports 9,952 frames in the 2019 breakdown and “over 10,000” in the
2020 interview; the larger number is not retained as established fact.
