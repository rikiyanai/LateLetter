# LateLetter

Letters that arrive after you're gone.

A tool for writing time-delayed letters to loved ones, delivered through a living ASCII garden in the browser.

![LateLetter TUI demo](docs/demo.gif)

## How it works

**Author** writes letters, sets delivery dates, and chooses a passphrase. Letters are bundled into a `.lateletter` file.

**Recipient** opens the file in their browser. A garden grows while they wait. Letters appear on their scheduled dates. Animals visit. The garden remembers.

## Quick start

Open `viewer-bnw.html` in a browser. Click **[get demo letter]** to load the demo bundle, or drop your own `.lateletter` file.

Demo passphrase: `biscuit`

**[get sealed letter]** loads a *really* encrypted demo (PBKDF2-SHA256 + AES-256-GCM, verified and decrypted in the browser). Passcode: `garden`. A wrong passcode is actually rejected.

## Send a real letter

```bash
cp letters/letter_source.example.json letters/my_letter.json
# edit letters/my_letter.json — your words, dates, passcode, hint
python3 make_letter.py letters/my_letter.json for_them.lateletter
python3 make_letter.py --verify for_them.lateletter   # round-trip check
```

Send `for_them.lateletter` to your friend with a link to the viewer
(https://rikiworld.com/lateletter/). Tell them the passcode in person.
The passcode is never stored in the file; `letters/` is gitignored
because the source JSON holds your plaintext letter and passcode.

### Or send just a link

Seal the letter into `public_letters/` instead and commit it — the repo
is public, but the letter is really encrypted, so only the passcode
opens it:

```bash
python3 make_letter.py letters/my_letter.json public_letters/to-personx.lateletter
git add public_letters && git commit -m "letter" && git push
```

After the Pages deploy, share `https://rikiworld.com/lateletter/to-personx/`
(passcode gate included — no file handling for the recipient at all).
Heads-up: your author name, the passphrase hint, and delivery dates are
plaintext in the bundle, so anyone with the URL (or browsing the repo)
can see those — the letter body and gift sentiments stay sealed.
Demo link once deployed: https://rikiworld.com/lateletter/to-a-friend/ (passcode `garden`).

## Project structure

```
viewer-bnw.html          Single-file browser viewer (garden + letter reader)
test_fixture.lateletter  Demo bundle (Buddy's letter)
src/lateletter/          Python author tools (CLI, intake, bundling)
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
