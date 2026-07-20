"""End-to-end offline author workflow.

This module owns the author-mode sequence after intake: choose a message,
complete the offline interview, edit the draft, seal it, and atomically export
the canonical bundle.  ``cli.py`` is intentionally only the command router.
"""

from __future__ import annotations

import random
import shutil
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from .bundle import (
    BUNDLE_VERSION,
    BUNDLE_VERSION_WITH_GARDEN_PROGRAM,
    Bundle,
    BundleValidationError,
    read_bundle,
    verify_checksum,
    write_bundle,
)
from .draft_editor import delete_draft, edit_draft, load_draft, save_draft
from .garden.atlas import load_atlas
from .garden.authoring import (
    ActionCard,
    AuthoringValidationError,
    BeatCard,
    FatigueLimitReached,
    Timeline,
    When,
    compile_timeline,
    explain_trace,
    preview_timeline,
)
from .garden.legacy import migrate_legacy_gifts
from .garden.program import Condition, GardenProgram, parse_program
from .garden.schedule import ScheduleValidationError, expand_schedule, parse_schedule
from .intake import IntakeData
from .question_selector import QuestionSelector
from .sealed import (
    open_garden_program,
    open_gift_sentiment,
    seal_bundle,
    seal_garden_program,
    seal_message,
    verify_bundle_hmac,
)
from .session_resumer import SessionResumer
from .session_store import SessionStore
from .steward import compact_session


_DATA_DIR = Path(__file__).resolve().parents[2] / "data"
_NOTES_MARKER = "--- Q&A NOTES (remove this section before sealing) ---"


class AuthorFlowError(RuntimeError):
    """A recoverable author-flow error that is safe to show to the author."""


class GardenAuthoringPaused(RuntimeError):
    """The author saved a Garden timeline to resume in a later session."""


def _ask(
    prompt: str,
    *,
    input_fn: Callable[[str], str] = input,
) -> str | None:
    try:
        return input_fn(prompt)
    except (EOFError, KeyboardInterrupt):
        return None


def _normalise_relationship(value: str) -> str:
    text = value.strip().lower()
    if any(word in text for word in ("daughter", "son", "child")):
        return "child"
    if any(word in text for word in ("wife", "husband", "spouse", "partner")):
        return "partner"
    if "friend" in text:
        return "friend"
    if any(word in text for word in ("sister", "brother", "sibling")):
        return "sibling"
    return "general"


def _new_message(
    store: SessionStore,
    *,
    input_fn: Callable[[str], str] = input,
    output_fn: Callable[[str], None] = print,
) -> dict | None:
    output_fn("")
    output_fn("  Add a new message")
    label = _ask("  Private label (encrypted in the bundle): ", input_fn=input_fn)
    if label is None or not label.strip():
        output_fn("  No message added.")
        return None

    while True:
        raw_date = _ask("  Delivery date (YYYY-MM-DD): ", input_fn=input_fn)
        if raw_date is None:
            output_fn("  No message added.")
            return None
        try:
            date.fromisoformat(raw_date.strip())
        except ValueError:
            output_fn("  Please enter a real date in YYYY-MM-DD form.")
            continue
        break

    occasion = _ask(
        "  Occasion (birthday, wedding, graduation, or general) [general]: ",
        input_fn=input_fn,
    )
    if occasion is None:
        return None

    message_id = str(uuid.uuid4())
    message = {
        "id": message_id,
        "label": label.strip(),
        "date": raw_date.strip(),
        "occasion": occasion.strip().lower() or "general",
        "status": "pending",
    }
    store.upsert_message(message_id, message)
    return message


def _choose_or_create_message(
    store: SessionStore,
    *,
    input_fn: Callable[[str], str] = input,
    output_fn: Callable[[str], None] = print,
) -> dict | None:
    unfinished = [
        msg for msg in store.load_session().get("messages", [])
        if msg.get("status") != "encrypted"
    ]
    if not unfinished:
        return _new_message(store, input_fn=input_fn, output_fn=output_fn)

    output_fn("")
    output_fn("  Unfinished messages")
    for index, msg in enumerate(unfinished, 1):
        output_fn(
            f"  {index}. {msg.get('label', '(untitled)')}  "
            f"{msg.get('date', 'TBD')}  [{msg.get('status', 'pending')}]"
        )
    output_fn("  a. Add a new message")
    choice = _ask("  Continue which message? [1]: ", input_fn=input_fn)
    if choice is None:
        return None
    choice = choice.strip().lower()
    if choice == "a":
        return _new_message(store, input_fn=input_fn, output_fn=output_fn)
    if not choice:
        return unfinished[0]
    try:
        return unfinished[int(choice) - 1]
    except (ValueError, IndexError):
        output_fn("  That selection was not recognized.")
        return None


