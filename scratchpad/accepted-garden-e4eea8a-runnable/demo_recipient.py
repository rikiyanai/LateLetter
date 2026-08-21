#!/usr/bin/env python3
"""
demo_recipient.py — LateLetter recipient arc demo harness (§24 step 11a Part B).

Simulates the complete recipient emotional arc in one sitting using the real
recipient module with a pre-configured dev fixture bundle and seeded store state.

Each --arc segment maps to one of the five §6.9 emotional moments:

  waiting      → Moment 1: The waiting  (garden alive, no delivery prompt)
  delivery     → Moment 2: The delivery (bird flies in, letter ready)
  trust1       → Moment 3: Animal trust arc — tier 1 (animal visits, keeps distance)
  trust2       → Moment 3: Animal trust arc — tier 2 (approaches, can be fed)
  trust3       → Moment 3: Animal trust arc — tier 3 (bonded, stays)
  postcomplete → Moment 4: Post-completion (memorial flower, permanent bird)
  item         → Moment 5: Item discovery (gift in garden, memory overlay)

Usage:
  python3 demo_recipient.py                       # default: waiting arc
  python3 demo_recipient.py --arc delivery
  python3 demo_recipient.py --arc trust2 --season summer
  python3 demo_recipient.py --arc postcomplete
  python3 demo_recipient.py --arc delivery --browser    # generate fixture + URL
  python3 demo_recipient.py --arc all --browser         # generate all fixtures
"""

import argparse
import base64
import json
import os
import sys
import uuid
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / 'src'))

from lateletter.bundle import Bundle, GardenGift, Message, Notification, Trigger

# ---------------------------------------------------------------------------
# Demo bundle constants
# ---------------------------------------------------------------------------

DEMO_BUNDLE_ID = "demo-arc-00000000-0000-0000-0000-000000000001"
DEMO_AUTHOR    = "Robert"
DEMO_RECIPIENT = "Maya"
DEMO_HINT      = "The name of our first dog"
DEMO_PASSPHRASE = "biscuit"  # dev fixtures accept any passphrase

MSG_ID_1 = "demo-msg-0001"
MSG_ID_2 = "demo-msg-0002"
MSG_ID_3 = "demo-msg-0003"
GIFT_ANIMAL_ID = "demo-gift-animal"
GIFT_ITEM_ID   = "demo-gift-item"

_RECEIPT_DIR   = Path.home() / ".lateletter" / "recipient"
_RECEIPTS_FILE = _RECEIPT_DIR / "receipts.json"
_GARDEN_FILE   = _RECEIPT_DIR / "garden_state.json"

ARCS = ["waiting", "delivery", "trust1", "trust2", "trust3", "postcomplete", "item"]


# ---------------------------------------------------------------------------
# Message bodies
# ---------------------------------------------------------------------------

_BODY_1 = (
    "Dear Maya,\n\n"
    "Thirty years. I remember the day you were born like it was\n"
    "last week — your mother's face, the way you grabbed my finger\n"
    "and wouldn't let go. You still haven't, not really.\n\n"
    "I won't pretend I'm not sad to miss this one. But I want you\n"
    "to know something: every single day I got with you was a gift.\n"
    "Not the kind you wrap — the kind that rewires your whole heart.\n\n"
    "You are brave and funny and stubborn in the best way. You got\n"
    "that from your mother. (Don't tell her I said the stubborn part.)\n\n"
    "Happy birthday, kid. I'm so proud of who you are.\n\n"
    "Love always,\nDad"
)

_BODY_2 = (
    "Dear Maya,\n\n"
    "I know today might be hard. Our kitchen always smelled like\n"
    "cinnamon and burned pie crust by noon — I never did figure out\n"
    "the oven timer. You'd sit on the counter and 'supervise,' which\n"
    "meant eating all the chocolate chips.\n\n"
    "I want you to make something today. Anything. Even toast.\n"
    "Stand in the kitchen and let it smell like something warm.\n\n"
    "I'm not gone from that kitchen, not really. Every time you\n"
    "burn something and laugh about it, that's me.\n\n"
    "Merry Christmas, sweetheart.\n\nDad"
)

