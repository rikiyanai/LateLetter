#!/usr/bin/env python3
"""Build the Contract P font decision surface.

What this is for
----------------
Contract P (operator decision, 2026-07-31) moves the Garden to proportional
glyph placement measured through PreText. Under P the face must be chosen
BEFORE any art is drawn, because proportional drawing is made against specific
glyph advances. This script builds the page the operator approves a face on.

Why it renders through real font files
--------------------------------------
The defect that produced this whole exercise was art reviewed in one font and
painted in another: the fixtures were signed off through DejaVu Sans Mono and
the product would paint them through Courier New. So this page embeds the
ACTUAL candidate font binaries via `@font-face` and renders every sample
through them. Nothing here is shown through a system font that the product
could not bundle -- that would repeat the original mistake.

What it deliberately does NOT do
--------------------------------
It does not show proposed art. No proportional art exists yet, and inventing
some here would smuggle an art-direction decision into what is meant to be a
typeface decision. Instead it shows each candidate's raw material -- weight
ramp, density ramp, italic, both candidate sizes -- plus a diagnostic panel
showing what proportional rendering does to the existing column-aligned art.
That diagnostic is evidence for WHY P requires a redraw; it is explicitly not a
means of telling the candidates apart, because all of them shear it equally.
"""

from __future__ import annotations

from html import escape
from pathlib import Path
import hashlib
import json
import re

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
REVIEW_DIR = REPOSITORY_ROOT / "docs/visual-review/font-decision"
FONT_DIR = REVIEW_DIR / "fonts"
ATLAS_ART = REPOSITORY_ROOT / "web/garden-atlas-art.mjs"

# The two sizes under consideration. 15px is what the review worksheet and the
# atlas both declare and what the accepted art was signed off at; 13px is what
# the product's `#g` rule actually paints. Step 4 requires comparing both.
CANDIDATE_SIZES = (13, 15)

# Candidate faces. Each is OFL-licensed and therefore redistributable, which
# system faces such as Georgia or Palatino are not -- that licensing wall is
# why none of the locally installed proportional fonts appear here.
CANDIDATES = (
    {
        "key": "literata",
        "css_family": "LL Literata Candidate",
        "upstream_family": "Literata",
        "file": "Literata-var.ttf",
        "italic_file": "Literata-Italic-var.ttf",
        "license_file": "OFL-literata.txt",
        "note": (
            "Widest tonal range of the three (weight 200-900) plus an optical "
            "size axis and a true italic. Designed for long-form reading."
        ),
    },
    {
        "key": "ebgaramond",
        "css_family": "LL EB Garamond Candidate",
        "upstream_family": "EB Garamond",
        "file": "EBGaramond-var.ttf",
        "italic_file": None,
        "license_file": "OFL-ebgaramond.txt",
        "note": (
            "Classical garamond; the most letter-like and warmest of the "
            "three. Narrower weight range (400-800) means less tonal contrast "
            "available for texture."
        ),
    },
    {
        "key": "sourceserif4",
        "css_family": "LL Source Serif Candidate",
        "upstream_family": "Source Serif 4",
        "file": "SourceSerif4-var.ttf",
        "italic_file": None,
        "license_file": "OFL-sourceserif4.txt",
        "note": (
            "Neutral and even-coloured, weight 200-900 with an optical size "
            "axis. The least characterful of the three, which can be a virtue "
            "when the art rather than the face should carry the personality."
        ),
    },
)

# Characters ordered light to dark by apparent ink coverage. This is the raw
# material proportional texture art is drawn from, and how evenly a face steps
# through it is the single most useful thing to judge a candidate on.
DENSITY_RAMP = " .,:;i1tfLCG08@"
WEIGHT_RAMP = (200, 300, 400, 500, 600, 700, 800, 900)
PANGRAM = "the garden remembers every letter you never sent"


def _sha256(path: Path) -> str:
    """Return the hex SHA-256 of a file, for the provenance record."""
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _accepted_art() -> dict[str, list[str]]:
    """Pull the idle-state rows of each accepted fixture out of the atlas module.

    The atlas is a JavaScript module, so the exported object literal is sliced
    out and parsed as JSON. It is emitted by a generator with `json.dumps`, so
    it is genuinely JSON despite living in a `.mjs` file.

    :returns: Asset id mapped to its first idle frame's rows.
    """
    source = ATLAS_ART.read_text(encoding="utf-8")
    start = source.index("ATLAS_PROPORTIONAL_ART = Object.freeze(") + len(
        "ATLAS_PROPORTIONAL_ART = Object.freeze("
    )
    # Walk braces to find the matching close, since the object contains nested
    # objects and a naive search for `})` would stop at the first inner one.
    depth = 0
    for offset in range(start, len(source)):
        if source[offset] == "{":
            depth += 1
        elif source[offset] == "}":
            depth -= 1
            if depth == 0:
                payload = source[start: offset + 1]
                break
    else:  # pragma: no cover - only reachable if the generator changes shape
        raise ValueError("could not locate ATLAS_PROPORTIONAL_ART object")

    art = json.loads(payload)
    return {
        asset: entry["states"]["idle"][0]["rows"]
        for asset, entry in art.items()
        if "idle" in entry.get("states", {})
    }


