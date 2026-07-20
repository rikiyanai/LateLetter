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
    BUNDLE_VERSION_WITH_GARDEN_PROGRAM, Bundle, GardenGift, Notification,
    Trigger, read_bundle, write_bundle,
)
from lateletter.garden.program import GardenProgram, parse_program  # noqa: E402
from lateletter.sealed import (  # noqa: E402
    open_garden_program, open_gift_sentiment, open_message, seal_bundle,
    seal_garden_program, seal_gift_sentiment, seal_message, verify_bundle_hmac,
)


def _program_to_mapping(program: GardenProgram) -> dict:
    def condition(value):
        if value.kind in {"all", "any"}:
            return {value.kind: [condition(child) for child in value.children]}
        if value.kind == "not":
            return {"not": condition(value.children[0])}
        result = {"fact": value.fact, "op": value.op}
        if value.ref is not None:
            result["ref"] = value.ref
        elif value.op != "exists" or value.value is not None:
            result["value"] = value.value
        return result

    return {
        "version": program.version,
        "evaluator_version": program.evaluator_version,
        "world_state_version": program.world_state_version,
        "atlas_version": program.atlas_version,
        "astronomy_catalog_version": program.astronomy_catalog_version,
        "author_timezone": program.author_timezone,
        "variables": dict(program.variables),
        "entities": [dict(value) for value in program.entities],
        "animals": [dict(value) for value in program.animals],
        "events": [{
            "id": event.id,
            "conditions": condition(event.conditions),
            "schedule": dict(event.schedule) if event.schedule is not None else None,
            "occurrence": event.occurrence,
            "priority": event.priority,
            "exclusive_group": event.exclusive_group,
            "cooldown": dict(event.cooldown) if event.cooldown is not None else None,
            "actions": [{
                "type": action.type, "target": action.target,
                "params": dict(action.params),
            } for action in event.actions],
        } for event in program.events],
    }


def _replace_message_references(value, messages):
    if isinstance(value, str):
        if value == "FIRST_MESSAGE":
            return messages[0].id
        if value.startswith("MESSAGE_") and value[8:].isdigit():
            index = int(value[8:])
            if index >= len(messages):
                raise ValueError(f"message reference {value} is out of range")
            return messages[index].id
        return value
    if isinstance(value, list):
        return [_replace_message_references(child, messages) for child in value]
    if isinstance(value, dict):
        return {
            key: _replace_message_references(child, messages)
            for key, child in value.items()
        }
    return value


def _garden_program_from_source(src: dict, messages) -> dict | None:
    if "garden_program" in src and "garden_beats" in src:
        raise ValueError("use either 'garden_program' or 'garden_beats', not both")
    raw = src.get("garden_program")
    if raw is None and "garden_beats" in src:
        beats_source = src["garden_beats"]
        if isinstance(beats_source, list):
            beats = beats_source
            garden = {}
        elif isinstance(beats_source, dict):
            garden = beats_source
            beats = garden.get("beats", [])
        else:
            raise ValueError("'garden_beats' must be a list or structured object")
        if not isinstance(beats, list):
            raise ValueError("'garden_beats.beats' must be a list")
        events = []
        for index, beat in enumerate(beats):
            if not isinstance(beat, dict):
                raise ValueError(f"garden beat {index} must be an object")
            events.append({
                "id": beat.get("id"),
                "conditions": beat.get("when", beat.get("conditions")),
                "schedule": beat.get("schedule"),
                "occurrence": beat.get(
                    "occurrence", "recurring" if beat.get("schedule", {}).get("recurrence") else "once",
                ) if isinstance(beat.get("schedule", {}), dict) else beat.get("occurrence", "once"),
                "priority": beat.get("priority", 0),
                "exclusive_group": beat.get("exclusive_group"),
                "cooldown": beat.get("cooldown"),
                "actions": beat.get("actions", []),
            })
        raw = {
            "version": 1,
            "evaluator_version": 1,
            "world_state_version": 1,
            "atlas_version": garden.get("atlas_version", src.get("atlas_version", "garden-atlas-1")),
            "astronomy_catalog_version": garden.get(
                "astronomy_catalog_version",
                src.get("astronomy_catalog_version", "bright-stars-1"),
            ),
            "author_timezone": garden.get(
                "author_timezone", src.get("author_timezone", "UTC")
            ),
            "variables": garden.get("variables", src.get("garden_variables", {})),
            "entities": garden.get("entities", src.get("garden_entities", [])),
            "animals": garden.get("animals", src.get("garden_animals", [])),
            "events": events,
        }
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("'garden_program' must be an object")
    resolved = _replace_message_references(raw, messages)
    return _program_to_mapping(parse_program(resolved))


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

    try:
        garden_program = _garden_program_from_source(src, messages)
    except ValueError as exc:
        sys.exit(f"error: invalid garden program: {exc}")
    if garden_program is not None and src.get("garden_gifts"):
        sys.exit("error: garden_program/garden_beats cannot be mixed with legacy garden_gifts")

    gifts = []
    for g in src.get("garden_gifts", []) if garden_program is None else []:
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
        version=(BUNDLE_VERSION_WITH_GARDEN_PROGRAM if garden_program is not None else 1),
        author_name=src.get("author_name", ""),
        passphrase_hint=src.get("passphrase_hint"),
        garden_seed=int(src.get("garden_seed", 0)),
        messages=messages,
        garden_gifts=gifts,
        garden_program=(seal_garden_program(passphrase, garden_program)
                        if garden_program is not None else None),
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
    if reread.garden_program is not None:
        parse_program(open_garden_program(passphrase, reread.garden_program))

    print(f"sealed  {out_path}")
    print(f"  author: {bundle.author_name}   seed: {bundle.garden_seed}")
    print(
        f"  messages: {len(messages)}   gifts: {len(gifts)}   "
        f"garden program: {'yes' if garden_program is not None else 'no'}"
    )
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
    if bundle.garden_program is not None:
        program = parse_program(open_garden_program(passphrase, bundle.garden_program))
        print(
            f"  garden program v{program.version}: "
            f"{len(program.events)} event(s), {len(program.animals)} animal(s)"
        )


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
