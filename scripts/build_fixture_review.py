#!/usr/bin/env python3
"""Build a companion worksheet for looking at drawn fixture art.

WHAT THIS IS, AND WHAT IT IS NOT
--------------------------------
This is a companion diagnostic only. It does not own a baseline and nothing it
displays constitutes a sign-off. It is a convenience for looking at drawings
side by side in a browser instead of squinting at JSON, and for carrying the
operator's own words back out again.

WHY IT IS GENERATED RATHER THAN HAND-WRITTEN
--------------------------------------------
Looking at art is only useful if what appears on screen is what is actually
stored. A hand-written page showing retyped drawings could drift from the atlas
without anyone noticing, and then the thing being looked at would not be the
thing that ships. So this reads `atlas.v2.json` and emits the page from it.

HOW MARKS SURVIVE, AND WHY THERE ARE THREE ROUTES
-------------------------------------------------
The previous worksheet kept marks in a JavaScript `Map` and persisted nothing.
The operator reviewed all ten fixtures and the first worksheet discarded every
verdict on exit. Historical receipts now survive, but current verdicts are owned
only by `docs/garden-asset-acceptance.json`, so persistence is deliberately
redundant -- no single mechanism can lose the work again:

  1. AUTOSAVE to `localStorage` on every keystroke and click, restored on load.
     Wrapped in try/catch because a sandboxed frame can throw on access rather
     than merely returning null, and a storage failure must not take the page
     down with it.
  2. A LIVE TRANSCRIPT that is always visible and always current, as plain
     selectable text. This cannot fail: it is just DOM text. Even if storage is
     unavailable and the download is declined, the words are on screen and can
     be copied by hand.
  3. A DOWNLOAD offered through `window.claude.downloads`, which the viewer
     confirms. Never assume it succeeded -- the viewer may decline.

A visible save indicator reports which of these routes is actually available,
because a worksheet that silently fails to save is worse than one that never
claimed to.
"""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]

# Only assets carrying real drawn artwork are worth looking at. The remaining
# placeholders are single glyphs; listing them would pad the sheet with rows
# whose state is already known.
DRAWN_SOURCE = "drawn for LateLetter"

# Bumped whenever the stored shape OR the artwork changes. Restoring round-1
# marks onto round-2 drawings would silently attach a verdict to a picture it
# was never given about, which is worse than losing it.
STORAGE_KEY = "lateletter.fixture-review.round-4.v1"


def specimen_markup(asset: dict[str, Any], verdict: dict[str, Any]) -> str:
    """Render one asset as a specimen row with its own feedback box."""
    asset_id = asset["id"]
    label = asset.get("label") or asset_id
    lineage = asset.get("art_lineage", {})
    width, height = asset["cell_box"]
    anchor = asset["anchor"]

    ascii_rows = asset["profiles"]["ascii-safe"]["idle"][0]["cells"]
    ascii_text = "\n".join("".join(row) for row in ascii_rows)
    proportional = asset["profiles"]["browser-proportional"]["idle"][0]["rows"]
    proportional_text = "\n".join(proportional)

    safe_id = html.escape(asset_id)
    safe_label = html.escape(label)

    return f"""
      <article class="specimen" data-asset="{safe_id}">
        <div class="meta">
          <p class="eyebrow">{safe_id}</p>
          <h2>{safe_label}</h2>
          <p class="verdict-chip" data-verdict="{html.escape(verdict['verdict'])}">current verdict: {
            html.escape(verdict["verdict"].replace("_", " "))}</p>
          <p class="reviewed-at">reviewed {html.escape(verdict.get("reviewed_at") or "not yet")}</p>
          <p class="note">{html.escape(lineage.get("note", ""))}</p>
          <dl class="facts">
            <div><dt>Cell box</dt><dd>{width} &times; {height}</dd></div>
            <div><dt>Anchor</dt><dd>{anchor[0]}, {anchor[1]}</dd></div>
          </dl>
        </div>

        <div class="plates">
          <figure class="plate">
            <figcaption><span class="dot terminal"></span>ascii-safe &middot; terminal</figcaption>
            <pre class="art">{html.escape(ascii_text)}</pre>
          </figure>
          <figure class="plate">
            <figcaption><span class="dot browser"></span>browser-proportional</figcaption>
            <pre class="art proportional">{html.escape(proportional_text)}</pre>
          </figure>
        </div>

        <div class="judgement">
          <div class="mark" role="group" aria-label="Mark for {safe_label}">
            <button type="button" class="pill keep" data-mark="keep" aria-pressed="false">Reads</button>
            <button type="button" class="pill redraw" data-mark="redraw" aria-pressed="false">Redraw</button>
          </div>
          <label class="feedback-label" for="fb-{safe_id}">What is wrong with it</label>
          <textarea id="fb-{safe_id}" class="feedback" rows="3"
                    placeholder="optional &mdash; e.g. reads as a box, can&rsquo;t tell it&rsquo;s water, too small"></textarea>
        </div>
      </article>"""


