#!/usr/bin/env python3
"""
demo_author.py — LateLetter author e2e demo (§24 step 11a Part C).

Runs the complete author flow with pre-filled answers in ≤60 seconds of
wall time, producing a valid demo_output.lateletter that the recipient demo
harness (demo_recipient.py) can immediately open.

Flow demonstrated:
  consent → intake → Q&A (3 questions) → draft editor bypass → export

Produces:
  ./demo_output.lateletter    — ready for demo_recipient.py to open

Usage:
  python3 demo_author.py
  python3 demo_author.py --quiet    # suppress progress messages
  python3 demo_author.py --out /tmp/my_demo.lateletter
"""

import argparse
import sys
import time
import uuid
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / 'src'))

from lateletter.bundle import Bundle, GardenGift, Notification, Trigger, write_bundle
from lateletter.sealed import seal_bundle, seal_gift_sentiment, seal_message

# ---------------------------------------------------------------------------
# Pre-seeded author content
# ---------------------------------------------------------------------------

AUTHOR_NAME    = "Robert"
RECIPIENT_NAME = "Maya"
PASSPHRASE     = "biscuit"
PASSPHRASE_HINT = "The name of our first dog"

TODAY = date.today()

# Three messages at meaningful dates (demonstrating past-due, near, and far delivery)
MESSAGES = [
    {
        "label": "For your 30th birthday",
        "date":  (TODAY - timedelta(days=1)).isoformat(),
        "body": (
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
        ),
    },
    {
        "label": "That first Christmas",
        "date":  (TODAY + timedelta(days=90)).isoformat(),
        "body": (
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
        ),
    },
    {
        "label": "Just an ordinary Tuesday",
        "date":  (TODAY + timedelta(days=365 * 3)).isoformat(),
        "body": (
            "Dear Maya,\n\n"
            "There's no occasion today. That's the point.\n\n"
            "I wanted you to know that I think about ordinary days the most.\n"
            "Not the birthdays or the holidays — the Tuesdays. The ones\n"
            "where we walked Biscuit around the block and didn't say much\n"
            "and it was perfect.\n\n"
            "I hope you're having a good ordinary day. I hope the weather\n"
            "is nice where you are. I hope someone made you laugh today.\n\n"
            "That's all. Just wanted to say hi.\n\nLove,\nDad"
        ),
    },
]

# Garden direction: one animal, one item
GARDEN_DIRECTION = {
    "animal": {
        "catalog_id": "rabbit",
        "trigger":    {"type": "cumulative_visits", "value": "1"},
        "sentiment":  (
            "I left a rabbit in your garden. She was always cautious, but patient.\n"
            "Give her time. She'll come close."
        ),
    },
    "item": {
        "catalog_id": "plate_of_food",
        "trigger":    {"type": "date", "value": (TODAY + timedelta(days=90)).isoformat()},
        "sentiment":  (
            "I used to plant bulbs in autumn so you'd have something to look\n"
            "forward to in spring. This one took longer to bloom. I hope it\n"
            "was worth the wait."
        ),
    },
}

# Abbreviated Q&A (3 questions) — answers pre-seeded
QA_PAIRS = [
    {
        "question": "What was a small ritual you shared that you'd want her to remember?",
        "answer":   (
            "Sunday mornings with bad coffee and good newspapers. "
            "She always took the comics section first."
        ),
    },
    {
        "question": "What quality in her do you most hope she carries forward?",
        "answer":   (
            "The way she laughs at herself when she messes up. "
            "It's a rare thing, and it's made her unbeatable."
        ),
    },
    {
        "question": "If you could leave her one piece of advice, what would it be?",
        "answer":   (
            "Don't mistake busy for alive. "
            "The quiet moments are the real ones."
        ),
    },
]

# ---------------------------------------------------------------------------
# Demo steps with timing
# ---------------------------------------------------------------------------

def _step(quiet: bool, msg: str, delay: float = 0.3) -> None:
    if not quiet:
        print(f"  {msg}")
        time.sleep(delay)


