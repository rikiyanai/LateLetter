#!/usr/bin/env python3
"""
make_letter.py — seal a real, passcode-gated .lateletter bundle.

Usage:
    python3 make_letter.py /safe/private/source.json /safe/private/out.lateletter
    python3 make_letter.py --verify out.lateletter        # prompts for passcode

The source file is plain JSON you edit by hand:

    {
      "author_name": "Riki",
      "passphrase_hint": "the word we always say instead of goodbye",
      "garden_seed": 20260719,
      "messages": [
        {"date": "2026-07-20", "label": "Open me", "body": "Dear ...\n..."}
      ],
      "garden_program": {
        "version": 1,
        "evaluator_version": 1,
        "world_state_version": 1,
        "atlas_version": "garden-atlas-1",
        "astronomy_catalog_version": "bright-stars-1",
        "author_timezone": "UTC",
        "variables": {}, "entities": [], "animals": [], "events": []
      }
    }

The passphrase is requested twice at runtime and is never accepted in the
source JSON.  The builder refuses tracked/unignored repository paths and
existing output files.  Keep real plaintext and recipient bundles in ignored
private storage; never use the tracked example or public output paths.
"""

from __future__ import annotations

import getpass
import json
import subprocess
import sys
import uuid
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from lateletter.bundle import (  # noqa: E402
    BUNDLE_VERSION_WITH_GARDEN_PROGRAM, Bundle, Notification, read_bundle,
    write_bundle,
)
from lateletter.garden.program import (  # noqa: E402
    GardenProgram, ProgramValidationError, parse_program,
)
from lateletter.intake import passphrase_strength_warning  # noqa: E402
from lateletter.sealed import (  # noqa: E402
    open_garden_program, open_gift_sentiment, open_message, seal_bundle,
    seal_garden_program, seal_message, verify_bundle_hmac,
)


_REPOSITORY_ROOT = Path(__file__).resolve().parent


def _repo_relative(path: Path) -> str | None:
    try:
        return path.resolve().relative_to(_REPOSITORY_ROOT).as_posix()
    except ValueError:
        return None