def _draft_seed(data: IntakeData, answers: list[dict]) -> str:
    notes: list[str] = []
    for answer in answers:
        question = answer.get("question_text", answer.get("question", ""))
        notes.append(f"Q: {question}\nA: {answer.get('answer', '')}")
    notes_text = "\n\n".join(notes) if notes else "(No Q&A notes were recorded.)"
    return (
        f"Dear {data.recipient_name},\n\n\n\nLove,\n{data.author_name}\n\n"
        f"{_NOTES_MARKER}\n{notes_text}\n"
    )


def _when_from_mapping(raw: dict) -> When:
    for kind in ("all", "any", "not"):
        if kind in raw:
            children_raw = [raw[kind]] if kind == "not" else raw[kind]
            children = tuple(_when_from_mapping(child) for child in children_raw)
            return When(kind, children=children)
    return When.fact(
        str(raw.get("fact", "")), str(raw.get("op", "")), raw.get("value"),
        reference=raw.get("ref"),
    )


def _timeline_to_mapping(timeline: Timeline) -> dict:
    return {
        "version": 1,
        "author_timezone": timeline.author_timezone,
        "atlas_version": timeline.atlas_version,
        "astronomy_catalog_version": timeline.astronomy_catalog_version,
        "variables": timeline.variables,
        "entities": timeline.entities,
        "animals": timeline.animals,
        "session_beat_limit": timeline.session_beat_limit,
        "beats": [
            {
                "id": beat.id, "title": beat.title, "track": beat.track,
                "when": beat.when.compile(),
                "actions": [action.compile() for action in beat.actions],
                "schedule": dict(beat.schedule) if beat.schedule is not None else None,
                "priority": beat.priority,
                "exclusive_group": beat.exclusive_group,
                "cooldown": dict(beat.cooldown) if beat.cooldown is not None else None,
            }
            for beat in timeline.beats
        ],
    }


def _timeline_from_mapping(raw: dict) -> Timeline:
    if raw.get("version") != 1:
        raise AuthorFlowError("The saved Garden timeline uses an unsupported version.")
    timeline = Timeline(
        author_timezone=str(raw.get("author_timezone", "UTC")),
        variables=dict(raw.get("variables", {})),
        entities=[dict(value) for value in raw.get("entities", [])],
        animals=[dict(value) for value in raw.get("animals", [])],
        atlas_version=str(raw.get("atlas_version", "garden-atlas-1")),
        astronomy_catalog_version=str(
            raw.get("astronomy_catalog_version", "bright-stars-1")
        ),
        session_beat_limit=int(raw.get("session_beat_limit", 3)),
    )
    for beat in raw.get("beats", []):
        timeline.beats.append(BeatCard(
            id=str(beat["id"]), title=str(beat["title"]),
            track=str(beat["track"]),
            when=_when_from_mapping(dict(beat["when"])),
            actions=tuple(ActionCard(
                str(action["type"]), action.get("target"),
                dict(action.get("params", {})),
            ) for action in beat.get("actions", [])),
            schedule=(dict(beat["schedule"]) if beat.get("schedule") is not None else None),
            priority=int(beat.get("priority", 0)),
            exclusive_group=beat.get("exclusive_group"),
            cooldown=(dict(beat["cooldown"]) if beat.get("cooldown") is not None else None),
        ))
    timeline.begin_session()
    return timeline


def _condition_to_mapping(condition: Condition) -> dict:
    if condition.kind in {"all", "any"}:
        return {condition.kind: [_condition_to_mapping(child) for child in condition.children]}
    if condition.kind == "not":
        return {"not": _condition_to_mapping(condition.children[0])}
    raw = {"fact": condition.fact, "op": condition.op}
    if condition.ref is not None:
        raw["ref"] = condition.ref
    elif condition.op != "exists" or condition.value is not None:
        raw["value"] = condition.value
    return raw


def garden_program_to_mapping(program: GardenProgram) -> dict:
    """Return the canonical encrypted inner payload for sealing/export."""
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
        "events": [
            {
                "id": event.id,
                "conditions": _condition_to_mapping(event.conditions),
                "schedule": dict(event.schedule) if event.schedule is not None else None,
                "occurrence": event.occurrence,
                "priority": event.priority,
                "exclusive_group": event.exclusive_group,
                "cooldown": dict(event.cooldown) if event.cooldown is not None else None,
                "actions": [
                    {"type": action.type, "target": action.target,
                     "params": dict(action.params)}
                    for action in event.actions
                ],
            }
            for event in program.events
        ],
    }