def _font_face_rules() -> str:
    """Emit `@font-face` rules binding each candidate to its real binary."""
    rules = []
    for candidate in CANDIDATES:
        rules.append(
            f"@font-face {{\n"
            f"  font-family: '{candidate['css_family']}';\n"
            f"  src: url('./fonts/{candidate['file']}') format('truetype');\n"
            # The variable weight axis is exposed by declaring the full range,
            # which lets `font-weight` interpolate rather than snapping.
            f"  font-weight: 200 900;\n"
            f"  font-style: normal;\n"
            f"  font-display: block;\n"
            f"}}"
        )
        if candidate["italic_file"]:
            rules.append(
                f"@font-face {{\n"
                f"  font-family: '{candidate['css_family']}';\n"
                f"  src: url('./fonts/{candidate['italic_file']}') format('truetype');\n"
                f"  font-weight: 200 900;\n"
                f"  font-style: italic;\n"
                f"  font-display: block;\n"
                f"}}"
            )
    return "\n".join(rules)


# The twelve non-ASCII characters the currently accepted art is drawn from.
# Coverage of this set is reported per candidate because it is the datum that
# decides whether a face can render the EXISTING art at all -- and all three
# proportional candidates fail it, which is why Contract P entails a redraw.
ART_REPERTOIRE = (
    0x223C, 0x2500, 0x2502, 0x2503, 0x2550, 0x2571,
    0x2572, 0x2575, 0x2581, 0x258C, 0x2590, 0x25E6,
)


def _repertoire_coverage(binary: Path) -> str:
    """Report how many of `ART_REPERTOIRE` a font file actually contains.

    Read from the font's own character map, so this is a measurement rather
    than an assumption about what a family "should" have. Returns a short
    ``n/12`` string, or a note when fontTools is unavailable.

    :param binary: Path to the `.ttf` to inspect.
    """
    try:
        from fontTools.ttLib import TTFont
    except ImportError:  # pragma: no cover - depends on the environment
        return "not measured"
    if not binary.is_file():
        return "-"
    font = TTFont(binary, lazy=True)
    codepoints: set[int] = set()
    for table in font["cmap"].tables:
        codepoints |= set(table.cmap.keys())
    present = sum(1 for point in ART_REPERTOIRE if point in codepoints)
    return f"{present}/12"


def _provenance_rows() -> str:
    """Build the contract table rows: filename, SHA-256, licence, coverage."""
    rows = []
    for candidate in CANDIDATES:
        binary = FONT_DIR / candidate["file"]
        digest = _sha256(binary) if binary.is_file() else "FILE MISSING"
        size_kb = f"{binary.stat().st_size // 1024} KB" if binary.is_file() else "-"
        italic = candidate["italic_file"] or "none obtained"
        coverage = _repertoire_coverage(binary)
        rows.append(
            "<tr>"
            f"<td><strong>{escape(candidate['upstream_family'])}</strong></td>"
            f"<td><code>{escape(candidate['file'])}</code><br>"
            f"<span class='dim'>italic: {escape(italic)}</span></td>"
            f"<td>{size_kb}</td>"
            f"<td class='cov'>{escape(coverage)}</td>"
            f"<td><code class='hash'>{escape(digest)}</code></td>"
            f"<td>SIL OFL 1.1<br><span class='dim'>"
            f"{escape(candidate['license_file'])}</span></td>"
            f"<td><code>{escape(candidate['css_family'])}</code></td>"
            "</tr>"
        )
    return "\n".join(rows)


