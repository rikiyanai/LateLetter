#!/usr/bin/env python3
"""Build the Contract P face-selection gallery.

History of this page
--------------------
It began as a viability test for Contract P, rendering the same art three ways:
A monospace as accepted, B naive proportional flow, C each glyph measured and
placed on a metric lattice. The operator confirmed on 2026-07-31 that C holds,
so the mechanism is settled and the page's job changed: it now exists to choose
the FACE that mechanism will use.

Why every candidate qualifies on repertoire
-------------------------------------------
The `ascii-safe` art profile is drawn from `|`, `_`, `'`, `/`, `\\`, `-`, `=`,
`~`, `*`, `[` and `]`. Every candidate here contains all eleven, verified from
each font's own character map. So repertoire no longer discriminates between
them, which is exactly why the earlier box-drawing repertoire mattered so much
and this one does not.

What actually discriminates
---------------------------
The drawing is made of PUNCTUATION, not letterforms. A face is being judged
here on how it draws a vertical stroke, an underscore, an apostrophe and a
slash -- their weight, length, and where they sit on the body -- not on how its
lowercase reads. That is an unusual way to choose a typeface, so the page shows
the marks in isolation alongside the assembled art.

The live controls exist because stroke weight is the single most consequential
variable: a face that looks delicate at weight 400 may be exactly right at 600,
and that cannot be judged from a static image.
"""

from __future__ import annotations

from pathlib import Path
import json

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
REVIEW_DIR = REPOSITORY_ROOT / "docs/visual-review/font-decision"
ATLAS_V2 = REPOSITORY_ROOT / "src/lateletter/garden/data/atlas.v2.json"

# Fixtures chosen to stress different structural demands: a trellis is a pure
# repeating lattice, a bench needs verticals to align across four rows, and an
# arbor combines both.
PROTOTYPE_ASSETS = ("fixture.trellis", "fixture.bench", "fixture.arbor")

# Every candidate is OFL or Bitstream-Vera licensed and therefore bundleable.
# `variable` records whether the weight control can do anything for that face;
# a static font ignores it, and saying so prevents a false comparison.
FACES = (
    ("Literata", "Literata-var.ttf", True),
    ("EB Garamond", "EBGaramond-var.ttf", True),
    ("Source Serif 4", "SourceSerif4-var.ttf", True),
    ("Fraunces", "Fraunces-var.ttf", True),
    ("Newsreader", "Newsreader-var.ttf", True),
    ("Crimson Pro", "CrimsonPro-var.ttf", True),
    ("Lora", "Lora-var.ttf", True),
    ("Bitter", "Bitter-var.ttf", True),
    ("Spectral", "Spectral-Regular.ttf", False),
    ("Xanh Mono", "XanhMono-Regular.ttf", False),
)

# The characters the ascii-safe art is actually drawn from. Shown in isolation
# because these -- not the alphabet -- are what the face is being judged on.
MARK_SET = "|_'/\\-=~*[]"

DEFAULT_SIZE = 15  # operator-approved, 2026-07-31
DEFAULT_WEIGHT = 400


def _ascii_art() -> dict[str, list[str]]:
    """Return each prototype asset's ascii-safe idle rows, joined into strings.

    The ascii-safe profile stores art as a matrix of single-character cells
    rather than as row strings, so each row is joined back into text here.

    :returns: Asset id mapped to a list of row strings.
    """
    atlas = json.loads(ATLAS_V2.read_text(encoding="utf-8"))
    art: dict[str, list[str]] = {}
    for asset in atlas["assets"]:
        if asset["id"] not in PROTOTYPE_ASSETS:
            continue
        profile = asset.get("profiles", {}).get("ascii-safe")
        if not profile or "idle" not in profile:
            continue
        art[asset["id"]] = ["".join(row) for row in profile["idle"][0]["cells"]]
    return art


def build(output: Path | None = None) -> Path:
    """Write the gallery page and return the path written."""
    destination = output or (REVIEW_DIR / "prototype.html")
    destination.parent.mkdir(parents=True, exist_ok=True)
    art = _ascii_art()

    font_faces = "\n".join(
        f"@font-face {{ font-family: 'LL {name}'; "
        f"src: url('./fonts/{binary}') format('truetype'); "
        f"font-weight: {'200 900' if variable else '400'}; "
        f"font-display: block; }}"
        for name, binary, variable in FACES
    )

    page = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Contract P &mdash; face selection</title>