def _slug(value: str, fallback: str) -> str:
    result = "-".join("".join(
        char.lower() if char.isalnum() else " " for char in value
    ).split())
    return result[:64] or fallback


def _prompt_condition(*, input_fn: Callable[[str], str],
                      message_ids: list[str], output_fn: Callable[[str], None]) -> When | None:
    output_fn("  When should this beat happen?")
    output_fn("  1 visits · 2 letter read · 3 date/time · 4 bond · 5 season · 6 absence")
    choice = _ask("  Condition [1]: ", input_fn=input_fn)
    if choice is None:
        return None
    choice = choice.strip() or "1"
    if choice == "1":
        value = _ask("  Minimum total visits [1]: ", input_fn=input_fn)
        return When.fact("visit.total", ">=", int((value or "1").strip() or "1"))
    if choice == "2":
        if not message_ids:
            output_fn("  No letters exist to reference yet.")
            return None
        for index, message_id in enumerate(message_ids, 1):
            output_fn(f"  {index}. {message_id}")
        selected = _ask("  Letter [1]: ", input_fn=input_fn)
        try:
            message_id = message_ids[int((selected or "1").strip() or "1") - 1]
        except (ValueError, IndexError):
            output_fn("  That letter selection was not recognized.")
            return None
        return When.fact("letter.read", "contains", reference=message_id)
    if choice == "3":
        value = _ask("  Local date/time (YYYY-MM-DD or ISO): ", input_fn=input_fn)
        if value is None or not value.strip():
            return None
        timestamp = value.strip()
        if len(timestamp) == 10:
            timestamp += "T00:00:00"
        datetime.fromisoformat(timestamp)
        return When.fact("time.local", ">=", timestamp)
    if choice == "4":
        value = _ask("  Minimum bond tier 0–3 [1]: ", input_fn=input_fn)
        return When.fact("animal.bond_tier", ">=", int((value or "1").strip() or "1"))
    if choice == "5":
        value = _ask("  Season (spring/summer/autumn/winter): ", input_fn=input_fn)
        return When.fact("season.current", "==", (value or "spring").strip().lower())
    if choice == "6":
        value = _ask("  Minimum days away [1]: ", input_fn=input_fn)
        return When.fact("absence.days", ">=", int((value or "1").strip() or "1"))
    output_fn("  That condition was not recognized.")
    return None


def _prompt_schedule(*, author_timezone: str,
                     input_fn: Callable[[str], str],
                     output_fn: Callable[[str], None]) -> dict | None:
    answer = _ask("  Add a calendar schedule as well? [y/N]: ", input_fn=input_fn)
    if answer is None or answer.strip().lower() not in {"y", "yes"}:
        return None
    start = _ask("  First local date/time (YYYY-MM-DD or ISO): ", input_fn=input_fn)
    if start is None or not start.strip():
        return None
    start_text = start.strip()
    if len(start_text) == 10:
        start_text += "T00:00:00"
    recurrence_choice = _ask(
        "  Repeat: 0 never · 1 daily · 2 weekly · 3 monthly · 4 yearly [0]: ",
        input_fn=input_fn,
    )
    frequencies = {"1": "daily", "2": "weekly", "3": "monthly", "4": "yearly"}
    recurrence: dict | None = None
    if (recurrence_choice or "").strip() in frequencies:
        frequency = frequencies[(recurrence_choice or "").strip()]
        interval_raw = _ask("  Repeat every how many periods? [1]: ", input_fn=input_fn)
        recurrence = {
            "frequency": frequency,
            "interval": int((interval_raw or "1").strip() or "1"),
            "dst_gap": "shift_forward",
            "dst_fold": "first",
        }
        bound = _ask("  End after a count, on a date, or never? [count/date/never]: ",
                     input_fn=input_fn)
        bound = (bound or "count").strip().lower()
        if bound.startswith("d"):
            until = _ask("  Last local date/time: ", input_fn=input_fn)
            if until is None or not until.strip():
                return None
            recurrence["until"] = (
                until.strip() + "T23:59:59" if len(until.strip()) == 10 else until.strip()
            )
        elif bound.startswith("n"):
            confirm = _ask("  Type NEVER to confirm an intentionally unbounded schedule: ",
                           input_fn=input_fn)
            if confirm != "NEVER":
                output_fn("  Unbounded schedule was not confirmed.")
                return None
            recurrence["intentional_unbounded"] = True
        else:
            count = _ask("  Number of occurrences [1]: ", input_fn=input_fn)
            recurrence["count"] = int((count or "1").strip() or "1")
    missed_choice = _ask(
        "  If visits are missed: 1 skip · 2 deliver latest · 3 summarize [2]: ",
        input_fn=input_fn,
    )
    missed = {
        "1": "skip", "2": "deliver_on_next_visit",
        "3": "summarize_then_current",
    }.get((missed_choice or "2").strip() or "2", "deliver_on_next_visit")
    raw = {
        "start": start_text,
        "timezone": author_timezone,
        "recurrence": recurrence,
        "exceptions": [],
        "missed": missed,
    }
    parse_schedule(raw)
    return raw


