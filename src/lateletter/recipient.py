"""
src/lateletter/recipient.py — Recipient mode.

Loads a .lateletter bundle and runs the living garden delivery experience:

  • Garden renders with the bundle's embedded seed (§6.1)
  • Status bar: i · unlock letters (§6.2–6.3)
  • Passphrase overlay with hint (§6.4)
  • Due-message detection, letter-bird, reading overlay (§6.4)
  • Letter archive (§6.6) with two sections:
      Letters   — all messages with read/unread/future markers
      Memories  — triggered garden gifts (items + landmarks) the author left
  • Memory overlay — the author's short sentiment text for a discovered item
  • Read receipts  → ~/.lateletter/recipient/receipts.json (§6.4 step 8)
  • Garden state   → ~/.lateletter/recipient/garden_state.json (§6.8.7)

Dev fixtures (bundle.hmac == "") store base64(plaintext) in ciphertext fields.
Real v0 sealed bundles use the same PBKDF2-SHA256 + AES-256-GCM implementation
as the browser viewer and are authenticated before any delivery state appears.
"""
from __future__ import annotations

import base64
import curses
import json
import os
import time
from datetime import date
from pathlib import Path
from typing import Any

from .bundle import Bundle, GardenGift, Message, read_bundle, verify_checksum
from .sealed import (
    open_gift_sentiment,
    open_message,
    verify_bundle_hmac,
)
from .garden.renderer import GardenRenderer
from .garden.colors import curses_attr, init_curses_colors


# ---------------------------------------------------------------------------
# Item catalog — v1 set (~15 objects)
#
# Each entry maps catalog_id → (display_name, ascii_art).
# ASCII art is 3–5 terminal-safe characters chosen to be recognisable at
# small scale and immediately evocative of a specific kind of memory.
# ---------------------------------------------------------------------------

ITEM_CATALOG: dict[str, tuple[str, str]] = {
    "coffee_mug":     ("A coffee mug",       "( ~ )"),
    "teacup":         ("A teacup",           "{ ~ }"),
    "plate_of_food":  ("A plate of food",    "[o.o]"),
    "pair_of_shoes":  ("A pair of shoes",    " >,> "),
    "book":           ("A book",             " [=] "),
    "small_radio":    ("A small radio",      "[~=~]"),
    "candle":         ("A candle",           " .*| "),
    "pocket_watch":   ("A pocket watch",     " (@) "),
    "photo_frame":    ("A photo frame",      " [ ] "),
    "pressed_flower": ("A pressed flower",   " *·* "),
    "fishing_rod":    ("A fishing rod",      " /~~ "),
    "compass":        ("A compass",          " (^) "),
    "old_key":        ("An old key",         " >-) "),
    "small_stone":    ("A small stone",      " (.) "),
    "ribbon":         ("A ribbon",           " ~o~ "),
}

_CATALOG_DEFAULT: tuple[str, str] = ("A small object", " (·) ")


def catalog_entry(catalog_id: str) -> tuple[str, str]:
    """Return (display_name, art) for a catalog_id, with a safe fallback."""
    return ITEM_CATALOG.get(catalog_id, _CATALOG_DEFAULT)


# ---------------------------------------------------------------------------
# Trigger evaluation (§6.8.4)
# ---------------------------------------------------------------------------

def is_gift_triggered(
    gift: GardenGift,
    today: date,
    total_visits: int,
    read_msg_ids: set[str],
) -> bool:
    """Return True when this gift's trigger condition has been met."""
    t = gift.trigger
    if t.type == "date":
        try:
            return today >= date.fromisoformat(t.value)
        except ValueError:
            return False
    if t.type == "cumulative_visits":
        try:
            return total_visits >= int(t.value)
        except ValueError:
            return False
    if t.type == "post_letter":
        return t.value in read_msg_ids
    return False


# ---------------------------------------------------------------------------
# Recipient-side persistent state
# ---------------------------------------------------------------------------

_RECIPIENT_DIR = Path.home() / ".lateletter" / "recipient"
_RECEIPTS_FILE = _RECIPIENT_DIR / "receipts.json"
_GARDEN_STATE_FILE = _RECIPIENT_DIR / "garden_state.json"