_BODY_3 = (
    "Dear Maya,\n\n"
    "There's no occasion today. That's the point.\n\n"
    "I wanted you to know that I think about ordinary days the most.\n"
    "Not the birthdays or the holidays — the Tuesdays. The ones\n"
    "where we walked Biscuit around the block and didn't say much\n"
    "and it was perfect.\n\n"
    "I hope you're having a good ordinary day. I hope the weather\n"
    "is nice where you are. I hope someone made you laugh today.\n\n"
    "That's all. Just wanted to say hi.\n\nLove,\nDad"
)

_SENTIMENT_ANIMAL = (
    "I left a rabbit in your garden. She was always cautious, but patient.\n"
    "Give her time. She'll come close."
)

_SENTIMENT_ITEM = (
    "I used to plant bulbs in autumn so you'd have something to look\n"
    "forward to in spring. This one took longer to bloom. I hope it\n"
    "was worth the wait."
)


# ---------------------------------------------------------------------------
# Bundle construction
# ---------------------------------------------------------------------------

def _enc(label: str, body: str) -> str:
    """Encode message content as base64 JSON (dev fixture format)."""
    return base64.b64encode(json.dumps({"label": label, "body": body}).encode()).decode()


def _enc_sentiment(text: str) -> str:
    """Encode gift sentiment as base64 plaintext (dev fixture)."""
    return base64.b64encode(text.encode()).decode()


def build_arc_bundle(arc: str) -> Bundle:
    """Build a dev fixture Bundle configured for the given arc segment."""
    today = date.today()
    yesterday = (today - timedelta(days=1)).isoformat()
    far = "2030-01-01"
    past = "2020-01-01"

    # Message dates per arc
    if arc == "waiting":
        d1, d2, d3 = far, far, far
    elif arc == "delivery":
        d1, d2, d3 = yesterday, far, far
    elif arc in ("trust1", "trust2", "trust3"):
        d1, d2, d3 = past, past, past
    elif arc == "postcomplete":
        d1, d2, d3 = past, past, past
    elif arc == "item":
        d1, d2, d3 = yesterday, far, far
    else:
        d1, d2, d3 = far, far, far

    messages = [
        Message(
            id=MSG_ID_1,
            date=d1,
            ciphertext=_enc("For your 30th birthday", _BODY_1),
        ),
        Message(
            id=MSG_ID_2,
            date=d2,
            ciphertext=_enc("That first Christmas", _BODY_2),
        ),
        Message(
            id=MSG_ID_3,
            date=d3,
            ciphertext=_enc("Just an ordinary Tuesday", _BODY_3),
        ),
    ]

    # Animal gift: triggered at cumulative_visits >= 1 for delivery/trust/item,
    # or date-triggered in the past for postcomplete
    if arc in ("waiting", "delivery"):
        animal_trigger = Trigger(type="cumulative_visits", value="1")
    elif arc in ("trust1", "trust2", "trust3", "postcomplete"):
        animal_trigger = Trigger(type="date", value=past)
    else:  # item
        animal_trigger = Trigger(type="cumulative_visits", value="1")

    # Item gift: triggered at date=yesterday for item/delivery arcs
    if arc in ("item", "postcomplete"):
        item_trigger = Trigger(type="date", value=yesterday)
    else:
        item_trigger = Trigger(type="date", value=far)

    garden_gifts = [
        GardenGift(
            id=GIFT_ANIMAL_ID,
            type="animal",
            catalog_id="rabbit",
            trigger=animal_trigger,
            placement_hint="random",
            sentiment_ciphertext=_enc_sentiment(_SENTIMENT_ANIMAL),
        ),
        GardenGift(
            id=GIFT_ITEM_ID,
            type="item",
            catalog_id="plate_of_food",
            trigger=item_trigger,
            placement_hint="random",
            sentiment_ciphertext=_enc_sentiment(_SENTIMENT_ITEM),
        ),
    ]

    return Bundle(
        bundle_id=DEMO_BUNDLE_ID,
        author_name=DEMO_AUTHOR,
        passphrase_hint=DEMO_HINT,
        bundle_auth_salt=base64.b64encode(b"demo-arc-salt---").decode(),
        garden_seed=42301,
        messages=messages,
        garden_gifts=garden_gifts,
        notification=Notification(),
        checksum="",
        hmac="",
    )