def _prompt_action(timeline: Timeline, *, input_fn: Callable[[str], str],
                   output_fn: Callable[[str], None]) -> ActionCard | None:
    output_fn("  What should happen?")
    output_fn("  1 reveal gift/fixture · 2 animal arrives · 3 plant · 4 memory · 5 scene · 6 variable")
    choice = _ask("  Action [1]: ", input_fn=input_fn)
    if choice is None:
        return None
    choice = choice.strip() or "1"
    if choice == "1":
        name = _ask("  Object name: ", input_fn=input_fn)
        if name is None or not name.strip():
            return None
        object_id = _slug(name, f"object-{len(timeline.entities) + 1}")
        catalog = _ask("  Portable atlas/catalog ID: ", input_fn=input_fn)
        kind = _ask("  Kind (gift/fixture/collectible) [gift]: ", input_fn=input_fn)
        timeline.entities.append({
            "id": object_id, "kind": (kind or "gift").strip() or "gift",
            "catalog_id": (catalog or object_id).strip() or object_id,
            "initial_state": {"revealed": False}, "placement": "authored",
        })
        return ActionCard.reveal(object_id)
    if choice == "2":
        name = _ask("  Animal name: ", input_fn=input_fn)
        species = _ask("  Species/catalog ID: ", input_fn=input_fn)
        if name is None or not name.strip() or species is None or not species.strip():
            return None
        animal_id = _slug(name, f"animal-{len(timeline.animals) + 1}")
        personality = _ask("  Personality in a few words: ", input_fn=input_fn)
        routine = _ask("  Daily routine/choreography: ", input_fn=input_fn)
        favorites = _ask("  Favorite places, comma-separated: ", input_fn=input_fn)
        prohibitions = _ask("  Things it must never do, comma-separated: ", input_fn=input_fn)
        timeline.animals.append({
            "id": animal_id, "species": species.strip(), "catalog_id": species.strip(),
            "name": name.strip(), "personality": (personality or "gentle").strip(),
            "routine": (routine or "wander and rest").strip(),
            "favorite_places": [v.strip() for v in (favorites or "").split(",") if v.strip()],
            "prohibited_behaviors": [v.strip() for v in (prohibitions or "").split(",") if v.strip()],
            "initial_state": {"present": False},
        })
        return ActionCard("animal.arrive", animal_id, {
            "position": "random", "routine": (routine or "wander and rest").strip(),
        })
    if choice == "3":
        name = _ask("  Plant name: ", input_fn=input_fn)
        species = _ask("  Species/catalog ID: ", input_fn=input_fn)
        position = _ask("  Garden position [authored]: ", input_fn=input_fn)
        if name is None or not name.strip() or species is None or not species.strip():
            return None
        plant_id = _slug(name, f"plant-{len(timeline.entities) + 1}")
        timeline.entities.append({
            "id": plant_id, "kind": "plant", "catalog_id": species.strip(),
            "initial_state": {"planted": False},
            "placement": (position or "authored").strip() or "authored",
        })
        return ActionCard("plant.plant", plant_id, {
            "species_id": species.strip(),
            "position": (position or "authored").strip() or "authored",
        })
    if choice == "4":
        text = _ask("  Memory text (encrypted in the bundle): ", input_fn=input_fn)
        label = _ask("  Short label [memory]: ", input_fn=input_fn)
        if text is None or not text.strip():
            return None
        return ActionCard.show_memory(text.strip(), label=(label or "memory").strip() or "memory")
    if choice == "5":
        palette = _ask("  Palette/season mood [natural]: ", input_fn=input_fn)
        weather = _ask("  Weather [clear]: ", input_fn=input_fn)
        sky = _ask("  Sky mode [privacy-preserving]: ", input_fn=input_fn)
        return ActionCard("scene.set", None, {
            "palette": (palette or "natural").strip() or "natural",
            "weather": (weather or "clear").strip() or "clear",
            "sky_mode": (sky or "privacy-preserving").strip() or "privacy-preserving",
        })
    if choice == "6":
        name = _ask("  Variable name: ", input_fn=input_fn)
        value = _ask("  Value (plain text): ", input_fn=input_fn)
        if name is None or not name.strip():
            return None
        timeline.variables.setdefault(_slug(name, "value"), None)
        return ActionCard.set_variable(_slug(name, "value"), value or "")
    output_fn("  That action was not recognized.")
    return None