def _git_path_status(path: Path) -> tuple[bool, bool]:
    """Return ``(tracked, ignored)`` without opening the target file."""
    relative = _repo_relative(path)
    if relative is None or not (_REPOSITORY_ROOT / ".git").exists():
        return False, False
    tracked = subprocess.run(
        [
            "git", "-C", str(_REPOSITORY_ROOT), "ls-files",
            "--error-unmatch", "--", relative,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    ).returncode == 0
    ignored = subprocess.run(
        [
            "git", "-C", str(_REPOSITORY_ROOT), "check-ignore",
            "--quiet", "--", relative,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    ).returncode == 0
    return tracked, ignored


def _validate_private_paths(source_path: Path, out_path: Path) -> tuple[Path, Path]:
    """Reject paths likely to expose personal plaintext or recipient output."""
    source = source_path.expanduser().resolve()
    output = out_path.expanduser().resolve()
    if source == output:
        raise ValueError("source and output paths must be different")
    if source.suffix.lower() != ".json":
        raise ValueError("source path must end in .json")
    if output.suffix.lower() != ".lateletter":
        raise ValueError("output path must end in .lateletter")
    if not source.is_file():
        raise ValueError(f"source file does not exist: {source}")
    if output.exists():
        raise ValueError(
            "output already exists; choose a new path for this fresh bundle"
        )
    if not output.parent.is_dir():
        raise ValueError(f"output folder does not exist: {output.parent}")

    source_tracked, source_ignored = _git_path_status(source)
    output_tracked, output_ignored = _git_path_status(output)
    if source_tracked:
        raise ValueError("refusing to read a Git-tracked plaintext letter source")
    if output_tracked:
        raise ValueError("refusing to overwrite a Git-tracked recipient bundle")
    if _repo_relative(source) is not None and not source_ignored:
        raise ValueError(
            "plaintext source is inside the repository and is not ignored by Git"
        )
    if _repo_relative(output) is not None and not output_ignored:
        raise ValueError(
            "recipient output is inside the repository and is not ignored by Git"
        )
    return source, output


def _fresh_passphrase(password_fn=getpass.getpass) -> str:
    try:
        passphrase = password_fn(
            "fresh passphrase (never committed or used for a compromised bundle): "
        )
        confirmation = password_fn("confirm fresh passphrase: ")
    except (EOFError, KeyboardInterrupt) as exc:
        raise ValueError("passphrase entry cancelled") from exc
    if passphrase != confirmation:
        raise ValueError("passphrases do not match")
    if len(passphrase) < 12:
        raise ValueError("fresh passphrase must contain at least 12 characters")
    warning = passphrase_strength_warning(passphrase)
    if warning is not None:
        raise ValueError(warning)
    return passphrase


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


def _replace_message_references(value, message_ids: list[str]):
    if isinstance(value, str):
        if value == "FIRST_MESSAGE":
            return message_ids[0]
        if value.startswith("MESSAGE_") and value[8:].isdigit():
            index = int(value[8:])
            if index >= len(message_ids):
                raise ValueError(f"message reference {value} is out of range")
            return message_ids[index]
        return value
    if isinstance(value, list):
        return [_replace_message_references(child, message_ids) for child in value]
    if isinstance(value, dict):
        return {
            key: _replace_message_references(child, message_ids)
            for key, child in value.items()
        }
    return value


def _garden_program_from_source(src: dict, message_ids: list[str]) -> dict | None:
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
                    "occurrence",
                    "recurring" if beat.get("schedule", {}).get("recurrence") else "once",
                ) if isinstance(beat.get("schedule", {}), dict) else beat.get(
                    "occurrence", "once",
                ),
                "priority": beat.get("priority", 0),
                "exclusive_group": beat.get("exclusive_group"),
                "cooldown": beat.get("cooldown"),
                "actions": beat.get("actions", []),
            })
        raw = {
            "version": 1,
            "evaluator_version": 1,
            "world_state_version": 1,
            "atlas_version": garden.get(
                "atlas_version", src.get("atlas_version", "garden-atlas-1"),
            ),
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
    resolved = _replace_message_references(raw, message_ids)
    return _program_to_mapping(parse_program(
        resolved, known_letter_ids=set(message_ids),
    ))


def _message_specs(src: dict) -> list[tuple[str, dict]]:
    raw_messages = src.get("messages")
    if not isinstance(raw_messages, list) or not raw_messages:
        raise ValueError("source file needs at least one message")
    specs: list[tuple[str, dict]] = []
    for index, message in enumerate(raw_messages):
        if not isinstance(message, dict):
            raise ValueError(f"messages[{index}] must be an object")
        raw_date = message.get("date")
        label = message.get("label", "")
        body = message.get("body")
        if not isinstance(raw_date, str):
            raise ValueError(f"messages[{index}].date must be an ISO date")
        try:
            date.fromisoformat(raw_date)
        except ValueError as exc:
            raise ValueError(f"messages[{index}].date must be a real ISO date") from exc
        if not isinstance(label, str):
            raise ValueError(f"messages[{index}].label must be text")
        if not isinstance(body, str) or not body.strip():
            raise ValueError(f"messages[{index}].body must be non-empty text")
        specs.append((str(uuid.uuid4()), message))
    return specs


def _bundle_metadata(src: dict) -> tuple[str, str | None, int, dict]:
    author_name = src.get("author_name", "")
    hint = src.get("passphrase_hint")
    seed = src.get("garden_seed", 0)
    notification = src.get("notification") or {}
    if not isinstance(author_name, str):
        raise ValueError("author_name must be text")
    if hint is not None and not isinstance(hint, str):
        raise ValueError("passphrase_hint must be text or null")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("garden_seed must be an integer")
    if not isinstance(notification, dict):
        raise ValueError("notification must be an object or null")
    unknown = set(notification) - {"email", "method"}
    if unknown:
        raise ValueError(
            f"notification has unknown fields: {', '.join(sorted(unknown))}"
        )
    return author_name, hint, seed, notification


def build(
    source_path: Path,
    out_path: Path,
    *,
    passphrase: str | None = None,
    password_fn=getpass.getpass,
) -> None:
    try:
        source_path, out_path = _validate_private_paths(source_path, out_path)
        src = json.loads(source_path.read_text(encoding="utf-8"))
        if not isinstance(src, dict):
            raise ValueError("source JSON must be an object")
        if "passphrase" in src:
            raise ValueError(
                "remove 'passphrase' from the plaintext source; it is requested privately"
            )
        passphrase = _fresh_passphrase(password_fn) if passphrase is None else passphrase
        if len(passphrase) < 12 or passphrase_strength_warning(passphrase) is not None:
            raise ValueError("provide a strong fresh passphrase of at least 12 characters")
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        sys.exit(f"error: {exc}")

    try:
        author_name, hint, garden_seed, notification = _bundle_metadata(src)
        specs = _message_specs(src)
        garden_program = _garden_program_from_source(
            src, [message_id for message_id, _message in specs],
        )
    except ValueError as exc:
        sys.exit(f"error: invalid source or garden program: {exc}")
    if src.get("garden_gifts"):
        sys.exit(
            "error: legacy garden_gifts are not accepted; use the encrypted v2 garden_program"
        )
    if garden_program is None:
        sys.exit("error: a full encrypted garden_program or garden_beats timeline is required")

    messages = [
        seal_message(
            passphrase,
            message_id=message_id,
            date=message["date"],
            label=message.get("label", ""),
            body=message["body"],
        )
        for message_id, message in specs
    ]

    bundle = Bundle(
        version=BUNDLE_VERSION_WITH_GARDEN_PROGRAM,
        author_name=author_name,
        passphrase_hint=hint,
        garden_seed=garden_seed,
        messages=messages,
        garden_gifts=[],
        garden_program=seal_garden_program(passphrase, garden_program),
        notification=Notification(
            email=notification.get("email"),
            method=notification.get("method"),
        ),
    )
    seal_bundle(bundle, passphrase)
    write_bundle(bundle, out_path)

    # Round-trip proof before declaring success.
    reread = read_bundle(out_path)
    assert verify_bundle_hmac(reread, passphrase), "HMAC round-trip failed"
    for msg in reread.messages:
        open_message(passphrase, msg)
    parse_program(
        open_garden_program(passphrase, reread.garden_program),
        known_letter_ids={message.id for message in reread.messages},
    )

    print(f"sealed  {out_path}")
    print(f"  author: {bundle.author_name}   seed: {bundle.garden_seed}")
    print(
        f"  messages: {len(messages)}   legacy gifts: 0   garden program: yes"
    )
    print(f"  hint shown to recipient: {bundle.passphrase_hint!r}")
    print("  passcode is NOT stored in the file — share it in person.")
    if out_path.parent.name == "public_letters":
        name = out_path.stem
        print("  publishable — after commit to main + Pages deploy:")
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
        try:
            program = parse_program(
                open_garden_program(passphrase, bundle.garden_program),
                known_letter_ids={message.id for message in bundle.messages},
            )
        except ProgramValidationError as exc:
            raise SystemExit(f"garden verification FAILED — {exc}") from exc
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
