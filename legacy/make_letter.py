#!/usr/bin/env python3
"""
make_letter.py — seal a real, passcode-gated .lateletter bundle.

Usage:
    python3 make_letter.py letters/letter_source.example.json out.lateletter
    python3 make_letter.py --verify out.lateletter        # prompts for passcode

The source file is plain JSON you edit by hand:

    {
      "author_name": "Riki",
      "passphrase": "our-word",          <- the passcode (never stored in output)
      "passphrase_hint": "the word we always say instead of goodbye",
      "garden_seed": 20260719,
      "messages": [
        {"date": "2026-07-20", "label": "Open me", "body": "Dear ...\n..."}
      ],
      "garden_gifts": [
        {"type": "animal", "catalog_id": "cat", "animal_name": "Mochi",
         "trigger": {"type": "cumulative_visits", "value": "3"},
         "sentiment": "She showed up because you kept coming back."}
      ]
    }

Keep your real source file out of git (letters/*.json is gitignored except
the example) — it holds the plaintext letter AND the passcode.
"""

from __future__ import annotations

import getpass
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from lateletter.bundle import (  # noqa: E402
    Bundle, GardenGift, Notification, Trigger, read_bundle, write_bundle,
)
from lateletter.sealed import (  # noqa: E402
    open_gift_sentiment, open_message, seal_bundle, seal_gift_sentiment,
    seal_message, verify_bundle_hmac,
)


def build(source_path: Path, out_path: Path) -> None:
    src = json.loads(source_path.read_text(encoding="utf-8"))
    passphrase = src["passphrase"]
    if not passphrase:
        sys.exit("error: source file needs a non-empty 'passphrase'")

    messages = [
        seal_message(
            passphrase,
            message_id=str(uuid.uuid4()),
            date=m["date"], label=m.get("label", ""), body=m["body"],
        )
        for m in src.get("messages", [])
    ]
    if not messages:
        sys.exit("error: source file needs at least one message")

    gifts = []
    for g in src.get("garden_gifts", []):
        trigger = Trigger.from_dict(g["trigger"])
        # post_letter triggers may reference "FIRST_MESSAGE" or "MESSAGE_<n>"
        # since real message IDs only exist after sealing.
        if trigger.type == "post_letter":
            if trigger.value == "FIRST_MESSAGE":
                trigger.value = messages[0].id
            elif trigger.value.startswith("MESSAGE_"):
                trigger.value = messages[int(trigger.value[8:])].id
        gift = GardenGift(
            id=str(uuid.uuid4()),
            type=g["type"],
            catalog_id=g["catalog_id"],
            trigger=trigger,
            placement_hint=g.get("placement_hint", "random"),
            animal_name=g.get("animal_name"),
            animal_collar_color=g.get("animal_collar_color"),
        )
        seal_gift_sentiment(passphrase, gift, g.get("sentiment", ""))
        gifts.append(gift)

    bundle = Bundle(
        author_name=src.get("author_name", ""),
        passphrase_hint=src.get("passphrase_hint"),
        garden_seed=int(src.get("garden_seed", 0)),
        messages=messages,
        garden_gifts=gifts,
        notification=Notification(
            email=(src.get("notification") or {}).get("email"),
            method=(src.get("notification") or {}).get("method"),
        ),
    )
    seal_bundle(bundle, passphrase)
    write_bundle(bundle, out_path)

    # Round-trip proof before declaring success.
    reread = read_bundle(out_path)
    assert verify_bundle_hmac(reread, passphrase), "HMAC round-trip failed"
    for msg in reread.messages:
        open_message(passphrase, msg)
    for gift in reread.garden_gifts:
        open_gift_sentiment(passphrase, gift)

    print(f"sealed  {out_path}")
    print(f"  author: {bundle.author_name}   seed: {bundle.garden_seed}")
    print(f"  messages: {len(messages)}   gifts: {len(gifts)}")
    print(f"  hint shown to recipient: {bundle.passphrase_hint!r}")
    print("  passcode is NOT stored in the file — share it in person.")
    if out_path.parent.name == "public_letters":
        name = out_path.stem
        print("  publishable — after commit to master + Pages deploy:")
        print(f"    https://rikiworld.com/lateletter/{name}/")
        print(f"    https://rikiworld.com/lateletter/?l={name}")
        print("  note: author name, hint, and dates are plaintext in the")
        print("  bundle and visible to anyone with the URL or the repo.")


def verify(path: Path) -> None:
    bundle = read_bundle(path)
    passphrase = getpass.getpass("passcode: ")
    if not verify_bundle_hmac(bundle, passphrase):
        sys.exit("HMAC verification FAILED — wrong passcode or modified file")
    print("HMAC ok")
    for msg in bundle.messages:
        content = open_message(passphrase, msg)
        print(f"  {msg.date}  {content['label']!r}  ({len(content['body'])} chars)")
    for gift in bundle.garden_gifts:
        text = open_gift_sentiment(passphrase, gift)
        print(f"  gift {gift.type}/{gift.catalog_id}: {text!r}")


def main() -> None:
    args = sys.argv[1:]
    if len(args) == 2 and args[0] == "--verify":
        verify(Path(args[1]))
    elif len(args) == 2:
        build(Path(args[0]), Path(args[1]))
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