def _prompt_beat(timeline: Timeline, *, message_ids: list[str],
                 input_fn: Callable[[str], str], output_fn: Callable[[str], None],
                 existing_id: str | None = None) -> BeatCard | None:
    title = _ask("  Beat title: ", input_fn=input_fn)
    if title is None or not title.strip():
        return None
    suggested = existing_id or _slug(title, f"beat-{len(timeline.beats) + 1}")
    raw_id = _ask(f"  Stable beat name [{suggested}]: ", input_fn=input_fn)
    beat_id = (raw_id or suggested).strip() or suggested
    if existing_id is None and any(beat.id == beat_id for beat in timeline.beats):
        output_fn("  That stable beat name is already in use.")
        return None
    tracks = ["letters", "animals", "plants", "fixtures", "gifts", "sky", "revisit"]
    output_fn("  Track: " + " · ".join(f"{i} {v}" for i, v in enumerate(tracks, 1)))
    track_raw = _ask("  Track [5]: ", input_fn=input_fn)
    try:
        track = tracks[int((track_raw or "5").strip() or "5") - 1]
    except (ValueError, IndexError):
        output_fn("  That track was not recognized.")
        return None
    when = _prompt_condition(input_fn=input_fn, message_ids=message_ids, output_fn=output_fn)
    if when is None:
        return None
    actions: list[ActionCard] = []
    while True:
        action = _prompt_action(timeline, input_fn=input_fn, output_fn=output_fn)
        if action is None:
            return None
        actions.append(action)
        another = _ask("  Add another action to this beat? [y/N]: ", input_fn=input_fn)
        if another is None or another.strip().lower() not in {"y", "yes"}:
            break
    schedule = _prompt_schedule(
        author_timezone=timeline.author_timezone, input_fn=input_fn, output_fn=output_fn,
    )
    priority_raw = _ask("  Priority [0]: ", input_fn=input_fn)
    group = _ask("  Exclusive group (optional): ", input_fn=input_fn)
    return BeatCard(
        id=beat_id, title=title.strip(), track=track, when=when,
        actions=tuple(actions), schedule=schedule,
        priority=int((priority_raw or "0").strip() or "0"),
        exclusive_group=(group.strip() if group and group.strip() else None),
    )


def _validation_context(timeline: Timeline, data: IntakeData,
                        message_ids: list[str]) -> dict:
    atlas = load_atlas()
    assets = atlas.get("assets", [])
    known_assets = {
        str(asset.get("id")) for asset in assets if isinstance(asset, dict) and asset.get("id")
    }
    return {
        "known_letter_ids": set(message_ids),
        "known_asset_ids": known_assets or None,
        "plaintext_envelope": {
            "author_name": data.author_name,
            "passphrase_hint": data.passphrase_hint,
        },
    }


def _preview_author_timeline(timeline: Timeline, *, data: IntakeData,
                             message_ids: list[str], input_fn: Callable[[str], str],
                             output_fn: Callable[[str], None]) -> None:
    today = datetime.now(timezone.utc)
    preview_raw = _ask(f"  Preview local date/time [{today.date().isoformat()}]: ",
                       input_fn=input_fn)
    preview_text = (preview_raw or today.date().isoformat()).strip()
    if len(preview_text) == 10:
        preview_text += "T12:00:00"
    preview_local = datetime.fromisoformat(preview_text)
    preview_utc = preview_local.replace(tzinfo=timezone.utc)
    visits_raw = _ask("  Total visits [1]: ", input_fn=input_fn)
    read_raw = _ask("  Read letter numbers, comma-separated [none]: ", input_fn=input_fn)
    read_ids: list[str] = []
    for value in (read_raw or "").split(","):
        if not value.strip():
            continue
        try:
            read_ids.append(message_ids[int(value.strip()) - 1])
        except (ValueError, IndexError):
            if value.strip() in message_ids:
                read_ids.append(value.strip())
    bond_raw = _ask("  Bond tier 0–3 [0]: ", input_fn=input_fn)
    season = _ask("  Season [spring]: ", input_fn=input_fn)
    absence_raw = _ask("  Days absent [0]: ", input_fn=input_fn)
    eligible: dict[str, str] = {}
    for beat in timeline.beats:
        if beat.schedule is None:
            continue
        result = expand_schedule(
            parse_schedule(beat.schedule), event_id=beat.id,
            last_seen_utc=preview_utc - timedelta(days=366), now_utc=preview_utc,
        )
        if result.occurrences:
            eligible[beat.id] = result.occurrences[-1].id
    context = {
        "seed": 0,
        "eligible_occurrences": eligible,
        "facts": {
            "time.local": preview_text,
            "visit.total": int((visits_raw or "1").strip() or "1"),
            "letter.read": read_ids,
            "animal.bond_tier": int((bond_raw or "0").strip() or "0"),
            "season.current": (season or "spring").strip().lower() or "spring",
            "absence.days": int((absence_raw or "0").strip() or "0"),
        },
    }
    result = preview_timeline(
        timeline, {"variables": dict(timeline.variables)}, context,
        **_validation_context(timeline, data, message_ids),
    )
    output_fn("  Exact recipient-evaluator trace:")
    for line in explain_trace(result):
        output_fn(f"    {line}")
    output_fn(f"  Preview would emit {len(result.effects)} effect(s).")