# ---------------------------------------------------------------------------
# Store state seeding
# ---------------------------------------------------------------------------

def _load_json(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            pass
    return {}


def _save_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    os.replace(tmp, path)


def seed_store(arc: str, bundle: Bundle) -> None:
    """Seed RecipientStore state for the given arc."""
    _RECEIPT_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)

    receipts = _load_json(_RECEIPTS_FILE)
    garden   = _load_json(_GARDEN_FILE)

    bid    = bundle.bundle_id
    today  = date.today().isoformat()
    past   = "2020-01-01"
    msgs   = bundle.messages
    animal = next((g for g in bundle.garden_gifts if g.type == "animal"), None)
    atype  = animal.catalog_id if animal else None

    # Reset this bundle's slot
    receipts[bid] = {}
    garden[bid] = {
        "total_visits": 0,
        "last_visit": None,
        "discovered_items": [],
        "animals": {},
    }

    if arc == "waiting":
        garden[bid]["total_visits"] = 1
        garden[bid]["last_visit"] = today

    elif arc == "delivery":
        garden[bid]["total_visits"] = 1
        garden[bid]["last_visit"] = today
        # animal trigger is cumulative_visits>=1, so it fires automatically on load

    elif arc in ("trust1", "trust2", "trust3"):
        tier_map = {"trust1": 1, "trust2": 2, "trust3": 3}
        action_map = {1: 3, 2: 7, 3: 14}
        tier    = tier_map[arc]
        actions = action_map[tier]
        garden[bid]["total_visits"] = 10
        garden[bid]["last_visit"] = today
        # All messages already read
        for m in msgs:
            receipts[bid][m.id] = {"read_at": past}
        # Animal triggered and at right trust level
        if animal:
            garden[bid]["discovered_items"].append(animal.id)
            if atype:
                garden[bid]["animals"][atype] = {
                    "trust_actions": actions,
                    "trust_tier": tier,
                    "last_fed": None,
                }

    elif arc == "postcomplete":
        garden[bid]["total_visits"] = 15
        garden[bid]["last_visit"] = today
        # All messages read
        for m in msgs:
            receipts[bid][m.id] = {"read_at": past}
        # All gifts triggered
        for g in bundle.garden_gifts:
            if g.id not in garden[bid]["discovered_items"]:
                garden[bid]["discovered_items"].append(g.id)
        # Animal bonded (tier 3)
        if atype:
            garden[bid]["animals"][atype] = {
                "trust_actions": 14,
                "trust_tier": 3,
                "last_fed": None,
            }

    elif arc == "item":
        garden[bid]["total_visits"] = 5
        garden[bid]["last_visit"] = today
        # First letter read already
        for m in msgs:
            if m.date <= today:
                receipts[bid][m.id] = {"read_at": today}
        # Non-animal gifts triggered (item shows in garden)
        for g in bundle.garden_gifts:
            if g.type != "animal":
                if g.id not in garden[bid]["discovered_items"]:
                    garden[bid]["discovered_items"].append(g.id)

    _save_json(_RECEIPTS_FILE, receipts)
    _save_json(_GARDEN_FILE, garden)


# ---------------------------------------------------------------------------
# Terminal (curses) launch
# ---------------------------------------------------------------------------

def run_terminal(arc: str, season: str | None, bundle: Bundle) -> None:
    """Seed state and launch the real recipient module in the terminal."""
    import curses
    from lateletter.recipient import RecipientStore, run_recipient

    seed_store(arc, bundle)

    store = RecipientStore(bundle.bundle_id)
    # increment_visit() is called inside run_recipient; we already seeded
    # total_visits — skip auto-increment so the count stays at the seeded value.
    # We do this by marking last_visit as today so increment_visit still runs
    # (it adds 1, which is fine — our seeded count accounts for that).

    is_dev = True  # dev fixture — any passphrase accepted

    print(f"\n  LateLetter — Demo Harness (arc: {arc})")
    print(f"  {'─' * 40}")
    _print_arc_hint(arc)
    print(f"\n  Passphrase: {DEMO_PASSPHRASE}  (any passphrase works in dev mode)")
    print(f"  Season override: {season or '(auto)'}")
    print(f"\n  Press Enter to open the garden…\n")
    input()

    curses.wrapper(run_recipient, bundle, store, season=season, is_dev_fixture=is_dev)