def run_demo(out_path: Path, quiet: bool) -> None:
    t_start = time.monotonic()

    if not quiet:
        print(f"\n  LateLetter — Author Demo (§24 step 11a Part C)")
        print(f"  {'─' * 44}")
        print()

    # ── Step 1: Consent ────────────────────────────────────────────────
    _step(quiet, "[ consent ]  Accepted — author acknowledges the nature of LateLetter.", 0.4)

    # ── Step 2: Intake ─────────────────────────────────────────────────
    _step(quiet, f"[ intake  ]  Author: {AUTHOR_NAME}  →  Recipient: {RECIPIENT_NAME}", 0.3)
    _step(quiet, f'           Passphrase hint: "{PASSPHRASE_HINT}"', 0.3)

    # ── Step 3: Q&A (3 questions) ──────────────────────────────────────
    _step(quiet, f"[ q&a     ]  3 questions answered:", 0.2)
    for i, qa in enumerate(QA_PAIRS, 1):
        _step(quiet, f"           Q{i}: {qa['question'][:60]}…", 0.25)
        _step(quiet, f"               → {qa['answer'][:60]}…", 0.2)

    # ── Step 4: Draft editor bypass ────────────────────────────────────
    _step(quiet, f"[ draft   ]  {len(MESSAGES)} letters pre-written and injected:", 0.2)
    for m in MESSAGES:
        _step(quiet, f'           · {m["date"]}  —  "{m["label"]}"', 0.2)

    # ── Step 5: Garden direction ───────────────────────────────────────
    _step(quiet, "[ garden  ]  Direction: 1 animal (rabbit) + 1 item (plate of food)", 0.3)

    # ── Step 6: Build bundle ───────────────────────────────────────────
    _step(quiet, "[ export  ]  Building bundle…", 0.3)

    messages = [
        seal_message(
            PASSPHRASE,
            message_id=str(uuid.uuid4()),
            date=m["date"],
            label=m["label"],
            body=m["body"],
        )
        for m in MESSAGES
    ]

    garden_gifts = [
        GardenGift(
            id=str(uuid.uuid4()),
            type="animal",
            catalog_id=GARDEN_DIRECTION["animal"]["catalog_id"],
            trigger=Trigger(**GARDEN_DIRECTION["animal"]["trigger"]),
            placement_hint="random",
        ),
        GardenGift(
            id=str(uuid.uuid4()),
            type="item",
            catalog_id=GARDEN_DIRECTION["item"]["catalog_id"],
            trigger=Trigger(**GARDEN_DIRECTION["item"]["trigger"]),
            placement_hint="random",
        ),
    ]
    seal_gift_sentiment(
        PASSPHRASE, garden_gifts[0], GARDEN_DIRECTION["animal"]["sentiment"],
    )
    seal_gift_sentiment(
        PASSPHRASE, garden_gifts[1], GARDEN_DIRECTION["item"]["sentiment"],
    )

    bundle = Bundle(
        bundle_id=str(uuid.uuid4()),
        author_name=AUTHOR_NAME,
        passphrase_hint=PASSPHRASE_HINT,
        garden_seed=42301,
        messages=messages,
        garden_gifts=garden_gifts,
        notification=Notification(),
    )

    # ── Step 7: Write output file ──────────────────────────────────────
    seal_bundle(bundle, PASSPHRASE)
    write_bundle(bundle, out_path)

    elapsed = time.monotonic() - t_start

    if not quiet:
        print()
        print(f"  ✓ Done in {elapsed:.1f}s — output: {out_path}")
        print()
        print(f"  To open with the terminal recipient:")
        print(f"    python3 demo_recipient.py --arc delivery")
        print(f"    (loads the demo bundle seeded for the delivery arc)")
        print()
        print(f"  To open in the browser:")
        print(f"    python3 demo_recipient.py --arc delivery --browser")
        print(f"    (generates a fixture URL — drag {out_path.name} onto the page)")
        print()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(
        description="LateLetter author e2e demo — pre-seeded, ≤60s (§24 step 11a Part C)"
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=Path("demo_output.lateletter"),
        help="Output path for the demo bundle (default: ./demo_output.lateletter)",
    )
    ap.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress progress messages",
    )
    args = ap.parse_args()

    run_demo(args.out, args.quiet)


if __name__ == "__main__":
    main()