def _run_garden_timeline_editor(store: SessionStore, data: IntakeData,
                                message_ids: list[str], *,
                                input_fn: Callable[[str], str],
                                output_fn: Callable[[str], None]) -> Timeline | None:
    saved = store.load_garden_timeline()
    if saved is not None:
        resume = _ask("  Resume your saved Garden timeline? [Y/n]: ", input_fn=input_fn)
        if resume is not None and resume.strip().lower() in {"n", "no"}:
            return None
        timeline = _timeline_from_mapping(saved)
    else:
        enabled = _ask("  Program the recipient's Garden? [y/N]: ", input_fn=input_fn)
        if enabled is None or enabled.strip().lower() not in {"y", "yes"}:
            return None
        timezone_name = _ask("  Author timezone [UTC]: ", input_fn=input_fn)
        timeline = Timeline(author_timezone=(timezone_name or "UTC").strip() or "UTC")
    output_fn("  Garden timeline uses plain-language beat cards; it saves after every change.")
    while True:
        output_fn("")
        for index, beat in enumerate(timeline.beats, 1):
            output_fn(f"  {index}. {beat.title} [{beat.track}] ({beat.id})")
        choice = _ask("  Garden: add, edit, reorder, preview, validate, done, save [done]: ",
                      input_fn=input_fn)
        command = (choice or "done").strip().lower()
        try:
            if command in {"a", "add"}:
                beat = _prompt_beat(
                    timeline, message_ids=message_ids,
                    input_fn=input_fn, output_fn=output_fn,
                )
                if beat is not None:
                    timeline.add_beat(beat)
                    store.save_garden_timeline(_timeline_to_mapping(timeline))
            elif command in {"e", "edit"}:
                selected = _ask("  Beat number to replace: ", input_fn=input_fn)
                index = int((selected or "0").strip()) - 1
                old = timeline.beats[index]
                entity_count, animal_count = len(timeline.entities), len(timeline.animals)
                beat = _prompt_beat(
                    timeline, message_ids=message_ids, existing_id=old.id,
                    input_fn=input_fn, output_fn=output_fn,
                )
                if beat is not None:
                    timeline.beats[index] = beat
                    store.save_garden_timeline(_timeline_to_mapping(timeline))
                else:
                    del timeline.entities[entity_count:]
                    del timeline.animals[animal_count:]
            elif command in {"r", "reorder"}:
                selected = _ask("  Beat number to move: ", input_fn=input_fn)
                destination = _ask("  New position: ", input_fn=input_fn)
                beat = timeline.beats[int((selected or "0").strip()) - 1]
                timeline.reorder(beat.id, int((destination or "1").strip()) - 1)
                store.save_garden_timeline(_timeline_to_mapping(timeline))
            elif command in {"p", "preview"}:
                _preview_author_timeline(
                    timeline, data=data, message_ids=message_ids,
                    input_fn=input_fn, output_fn=output_fn,
                )
            elif command in {"v", "validate"}:
                compile_timeline(timeline, **_validation_context(timeline, data, message_ids))
                output_fn("  Garden timeline is valid for encrypted export.")
            elif command in {"s", "save"}:
                store.save_garden_timeline(_timeline_to_mapping(timeline))
                output_fn("  Garden timeline saved. Resume it on the next --write run.")
                raise GardenAuthoringPaused
            elif command in {"d", "done", ""}:
                store.save_garden_timeline(_timeline_to_mapping(timeline))
                return timeline
            else:
                output_fn("  Choose add, edit, reorder, preview, validate, done, or save.")
        except FatigueLimitReached as exc:
            store.save_garden_timeline(_timeline_to_mapping(timeline))
            output_fn(f"  {exc}")
            raise GardenAuthoringPaused from exc
        except (AuthoringValidationError, ScheduleValidationError, ValueError, IndexError) as exc:
            output_fn(f"  Garden edit needs attention: {exc}")