def _print_arc_hint(arc: str) -> None:
    hints = {
        "waiting":      "§6.9 Moment 1 — The waiting. Garden is alive; no letters yet. Watch for 2 min.",
        "delivery":     "§6.9 Moment 2 — The delivery. Press 'e' to unlock, bird will arrive.",
        "trust1":       "§6.9 Moment 3 — Animal trust tier 1. Rabbit visits but keeps distance.",
        "trust2":       "§6.9 Moment 3 — Animal trust tier 2. Rabbit approaches; press 'f' to feed.",
        "trust3":       "§6.9 Moment 3 — Animal trust tier 3. Bonded. Rabbit stays.",
        "postcomplete": "§6.9 Moment 4 — Post-completion. All letters read; memorial garden state.",
        "item":         "§6.9 Moment 5 — Item discovery. Press 'i' to examine the gift in the garden.",
    }
    print(f"  {hints.get(arc, arc)}")


# ---------------------------------------------------------------------------
# Browser fixture generation
# ---------------------------------------------------------------------------

def run_browser(arc: str, season: str | None, bundle: Bundle) -> None:
    """Generate a dev fixture .lateletter file and print the browser URL."""
    viewer_path = Path(__file__).resolve().parent / "viewer-bnw.html"
    out_path = Path(f"/tmp/lateletter_demo_{arc}.lateletter")

    bundle_dict = bundle.to_dict()
    out_path.write_text(json.dumps(bundle_dict, indent=2))

    params = []
    if season:
        params.append(f"season={season}")
    if arc != "waiting":
        params.append(f"arc={arc}")

    qs = ("?" + "&".join(params)) if params else ""
    url = f"file://{viewer_path}{qs}"

    print(f"\n  LateLetter — Browser Demo Fixture (arc: {arc})")
    print(f"  {'─' * 48}")
    _print_arc_hint(arc)
    print(f"\n  Bundle:  {out_path}")
    print(f"  URL:     {url}")
    print(f"\n  Steps:")
    print(f"  1. Open the URL in your browser")
    print(f"  2. Drag-and-drop the bundle file onto the garden page")
    print(f"  3. Enter any passphrase (dev mode — passphrase is not checked)")
    if arc != "postcomplete":
        print(f"  4. Watch for §6.9 Moment {_arc_moment(arc)}")
    print()


def _arc_moment(arc: str) -> str:
    return {"waiting": "1", "delivery": "2",
            "trust1": "3", "trust2": "3", "trust3": "3",
            "postcomplete": "4", "item": "5"}.get(arc, "?")


# ---------------------------------------------------------------------------
# All-arcs batch mode
# ---------------------------------------------------------------------------

def run_all_browser(season: str | None) -> None:
    """Generate fixtures for every arc and print all URLs."""
    print(f"\n  LateLetter — All-Arc Browser Fixtures")
    print(f"  {'─' * 40}")
    for arc in ARCS:
        bundle = build_arc_bundle(arc)
        run_browser(arc, season, bundle)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(
        description="LateLetter recipient arc demo harness (§24 step 11a Part B)"
    )
    ap.add_argument(
        "--arc",
        choices=ARCS + ["all"],
        default="waiting",
        help="Emotional arc segment to demo (default: waiting)",
    )
    ap.add_argument(
        "--season",
        choices=["spring", "summer", "autumn", "winter"],
        default=None,
        help="Force season (default: auto from system clock)",
    )
    ap.add_argument(
        "--browser",
        action="store_true",
        help="Generate browser fixture + URL instead of launching curses",
    )
    ap.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Override garden seed (default: arc-appropriate value)",
    )
    args = ap.parse_args()

    if args.arc == "all":
        if args.browser:
            run_all_browser(args.season)
        else:
            ap.error("--arc all is only supported with --browser")
        return

    bundle = build_arc_bundle(args.arc)
    if args.seed is not None:
        bundle.garden_seed = args.seed

    if args.browser:
        run_browser(args.arc, args.season, bundle)
    else:
        run_terminal(args.arc, args.season, bundle)


if __name__ == "__main__":
    main()