def _diagnostic_panel(art: dict[str, list[str]]) -> str:
    """Render accepted column-aligned art through each proportional candidate.

    CORRECTION, 2026-07-31: an earlier version of this panel claimed the
    candidates "shear this art equally" because of proportional advances. That
    was the wrong mechanism. Measured against each font's `cmap`, Literata and
    Source Serif 4 contain NONE of the twelve non-ASCII characters this art is
    drawn from, and EB Garamond contains two. The browser therefore substitutes
    a fallback font for nearly every glyph, which is why all three columns
    render almost identically -- they are largely not showing the candidate
    faces at all.

    So this panel demonstrates per-glyph fallback, the very defect that started
    this exercise, reproduced under new fonts. It remains the evidence for why
    Contract P requires a redraw, and it still cannot discriminate between
    candidates -- but for a different and more decisive reason than first
    stated.
    """
    # Two fixtures are enough to make the shearing unmistakable; showing all
    # ten would pad the page without adding information.
    shown = [key for key in ("fixture.trellis", "fixture.bench") if key in art]
    blocks = []
    for asset in shown:
        rows = escape("\n".join(art[asset]))
        columns = [
            "<div class='cmp'><div class='cmp-label'>monospace reference"
            "<br><span class='dim'>as accepted &mdash; not bundleable</span></div>"
            f"<pre class='art mono'>{rows}</pre></div>"
        ]
        for candidate in CANDIDATES:
            columns.append(
                "<div class='cmp'>"
                f"<div class='cmp-label'>{escape(candidate['upstream_family'])}"
                "<br><span class='dim'>proportional</span></div>"
                f"<pre class='art' style=\"font-family:'{candidate['css_family']}'\">"
                f"{rows}</pre></div>"
            )
        blocks.append(
            f"<h3>{escape(asset)}</h3><div class='cmp-row'>{''.join(columns)}</div>"
        )
    return "\n".join(blocks)


def _candidate_panel(candidate: dict) -> str:
    """Render one candidate's raw material at both sizes under consideration."""
    sections = []
    for size in CANDIDATE_SIZES:
        weight_rows = "".join(
            f"<div class='wrow'><span class='wlabel'>{weight}</span>"
            f"<span style='font-weight:{weight}'>{escape(PANGRAM)}</span></div>"
            for weight in WEIGHT_RAMP
        )
        density = "".join(
            f"<span style='font-weight:{weight}'>{escape(DENSITY_RAMP)}</span> "
            for weight in (300, 500, 700, 900)
        )
        italic = (
            f"<div class='wrow'><span class='wlabel'>italic</span>"
            f"<span style='font-style:italic'>{escape(PANGRAM)}</span></div>"
            if candidate["italic_file"]
            else "<div class='wrow'><span class='wlabel'>italic</span>"
            "<span class='dim'>no italic obtained for this candidate</span></div>"
        )
        sections.append(
            f"<div class='size-block' style=\"font-family:'{candidate['css_family']}';"
            f"font-size:{size}px;line-height:{size + 2}px\">"
            f"<div class='size-tag'>{size}px / {size + 2}px</div>"
            f"{weight_rows}{italic}"
            f"<div class='wrow'><span class='wlabel'>density</span>"
            f"<span class='ramp'>{density}</span></div>"
            "</div>"
        )
    return (
        f"<section class='candidate'><h3>{escape(candidate['upstream_family'])}</h3>"
        f"<p class='note'>{escape(candidate['note'])}</p>"
        f"<div class='sizes'>{''.join(sections)}</div></section>"
    )


def build(output: Path | None = None) -> Path:
    """Write the decision surface and return the path written.

    :param output: Destination file. Defaults to `index.html` in the review dir.
    :returns: The path actually written.
    """
    destination = output or (REVIEW_DIR / "index.html")
    destination.parent.mkdir(parents=True, exist_ok=True)
    art = _accepted_art()

    page = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Contract P &mdash; font decision surface</title>