PAGE_TEMPLATE = """<title>Fixture art worksheet &mdash; LateLetter Garden</title>
<style>
  /* ---------------------------------------------------------------------
     Palette taken from the Garden's own daylight colours in
     garden-renderer.mjs, so the worksheet sits in the product's world
     rather than a generic document theme. Neutrals carry a slight leaf
     bias so they read as chosen rather than inherited.
     --------------------------------------------------------------------- */
  :root {
    --paper:  #F2F4EF;
    --panel:  #E9ECE3;
    --ink:    #161A15;
    --muted:  #656B5F;
    --rule:   #D3D9CB;
    --leaf:   #436C2D;
    --water:  #416F8F;
    --clay:   #9E367F;
    --shadow: rgba(22, 26, 21, 0.07);
  }

  @media (prefers-color-scheme: dark) {
    :root {
      --paper:  #121410;
      --panel:  #1B1E18;
      --ink:    #E4E7DC;
      --muted:  #8D9484;
      --rule:   #2C312A;
      --leaf:   #8CB86A;
      --water:  #7FAECB;
      --clay:   #D083B6;
      --shadow: rgba(0, 0, 0, 0.4);
    }
  }
  /* The viewer's own toggle stamps data-theme on the root and must win over
     the media query in BOTH directions, not just into dark. */
  :root[data-theme="dark"] {
    --paper:  #121410; --panel: #1B1E18; --ink: #E4E7DC; --muted: #8D9484;
    --rule:   #2C312A; --leaf:  #8CB86A; --water: #7FAECB; --clay: #D083B6;
    --shadow: rgba(0, 0, 0, 0.4);
  }
  :root[data-theme="light"] {
    --paper:  #F2F4EF; --panel: #E9ECE3; --ink: #161A15; --muted: #656B5F;
    --rule:   #D3D9CB; --leaf:  #436C2D; --water: #416F8F; --clay: #9E367F;
    --shadow: rgba(22, 26, 21, 0.07);
  }

  * { box-sizing: border-box; }

  body {
    margin: 0;
    background: var(--paper);
    color: var(--ink);
    font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
    font-size: 16px;
    line-height: 1.55;
    -webkit-font-smoothing: antialiased;
  }

  .wrap { max-width: 66rem; margin: 0 auto; padding: 0 1.5rem 3rem; }

  /* Header ------------------------------------------------------------- */
  header { padding: 4rem 0 2rem; border-bottom: 2px solid var(--ink); }
  .kicker {
    margin: 0 0 0.75rem;
    font-family: ui-monospace, "SF Mono", Menlo, monospace;
    font-size: 0.6875rem; letter-spacing: 0.16em; text-transform: uppercase;
    color: var(--leaf);
  }
  h1 {
    margin: 0 0 0.75rem;
    font-size: clamp(1.75rem, 4vw, 2.5rem);
    line-height: 1.1; font-weight: 620; letter-spacing: -0.02em;
    text-wrap: balance;
  }
  .standfirst { margin: 0; max-width: 42rem; color: var(--muted); }

  /* Specimens ----------------------------------------------------------- */
  .sheet { display: flex; flex-direction: column; }

  .specimen {
    display: grid;
    grid-template-columns: 13rem minmax(0, 1fr) 15rem;
    gap: 1.75rem;
    align-items: start;
    padding: 2.25rem 0;
    border-bottom: 1px solid var(--rule);
  }
  .specimen[data-state="keep"]   { box-shadow: inset 3px 0 0 var(--leaf); padding-left: 1rem; }
  .specimen[data-state="redraw"] { box-shadow: inset 3px 0 0 var(--clay); padding-left: 1rem; }

  .eyebrow {
    margin: 0 0 0.25rem;
    font-family: ui-monospace, "SF Mono", Menlo, monospace;
    font-size: 0.6875rem; letter-spacing: 0.08em; color: var(--muted);
  }
  .meta h2 { margin: 0 0 0.5rem; font-size: 1.1875rem; font-weight: 600; letter-spacing: -0.01em; }
  .note { margin: 0 0 1rem; font-size: 0.875rem; color: var(--muted); }
  /* Prior verdict, carried from the atlas so the sheet shows what was already
     judged instead of asking for the same decision twice. */
  .verdict-chip {
    display: inline-block; margin: 0 0 0.6rem;
    padding: 0.1rem 0.5rem; border-radius: 999px;
    font-family: ui-monospace, "SF Mono", Menlo, monospace;
    font-size: 0.625rem; letter-spacing: 0.07em; text-transform: uppercase;
    border: 1px solid var(--rule); color: var(--muted);
  }
  .verdict-chip[data-verdict="accepted"] { border-color: var(--leaf); color: var(--leaf); }
  .verdict-chip[data-verdict="accepted with refinement"] { border-color: var(--water); color: var(--water); }
  .verdict-chip[data-verdict="rejected"] { border-color: var(--clay); color: var(--clay); }

  .facts { margin: 0; display: flex; flex-wrap: wrap; gap: 0.25rem 1.25rem; }
  .facts div { display: flex; gap: 0.4rem; align-items: baseline; }
  .facts dt {
    font-family: ui-monospace, "SF Mono", Menlo, monospace;
    font-size: 0.625rem; letter-spacing: 0.1em; text-transform: uppercase;
    color: var(--muted);
  }
  .facts dd {
    margin: 0; font-family: ui-monospace, "SF Mono", Menlo, monospace;
    font-size: 0.75rem; font-variant-numeric: tabular-nums;
  }

  .plates { display: grid; grid-template-columns: repeat(auto-fit, minmax(12rem, 1fr)); gap: 1rem; }
  .plate { margin: 0; min-width: 0; }
  figcaption {
    display: flex; align-items: center; gap: 0.45rem; margin-bottom: 0.5rem;
    font-family: ui-monospace, "SF Mono", Menlo, monospace;
    font-size: 0.625rem; letter-spacing: 0.09em; text-transform: uppercase;
    color: var(--muted);
  }
  .dot { width: 6px; height: 6px; border-radius: 50%; flex: none; }
  .dot.terminal { background: var(--leaf); }
  .dot.browser  { background: var(--water); }

  /* The art itself. Line-height 1.0 matches the renderer's
     DEFAULT_LINE_HEIGHT_RATIO, so box-drawing rows touch exactly as they do
     in the Garden. Anything looser breaks vertical strokes apart. */
  .art {
    margin: 0; padding: 1.1rem 1rem;
    background: var(--panel);
    border: 1px solid var(--rule); border-radius: 2px;
    font-family: ui-monospace, "SF Mono", Menlo, "DejaVu Sans Mono", monospace;
    font-size: 15px; line-height: 1;
    white-space: pre; overflow-x: auto; tab-size: 1;
  }
  .art.proportional { font-family: "IBM Plex Mono", "DejaVu Sans Mono", ui-monospace, monospace; }

  /* Judgement column ----------------------------------------------------- */
  .judgement { display: flex; flex-direction: column; gap: 0.6rem; }
  .mark { display: flex; gap: 0.4rem; }
  .pill {
    font: inherit; font-size: 0.8125rem; font-weight: 550;
    padding: 0.4rem 0.9rem;
    border: 1px solid var(--rule); border-radius: 999px;
    background: transparent; color: var(--muted); cursor: pointer;
    transition: background 0.12s ease, color 0.12s ease, border-color 0.12s ease;
  }
  .pill:hover { border-color: var(--ink); color: var(--ink); }
  .pill:focus-visible { outline: 2px solid var(--leaf); outline-offset: 2px; }
  .pill[aria-pressed="true"].keep   { background: var(--leaf); border-color: var(--leaf); color: var(--paper); }
  .pill[aria-pressed="true"].redraw { background: var(--clay); border-color: var(--clay); color: var(--paper); }

  .feedback-label {
    font-family: ui-monospace, "SF Mono", Menlo, monospace;
    font-size: 0.625rem; letter-spacing: 0.09em; text-transform: uppercase;
    color: var(--muted);
  }
  .feedback {
    font: inherit; font-size: 0.8125rem; line-height: 1.45;
    width: 100%; resize: vertical; min-height: 4.5rem;
    padding: 0.55rem 0.65rem;
    background: var(--paper); color: var(--ink);
    border: 1px solid var(--rule); border-radius: 2px;
  }
  .feedback:focus-visible { outline: 2px solid var(--leaf); outline-offset: 1px; border-color: var(--leaf); }
  .feedback::placeholder { color: var(--muted); opacity: 0.75; }

  /* Persistent footer ---------------------------------------------------- */
  .summary {
    position: sticky; bottom: 0;
    background: var(--panel);
    border-top: 1px solid var(--rule);
    box-shadow: 0 -2px 16px var(--shadow);
    padding: 0.85rem 0;
  }
  .summary-inner {
    max-width: 66rem; margin: 0 auto; padding: 0 1.5rem;
    display: flex; align-items: flex-start; gap: 1rem; flex-wrap: wrap;
  }
  .status-col { display: flex; flex-direction: column; gap: 0.35rem; min-width: 11rem; }
  .tally {
    font-family: ui-monospace, "SF Mono", Menlo, monospace;
    font-size: 0.75rem; letter-spacing: 0.04em;
    font-variant-numeric: tabular-nums; color: var(--muted);
  }
  .tally b { color: var(--ink); font-weight: 600; }
  .save-state {
    display: inline-flex; align-items: center; gap: 0.4rem;
    font-family: ui-monospace, "SF Mono", Menlo, monospace;
    font-size: 0.6875rem; letter-spacing: 0.04em; color: var(--muted);
  }
  .save-state .dot { width: 7px; height: 7px; }
  .save-state[data-ok="yes"] .dot { background: var(--leaf); }
  .save-state[data-ok="no"]  .dot { background: var(--clay); }
  .save-state[data-ok="no"]  { color: var(--clay); }

  #transcript {
    flex: 1 1 22rem; min-width: 0;
    margin: 0; padding: 0.55rem 0.7rem;
    background: var(--paper); border: 1px solid var(--rule); border-radius: 2px;
    font-family: ui-monospace, "SF Mono", Menlo, monospace;
    font-size: 0.6875rem; line-height: 1.55;
    max-height: 7rem; overflow-y: auto; white-space: pre-wrap;
    color: var(--ink);
    user-select: all;
  }

  .actions { display: flex; flex-direction: column; gap: 0.35rem; }
  .action {
    font: inherit; font-size: 0.75rem; font-weight: 550;
    padding: 0.4rem 0.85rem; white-space: nowrap;
    border: 1px solid var(--ink); border-radius: 2px;
    background: var(--ink); color: var(--paper); cursor: pointer;
  }
  .action.secondary { background: transparent; color: var(--ink); border-color: var(--rule); }
  .action:focus-visible { outline: 2px solid var(--leaf); outline-offset: 2px; }
  .action[disabled] { opacity: 0.45; cursor: not-allowed; }

  .footnote {
    margin: 2.5rem 0 0; padding: 1.25rem 0 0;
    border-top: 1px solid var(--rule);
    font-size: 0.8125rem; color: var(--muted);
  }
  .footnote code { font-family: ui-monospace, "SF Mono", Menlo, monospace; font-size: 0.75rem; }

  @media (max-width: 60rem) {
    .specimen { grid-template-columns: 1fr; gap: 1.25rem; }
  }
  @media (prefers-reduced-motion: reduce) { * { transition: none !important; } }
</style>

<div class="wrap">
  <header>
    <p class="kicker">operator fixture review record</p>
    <h1>Fixture art &mdash; accepted starter set</h1>
    <p class="standfirst">
      <strong>All ten drawings carry the operator's accepted verdict.</strong>
      Round 3 accepted bench, trellis and birdbath; round 4 accepted the remaining seven.
      Current verdicts come from <code>docs/garden-asset-acceptance.json</code>; the exact
      operator messages remain in <code>docs/operator-decision-record.md</code>.
    </p>
  </header>

  <div class="sheet">__SPECIMENS__
  </div>

  <p class="footnote">
    Rendered from <code>src/lateletter/garden/data/atlas.v2.json</code>, so this is the
    art as stored. The proportional column is drawn here as ordinary browser text; the
    Garden itself measures those rows through PreText and places each glyph at its
    measured offset, so treat this column as the drawing, not the final geometry.
    <br><br>
    Still undrawn and holding a single placeholder glyph: __UNDRAWN__.
  </p>
</div>

<div class="summary">
  <div class="summary-inner">
    <div class="status-col">
      <span class="tally" id="tally"></span>
      <span class="save-state" id="save-state"><span class="dot"></span><span id="save-text">&hellip;</span></span>
    </div>
    <pre id="transcript" tabindex="0" aria-label="Review transcript"></pre>
    <div class="actions">
      <button type="button" class="action" id="copy">Copy</button>
      <button type="button" class="action secondary" id="download">Download</button>
      <button type="button" class="action secondary" id="clear">Clear all</button>
    </div>
  </div>
</div>

<script>
(function () {
  'use strict';

  var STORAGE_KEY = '__STORAGE_KEY__';
  var specimens = Array.prototype.slice.call(document.querySelectorAll('.specimen'));
  var transcript = document.getElementById('transcript');
  var saveState = document.getElementById('save-state');
  var saveText = document.getElementById('save-text');

  // { assetId: { mark: 'keep'|'redraw'|null, note: string } }
  var review = {};
  var storageUsable = true;

  /* --- persistence ---------------------------------------------------- */
  // A sandboxed frame can THROW on localStorage access rather than returning
  // null, so every touch is guarded. A storage failure degrades the page to
  // the always-visible transcript; it never breaks it.
  function readStored() {
    try {
      var raw = window.localStorage.getItem(STORAGE_KEY);
      return raw ? JSON.parse(raw) : null;
    } catch (error) {
      storageUsable = false;
      return null;
    }
  }

  function writeStored() {
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(review));
      return true;
    } catch (error) {
      storageUsable = false;
      return false;
    }
  }

  function reportSaveState(saved) {
    if (storageUsable && saved) {
      saveState.dataset.ok = 'yes';
      saveText.textContent = 'saved in this browser';
    } else {
      saveState.dataset.ok = 'no';
      // Stated plainly rather than hidden: the operator needs to know to copy
      // the transcript before leaving the page.
      saveText.textContent = 'not saving \\u2014 copy before you leave';
    }
  }

  /* --- transcript ----------------------------------------------------- */
  function entriesFor(mark) {
    return Object.keys(review).filter(function (id) { return review[id].mark === mark; });
  }

  function buildTranscript() {
    var lines = ['# LateLetter fixture review, round 4'];
    var keep = entriesFor('keep');
    var redraw = entriesFor('redraw');

    if (keep.length) lines.push('', 'READS: ' + keep.join(', '));
    if (redraw.length) lines.push('', 'REDRAW: ' + redraw.join(', '));

    var noted = Object.keys(review).filter(function (id) {
      return review[id].note && review[id].note.trim();
    });
    if (noted.length) {
      lines.push('', '## notes');
      noted.forEach(function (id) {
        var mark = review[id].mark ? ' [' + review[id].mark + ']' : '';
        lines.push('- ' + id + mark + ': ' + review[id].note.trim().replace(/\\s+/g, ' '));
      });
    }

    var unmarked = specimens.length - keep.length - redraw.length;
    if (unmarked > 0) lines.push('', '(' + unmarked + ' still unmarked)');
    return lines.join('\\n');
  }

  function refresh(persist) {
    var keep = entriesFor('keep').length;
    var redraw = entriesFor('redraw').length;
    document.getElementById('tally').innerHTML =
      '<b>' + keep + '</b> reads &nbsp; <b>' + redraw + '</b> redraw &nbsp; <b>' +
      (specimens.length - keep - redraw) + '</b> unmarked';
    transcript.textContent = buildTranscript();
    if (persist !== false) reportSaveState(writeStored());
  }

  /* --- wiring --------------------------------------------------------- */
  var stored = readStored() || {};

  specimens.forEach(function (specimen) {
    var asset = specimen.dataset.asset;
    var entry = stored[asset] || { mark: null, note: '' };
    review[asset] = { mark: entry.mark || null, note: entry.note || '' };

    var textarea = specimen.querySelector('.feedback');
    textarea.value = review[asset].note;
    if (review[asset].mark) specimen.dataset.state = review[asset].mark;

    Array.prototype.forEach.call(specimen.querySelectorAll('.pill'), function (button) {
      button.setAttribute('aria-pressed', String(review[asset].mark === button.dataset.mark));
      button.addEventListener('click', function () {
        // Clicking the active mark again clears it, so a misclick is
        // recoverable without a third control.
        review[asset].mark = review[asset].mark === button.dataset.mark ? null : button.dataset.mark;
        if (review[asset].mark) specimen.dataset.state = review[asset].mark;
        else specimen.removeAttribute('data-state');
        Array.prototype.forEach.call(specimen.querySelectorAll('.pill'), function (sibling) {
          sibling.setAttribute('aria-pressed', String(review[asset].mark === sibling.dataset.mark));
        });
        refresh();
      });
    });

    // Saved on every keystroke rather than on blur: a tab dismissed
    // mid-sentence must not lose the sentence.
    textarea.addEventListener('input', function () {
      review[asset].note = textarea.value;
      refresh();
    });
  });

  /* --- actions -------------------------------------------------------- */
  function selectTranscript() {
    // Clipboard access can be denied inside a frame. Selecting the text is the
    // fallback that needs no permission at all.
    var range = document.createRange();
    range.selectNodeContents(transcript);
    var selection = window.getSelection();
    selection.removeAllRanges();
    selection.addRange(range);
    transcript.focus();
  }

  document.getElementById('copy').addEventListener('click', function (event) {
    var button = event.currentTarget;
    var text = buildTranscript();
    var restore = function (message) {
      button.textContent = message;
      window.setTimeout(function () { button.textContent = 'Copy'; }, 1600);
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(
        function () { restore('Copied'); },
        function () { selectTranscript(); restore('Select + \\u2318C'); }
      );
    } else {
      selectTranscript();
      restore('Select + \\u2318C');
    }
  });

  var downloadButton = document.getElementById('download');
  if (!window.claude || !window.claude.downloads) {
    // Disable UI that cannot function here rather than offering a button that
    // fails every time it is pressed.
    downloadButton.disabled = true;
    downloadButton.title = 'Downloads are unavailable in this view';
  } else {
    downloadButton.addEventListener('click', function (event) {
      var button = event.currentTarget;
      var restore = function (message) {
        button.textContent = message;
        window.setTimeout(function () { button.textContent = 'Download'; }, 2200);
      };
      window.claude.downloads.save({
        filename: 'fixture-review-round-4.md',
        data: buildTranscript() + '\\n'
      }).then(function () { restore('Saved'); }, function (error) {
        // The viewer declining is a normal outcome, not an error to retry.
        var code = error && error.code;
        if (code === 'declined') restore('Download');
        else if (code === 'rate_limited') restore('Try again');
        else restore('Unavailable');
      });
    });
  }

  document.getElementById('clear').addEventListener('click', function () {
    if (!window.confirm('Clear every mark and note on this sheet?')) return;
    specimens.forEach(function (specimen) {
      var asset = specimen.dataset.asset;
      review[asset] = { mark: null, note: '' };
      specimen.removeAttribute('data-state');
      specimen.querySelector('.feedback').value = '';
      Array.prototype.forEach.call(specimen.querySelectorAll('.pill'), function (pill) {
        pill.setAttribute('aria-pressed', 'false');
      });
    });
    refresh();
  });

  // Probe storage once at load so the indicator is truthful before the
  // operator has typed anything and discovered otherwise the hard way.
  refresh(true);
})();
</script>
"""