class RecipientStore:
    """Read/write ~/.lateletter/recipient/receipts.json and garden_state.json."""

    def __init__(self, bundle_id: str) -> None:
        self.bundle_id = bundle_id
        self.was_absent: bool = False  # set by increment_visit
        _RECIPIENT_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._receipts: dict[str, Any] = self._load(_RECEIPTS_FILE)
        self._state: dict[str, Any] = self._load(_GARDEN_STATE_FILE)
        # Ensure per-bundle slots exist
        self._receipts.setdefault(bundle_id, {})
        self._state.setdefault(bundle_id, {
            "total_visits": 0,
            "last_visit": None,
            "discovered_items": [],
            "animals": {},
        })

    # -- JSON helpers --------------------------------------------------------

    @staticmethod
    def _load(path: Path) -> dict[str, Any]:
        if path.exists():
            try:
                with open(path, encoding="utf-8") as fh:
                    return json.load(fh)
            except (json.JSONDecodeError, OSError):
                pass
        return {}

    def _save(self, path: Path, data: dict[str, Any]) -> None:
        tmp = path.with_suffix(".tmp")
        try:
            with open(tmp, "w", encoding="utf-8",
                      opener=lambda p, flags: os.open(p, flags, 0o600)) as fh:
                json.dump(data, fh, indent=2)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, path)
        except OSError:
            if tmp.exists():
                tmp.unlink(missing_ok=True)

    # -- Read receipts (§6.4 step 8) -----------------------------------------

    def is_read(self, message_id: str) -> bool:
        return message_id in self._receipts.get(self.bundle_id, {})

    def mark_read(self, message_id: str) -> None:
        self._receipts[self.bundle_id][message_id] = {
            "read_at": date.today().isoformat()
        }
        self._save(_RECEIPTS_FILE, self._receipts)

    def read_set(self) -> set[str]:
        return set(self._receipts.get(self.bundle_id, {}).keys())

    # -- Garden state (§6.8.7) -----------------------------------------------

    def total_visits(self) -> int:
        return self._state.get(self.bundle_id, {}).get("total_visits", 0)

    def increment_visit(self) -> None:
        s = self._state[self.bundle_id]
        today_str = date.today().isoformat()
        prev = s.get("last_visit")
        # Detect absence: gap of ≥ 1 day since last visit
        if prev and prev < today_str:
            try:
                self.was_absent = (date.today() - date.fromisoformat(prev)).days >= 1
            except ValueError:
                self.was_absent = False
        s["total_visits"] = s.get("total_visits", 0) + 1
        s["last_visit"] = today_str
        self._save(_GARDEN_STATE_FILE, self._state)

    def is_discovered(self, gift_id: str) -> bool:
        items = self._state.get(self.bundle_id, {}).get("discovered_items", [])
        return gift_id in items

    def mark_discovered(self, gift_id: str) -> None:
        s = self._state[self.bundle_id]
        lst = s.setdefault("discovered_items", [])
        if gift_id not in lst:
            lst.append(gift_id)
            self._save(_GARDEN_STATE_FILE, self._state)

    # -- Animal relationships (§6.8.2) ----------------------------------------

    def get_animal_state(self, animal_type: str) -> dict[str, Any]:
        """Return the current state dict for this animal type."""
        return (
            self._state.get(self.bundle_id, {})
            .get("animals", {})
            .get(animal_type, {"trust_actions": 0, "trust_tier": 0, "last_fed": None})
        )

    def feed_animal(self, animal_type: str) -> int:
        """Increment trust_actions, recalculate tier.  Returns new tier."""
        s = self._state[self.bundle_id]
        animals = s.setdefault("animals", {})
        a = animals.setdefault(animal_type, {
            "trust_actions": 0, "trust_tier": 0, "last_fed": None,
        })
        a["trust_actions"] = a.get("trust_actions", 0) + 1
        actions = a["trust_actions"]
        tier = 0
        for t, threshold in enumerate((3, 7, 14)):
            if actions >= threshold:
                tier = t + 1
        a["trust_tier"] = tier
        a["last_fed"] = date.today().isoformat()
        self._save(_GARDEN_STATE_FILE, self._state)
        return tier


# ---------------------------------------------------------------------------
# Dev-fixture content decoding
#
# Dev fixtures (bundle.hmac == "") store base64(plaintext) in ciphertext fields
# so the schema shape is correct while the encryption layer is not yet built.
# ---------------------------------------------------------------------------

def _b64decode(b64_str: str) -> str:
    """Base64-decode a dev fixture text field.  Returns "" on failure."""
    if not b64_str:
        return ""
    try:
        return base64.b64decode(b64_str).decode("utf-8")
    except Exception:
        return ""


def _decode_message(msg: Message) -> tuple[str, str]:
    """Return (label, body) from a dev fixture message.

    Dev fixtures encode JSON {"label": ..., "body": ...} in the ciphertext
    field (base64).  Falls back to treating raw text as the body.
    """
    raw = _b64decode(msg.ciphertext)
    if raw:
        try:
            data = json.loads(raw)
            return data.get("label", ""), data.get("body", "")
        except json.JSONDecodeError:
            return "", raw
    return "(encrypted)", "(This letter requires Phase 3 decryption.)"


# ---------------------------------------------------------------------------
# Drawing helpers
# ---------------------------------------------------------------------------

def _draw_box(
    scr: curses.window, y: int, x: int, h: int, w: int, attr: int = 0
) -> None:
    try:
        scr.addstr(y, x, "╔" + "═" * (w - 2) + "╗", attr)
        for row in range(y + 1, y + h - 1):
            scr.addstr(row, x, "║", attr)
            scr.addstr(row, x + w - 1, "║", attr)
        scr.addstr(y + h - 1, x, "╚" + "═" * (w - 2) + "╝", attr)
    except curses.error:
        pass