<style>
{_font_face_rules()}
:root {{ color-scheme: light dark; }}
body {{
  margin: 0; padding: 2rem 1.5rem 6rem;
  background: #12100e; color: #e8e2d9;
  font: 15px/1.55 ui-sans-serif, system-ui, sans-serif;
  max-width: 1180px; margin-inline: auto;
}}
h1 {{ font-size: 1.5rem; margin: 0 0 .35rem; letter-spacing: -.01em; }}
h2 {{ font-size: 1.05rem; margin: 3rem 0 .5rem; padding-bottom: .35rem;
      border-bottom: 1px solid #35302a; letter-spacing: .02em; }}
h3 {{ font-size: .95rem; margin: 1.6rem 0 .5rem; font-weight: 600; }}
p {{ max-width: 74ch; }}
.dim {{ color: #8d8478; font-size: .82em; }}
.note {{ color: #b6ada0; font-size: .9rem; max-width: 74ch; }}
.lede {{ color: #c7bfb3; }}
.warn {{ border-left: 3px solid #a8783c; background: #1d1813;
         padding: .8rem 1rem; margin: 1rem 0; max-width: 74ch; }}
table {{ border-collapse: collapse; width: 100%; margin-top: .8rem;
         font-size: .84rem; }}
th, td {{ text-align: left; padding: .5rem .6rem; vertical-align: top;
          border-bottom: 1px solid #2b2620; }}
th {{ color: #9c9285; font-weight: 600; text-transform: uppercase;
      font-size: .72rem; letter-spacing: .06em; }}
code {{ font-family: ui-monospace, Menlo, monospace; font-size: .92em; }}
code.hash {{ word-break: break-all; color: #9c9285; font-size: .78em; }}
.cov {{ font: 600 .95rem/1 ui-monospace, Menlo, monospace; color: #c98b52;
        white-space: nowrap; }}
.cmp-row {{ display: flex; gap: 1rem; flex-wrap: wrap; align-items: flex-start; }}
.cmp {{ flex: 1 1 210px; min-width: 190px; }}
.cmp-label {{ font-size: .76rem; color: #9c9285; margin-bottom: .35rem;
              text-transform: uppercase; letter-spacing: .05em; }}
pre.art {{ margin: 0; padding: .7rem .8rem; background: #1b1712;
           border: 1px solid #2f2a23; border-radius: 2px;
           font-size: 15px; line-height: 1; white-space: pre;
           overflow-x: auto; }}
pre.art.mono {{ font-family: 'DejaVu Sans Mono', Menlo, monospace; }}
.sizes {{ display: flex; gap: 1rem; flex-wrap: wrap; }}
.size-block {{ flex: 1 1 340px; background: #1b1712; border: 1px solid #2f2a23;
               padding: .9rem 1rem 1rem; border-radius: 2px; }}
.size-tag {{ font: 600 .7rem/1 ui-sans-serif, system-ui, sans-serif;
             color: #9c9285; letter-spacing: .06em; margin-bottom: .7rem; }}
.wrow {{ display: flex; gap: .7rem; align-items: baseline; margin: .18rem 0; }}
.wlabel {{ flex: 0 0 3.2rem; font: 400 .68rem/1 ui-monospace, monospace;
           color: #7d7468; }}
.ramp {{ letter-spacing: .02em; }}
</style></head><body>

<h1>Contract P &mdash; font decision surface</h1>
<p class="lede">Choose the exact face the Garden will be drawn against. Under
Contract P the typeface is chosen <em>before</em> the art, because proportional
drawing is made against specific glyph advances.</p>

<div class="warn">
<strong>Everything below renders through the real candidate font binaries</strong>,
embedded via <code>@font-face</code> from <code>./fonts/</code>. No sample is
shown through a system font. That is deliberate: the defect this whole exercise
exists to correct was art reviewed in one font and painted in another.
</div>

<h2>1. Provenance &mdash; the exact resources</h2>
<p class="note">All three are SIL Open Font License 1.1 and therefore
redistributable. Locally installed proportional faces (Georgia, Palatino,
Optima, Baskerville, Hoefler Text) are absent from this list because they are
system fonts that cannot legally be bundled into the product.</p>
<table>
<thead><tr><th>Family</th><th>File</th><th>Size</th>
<th>Existing&nbsp;art<br>coverage</th><th>SHA-256</th>
<th>License</th><th>CSS family</th></tr></thead>
<tbody>
{_provenance_rows()}
</tbody></table>

<h2>2. Candidates &mdash; raw material at both sizes</h2>
<p class="note">This is what a proportional face offers as drawing material:
its weight ramp, its italic, and how evenly it steps through a density
sequence. Judge the candidates here. No proposed art is shown, because none
exists yet &mdash; inventing some would smuggle an art-direction decision into
a typeface decision.</p>
{''.join(_candidate_panel(candidate) for candidate in CANDIDATES)}

<h2>3. Diagnostic &mdash; what proportional rendering does to the accepted art</h2>
<div class="warn">
<strong>Correction.</strong> An earlier version of this panel said the candidates
&ldquo;shear this art equally&rdquo; because of proportional advances. That was the
wrong mechanism. Measured against each font's <code>cmap</code>: <strong>Literata
0/12</strong>, <strong>Source Serif 4 0/12</strong>, <strong>EB Garamond
2/12</strong> of the twelve non-ASCII characters this art uses. The browser is
substituting a fallback font for nearly every glyph &mdash; which is why all three
columns below look almost identical. They are largely <em>not showing the candidate
faces at all</em>.
<br><br>
What this panel actually demonstrates is per-glyph fallback: the original defect,
reproduced under new fonts. It is still the evidence for why Contract P requires the
ten fixtures to be <strong>redrawn</strong> rather than re-reviewed, and it still
cannot tell the candidates apart &mdash; for a more decisive reason than first stated.
</div>
{_diagnostic_panel(art)}

<h2>4. Still outstanding after this page</h2>
<p class="note">Approving a face here settles step 4's face question. It does
not settle the size: 15px is what the worksheet and the atlas declare and what
the accepted art was signed off at, 13px is what the product currently paints,
and the right answer depends on art that does not exist yet. Line height,
weight, style and letter spacing become part of the runtime contract in step 6.
Scene captures of the current-root and frozen-legacy viewers are not included
here &mdash; they show monospace box art and would say nothing about a
proportional face choice.</p>

</body></html>
"""
    destination.write_text(page, encoding="utf-8")
    return destination


if __name__ == "__main__":
    written = build()
    print(f"wrote {written.relative_to(REPOSITORY_ROOT)}")