<style>
{font_faces}
body {{ margin: 0 auto; padding: 2rem 1.5rem 6rem; max-width: 1240px;
  background: #12100e; color: #e8e2d9;
  font: 15px/1.55 ui-sans-serif, system-ui, sans-serif; }}
h1 {{ font-size: 1.5rem; margin: 0 0 .4rem; }}
h2 {{ font-size: 1.05rem; margin: 2.4rem 0 .8rem; padding-bottom: .35rem;
  border-bottom: 1px solid #35302a; }}
p {{ max-width: 76ch; color: #b6ada0; }}
.note {{ border-left: 3px solid #4a7c59; background: #161a16;
  padding: .8rem 1rem; margin: 1rem 0; max-width: 76ch; color: #cfd8cd; }}
.controls {{ position: sticky; top: 0; z-index: 5; display: flex; gap: 2rem;
  flex-wrap: wrap; align-items: center; background: #191510;
  border: 1px solid #3a332a; border-radius: 3px;
  padding: .8rem 1.1rem; margin: 1.4rem 0 .6rem; }}
.controls label {{ font-size: .78rem; color: #b6ada0; display: flex;
  gap: .6rem; align-items: center; }}
.controls output {{ font: 600 .82rem ui-monospace, Menlo, monospace;
  color: #c98b52; min-width: 3.2rem; }}
input[type=range] {{ width: 190px; accent-color: #c98b52; }}
.gallery {{ display: grid; gap: 1rem;
  grid-template-columns: repeat(auto-fill, minmax(215px, 1fr)); }}
.face {{ background: #1b1712; border: 1px solid #2f2a23; border-radius: 2px;
  padding: .85rem .9rem 1rem; }}
.face h3 {{ margin: 0 0 .1rem; font-size: .84rem; font-weight: 600;
  color: #e8e2d9; }}
.face .meta {{ font-size: .68rem; color: #8d8478; margin-bottom: .7rem;
  letter-spacing: .04em; text-transform: uppercase; }}
.marks {{ margin-bottom: .7rem; padding-bottom: .7rem;
  border-bottom: 1px dashed #322c25; color: #cbbfae; }}
.measured {{ position: relative; }}
.measured span {{ position: absolute; display: block; }}
.ref {{ font-family: 'DejaVu Sans Mono', Menlo, monospace; white-space: pre;
  line-height: 1; margin: 0; color: #7f8f7f; }}
.asset-head {{ font-size: .74rem; letter-spacing: .06em; color: #9c9285;
  text-transform: uppercase; margin: 2rem 0 .6rem; }}
</style></head><body>

<h1>Contract P &mdash; face selection</h1>
<div class="note">
<strong>Mechanism settled.</strong> Measured placement (variant C) was confirmed
by the operator on 2026-07-31, so every sample below uses it: each glyph measured
through the browser's own text engine and centred on a metric lattice. Size is
15px, approved the same day. What remains is the face.
</div>
<p>All ten candidates contain every character this art uses (11/11, read from each
font's character map), so repertoire no longer separates them. The drawing is made
of <strong>punctuation</strong> &mdash; <code>| _ ' / \\ - = ~ * [ ]</code> &mdash;
so each card shows those marks in isolation above the assembled art. Judge stroke
weight, length, and where each mark sits on the body.</p>

<div class="controls">
  <label>size <input type="range" id="size" min="11" max="22" step="1"
    value="{DEFAULT_SIZE}"><output id="sizeOut">{DEFAULT_SIZE}px</output></label>
  <label>weight <input type="range" id="weight" min="200" max="900" step="50"
    value="{DEFAULT_WEIGHT}"><output id="weightOut">{DEFAULT_WEIGHT}</output></label>
  <label><input type="checkbox" id="showRef"> show monospace reference</label>
</div>

<div id="out"></div>

<script type="module">
const ART = {json.dumps(art, ensure_ascii=False)};
const FACES = {json.dumps([[n, v] for n, _, v in FACES])};
const MARKS = {json.dumps(MARK_SET)};

// One offscreen canvas measures every glyph. The browser's text engine is the
// authority: measuring anywhere else would measure a different thing than the
// one that paints.
const ctx = document.createElement('canvas').getContext('2d');

/**
 * Advance width of one character under a CSS font shorthand, in pixels.
 * @param {{string}} ch   Single character to measure.
 * @param {{string}} font CSS font shorthand including weight and size.
 */
function advance(ch, font) {{
  ctx.font = font;
  return ctx.measureText(ch).width;
}}

/**
 * Lay rows out with each glyph measured and centred on a metric lattice.
 *
 * The pitch is the widest advance among the characters the drawing actually
 * uses, so no glyph can collide with its neighbour. Centring each glyph in its
 * cell is what keeps a vertical stroke in row 1 above a vertical stroke in row
 * 3 even when the two rows hold different characters -- which is precisely why
 * naive proportional flow fails and this does not.
 */
function measuredBlock(rows, font, sizePx) {{
  const lineHeight = sizePx + 2;
  const used = new Set(rows.join('').split('').filter(c => c !== ' '));
  let pitch = advance('0', font);
  for (const ch of used) pitch = Math.max(pitch, advance(ch, font));

  const wrap = document.createElement('div');
  wrap.className = 'measured';
  wrap.style.font = font;
  wrap.style.height = (rows.length * lineHeight) + 'px';
  wrap.style.width = (Math.max(...rows.map(r => r.length)) * pitch) + 'px';

  rows.forEach((row, rowIndex) => {{
    [...row].forEach((ch, colIndex) => {{
      if (ch === ' ') return;                        // nothing to paint
      const glyph = document.createElement('span');
      glyph.textContent = ch;
      glyph.style.left = (colIndex * pitch + (pitch - advance(ch, font)) / 2) + 'px';
      glyph.style.top = (rowIndex * lineHeight) + 'px';
      wrap.appendChild(glyph);
    }});
  }});
  return wrap;
}}

const sizeEl = document.getElementById('size');
const weightEl = document.getElementById('weight');
const refEl = document.getElementById('showRef');
const sizeOut = document.getElementById('sizeOut');
const weightOut = document.getElementById('weightOut');
const out = document.getElementById('out');

function render() {{
  const size = Number(sizeEl.value);
  const weight = Number(weightEl.value);
  sizeOut.textContent = size + 'px';
  weightOut.textContent = weight;
  out.textContent = '';

  for (const [asset, rows] of Object.entries(ART)) {{
    const head = document.createElement('div');
    head.className = 'asset-head';
    head.textContent = asset;
    out.appendChild(head);

    if (refEl.checked) {{
      const ref = document.createElement('pre');
      ref.className = 'ref';
      ref.style.fontSize = size + 'px';
      ref.textContent = rows.join('\\n');
      out.appendChild(ref);
    }}

    const gallery = document.createElement('div');
    gallery.className = 'gallery';

    for (const [name, variable] of FACES) {{
      // A static font cannot honour the weight axis; asking for 700 would get
      // a synthesised bold and make the comparison dishonest, so static faces
      // are always drawn at 400 and labelled as such.
      const usedWeight = variable ? weight : 400;
      const font = `${{usedWeight}} ${{size}}px 'LL ${{name}}'`;

      const card = document.createElement('div');
      card.className = 'face';

      const title = document.createElement('h3');
      title.textContent = name;

      const meta = document.createElement('div');
      meta.className = 'meta';
      meta.textContent = variable ? `variable · ${{usedWeight}}` : 'static · 400 only';

      const marks = document.createElement('div');
      marks.className = 'marks';
      marks.style.font = font;
      marks.textContent = MARKS;

      card.append(title, meta, marks, measuredBlock(rows, font, size));
      gallery.appendChild(card);
    }}
    out.appendChild(gallery);
  }}
}}

// Measuring before the real faces load would silently measure a fallback, so
// everything waits. This is the same precondition the runtime contract needs.
await document.fonts.ready;
await Promise.all(FACES.map(([name]) =>
  document.fonts.load(`400 20px 'LL ${{name}}'`)));

for (const el of [sizeEl, weightEl, refEl]) el.addEventListener('input', render);
render();
</script>
</body></html>
"""
    destination.write_text(page, encoding="utf-8")
    return destination


if __name__ == "__main__":
    written = build()
    print(f"wrote {written.relative_to(REPOSITORY_ROOT)}")