def _draw_centered(
    scr: curses.window, y: int, text: str, attr: int = 0
) -> None:
    _, sw = scr.getmaxyx()
    x = max(0, (sw - len(text)) // 2)
    try:
        scr.addstr(y, x, text[:sw], attr)
    except curses.error:
        pass


def _draw_text_block(
    scr: curses.window, y: int, x: int, w: int, h: int,
    lines: list[str], scroll: int, attr: int = 0,
) -> int:
    """Word-wrap and draw text lines.  Returns total wrapped line count."""
    wrapped: list[str] = []
    for line in lines:
        if not line:
            wrapped.append("")
            continue
        while len(line) > w:
            brk = line.rfind(" ", 0, w)
            if brk <= 0:
                brk = w
            wrapped.append(line[:brk])
            line = line[brk:].lstrip()
        wrapped.append(line)
    for i, line in enumerate(wrapped[scroll: scroll + h]):
        try:
            scr.addstr(y + i, x, line[:w], attr)
        except curses.error:
            pass
    return len(wrapped)


# ---------------------------------------------------------------------------
# Archive helpers
# ---------------------------------------------------------------------------

# An "archive row" is one of:
#   ("letter",  msg_idx: int,  msg: Message)
#   ("divider", None,          None)            ← not selectable
#   ("gift",    gift_id: str,  gift: GardenGift)

_ArchiveRow = tuple[str, Any, Any]


def _build_archive_rows(
    bundle: Bundle,
    today: date,
    total_visits: int,
    read_msg_ids: set[str],
) -> list[_ArchiveRow]:
    """Build the flat row list for the archive overlay."""
    rows: list[_ArchiveRow] = []
    for i, msg in enumerate(bundle.messages):
        rows.append(("letter", i, msg))
    triggered = [
        g for g in bundle.garden_gifts
        if g.type in ("item", "landmark")
        and is_gift_triggered(g, today, total_visits, read_msg_ids)
    ]
    if triggered:
        rows.append(("divider", None, None))
        for g in triggered:
            rows.append(("gift", g.id, g))
    return rows


def _selectable(rows: list[_ArchiveRow]) -> list[int]:
    """Return indices of rows the cursor can land on (not dividers)."""
    return [i for i, r in enumerate(rows) if r[0] != "divider"]


def _clamp_scroll(
    sel: int,
    sel_indices: list[int],
    scroll: int,
    n_visible: int,
) -> int:
    """Adjust scroll so the selected row is in the visible window."""
    if not sel_indices:
        return 0
    vis_idx = sel_indices[sel]
    if vis_idx < scroll:
        return vis_idx
    if vis_idx >= scroll + n_visible:
        return vis_idx - n_visible + 1
    return scroll


# ---------------------------------------------------------------------------
# Overlay renderers
# ---------------------------------------------------------------------------

def _draw_passphrase(
    scr: curses.window, h: int, w: int,
    author: str, hint: str | None,
    buf: str, error: str,
) -> None:
    bw = min(54, w - 4)
    bh = 10 if hint else 9
    bx = (w - bw) // 2
    by = (h - bh) // 2
    _draw_box(scr, by, bx, bh, bw, curses.A_BOLD)
    _draw_centered(scr, by + 1, f"Letters from {author}", curses.A_BOLD)
    _draw_centered(scr, by + 2, "Unlock to check for due messages")
    field = buf + "_" * max(0, 20 - len(buf))
    _draw_centered(scr, by + 4, f"Passphrase: [{field[:20]}]")
    if hint:
        _draw_centered(scr, by + 5, f"Hint: {hint}", curses.A_DIM)
    if error:
        _draw_centered(scr, by + (7 if hint else 6), error, curses.A_BOLD)


def _draw_selection(
    scr: curses.window, h: int, w: int,
    bundle: Bundle, due_indices: list[int], sel: int,
) -> None:
    bw = min(52, w - 4)
    bh = len(due_indices) + 6
    bx = (w - bw) // 2
    by = (h - bh) // 2
    _draw_box(scr, by, bx, bh, bw, curses.A_BOLD)
    _draw_centered(scr, by + 1, "Letters waiting:", curses.A_BOLD)
    _draw_centered(scr, by + 2, "─" * (bw - 4))
    for i, mi in enumerate(due_indices):
        marker = "▸ " if i == sel else "  "
        attr = curses.A_BOLD if i == sel else 0
        _draw_centered(scr, by + 3 + i,
                       f"{marker}{i + 1}. {bundle.messages[mi].date}", attr)
    _draw_centered(scr, by + bh - 2,
                   "↑/↓ select  ·  enter to read  ·  esc return",
                   curses.A_DIM)


def _draw_reading(
    scr: curses.window, h: int, w: int,
    author: str, label: str, body: str, scroll: int,
) -> None:
    bw = min(62, w - 4)
    bh = h - 4
    bx = (w - bw) // 2
    by = 2
    _draw_box(scr, by, bx, bh, bw, curses.A_BOLD)
    _draw_centered(scr, by + 1, f"From {author}: {label}", curses.A_BOLD)
    _draw_centered(scr, by + 2, "─" * (bw - 4))
    text_h = bh - 6
    total = _draw_text_block(
        scr, by + 3, bx + 2, bw - 4, text_h,
        body.split("\n"), scroll,
    )
    if scroll + text_h < total:
        _draw_centered(scr, by + bh - 2,
                       "↓ scroll for more  ·  esc return", curses.A_DIM)
    else:
        _draw_centered(scr, by + bh - 2,
                       "— end of letter —  ·  esc return", curses.A_DIM)


def _draw_archive(
    scr: curses.window, h: int, w: int,
    bundle: Bundle,
    rows: list[_ArchiveRow],
    sel: int,
    scroll: int,
    read_ids: set[str],
    store: RecipientStore,
    today: date,
    msg_content: list[tuple[str, str]],
) -> None:
    """Draw the archive overlay: Letters section + Memories section."""
    sel_indices = _selectable(rows)
    n_visible = min(len(rows), 14)
    bw = min(62, w - 4)
    bh = n_visible + 6
    bh = max(bh, 8)
    bx = (w - bw) // 2
    by = max(1, (h - bh) // 2)

    _draw_box(scr, by, bx, bh, bw, curses.A_BOLD)
    _draw_centered(scr, by + 1, f"Letters from {bundle.author_name}", curses.A_BOLD)
    _draw_centered(scr, by + 2, "─" * (bw - 4))

    all_read = all(msg.id in read_ids for msg in bundle.messages)
    sel_abs = sel_indices[sel] if sel_indices else -1
    visible = rows[scroll: scroll + n_visible]

    for offset, row in enumerate(visible):
        sy = by + 3 + offset
        abs_idx = scroll + offset
        is_sel = abs_idx == sel_abs
        mk = "▸ " if is_sel else "  "
        attr = curses.A_BOLD if is_sel else 0

        rtype = row[0]

        if rtype == "divider":
            div = ("── Memories " + "─" * max(0, bw - 16))[:bw - 4]
            try:
                scr.addstr(sy, bx + 2, div, curses.A_DIM)
            except curses.error:
                pass

        elif rtype == "letter":
            mi = row[1]
            msg = row[2]
            try:
                msg_date = date.fromisoformat(msg.date)
                is_future = today < msg_date
            except ValueError:
                is_future = False

            if msg.id in read_ids:
                status = "✓"
                label, _ = msg_content[mi]
                if label:
                    text = f"{mk}{status}  {msg.date} — {label}"
                else:
                    text = f"{mk}{status}  {msg.date}"
            elif is_future:
                status = "◻"
                text = f"{mk}{status}  {msg.date} — (not yet available)"
            else:
                status = "◻"
                text = f"{mk}{status}  {msg.date}"

            try:
                scr.addstr(sy, bx + 2, text[:bw - 4], attr)
            except curses.error:
                pass

        elif rtype == "gift":
            gift = row[2]
            name, art = catalog_entry(gift.catalog_id)
            disc = "✦" if store.is_discovered(gift.id) else "·"
            text = f"{mk}{disc}  {art}  {name}"
            try:
                scr.addstr(sy, bx + 2, text[:bw - 4], attr)
            except curses.error:
                pass

    footer = ("All letters delivered. This garden is yours." if all_read
              else "↑/↓ navigate  ·  enter to open  ·  esc return")
    _draw_centered(scr, by + bh - 2, footer, curses.A_DIM)


def _draw_memory(
    scr: curses.window, h: int, w: int,
    gift: GardenGift,
    sentiment: str,
) -> None:
    """Overlay showing the author's sentiment for a discovered item."""
    name, art = catalog_entry(gift.catalog_id)
    bw = min(54, w - 4)
    bh = 9
    bx = (w - bw) // 2
    by = (h - bh) // 2

    _draw_box(scr, by, bx, bh, bw, curses.A_BOLD)
    _draw_centered(scr, by + 1, f"◆  {name}  {art.strip()}", curses.A_BOLD)
    _draw_centered(scr, by + 2, "─" * (bw - 4))

    lines = [f'"{sentiment}"'] if sentiment else ["(no memory text)"]
    _draw_text_block(scr, by + 4, bx + 3, bw - 6, 3, lines, 0)
    _draw_centered(scr, by + bh - 2, "any key to return", curses.A_DIM)


def _draw_item_select(
    scr: curses.window, h: int, w: int,
    items: list[GardenGift], sel: int,
) -> None:
    """Overlay for choosing which garden item to examine."""
    bw = min(52, w - 4)
    bh = len(items) + 6
    bx = (w - bw) // 2
    by = (h - bh) // 2
    _draw_box(scr, by, bx, bh, bw, curses.A_BOLD)
    _draw_centered(scr, by + 1, "What would you like to examine?", curses.A_BOLD)
    _draw_centered(scr, by + 2, "─" * (bw - 4))
    for i, gift in enumerate(items):
        name, art = catalog_entry(gift.catalog_id)
        marker = "▸ " if i == sel else "  "
        attr = curses.A_BOLD if i == sel else 0
        _draw_centered(scr, by + 3 + i,
                       f"{marker}{art.strip()}  {name}", attr)
    _draw_centered(scr, by + bh - 2,
                   "↑/↓ select  ·  enter  ·  esc return", curses.A_DIM)


# ---------------------------------------------------------------------------
# Passphrase verification and content unlock
# ---------------------------------------------------------------------------

def _verify_passphrase(passphrase: str, bundle: Bundle, is_dev: bool) -> bool:
    if is_dev:
        return True
    try:
        return verify_bundle_hmac(bundle, passphrase)
    except (ValueError, TypeError):
        return False


def _unlock_content(
    passphrase: str,
    bundle: Bundle,
    is_dev: bool,
) -> tuple[list[tuple[str, str]], dict[str, str]]:
    """Return decrypted messages and gift sentiments after authentication."""
    if is_dev:
        return (
            [_decode_message(message) for message in bundle.messages],
            {
                gift.id: _b64decode(gift.sentiment_ciphertext)
                for gift in bundle.garden_gifts
            },
        )
    messages: list[tuple[str, str]] = []
    for message in bundle.messages:
        opened = open_message(passphrase, message)
        messages.append((opened.get("label", ""), opened.get("body", "")))
    gifts = {
        gift.id: open_gift_sentiment(passphrase, gift)
        for gift in bundle.garden_gifts
        if gift.sentiment_ciphertext
    }
    return messages, gifts


def _is_post_complete(bundle: Bundle, read_ids: set[str]) -> bool:
    """True when every message in the bundle has a read receipt."""
    return bool(bundle.messages) and all(
        msg.id in read_ids for msg in bundle.messages
    )


def _save_to_text(bundle: Bundle, msg: Message, label: str, body: str) -> Path:
    """Write a letter to ~/Desktop as plain text. Returns the saved path."""
    safe_author = "".join(
        c if c.isalnum() or c in " _-" else "_" for c in bundle.author_name
    ).strip().replace(" ", "_")
    filename = f"letter_from_{safe_author}_{msg.date}.txt"
    desktop = Path.home() / "Desktop"
    dest = (desktop if desktop.is_dir() else Path.home()) / filename
    lines: list[str] = [
        f"From: {bundle.author_name}",
        f"Date: {msg.date}",
    ]
    if label:
        lines.append(f"Subject: {label}")
    lines += ["", body, ""]
    dest.write_text("\n".join(lines), encoding="utf-8")
    return dest


def _compute_due(bundle: Bundle, today: date, read_ids: set[str]) -> list[int]:
    """Indices into bundle.messages for due, unread messages."""
    due = []
    for i, msg in enumerate(bundle.messages):
        try:
            msg_date = date.fromisoformat(msg.date)
        except ValueError:
            continue
        if today >= msg_date and msg.id not in read_ids:
            due.append(i)
    return due


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

_BIRD_FRAMES = [
    [r"  __     ", r" (  )>   ", r"  ^^  [✉]"],
    [r"  __     ", r" (  )>   ", r"  vv  [✉]"],
]


# ── Animal relationship system (§6.8.2) ──────────────────────────────────────

def _trust_tier(actions: int) -> int:
    """Map cumulative feed actions to trust tier 0–3."""
    tier = 0
    for t, threshold in enumerate((3, 7, 14)):
        if actions >= threshold:
            tier = t + 1
    return tier


# ASCII art per animal × trust tier.
# Tier 0: peeking from right edge.  Tiers 1–3: home position (inside garden).
_ANIMAL_ART: dict[str, dict[int, list[str]]] = {
    "cat": {
        0: ["/\\_ ", "o.  "],             # peeking from edge — 4 wide
        1: ["/\\_/\\", "(o.o)", " >^< "],  # curious sitting — 5 wide
        2: ["/\\_/\\", "(-.-)", " = = "],  # familiar settled — 5 wide
        3: ["/\\_/\\", "(zzz)", " ~_~ "],  # bonded napping — 5 wide
    },
    "bird": {
        0: [">-"],                         # distant silhouette — 2 wide
        1: [">o<", " | "],                # curious perch — 3 wide
        2: [">o<", "/|\\"],               # familiar perch — 3 wide
        3: ["(o)", "/|\\"],               # bonded settled — 3 wide
    },
    "rabbit": {
        0: ["(\\ "],                       # ears peeking — 3 wide
        1: ["(\\ /)", ".    "],            # shy, in garden — 4 wide
        2: ["(\\ /)", " . . "],            # present — 4 wide
        3: ["(\\./)","  z  "],             # napping — 5 wide
    },
    "turtle": {
        0: [" (~) "],                      # peeking head — 5 wide
        1: [" (~) ", "{__} "],             # walking — 5 wide
        2: [" (~) ", "{__} "],             # present — 5 wide
        3: ["(~o~)", "{__}"],              # home rock — 4 wide
    },
}

# Delivery art: bonded animal carries the letter (replaces letter-bird)
_ANIMAL_DELIVERY_FRAMES: dict[str, list[list[str]]] = {
    "cat": [
        [r"/\_/\  ", r"(>[✉])  "],
        [r"/\_/\  ", r"(=[✉])  "],
    ],
    "bird": [
        [r"  >o<   ", r" /|\    ", r" [✉]    "],
        [r"  >o<   ", r"  |\    ", r" [✉]    "],
    ],
    "rabbit": [
        [r"(\ /)  ", r".[✉].   "],
        [r"(\ /)  ", r" [✉]    "],
    ],
    "turtle": [
        [r" (~)    ", r"{[✉]}   "],
        [r" (~)    ", r"{[✉]}   "],
    ],
}

# Footprint chars shown near home position when recipient was absent
_ANIMAL_FOOTPRINTS: dict[str, str] = {
    "cat":    ". .",
    "bird":   "v v",
    "rabbit": ". .",
    "turtle": "---",
}

# Display names for status bar nudges
_ANIMAL_LABEL: dict[str, str] = {
    "cat": "cat", "bird": "bird", "rabbit": "rabbit", "turtle": "turtle",
}


def _find_animal_gift(bundle: Bundle) -> GardenGift | None:
    """Return the first animal-type gift in the bundle, or None."""
    for g in bundle.garden_gifts:
        if g.type == "animal":
            return g
    return None


def _animal_home_pos(animal_type: str, garden_seed: int, w: int, h: int
                     ) -> tuple[int, int]:
    """Stable (row, col) for the animal's home position (tiers 1–3)."""
    import random as _rnd
    rng = _rnd.Random(garden_seed ^ (hash(animal_type) & 0xFFFF_FFFF))
    row = h - 4
    col = min(w - 10, max(4, int(w * 0.25) + rng.randint(-6, 6)))
    return row, col


# UI state constants
_ST_GARDEN      = "garden"
_ST_PASSPHRASE  = "passphrase"
_ST_VERIFYING   = "verifying"
_ST_SELECTION   = "selection"       # select which due letter to read
_ST_READING     = "reading"
_ST_ARCHIVE     = "archive"
_ST_ITEM_SELECT = "item_select"     # select which garden item to examine
_ST_MEMORY      = "memory"          # viewing an item's sentiment
_ST_NO_LETTERS  = "no_letters"
_ST_CORRUPTED   = "corrupted"


def _item_position(
    gift: GardenGift, garden_seed: int, w: int, h: int
) -> tuple[int, int]:
    """Deterministic (row, col) for placing an item in the garden scene.

    Uses garden_seed XOR a hash of the gift id so each item lands in a
    stable, unique position that varies naturally across gardens.
    """
    import random as _rnd
    rng = _rnd.Random(garden_seed ^ (hash(gift.id) & 0xFFFF_FFFF))
    ground = h - 4
    if gift.placement_hint == "near_tallest_tree":
        col = min(w - 8, max(4, int(w * 0.6) + rng.randint(-4, 4)))
        row = ground - 1
    elif gift.placement_hint == "by_edge":
        left = rng.random() < 0.5
        col = rng.randint(2, 6) if left else rng.randint(w - 9, w - 5)
        row = ground
    else:
        col = min(w - 8, max(4, rng.randint(int(w * 0.15), int(w * 0.85))))
        row = ground
    return max(0, min(row, h - 3)), max(0, col)


def run_recipient(
    stdscr: curses.window,
    bundle: Bundle,
    store: RecipientStore,
    season: str | None = None,
    is_dev_fixture: bool = False,
    corrupted: bool = False,
) -> None:
    """Run the recipient garden loop with a loaded bundle."""
    init_curses_colors()
    curses.curs_set(0)
    stdscr.nodelay(True)
    stdscr.timeout(50)

    h, w = stdscr.getmaxyx()
    renderer = GardenRenderer(w, h, bundle.garden_seed, season=season)

    today = date.today()
    read_ids: set[str] = store.read_set()
    total_visits = store.total_visits()

    # Decode message content (dev fixtures only)
    msg_content: list[tuple[str, str]] = [
        _decode_message(m) if is_dev_fixture
        else ("", "")
        for m in bundle.messages
    ]
    gift_content: dict[str, str] = (
        {
            gift.id: _b64decode(gift.sentiment_ciphertext)
            for gift in bundle.garden_gifts
        }
        if is_dev_fixture else {}
    )

    state = _ST_CORRUPTED if corrupted else _ST_GARDEN
    authenticated = False
    passphrase_buf = ""
    passphrase_error = ""
    verify_start = 0.0

    bird_visible = False
    bird_x = -10
    bird_y = 3
    bird_frame = 0
    bird_perched = False

    selection_idx = 0
    reading_msg_idx = 0
    reading_scroll = 0

    archive_rows: list[_ArchiveRow] = []
    archive_sel = 0
    archive_scroll = 0

    memory_gift: GardenGift | None = None
    memory_return_state: str = _ST_ARCHIVE  # where esc goes after viewing a memory

    unread_due: list[int] = []
    triggered_items: list[GardenGift] = []  # items/landmarks whose trigger is met
    item_sel = 0  # cursor for _ST_ITEM_SELECT
    post_complete = False  # all messages read (§6.7)
    save_flash_msg = ""    # brief save-to-text confirmation in status bar
    save_flash_timer = 0.0

    # Animal relationship state (§6.8.2)
    animal_gift: GardenGift | None = _find_animal_gift(bundle)
    animal_type: str | None = None
    animal_tier: int = 0
    animal_triggered: bool = False
    delivery_animal: str | None = None  # set at auth if bonded
    feed_flash_msg = ""
    feed_flash_timer = 0.0
    if animal_gift is not None:
        animal_type = animal_gift.catalog_id
        a_st = store.get_animal_state(animal_type)
        animal_tier = _trust_tier(a_st.get("trust_actions", 0))
        animal_triggered = is_gift_triggered(
            animal_gift, today, total_visits, read_ids
        )

    # First-run welcome (§6.5)
    first_run_timer = 0.0
    welcome_visible = False
    welcome_done = False

    while True:
        nh, nw = stdscr.getmaxyx()
        if (nh, nw) != (h, w):
            h, w = nh, nw
            renderer.resize(w, h)

        stdscr.erase()
        renderer.tick()

        # Dim garden when any overlay is active
        if state != _ST_GARDEN:
            buf = renderer.buf
            for row in range(buf.height - 1):
                for col in range(buf.width):
                    ch, _ = buf.get(row, col)
                    try:
                        stdscr.addstr(row, col, ch, curses.A_DIM)
                    except curses.error:
                        pass
        else:
            renderer.blit_curses(stdscr)
            if renderer.state.flash_frames > 0:
                try:
                    curses.flash()
                except curses.error:
                    pass
            # Draw triggered garden items in the scene
            for gift in triggered_items:
                grow, gcol = _item_position(gift, bundle.garden_seed, w, h)
                _, art = catalog_entry(gift.catalog_id)
                try:
                    stdscr.addstr(grow, gcol, art.strip(), curses.A_BOLD)
                except curses.error:
                    pass

            # Draw animal relationship (§6.8.2)
            if animal_type and animal_triggered and not (bird_visible and delivery_animal == animal_type):
                _art_tiers = _ANIMAL_ART.get(animal_type, {})
                _art_lines = _art_tiers.get(animal_tier, _art_tiers.get(0, []))
                if _art_lines:
                    if animal_tier == 0:
                        # Tier 0: peek from right edge, occasional appearance
                        if (renderer.state.frame // 60) % 3 == 0:
                            _a_row = h - 4
                            _a_col = w - len(_art_lines[0]) - 1
                            for _i, _ln in enumerate(_art_lines):
                                try:
                                    stdscr.addstr(_a_row + _i, max(0, _a_col),
                                                  _ln, curses.A_BOLD)
                                except curses.error:
                                    pass
                    else:
                        _a_row, _a_col = _animal_home_pos(
                            animal_type, bundle.garden_seed, w, h
                        )
                        # Footprints: evidence of visits while absent (§6.8.2)
                        if store.was_absent:
                            _fp = _ANIMAL_FOOTPRINTS.get(animal_type, "...")
                            try:
                                stdscr.addstr(
                                    _a_row + len(_art_lines),
                                    max(0, _a_col), _fp, curses.A_DIM,
                                )
                            except curses.error:
                                pass
                        for _i, _ln in enumerate(_art_lines):
                            try:
                                stdscr.addstr(
                                    _a_row + _i,
                                    max(0, min(_a_col, w - len(_ln) - 1)),
                                    _ln, curses.A_BOLD,
                                )
                            except curses.error:
                                pass

            # Post-completion: memorial flower + bonded animal perch (§6.7, §6.8.8)
            if post_complete:
                import random as _rnd
                _rng = _rnd.Random(bundle.garden_seed ^ 0xF100)
                fc = max(4, min(w - 6, int(w * 0.45) + _rng.randint(-8, 8)))
                try:
                    stdscr.addstr(h - 4, fc, "✿", curses_attr("magenta"))
                except curses.error:
                    pass
                if animal_type and animal_tier >= 3:
                    # Bonded animal perches permanently (§6.8.8)
                    _pc_lines = _ANIMAL_ART.get(animal_type, {}).get(3, [])
                    _pc_row, _pc_col = _animal_home_pos(
                        animal_type, bundle.garden_seed, w, h
                    )
                    for _i, _ln in enumerate(_pc_lines):
                        try:
                            stdscr.addstr(
                                _pc_row + _i,
                                max(0, min(_pc_col, w - len(_ln) - 1)),
                                _ln, curses.A_BOLD,
                            )
                        except curses.error:
                            pass
                else:
                    # Fallback: static letter-bird perch
                    perch_art = [r"  __  ", r" (  ) ", r"  ^^  "]
                    for i, line in enumerate(perch_art):
                        try:
                            stdscr.addstr(2 + i, max(0, w // 4), line, curses.A_BOLD)
                        except curses.error:
                            pass

        # First-run welcome message
        if not welcome_done and state == _ST_GARDEN:
            now = time.monotonic()
            if first_run_timer == 0.0:
                first_run_timer = now
            elapsed = now - first_run_timer
            if elapsed > 3.0:
                welcome_visible = True
            if elapsed > 12.0:
                welcome_done = True
                welcome_visible = False
            if welcome_visible:
                _draw_centered(
                    stdscr, h // 2,
                    f"This garden was planted for you by {bundle.author_name}.",
                    curses.A_BOLD,
                )

        # Letter delivery animation (letter-bird or bonded animal)
        if bird_visible and state == _ST_GARDEN:
            if not bird_perched:
                bird_x += 1
                if bird_x > w // 3:
                    bird_perched = True
                    bird_y = 2
                bird_frame += 1
            if delivery_animal and delivery_animal in _ANIMAL_DELIVERY_FRAMES:
                _del_frames = _ANIMAL_DELIVERY_FRAMES[delivery_animal]
            else:
                _del_frames = _BIRD_FRAMES
            art = _del_frames[bird_frame % len(_del_frames)]
            bx = max(0, bird_x)
            for i, line in enumerate(art):
                try:
                    stdscr.addstr(bird_y + i, bx, line, curses.A_BOLD)
                except curses.error:
                    pass

        # ── Overlays ──────────────────────────────────────────────────────

        if state == _ST_CORRUPTED:
            _draw_centered(stdscr, h // 2 - 1,
                           "This file appears damaged.", curses.A_BOLD)
            _draw_centered(stdscr, h // 2 + 1,
                           "The letters inside may not be readable.",
                           curses.A_DIM)

        elif state == _ST_PASSPHRASE:
            _draw_passphrase(
                stdscr, h, w,
                bundle.author_name, bundle.passphrase_hint,
                passphrase_buf, passphrase_error,
            )

        elif state == _ST_VERIFYING:
            spinner = ["|", "/", "-", "\\"]
            idx = int((time.monotonic() - verify_start) * 4) % 4
            _draw_centered(stdscr, h // 2,
                           f"  Verifying… {spinner[idx]}  ", curses.A_BOLD)

        elif state == _ST_NO_LETTERS:
            _draw_centered(stdscr, h // 2, "No letters today.", curses.A_BOLD)
            _draw_centered(stdscr, h // 2 + 2,
                           "This garden is yours. Come back anytime.",
                           curses.A_DIM)

        elif state == _ST_SELECTION:
            _draw_selection(stdscr, h, w, bundle, unread_due, selection_idx)

        elif state == _ST_READING:
            label, body = msg_content[reading_msg_idx]
            _draw_reading(
                stdscr, h, w,
                bundle.author_name, label, body, reading_scroll,
            )

        elif state == _ST_ARCHIVE:
            _draw_archive(
                stdscr, h, w, bundle,
                archive_rows, archive_sel, archive_scroll,
                read_ids, store, today, msg_content,
            )

        elif state == _ST_ITEM_SELECT:
            _draw_item_select(stdscr, h, w, triggered_items, item_sel)

        elif state == _ST_MEMORY and memory_gift is not None:
            _draw_memory(
                stdscr, h, w, memory_gift,
                gift_content.get(memory_gift.id, ""),
            )

        # ── Status bar ────────────────────────────────────────────────────

        if state == _ST_GARDEN:
            seed = bundle.garden_seed
            # Animal nudge overrides the whole bar at tier 0 (§6.8.2)
            _animal_nudge = ""
            if animal_type and animal_triggered and authenticated:
                _alabel = _ANIMAL_LABEL.get(animal_type, animal_type)
                _aname = (animal_gift.animal_name or _alabel) if animal_gift else _alabel
                if animal_tier == 0:
                    _animal_nudge = (
                        f"a stray {_alabel} lingers at the edge… "
                        f"press f to leave food"
                    )
                elif animal_tier < 3:
                    _animal_nudge = f"f · feed {_aname}"
            if _animal_nudge:
                bar = f"  {_animal_nudge}"
            elif not authenticated:
                bar = f"  seed={seed}  q=quit  · e · unlock letters"
            elif post_complete:
                parts = [f"  seed={seed}  q=quit"]
                if triggered_items:
                    parts.append("i · examine")
                parts.append("l · your letters")
                bar = "  ·  ".join(parts)
            else:
                parts = [f"  seed={seed}  q=quit"]
                if unread_due:
                    n = len(unread_due)
                    lbl = "a letter has arrived" if n == 1 else f"{n} letters have arrived"
                    parts.append(f"e · {lbl}")
                if triggered_items:
                    parts.append("i · examine")
                parts.append("l · your letters")
                bar = "  ·  ".join(parts)
        elif state == _ST_PASSPHRASE:
            bar = "  enter passphrase  ·  esc cancel"
        elif state == _ST_READING:
            if save_flash_msg and time.monotonic() - save_flash_timer < 3.0:
                bar = f"  {save_flash_msg}"
            else:
                save_flash_msg = ""
                bar = "  j/↓ scroll  ·  k/↑ scroll  ·  p · save  ·  esc return"
        elif state == _ST_MEMORY:
            bar = "  j/↓ scroll  ·  k/↑ scroll  ·  esc return"
        elif state in (_ST_SELECTION, _ST_ARCHIVE, _ST_ITEM_SELECT):
            bar = "  ↑/↓ navigate  ·  enter open  ·  esc return"
        elif state == _ST_CORRUPTED:
            bar = "  q quit"
        else:
            bar = "  esc return"

        try:
            stdscr.addstr(h - 1, 0, bar[:w].ljust(w), curses.A_REVERSE)
        except curses.error:
            pass

        stdscr.refresh()

        # ── Input ─────────────────────────────────────────────────────────

        key = stdscr.getch()

        if state == _ST_VERIFYING:
            if time.monotonic() - verify_start > 1.5:
                ok = _verify_passphrase(passphrase_buf, bundle, is_dev_fixture)
                if ok:
                    try:
                        msg_content, gift_content = _unlock_content(
                            passphrase_buf, bundle, is_dev_fixture,
                        )
                    except Exception:
                        ok = False
                if ok:
                    authenticated = True
                    passphrase_buf = ""
                    passphrase_error = ""
                    read_ids = store.read_set()
                    unread_due = _compute_due(bundle, today, read_ids)
                    post_complete = _is_post_complete(bundle, read_ids)
                    triggered_items = [
                        g for g in bundle.garden_gifts
                        if g.type in ("item", "landmark")
                        and (post_complete or is_gift_triggered(
                            g, today, total_visits, read_ids))
                    ]
                    # Re-evaluate animal trigger (post_letter trigger may now fire)
                    if animal_gift is not None and animal_type is not None:
                        animal_triggered = is_gift_triggered(
                            animal_gift, today, total_visits, read_ids
                        )
                    if unread_due:
                        bird_visible = True
                        bird_x = -10
                        bird_perched = False
                        # Bonded animal delivers instead of letter-bird (§6.8.2)
                        delivery_animal = (
                            animal_type
                            if animal_type and animal_triggered and animal_tier >= 3
                            else None
                        )
                        state = _ST_GARDEN
                    else:
                        state = _ST_NO_LETTERS
                else:
                    passphrase_error = (
                        "Incorrect passphrase, or this file has been modified."
                    )
                    passphrase_buf = ""
                    state = _ST_PASSPHRASE
            continue

        if state == _ST_CORRUPTED:
            if key == ord("q"):
                break
            continue

        if state == _ST_NO_LETTERS:
            if key in (27, ord("q")):
                state = _ST_GARDEN
            continue

        if key == -1:
            continue

        # Garden
        if state == _ST_GARDEN:
            if key == ord("q"):
                break
            elif key == ord("e"):
                # e = envelope: unlock / open due letters
                if not authenticated:
                    state = _ST_PASSPHRASE
                    passphrase_buf = ""
                    passphrase_error = ""
                elif unread_due:
                    if len(unread_due) == 1:
                        reading_msg_idx = unread_due[0]
                        reading_scroll = 0
                        state = _ST_READING
                    else:
                        selection_idx = 0
                        state = _ST_SELECTION
            elif key == ord("i") and authenticated and triggered_items:
                # i = interact: examine a garden item
                if len(triggered_items) == 1:
                    memory_gift = triggered_items[0]
                    store.mark_discovered(memory_gift.id)
                    memory_return_state = _ST_GARDEN
                    state = _ST_MEMORY
                else:
                    item_sel = 0
                    state = _ST_ITEM_SELECT
            elif key == ord("f") and authenticated and animal_type and animal_triggered and animal_tier < 3:
                # f = feed: advance animal trust (§6.8.2)
                animal_tier = store.feed_animal(animal_type)
            elif key == ord("l") and authenticated:
                archive_rows = _build_archive_rows(
                    bundle, today, total_visits, read_ids
                )
                archive_sel = 0
                archive_scroll = 0
                state = _ST_ARCHIVE

        # Passphrase entry
        elif state == _ST_PASSPHRASE:
            if key == 27:
                state = _ST_GARDEN
            elif key in (10, 13):
                verify_start = time.monotonic()
                state = _ST_VERIFYING
            elif key in (curses.KEY_BACKSPACE, 127, 8):
                passphrase_buf = passphrase_buf[:-1]
                passphrase_error = ""
            elif 32 <= key < 127:
                passphrase_buf += chr(key)
                passphrase_error = ""

        # Letter selection
        elif state == _ST_SELECTION:
            if key == 27:
                state = _ST_GARDEN
            elif key in (curses.KEY_UP, ord("k")):
                selection_idx = max(0, selection_idx - 1)
            elif key in (curses.KEY_DOWN, ord("j")):
                selection_idx = min(len(unread_due) - 1, selection_idx + 1)
            elif key in (10, 13):
                reading_msg_idx = unread_due[selection_idx]
                reading_scroll = 0
                state = _ST_READING

        # Letter reading
        elif state == _ST_READING:
            if key in (27, ord("q")):
                store.mark_read(bundle.messages[reading_msg_idx].id)
                read_ids = store.read_set()
                unread_due = _compute_due(bundle, today, read_ids)
                post_complete = _is_post_complete(bundle, read_ids)
                # Post-letter triggers (and post-completion unlock) may now fire
                triggered_items = [
                    g for g in bundle.garden_gifts
                    if g.type in ("item", "landmark")
                    and (post_complete or is_gift_triggered(
                        g, today, total_visits, read_ids))
                ]
                # Animal trigger may also fire on post_letter
                if animal_gift is not None and animal_type is not None:
                    animal_triggered = post_complete or is_gift_triggered(
                        animal_gift, today, total_visits, read_ids
                    )
                if unread_due:
                    selection_idx = 0
                    state = _ST_SELECTION
                else:
                    bird_visible = False
                    state = _ST_GARDEN
            elif key == ord("p"):
                label, body = msg_content[reading_msg_idx]
                try:
                    dest = _save_to_text(
                        bundle, bundle.messages[reading_msg_idx], label, body
                    )
                    save_flash_msg = f"Saved to {dest.name}"
                except OSError:
                    save_flash_msg = "Could not save — check Desktop permissions"
                save_flash_timer = time.monotonic()
            elif key in (curses.KEY_DOWN, ord("j")):
                reading_scroll += 1
            elif key in (curses.KEY_UP, ord("k")):
                reading_scroll = max(0, reading_scroll - 1)

        # Archive navigation
        elif state == _ST_ARCHIVE:
            sel_indices = _selectable(archive_rows)
            n_visible = min(len(archive_rows), 14)
            if key == 27:
                state = _ST_GARDEN
            elif key in (curses.KEY_UP, ord("k")):
                if archive_sel > 0:
                    archive_sel -= 1
                    archive_scroll = _clamp_scroll(
                        archive_sel, sel_indices, archive_scroll, n_visible
                    )
            elif key in (curses.KEY_DOWN, ord("j")):
                if archive_sel < len(sel_indices) - 1:
                    archive_sel += 1
                    archive_scroll = _clamp_scroll(
                        archive_sel, sel_indices, archive_scroll, n_visible
                    )
            elif key in (10, 13) and sel_indices:
                sel_row = archive_rows[sel_indices[archive_sel]]
                if sel_row[0] == "letter":
                    reading_msg_idx = sel_row[1]
                    reading_scroll = 0
                    state = _ST_READING
                elif sel_row[0] == "gift":
                    memory_gift = sel_row[2]
                    store.mark_discovered(memory_gift.id)
                    memory_return_state = _ST_ARCHIVE
                    state = _ST_MEMORY

        # Item selection (multiple items in garden)
        elif state == _ST_ITEM_SELECT:
            if key == 27:
                state = _ST_GARDEN
            elif key in (curses.KEY_UP, ord("k")):
                item_sel = max(0, item_sel - 1)
            elif key in (curses.KEY_DOWN, ord("j")):
                item_sel = min(len(triggered_items) - 1, item_sel + 1)
            elif key in (10, 13) and triggered_items:
                memory_gift = triggered_items[item_sel]
                store.mark_discovered(memory_gift.id)
                memory_return_state = _ST_GARDEN
                state = _ST_MEMORY

        # Memory viewing — any key returns to wherever we came from
        elif state == _ST_MEMORY:
            state = memory_return_state


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run_recipient_file(path: str | Path, season: str | None = None) -> None:
    """Load a .lateletter file and run the recipient experience.

    Called from garden.py when a file argument is provided.
    """
    fpath = Path(path)
    if not fpath.exists():
        print(f"  Error: file not found: {fpath}")
        raise SystemExit(1)

    try:
        bundle = read_bundle(fpath)
    except Exception as exc:
        print(f"  Error: could not read bundle: {exc}")
        raise SystemExit(1)

    checksum_ok = verify_checksum(bundle)
    is_dev_fixture = not bundle.hmac  # dev fixtures have no HMAC set

    store = RecipientStore(bundle.bundle_id)
    store.increment_visit()

    curses.wrapper(
        run_recipient, bundle, store, season, is_dev_fixture, not checksum_ok
    )