def _backup_v1_bundle(path: Path) -> Path:
    candidate = path.with_name(f"{path.stem}.v1.backup{path.suffix}")
    counter = 2
    while candidate.exists():
        candidate = path.with_name(f"{path.stem}.v1.backup-{counter}{path.suffix}")
        counter += 1
    shutil.copy2(path, candidate)
    return candidate


def _merge_programs(first: GardenProgram, second: GardenProgram) -> GardenProgram:
    first_raw = garden_program_to_mapping(first)
    second_raw = garden_program_to_mapping(second)
    merged = dict(first_raw)
    merged["variables"] = {**first_raw["variables"], **second_raw["variables"]}
    for field in ("entities", "animals", "events"):
        merged[field] = [*first_raw[field], *second_raw[field]]
    return parse_program(merged)


def _install_timeline_program(
    bundle: Bundle, *, path: Path, existed: bool, timeline_program: GardenProgram,
    passphrase: str, input_fn: Callable[[str], str], output_fn: Callable[[str], None],
) -> bool:
    """Install a v2 program or explicitly preserve an authenticated v1 bundle."""
    program = timeline_program
    if existed and bundle.version == BUNDLE_VERSION:
        output_fn("  This is an authenticated version-1 bundle with legacy Garden gifts.")
        confirm = _ask(
            "  Type UPGRADE to back it up, migrate its gifts, and install Garden v2: ",
            input_fn=input_fn,
        )
        if confirm != "UPGRADE":
            output_fn("  Garden upgrade declined; the existing bundle remains version 1.")
            return False
        backup = _backup_v1_bundle(path)
        if bundle.garden_gifts:
            sentiments = {
                gift.id: open_gift_sentiment(passphrase, gift)
                for gift in bundle.garden_gifts
            }
            legacy = migrate_legacy_gifts(
                bundle.garden_gifts, authenticated=True,
                decrypted_sentiments=sentiments,
                message_ids=[message.id for message in bundle.messages],
                author_timezone=timeline_program.author_timezone,
            )
            program = _merge_programs(legacy, timeline_program)
        output_fn(f"  Authenticated version-1 backup created: {backup}")
    elif bundle.version not in {BUNDLE_VERSION, BUNDLE_VERSION_WITH_GARDEN_PROGRAM}:
        raise AuthorFlowError(f"Unsupported existing bundle version {bundle.version}.")

    bundle.version = BUNDLE_VERSION_WITH_GARDEN_PROGRAM
    bundle.garden_gifts = []
    bundle.garden_program = seal_garden_program(
        passphrase, garden_program_to_mapping(program),
    )
    return True


def _prompt_export_path(
    store: SessionStore,
    data: IntakeData,
    *,
    input_fn: Callable[[str], str] = input,
) -> Path | None:
    session = store.load_session()
    prior = session.get("bundle_path", "")
    safe_name = "".join(
        ch.lower() if ch.isalnum() else "-" for ch in data.recipient_name
    ).strip("-") or "letters"
    default = prior or str(Path.cwd() / f"{safe_name}.lateletter")
    answer = _ask(f"  Export bundle [{default}]: ", input_fn=input_fn)
    if answer is None:
        return None
    path = Path(answer.strip() or default).expanduser().resolve()
    if path.suffix != ".lateletter":
        path = path.with_suffix(".lateletter")
    return path


def _load_export_bundle(path: Path, data: IntakeData, passphrase: str) -> Bundle:
    if path.exists():
        bundle = read_bundle(path)
        if not verify_checksum(bundle):
            raise AuthorFlowError("The existing bundle is damaged; it was not changed.")
        if not verify_bundle_hmac(bundle, passphrase):
            raise AuthorFlowError(
                "The passphrase does not unlock the existing bundle; it was not changed."
            )
        return bundle
    if not path.parent.exists():
        raise AuthorFlowError(f"The export folder does not exist: {path.parent}")
    return Bundle(
        author_name=data.author_name,
        passphrase_hint=data.passphrase_hint,
        garden_seed=random.SystemRandom().randrange(1, 2**31),
    )


