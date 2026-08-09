"""author_service — the single canonical owner of letter-bundle construction.

WHAT THIS FILE IS FOR
=====================
Turning an author's draft into a sealed ``.lateletter`` bundle used to live
inside ``make_letter.py``, a command-line script. That made the logic reachable
only by running that script against a file on disk, so a second front end — the
HTML author UI — would have had to reimplement it, and two implementations of a
sealing path is exactly how a recipient ends up with a bundle their viewer
cannot open.

This module now owns that work, and nothing else does. ``make_letter.py`` is a
thin adapter over it: it handles private-file paths and the interactive
passphrase prompt, then calls in here. ``author_web.py`` is a second adapter,
serving the same functions over loopback HTTP.

WHAT THIS FILE DOES NOT DO
==========================
It does not implement cryptography, and it does not implement the bundle
schema. Sealing, HMAC and key derivation belong to ``lateletter.sealed``;
the schema and its validation belong to ``lateletter.bundle``; the Garden
program grammar belongs to ``lateletter.garden.program``. Those modules stay
the semantic authority and are called, never copied.

It also never persists anything. Callers decide where bytes go, and the
passphrase is only ever a parameter — it is not stored, logged, or returned.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from lateletter.bundle import (
    BUNDLE_VERSION_WITH_GARDEN_PROGRAM, Bundle, BundleValidationError,
    Notification, read_bundle, validate_bundle_dict, write_bundle,
)
from lateletter.garden.program import (
    GardenProgram, ProgramValidationError, parse_program,
)
from lateletter.sealed import (
    open_garden_program, open_message, seal_bundle, seal_garden_program,
    seal_message, verify_bundle_hmac,
)

# This is the one blocking passphrase policy shared by every author front end.
# Strength guidance is advisory UI copy; it must not become a second export
# gate. The operator set the current floor to four characters on 2026-08-10.
PASSPHRASE_MIN_LENGTH = 4

# Any mapping key whose name suggests a secret must never reach a saved draft.
# The session store applies its own version of this rule at its top level; the
# author service scans the whole structure, because a draft arriving from a
# browser is nested and a secret could be buried several levels down.
PASSPHRASE_KEY_NAMES = frozenset({
    "passphrase", "passphrase_confirm", "passcode", "key", "secret", "password",
})


class AuthorServiceError(Exception):
    """A draft could not be turned into a bundle.

    Carries a list of human-readable problems rather than one string, so a
    front end can show the author everything that is wrong at once instead of
    making them resubmit to discover the next fault.
    """

    def __init__(self, issues: list[str]) -> None:
        self.issues = list(issues)
        super().__init__("; ".join(self.issues))


@dataclass
class ValidationResult:
    """Outcome of checking a draft without sealing it.

    errors   every problem found, in the order they were found; empty means the
             draft could be exported as it stands
    preview  a normalized, secret-free summary the UI can render back to the
             author: what the bundle would contain if they exported now
    """

    errors: list[str] = field(default_factory=list)
    preview: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors


# ── Deep secret scan ────────────────────────────────────────────────────────

def find_passphrase_key(value: Any, path: str = "") -> str | None:
    """Return the location of the first secret-looking key, or None.

    Walks the entire structure rather than only its top level. A draft posted
    by a browser is nested — messages, garden program, guided answers — and a
    key called ``passphrase`` sitting inside one of those would be written to
    disk by a top-level-only check.

    value  any JSON-shaped value
    path   dotted path accumulated during the walk, used in the return value so
           the caller can tell the author exactly where the offending key is
    """
    if isinstance(value, dict):
        for key, child in value.items():
            here = f"{path}.{key}" if path else str(key)
            if str(key).strip().lower() in PASSPHRASE_KEY_NAMES:
                return here
            found = find_passphrase_key(child, here)
            if found is not None:
                return found
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found = find_passphrase_key(child, f"{path}[{index}]")
            if found is not None:
                return found
    return None


def passphrase_problem(passphrase: Any) -> str | None:
    """Return why this passphrase is unacceptable, or None if it is fine.

    Only the canonical four-character floor blocks export. Front ends may show
    non-blocking strength guidance, but must not turn it into another policy.
    """
    if not isinstance(passphrase, str):
        return "passphrase must be text"
    if len(passphrase) < PASSPHRASE_MIN_LENGTH:
        return f"passphrase must contain at least {PASSPHRASE_MIN_LENGTH} characters"
    return None


# ── Draft → bundle parts ────────────────────────────────────────────────────

def program_to_mapping(program: GardenProgram) -> dict:
    """Flatten a parsed Garden program back into plain JSON-shaped data.

    ``parse_program`` returns typed objects; the bundle stores plain mappings.
    Round-tripping through the parser first is deliberate: it means anything
    stored in a bundle has already been proven parseable.
    """
    def condition(value):
        # Conditions are a small recursive grammar: all/any hold children, not
        # holds exactly one, and a leaf compares a fact against a value or a
        # reference to another fact.
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


def replace_message_references(value, message_ids: list[str]):
    """Swap authoring placeholders for the real message identifiers.

    An author writes ``FIRST_MESSAGE`` or ``MESSAGE_2`` in their timeline
    because the actual identifiers are random and only exist once the messages
    have been prepared. This substitutes them everywhere they appear.

    Raises ValueError when a placeholder points past the end of the message
    list, which otherwise becomes a Garden event that can never fire.
    """
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
        return [replace_message_references(child, message_ids) for child in value]
    if isinstance(value, dict):
        return {
            key: replace_message_references(child, message_ids)
            for key, child in value.items()
        }
    return value


def garden_program_from_draft(draft: dict, message_ids: list[str]) -> dict | None:
    """Build the canonical Garden program mapping from whichever form the
    draft supplies.

    Two authoring shapes are accepted. ``garden_program`` is the full v2 form.
    ``garden_beats`` is a friendlier timeline that is expanded into the same
    structure here. Supplying both is refused rather than guessed at.

    Returns None when the draft has neither, which the caller treats as an
    error — a bundle without a Garden program cannot be presented.
    """
    if "garden_program" in draft and "garden_beats" in draft:
        raise ValueError("use either 'garden_program' or 'garden_beats', not both")
    raw = draft.get("garden_program")
    if raw is None and "garden_beats" in draft:
        beats_source = draft["garden_beats"]
        # The timeline may be a bare list of beats, or an object holding the
        # beats plus scene-wide settings.
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
            schedule = beat.get("schedule", {})
            events.append({
                "id": beat.get("id"),
                "conditions": beat.get("when", beat.get("conditions")),
                "schedule": beat.get("schedule"),
                # A beat that repeats on a recurrence is recurring unless the
                # author said otherwise; anything else happens once.
                "occurrence": beat.get(
                    "occurrence",
                    "recurring" if schedule.get("recurrence") else "once",
                ) if isinstance(schedule, dict) else beat.get("occurrence", "once"),
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
                "atlas_version", draft.get("atlas_version", "garden-atlas-1"),
            ),
            "astronomy_catalog_version": garden.get(
                "astronomy_catalog_version",
                draft.get("astronomy_catalog_version", "bright-stars-1"),
            ),
            "author_timezone": garden.get(
                "author_timezone", draft.get("author_timezone", "UTC"),
            ),
            "variables": garden.get("variables", draft.get("garden_variables", {})),
            "entities": garden.get("entities", draft.get("garden_entities", [])),
            "animals": garden.get("animals", draft.get("garden_animals", [])),
            "events": events,
        }
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("'garden_program' must be an object")
    substituted = replace_message_references(raw, message_ids)
    # parse_program is the grammar authority; flattening its result guarantees
    # only parseable programs are ever stored.
    return program_to_mapping(parse_program(
        substituted, known_letter_ids=set(message_ids),
    ))


def message_specs(draft: dict) -> list[tuple[str, dict]]:
    """Pair each drafted message with a fresh identifier, checking its shape.

    Returns a list of ``(message_id, message)`` tuples. Identifiers are random
    UUIDs generated here rather than authored, so two messages can never share
    one and an author cannot accidentally leak an ordering.
    """
    raw_messages = draft.get("messages")
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


def bundle_metadata(draft: dict) -> tuple[str, str | None, int, dict]:
    """Pull and check the plaintext bundle header fields.

    These four values are NOT encrypted in the finished bundle: the author's
    name, the passphrase hint, the Garden seed and the notification block are
    readable by anyone holding the file. That is why the hint is checked for
    type here but never inspected for content — it is the author's decision
    what to put in a field they know is public.
    """
    author_name = draft.get("author_name", "")
    hint = draft.get("passphrase_hint")
    seed = draft.get("garden_seed", 0)
    notification = draft.get("notification") or {}
    if not isinstance(author_name, str):
        raise ValueError("author_name must be text")
    if hint is not None and not isinstance(hint, str):
        raise ValueError("passphrase_hint must be text or null")
    # bool is a subclass of int in Python, so True would otherwise pass as a
    # seed and silently become 1.
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


# ── Validation and preview ──────────────────────────────────────────────────

def validate_draft(draft: Any) -> ValidationResult:
    """Check a draft and describe what it would produce, without sealing it.

    Never raises for ordinary authoring mistakes: those are collected into
    ``errors`` so a UI can display them all together. The preview it returns
    contains no message bodies and no secrets — only counts, dates and labels —
    because it is intended to be safe to render and to log.
    """
    errors: list[str] = []

    if not isinstance(draft, dict):
        return ValidationResult(errors=["draft must be an object"], preview={})

    # A secret anywhere in the draft is a hard stop: the draft is the thing
    # that gets saved to disk, and the passphrase must never be saved.
    secret_at = find_passphrase_key(draft)
    if secret_at is not None:
        errors.append(
            f"remove the secret field at '{secret_at}'; the passphrase is "
            "requested separately and is never stored in a draft"
        )

    author_name: Any = ""
    hint: Any = None
    seed: Any = 0
    try:
        author_name, hint, seed, _notification = bundle_metadata(draft)
    except ValueError as exc:
        errors.append(str(exc))

    specs: list[tuple[str, dict]] = []
    try:
        specs = message_specs(draft)
    except ValueError as exc:
        errors.append(str(exc))

    # Legacy gifts predate the encrypted program and are not accepted; saying
    # so explicitly is kinder than a schema error further down.
    if draft.get("garden_gifts"):
        errors.append(
            "legacy garden_gifts are not accepted; use the encrypted v2 garden_program"
        )

    program_mapping = None
    if specs:
        try:
            program_mapping = garden_program_from_draft(
                draft, [message_id for message_id, _message in specs],
            )
        except (ValueError, ProgramValidationError) as exc:
            errors.append(f"invalid garden program: {exc}")
        if program_mapping is None and not any(
            "garden program" in issue for issue in errors
        ):
            errors.append(
                "a full encrypted garden_program or garden_beats timeline is required"
            )

    preview = {
        "author_name": author_name if isinstance(author_name, str) else "",
        "passphrase_hint": hint,
        "garden_seed": seed,
        "message_count": len(specs),
        # Dates and labels only. Bodies are the private part of the letter and
        # are deliberately absent from anything a caller might display or log.
        "messages": [
            {"date": message.get("date"), "label": message.get("label", ""),
             "body_characters": len(message.get("body", ""))}
            for _message_id, message in specs
        ],
        "garden_event_count":
            len(program_mapping["events"]) if program_mapping else 0,
        "garden_animal_count":
            len(program_mapping["animals"]) if program_mapping else 0,
        "has_garden_program": program_mapping is not None,
    }
    return ValidationResult(errors=errors, preview=preview)


# ── Sealing ─────────────────────────────────────────────────────────────────

def serialize_bundle(bundle: Bundle) -> bytes:
    """Produce the exact bytes ``write_bundle`` would write to disk.

    Kept byte-identical on purpose, and proven so by test: the HTML author UI
    hands the recipient a download, and a download that differs from what the
    command-line builder produces would be a second bundle format nobody
    intended to create.

    Schema validation and checksum computation are delegated, not reproduced.
    """
    errors = validate_bundle_dict(bundle.to_dict())
    if errors:
        raise BundleValidationError(errors)
    bundle.checksum = bundle.compute_checksum()
    return json.dumps(
        bundle.to_dict(), indent=2, ensure_ascii=False,
    ).encode("utf-8")


def build_bundle(draft: dict, passphrase: str) -> Bundle:
    """Seal a draft into an in-memory bundle.

    draft       the author's content; must already be free of secrets
    passphrase  used to derive keys and seal; never stored anywhere

    Raises AuthorServiceError with every problem found if the draft or the
    passphrase is unacceptable.
    """
    result = validate_draft(draft)
    problem = passphrase_problem(passphrase)
    issues = list(result.errors)
    if problem is not None:
        issues.append(problem)
    if issues:
        raise AuthorServiceError(issues)

    # Re-derive rather than reuse the validation pass, so the identifiers that
    # end up in the bundle are the same ones the Garden program was built
    # against in this call.
    specs = message_specs(draft)
    message_ids = [message_id for message_id, _message in specs]
    program_mapping = garden_program_from_draft(draft, message_ids)
    author_name, hint, garden_seed, notification = bundle_metadata(draft)

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
        garden_program=seal_garden_program(passphrase, program_mapping),
        notification=Notification(
            email=notification.get("email"),
            method=notification.get("method"),
        ),
    )
    seal_bundle(bundle, passphrase)
    return bundle


def verify_bundle_roundtrip(bundle: Bundle, passphrase: str) -> dict[str, Any]:
    """Prove a sealed bundle can actually be opened again.

    Sealing that produces an unopenable file is the worst possible failure for
    this product: the author believes the letter was delivered and the
    recipient can never read it. So every export re-verifies the HMAC, decrypts
    every message, and re-parses the Garden program before the bytes are handed
    over.

    Returns a small summary for the caller to show; raises AuthorServiceError
    if any part of the round trip fails.
    """
    if not verify_bundle_hmac(bundle, passphrase):
        raise AuthorServiceError(["HMAC round-trip failed"])
    try:
        for message in bundle.messages:
            open_message(passphrase, message)
        program = parse_program(
            open_garden_program(passphrase, bundle.garden_program),
            known_letter_ids={message.id for message in bundle.messages},
        )
    except (ProgramValidationError, ValueError, KeyError) as exc:
        raise AuthorServiceError([f"round-trip verification failed: {exc}"]) from exc
    return {
        "message_count": len(bundle.messages),
        "garden_event_count": len(program.events),
        "garden_animal_count": len(program.animals),
        "garden_program_version": program.version,
    }


def export_bundle_bytes(draft: dict, passphrase: str) -> tuple[bytes, dict[str, Any]]:
    """Draft plus passphrase in, canonical ``.lateletter`` bytes out.

    This is the whole export path in one call, and the only one any front end
    should use. It seals, serializes, then re-reads and fully round-trips the
    serialized bytes — not the in-memory object — so what is verified is
    exactly what the recipient will receive.

    Returns ``(bytes, summary)``. The summary contains counts only; it never
    contains the passphrase or any message body.
    """
    bundle = build_bundle(draft, passphrase)
    payload = serialize_bundle(bundle)
    # Re-read from the produced bytes. Verifying the object just built in
    # memory would not catch a serialization fault, which is precisely the
    # class of bug that leaves a recipient with an unopenable file.
    reread = Bundle.from_dict(json.loads(payload.decode("utf-8")))
    summary = verify_bundle_roundtrip(reread, passphrase)
    return payload, summary


def write_bundle_file(draft: dict, passphrase: str, out_path) -> dict[str, Any]:
    """Seal a draft and write it to *out_path*, returning the summary.

    Used by the command-line adapter. Writing goes through ``write_bundle`` so
    the on-disk atomic-write and permission behaviour stays owned by the bundle
    module rather than being reimplemented here.
    """
    bundle = build_bundle(draft, passphrase)
    write_bundle(bundle, out_path)
    return verify_bundle_roundtrip(read_bundle(out_path), passphrase)
