"""
Accessible line-mode intake form (§5.1, §12a).

Plain line-oriented prompts with the same fields, validation, and autosave
behavior as the curses form.  Used when --accessible is passed or when the
terminal accessibility probe says full-screen curses is unsuitable.

Screen reader compatible, braille display compatible, VoiceOver compatible.
No curses dependency.  All output is ordinary terminal text.
"""

from __future__ import annotations

import getpass
from typing import Callable

from .intake import (
    IntakeData,
    KeyDate,
    passphrase_communication_warning,
    passphrase_strength_warning,
    save_intake,
    validate_intake,
    validate_passphrase,
)
from .session_store import SessionStore


# ---------------------------------------------------------------------------
# I/O helpers (injectable for testing)
# ---------------------------------------------------------------------------

def _default_input(prompt: str) -> str:
    return input(prompt)


def _default_password_input(prompt: str) -> str:
    return getpass.getpass(prompt)


def _default_output(text: str) -> None:
    print(text)


# ---------------------------------------------------------------------------
# Line-mode form
# ---------------------------------------------------------------------------

def run_intake_accessible(
    store: SessionStore,
    existing: IntakeData | None = None,
    *,
    input_fn: Callable[[str], str] | None = None,
    password_fn: Callable[[str], str] | None = None,
    output_fn: Callable[[str], None] | None = None,
) -> tuple[IntakeData, str] | None:
    """Run the accessible line-mode intake form.

    Returns (IntakeData, passphrase) on success, or None if the user exits.
    """
    inp = input_fn or _default_input
    pwd = password_fn or _default_password_input
    out = output_fn or _default_output

    d = existing or IntakeData()

    out("")
    out("LateLetter — Author Intake")
    out("=" * 40)
    out("")
    out("Fill in each field below. Press Enter to keep the current value (shown in brackets).")
    out("Type 'quit' at any prompt to exit without saving.")
    out("")

    def _ask(label: str, current: str = "", required: bool = True) -> str | None:
        hint = f" [{current}]" if current else ""
        while True:
            try:
                val = inp(f"  {label}{hint}: ").strip()
            except (EOFError, KeyboardInterrupt):
                return None
            if val.lower() == "quit":
                return None
            if val == "" and current:
                return current
            if val == "" and required:
                out(f"  {label} is required.")
                continue
            return val

    def _ask_optional(label: str, current: str = "") -> str | None:
        hint = f" [{current}]" if current else ""
        try:
            val = inp(f"  {label}{hint}: ").strip()
        except (EOFError, KeyboardInterrupt):
            return None
        if val.lower() == "quit":
            return None
        return val if val else current

    # --- Fields ---

    author_name = _ask("Your name", d.author_name)
    if author_name is None:
        return None

    relationship = _ask("Your relationship (e.g. Father, Mother, Friend)", d.relationship)
    if relationship is None:
        return None

    recipient_name = _ask("Recipient's name", d.recipient_name)
    if recipient_name is None:
        return None

    recipient_relationship = _ask("Recipient's relationship (e.g. Daughter, Son, Partner)", d.recipient_relationship)
    if recipient_relationship is None:
        return None

    # Key dates
    out("")
    out("  Key dates — enter one per line as 'label: date'.")
    out("  Example: Maya's birthday: June 15")
    if d.key_dates:
        out("  Current dates:")
        for kd in d.key_dates:
            out(f"    {kd.label}: {kd.date}")
        out("  Press Enter to keep, or enter new dates (blank line when done).")
    else:
        out("  Enter at least one. Blank line when done.")
    key_dates: list[KeyDate] = []
    while True:
        try:
            line = inp("  Date: ").strip()
        except (EOFError, KeyboardInterrupt):
            return None
        if line.lower() == "quit":
            return None
        if not line:
            if not key_dates and d.key_dates:
                key_dates = list(d.key_dates)
            break
        if ":" in line:
            label, date = line.split(":", 1)
            key_dates.append(KeyDate(label=label.strip(), date=date.strip()))
        else:
            key_dates.append(KeyDate(label=line, date=""))
    while not key_dates:
        out("  At least one key date is required.")
        try:
            line = inp("  Date: ").strip()
        except (EOFError, KeyboardInterrupt):
            return None
        if line.lower() == "quit":
            return None
        if not line:
            continue
        if ":" in line:
            label, date = line.split(":", 1)
            key_dates.append(KeyDate(label=label.strip(), date=date.strip()))
        else:
            key_dates.append(KeyDate(label=line, date=""))

    # Memory tags
    tags_str = _ask_optional(
        "Shared memories/tags (comma-separated)",
        ", ".join(d.memory_tags),
    )
    if tags_str is None:
        return None
    memory_tags = [t.strip() for t in tags_str.split(",") if t.strip()] if tags_str else []

    # Steward
    out("")
    out("  Steward — a trusted person who can deliver your letters if you cannot.")
    steward_name = _ask_optional("Steward name (optional)", d.steward_name)
    if steward_name is None:
        return None
    steward_contact = ""
    if steward_name:
        steward_contact = _ask_optional("Steward contact (email or phone)", d.steward_contact)
        if steward_contact is None:
            return None

    # Incapacitation choice
    out("")
    out("  If you are unable to finish writing:")
    out("  1. Only deliver completed letters")
    out("  2. Release all on a specific date")
    current_choice = "2" if d.release_unfinished else "1"
    try:
        choice = inp(f"  Choice [1/2] [{current_choice}]: ").strip()
    except (EOFError, KeyboardInterrupt):
        return None
    if choice.lower() == "quit":
        return None
    if not choice:
        choice = current_choice
    release_unfinished = (choice == "2")
    release_date = None
    if release_unfinished:
        release_date = _ask("Release date (e.g. 2027-01-01)", d.release_date or "") or None
        if release_date is None:
            return None

    # Passphrase
    out("")
    out("  Passphrase — this protects your letters. Your recipient will need it to read them.")
    while True:
        try:
            passphrase = pwd("  Passphrase: ")
        except (EOFError, KeyboardInterrupt):
            return None
        if passphrase.lower() == "quit":
            return None
        if not passphrase:
            out("  Passphrase is required.")
            continue
        try:
            confirm = pwd("  Confirm passphrase: ")
        except (EOFError, KeyboardInterrupt):
            return None
        errors = validate_passphrase(passphrase, confirm)
        if errors:
            for e in errors:
                out(f"  {e.message}")
            continue
        break

    # Strength warning
    strength = passphrase_strength_warning(passphrase)
    if strength:
        out(f"\n  Warning: {strength}")
        out("  You can proceed — memorability is a valid priority.\n")

    # Passphrase hint
    passphrase_hint = _ask("Passphrase hint (required — helps your recipient remember)", d.passphrase_hint)
    if passphrase_hint is None:
        return None

    # Communication warning
    out("")
    out(f"  {passphrase_communication_warning(recipient_name)}")
    out("")

    # Build and validate
    data = IntakeData(
        author_name=author_name,
        relationship=relationship,
        recipient_name=recipient_name,
        recipient_relationship=recipient_relationship,
        key_dates=key_dates,
        memory_tags=memory_tags,
        steward_name=steward_name or "",
        steward_contact=steward_contact,
        release_unfinished=release_unfinished,
        release_date=release_date,
        passphrase_hint=passphrase_hint,
    )

    errors = validate_intake(data)
    if errors:
        out("")
        for e in errors:
            out(f"  Error: {e.message}")
        out("  Please run intake again to correct these fields.")
        return None

    # Save
    save_intake(data, store)
    out("")
    out("  Intake saved.")
    out("")

    return (data, passphrase)
