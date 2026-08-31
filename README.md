# LateLetter

Letters that arrive after you're gone.

A tool for writing time-delayed letters to loved ones, delivered through a living ASCII garden in the browser.

## Browser viewer previews

The production URL currently serves the frozen legacy viewer while the newer
root viewer completes its acceptance work. The two GIFs below are README-facing
browser-flow captures from the real HTML routes: the root candidate opens
`viewer-bnw.html`, and the legacy capture opens `legacy/viewer-bnw.html`, the
surface retained for `rikiworld.com/lateletter`.

[![Current root HTML viewer candidate](docs/lateletter-viewer-current.gif)](docs/lateletter-viewer-current.gif)

[![Production legacy HTML viewer](docs/lateletter-viewer-legacy.gif)](docs/lateletter-viewer-legacy.gif)

The legacy Pages fingerprint, deployment commit, and safe tag/release plan are
recorded in [`docs/legacy-pages-release-plan.md`](docs/legacy-pages-release-plan.md).

![LateLetter TUI demo](docs/demo.gif)

## How it works

**Author** writes letters, sets delivery dates, and chooses a passphrase. Letters are bundled into a `.lateletter` file.

**Recipient** opens the file in their browser. A garden grows while they wait. Letters appear on their scheduled dates. Animals visit. The garden remembers.

## Quick start

Open `viewer-bnw.html` in a browser. Click **[get demo letter]** to load the
demo bundle, or drop your own `.lateletter` file. The public URL is intentionally
served from `legacy/viewer-bnw.html`; the root viewer is the newer development
candidate until its release gates are complete.

Demo passphrase: `garden-biscuit-2026`

**[get passcode-locked demo]** loads a demo whose private content can only be opened with passcode `garden-biscuit-2026`. A wrong passcode is rejected. Internally, the output bundle uses PBKDF2-SHA256 and AES-256-GCM.

## Send a real letter

```bash
cp letters/letter_source.example.json letters/my_letter.json
# edit letters/my_letter.json — your words, dates, hint, and Garden program
python3 make_letter.py letters/my_letter.json letters/for_them.lateletter
python3 make_letter.py --verify letters/for_them.lateletter   # round-trip check
```

Send `letters/for_them.lateletter` to your friend with a link to the viewer
(https://rikiworld.com/lateletter/). Tell them the passcode in person.
The builder asks for a fresh passphrase twice; it is never stored in the source
JSON or output bundle. Keep the editable source and first sealed output under
ignored `letters/` filenames. The tracked example contains synthetic text only.

### Or send just a link

Build and verify in ignored private storage first. After final copy approval,
copy only the sealed output into `public_letters/` and commit that bundle. A
standard GitHub Pages site is public even when its source repository
is private, so anyone with the URL can download the bundle; only someone with
the passcode can open its private content:

```bash
python3 make_letter.py letters/my_letter.json letters/to-personx.lateletter
python3 make_letter.py --verify letters/to-personx.lateletter
cp letters/to-personx.lateletter public_letters/to-personx.lateletter
git add public_letters/to-personx.lateletter && git commit -m "letter" && git push
```

After the Pages deploy, share `https://rikiworld.com/lateletter/to-personx/`
(passcode gate included — no file handling for the recipient at all).
Heads-up: your author name, the passphrase hint, and delivery dates are
plaintext in the bundle, so anyone with the URL (or browsing the repo)
can see those — the letter body and gift sentiments stay sealed.
Demo link once deployed: https://rikiworld.com/lateletter/to-a-friend/ (passcode `garden-biscuit-2026`).

## Project structure

```
viewer-bnw.html          Single-file browser viewer (garden + letter reader)
test_fixture.lateletter  Demo bundle (Buddy's letter)
src/lateletter/          Python author tools (CLI, intake, bundling)
legacy/                  Frozen pre-July-19 browser viewer used by Pages
docs/visual-review/      Browser captures, masters, stills, and validation receipts
```

## Garden

The viewer renders an ASCII garden that changes with the seasons. Plants grow procedurally from a seed. Rain falls in spring and autumn, snow in winter, butterflies in summer. Clicking plants scatters particles. An animal companion appears after the first visit.

## Dev tools

Load the demo fixture (no HMAC = dev mode) to unlock dev keybindings:

- `,` / `.` cycle seasons + night
- `Shift+B` cycle color modes
- `Shift+G` grid overlay with FPS
- `Shift+A` cycle animal types/tiers
- `f` feed the animal

## License

Private project.