def run_author_workflow(
    store: SessionStore,
    data: IntakeData,
    passphrase: str,
    *,
    accessible: bool = False,
    input_fn: Callable[[str], str] = input,
    output_fn: Callable[[str], None] = print,
) -> int:
    """Run questions → drafting → sealing → canonical export for one message."""
    message = _choose_or_create_message(
        store, input_fn=input_fn, output_fn=output_fn,
    )
    if message is None:
        return 0

    message_id = message["id"]
    if message.get("status") != "written":
        selector = QuestionSelector.load(
            _DATA_DIR / "question_bank_seed.v0.json",
            _DATA_DIR / "question_bank_domain_pools.v0.json",
        )
        resumer = SessionResumer(
            selector=selector,
            store=store,
            message_id=message_id,
            occasion=message.get("occasion", "general"),
            relationship=_normalise_relationship(data.recipient_relationship),
            memory_tags=data.memory_tags,
            exchange_target=int(message.get("qa_exchange_target", 10)),
            input_fn=lambda: input_fn("  "),
            output_fn=output_fn,
        )
        qa_result = resumer.prepare().run()
        if qa_result.interrupted:
            output_fn("  Your interview is saved. Run lateletter --write to continue.")
            return 0

    current = store.get_message(message_id) or message
    initial = load_draft(message_id, base_dir=store.author_dir)
    if initial is None:
        initial = _draft_seed(data, current.get("qa_answers", []))

    text, should_seal = edit_draft(
        message_id,
        initial,
        accessible=accessible,
        base_dir=store.author_dir,
        output_fn=output_fn,
    )
    if text is None:
        output_fn("  Drafting stopped; your interview notes are still saved.")
        return 0

    save_draft(message_id, text, base_dir=store.author_dir)
    store.upsert_message(message_id, {"status": "written"})
    if not should_seal:
        output_fn("  Draft saved. Run lateletter --write when you are ready to seal it.")
        return 0
    if _NOTES_MARKER in text:
        output_fn("  Draft saved, but not sealed: remove the Q&A notes section first.")
        return 0

    message_ids = [
        str(value.get("id")) for value in store.load_session().get("messages", [])
        if value.get("id")
    ]
    try:
        timeline = _run_garden_timeline_editor(
            store, data, message_ids, input_fn=input_fn, output_fn=output_fn,
        )
    except GardenAuthoringPaused:
        output_fn("  Garden authoring paused; your draft and timeline are saved.")
        return 0
    timeline_program: GardenProgram | None = None
    if timeline is not None:
        try:
            timeline_program = compile_timeline(
                timeline, **_validation_context(timeline, data, message_ids),
            )
        except AuthoringValidationError as exc:
            output_fn("  Garden export blocked until these errors are fixed:")
            for issue in exc.issues:
                output_fn(f"    {issue.path}: {issue.message}")
            output_fn("  The Garden timeline and plaintext draft remain saved.")
            return 1

    export_path = _prompt_export_path(store, data, input_fn=input_fn)
    if export_path is None:
        output_fn("  Draft saved, but not sealed or exported.")
        return 0

    try:
        existed = export_path.exists()
        bundle = _load_export_bundle(export_path, data, passphrase)
        bundle.author_name = data.author_name
        bundle.passphrase_hint = data.passphrase_hint
        if not any(existing.id == message_id for existing in bundle.messages):
            bundle.messages.append(seal_message(
                passphrase,
                message_id=message_id,
                date=message["date"],
                label=message["label"],
                body=text,
            ))
        if timeline_program is not None:
            _install_timeline_program(
                bundle, path=export_path, existed=existed,
                timeline_program=timeline_program, passphrase=passphrase,
                input_fn=input_fn, output_fn=output_fn,
            )
        seal_bundle(bundle, passphrase)
        write_bundle(bundle, export_path)
    except (OSError, ValueError, BundleValidationError, AuthorFlowError) as exc:
        output_fn(f"  Export failed: {exc}")
        output_fn("  Your plaintext draft remains saved on this computer.")
        return 1

    session = store.load_session()
    session["bundle_path"] = str(export_path)
    store.save_session(session)
    store.upsert_message(message_id, {"status": "encrypted"})

    output_fn("")
    output_fn(f"  Sealed and exported: {export_path}")
    output_fn(
        f"  Important: if {data.recipient_name} forgets the passphrase, "
        "the letter cannot be recovered."
    )
    output_fn("  Keep a second copy of the .lateletter file somewhere safe.")

    cleanup = _ask(
        "  Securely delete this completed draft and its interview notes? [Y/n] ",
        input_fn=input_fn,
    )
    if cleanup is not None and cleanup.strip().lower() not in ("n", "no"):
        delete_draft(message_id, base_dir=store.author_dir)
        compact_session(store)
        output_fn("  Completed plaintext draft and notes deleted.")
    else:
        output_fn("  Plaintext draft retained in your private author folder.")

    output_fn(f"  Give the .lateletter file to {data.recipient_name}.")
    return 0