def build_page(atlas: dict[str, Any], registry: dict[str, Any]) -> str:
    drawn = [a for a in atlas["assets"]
             if a.get("art_lineage", {}).get("source") == DRAWN_SOURCE]
    undrawn = [a for a in atlas["assets"]
               if a.get("art_lineage", {}).get("source") != DRAWN_SOURCE]
    verdicts = {row["asset_id"]: row for row in registry["assets"]}

    return (
        PAGE_TEMPLATE
        .replace("__SPECIMENS__", "\n".join(
            specimen_markup(asset, verdicts[asset["id"]]) for asset in drawn
        ))
        .replace("__UNDRAWN__", ", ".join(html.escape(a["id"]) for a in undrawn))
        .replace("__STORAGE_KEY__", STORAGE_KEY)
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--atlas", type=Path,
        default=REPOSITORY_ROOT / "src/lateletter/garden/data/atlas.v2.json",
    )
    parser.add_argument(
        "--registry", type=Path,
        default=REPOSITORY_ROOT / "docs/garden-asset-acceptance.json",
    )
    # One stable path, not one file per round. The worksheet is republished to a
    # single artifact URL, and a new filename would mint a new URL and orphan the
    # one the operator already has open. The round is carried in the page's own
    # heading and in STORAGE_KEY, which is what actually has to change per round.
    parser.add_argument(
        "--output", type=Path,
        default=REPOSITORY_ROOT / "docs/visual-review/fixtures.html",
    )
    args = parser.parse_args()

    atlas = json.loads(args.atlas.read_text(encoding="utf-8"))
    registry = json.loads(args.registry.read_text(encoding="utf-8"))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(build_page(atlas, registry), encoding="utf-8")

    drawn = sum(1 for a in atlas["assets"]
                if a.get("art_lineage", {}).get("source") == DRAWN_SOURCE)
    print(f"wrote {args.output} ({drawn} assets shown)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
