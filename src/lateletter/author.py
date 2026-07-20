"""End-to-end offline author workflow.

This module owns the author-mode sequence after intake: choose a message,
complete the offline interview, edit the draft, seal it, and atomically export
the canonical bundle.  ``cli.py`` is intentionally only the command router.
"""

from __future__ import annotations

import random
import uuid
from datetime import date
from pathlib import Path
from typing import Callable

from .bundle import (
    Bundle,
    BundleValidationError,
    read_bundle,
    verify_checksum,
    write_bundle,
)
from .draft_editor import delete_draft, edit_draft, load_draft, save_draft
from .intake import IntakeData
from .question_selector import QuestionSelector
from .sealed import seal_bundle, seal_message, verify_bundle_hmac
from .session_resumer import SessionResumer
from .session_store import SessionStore
from .steward import compact_session


_DATA_DIR = Path(__file__).resolve().parents[2] / "data"
_NOTES_MARKER = "--- Q&A NOTES (remove this section before sealing) ---"


class AuthorFlowError(RuntimeError):
    """A recoverable author-flow error that is safe to show to the author."""


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

    export_path = _prompt_export_path(store, data, input_fn=input_fn)
    if export_path is None:
        output_fn("  Draft saved, but not sealed or exported.")
        return 0

    try:
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
