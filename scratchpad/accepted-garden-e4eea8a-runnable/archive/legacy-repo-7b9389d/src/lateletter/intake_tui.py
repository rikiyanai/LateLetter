"""
Curses-based TUI intake form (§5.1).

A quiet form for author intake — not a scrolling CLI.  Fields match the spec
mockup: name, relationship, recipient, key dates, memories/tags, steward,
incapacitation choice, passphrase + confirm + hint.

Navigation: Tab/Enter between fields, Esc exits with confirmation.
Passphrase fields are masked.  Validation is inline.

Falls back to --accessible line-mode if curses is unavailable or if the
user passes --accessible.
"""

from __future__ import annotations

import curses
from dataclasses import dataclass, field

from .intake import (
    IntakeData,
    KeyDate,
    ValidationError,
    passphrase_communication_warning,
    passphrase_strength_warning,
    save_intake,
    validate_intake,
    validate_passphrase,
)
from .session_store import SessionStore


# ---------------------------------------------------------------------------
# Field definitions
# ---------------------------------------------------------------------------

@dataclass
class FormField:
    name: str
    label: str
    value: str = ""
    masked: bool = False
    error: str = ""
    is_radio: bool = False
    radio_options: list[str] = field(default_factory=list)
    radio_selected: int = 0


def _build_fields(data: IntakeData | None) -> list[FormField]:
    """Build form fields, pre-populated from existing intake data if any."""
    d = data or IntakeData()
    key_dates_str = "; ".join(
        f"{kd.label}: {kd.date}" for kd in d.key_dates
    ) if d.key_dates else ""
    tags_str = ", ".join(d.memory_tags) if d.memory_tags else ""

    return [
        FormField("author_name", "Your name", d.author_name),
        FormField("relationship", "Your relationship", d.relationship),
        FormField("recipient_name", "Recipient's name", d.recipient_name),
        FormField("recipient_relationship", "Recipient's relationship", d.recipient_relationship),
        FormField("key_dates", "Key dates (semicolon-separated)", key_dates_str),
        FormField("memory_tags", "Shared memories/tags", tags_str),
        FormField("steward_name", "Steward (optional)", d.steward_name),
        FormField("steward_contact", "Steward contact", d.steward_contact),
        FormField(
            "release_choice", "If unable to finish",
            is_radio=True,
            radio_options=[
                "Only deliver completed letters",
                "Release all on date:",
            ],
            radio_selected=1 if d.release_unfinished else 0,
        ),
        FormField("release_date", "Release date", d.release_date or ""),
        FormField("passphrase", "Passphrase", masked=True),
        FormField("passphrase_confirm", "Confirm passphrase", masked=True),
        FormField("passphrase_hint", "Passphrase hint", d.passphrase_hint),
    ]


# ---------------------------------------------------------------------------
# Field value -> IntakeData
# ---------------------------------------------------------------------------

def _parse_key_dates(text: str) -> list[KeyDate]:
    """Parse 'label: date; label: date' into KeyDate list."""
    dates = []
    for part in text.split(";"):
        part = part.strip()
        if not part:
            continue
        if ":" in part:
            label, date = part.split(":", 1)
            dates.append(KeyDate(label=label.strip(), date=date.strip()))
        else:
            dates.append(KeyDate(label=part, date=""))
    return dates


def _fields_to_intake(fields: list[FormField]) -> IntakeData:
    """Extract IntakeData from form fields."""
    by_name = {f.name: f for f in fields}
    release_radio = by_name["release_choice"]
    tags_raw = by_name["memory_tags"].value
    return IntakeData(
        author_name=by_name["author_name"].value.strip(),
        relationship=by_name["relationship"].value.strip(),
        recipient_name=by_name["recipient_name"].value.strip(),
        recipient_relationship=by_name["recipient_relationship"].value.strip(),
        key_dates=_parse_key_dates(by_name["key_dates"].value),
        memory_tags=[t.strip() for t in tags_raw.split(",") if t.strip()],
        steward_name=by_name["steward_name"].value.strip(),
        steward_contact=by_name["steward_contact"].value.strip(),
        release_unfinished=(release_radio.radio_selected == 1),
        release_date=by_name["release_date"].value.strip() or None,
        passphrase_hint=by_name["passphrase_hint"].value.strip(),
    )


# ---------------------------------------------------------------------------
# Curses rendering
# ---------------------------------------------------------------------------

_LABEL_WIDTH = 30
_FIELD_START = 32
_MIN_FIELD_WIDTH = 30

_COLOR_LABEL = 1
_COLOR_VALUE = 2
_COLOR_ERROR = 3
_COLOR_WARNING = 4
_COLOR_HEADER = 5
_COLOR_HELP = 6


def _init_colors() -> None:
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(_COLOR_LABEL, curses.COLOR_WHITE, -1)
    curses.init_pair(_COLOR_VALUE, curses.COLOR_CYAN, -1)
    curses.init_pair(_COLOR_ERROR, curses.COLOR_RED, -1)
    curses.init_pair(_COLOR_WARNING, curses.COLOR_YELLOW, -1)
    curses.init_pair(_COLOR_HEADER, curses.COLOR_WHITE, -1)
    curses.init_pair(_COLOR_HELP, curses.COLOR_WHITE, -1)


def _draw_form(
    stdscr: curses.window,
    fields: list[FormField],
    current: int,
    scroll_offset: int,
    warnings: list[str],
) -> None:
    """Redraw the entire form."""
    stdscr.erase()
    max_y, max_x = stdscr.getmaxyx()
    field_width = max(max_x - _FIELD_START - 6, _MIN_FIELD_WIDTH)

    # Header
    header = " LateLetter \u2014 Author Intake "
    stdscr.addnstr(0, 2, header, max_x - 4, curses.color_pair(_COLOR_HEADER) | curses.A_BOLD)
    stdscr.addnstr(1, 2, "\u2500" * min(len(header) + 4, max_x - 4), max_x - 4,
                   curses.color_pair(_COLOR_HELP))

    row = 3 - scroll_offset
    for i, fld in enumerate(fields):
        is_active = (i == current)
        label_attr = curses.color_pair(_COLOR_LABEL)
        if is_active:
            label_attr |= curses.A_BOLD

        if fld.is_radio:
            if 2 <= row < max_y - 3:
                stdscr.addnstr(row, 2, fld.label, _LABEL_WIDTH, label_attr)
            row += 1
            for oi, opt in enumerate(fld.radio_options):
                if 2 <= row < max_y - 3:
                    marker = "(*)" if oi == fld.radio_selected else "( )"
                    opt_attr = curses.color_pair(_COLOR_VALUE)
                    if is_active and oi == fld.radio_selected:
                        opt_attr |= curses.A_BOLD
                    stdscr.addnstr(row, _FIELD_START, f"{marker} {opt}",
                                   max_x - _FIELD_START - 2, opt_attr)
                row += 1
        else:
            if 2 <= row < max_y - 3:
                stdscr.addnstr(row, 2, fld.label, _LABEL_WIDTH, label_attr)
                display = "*" * len(fld.value) if fld.masked else fld.value
                bracket_text = display[:field_width]
                val_attr = curses.color_pair(_COLOR_VALUE)
                if is_active:
                    val_attr |= curses.A_UNDERLINE
                stdscr.addnstr(row, _FIELD_START, "[ ",
                               max_x - _FIELD_START - 2, curses.color_pair(_COLOR_HELP))
                stdscr.addnstr(row, _FIELD_START + 2,
                               bracket_text.ljust(field_width), field_width, val_attr)
                end_pos = _FIELD_START + 2 + field_width
                if end_pos < max_x - 1:
                    stdscr.addnstr(row, end_pos, " ]",
                                   max_x - end_pos - 1, curses.color_pair(_COLOR_HELP))
            row += 1

            if fld.error and 2 <= row < max_y - 3:
                stdscr.addnstr(row, _FIELD_START, fld.error,
                               max_x - _FIELD_START - 2, curses.color_pair(_COLOR_ERROR))
                row += 1

    # Warnings
    for w in warnings:
        if 2 <= row < max_y - 2:
            stdscr.addnstr(row, 2, w, max_x - 4, curses.color_pair(_COLOR_WARNING))
            row += 1

    # Help bar
    help_text = "Tab/Enter: next  Shift+Tab: prev  Esc: exit  Ctrl+S: save and continue"
    if max_y > 2:
        stdscr.addnstr(max_y - 1, 2, help_text, max_x - 4, curses.color_pair(_COLOR_HELP))

    stdscr.refresh()


def _show_warning_screen(stdscr: curses.window, lines: list[str]) -> None:
    """Show a warning screen and wait for any key."""
    stdscr.erase()
    max_y, max_x = stdscr.getmaxyx()
    for i, line in enumerate(lines):
        if i + 2 < max_y - 2:
            stdscr.addnstr(i + 2, 4, line, max_x - 8, curses.color_pair(_COLOR_WARNING))
    prompt_row = min(len(lines) + 4, max_y - 2)
    stdscr.addnstr(prompt_row, 4, "Press any key to continue...",
                   max_x - 8, curses.color_pair(_COLOR_HELP))
    stdscr.refresh()
    stdscr.getch()


# ---------------------------------------------------------------------------
# Input handling
# ---------------------------------------------------------------------------

def _handle_text_input(
    ch: int,
    fld: FormField,
    passphrase: str,
    passphrase_confirm: str,
) -> tuple[str, str]:
    """Handle a keypress for a text field. Returns (passphrase, passphrase_confirm)."""
    if ch in (curses.KEY_BACKSPACE, 127, 8):
        if fld.name == "passphrase":
            passphrase = passphrase[:-1]
            fld.value = passphrase
        elif fld.name == "passphrase_confirm":
            passphrase_confirm = passphrase_confirm[:-1]
            fld.value = passphrase_confirm
        else:
            fld.value = fld.value[:-1]
        fld.error = ""
    elif 32 <= ch <= 126:
        char = chr(ch)
        if fld.name == "passphrase":
            passphrase += char
            fld.value = passphrase
        elif fld.name == "passphrase_confirm":
            passphrase_confirm += char
            fld.value = passphrase_confirm
        else:
            fld.value += char
        fld.error = ""
    return passphrase, passphrase_confirm


def _validate_and_apply_errors(
    fields: list[FormField],
    passphrase: str,
    passphrase_confirm: str,
) -> list[ValidationError]:
    """Validate fields. Apply error messages. Return error list."""
    intake = _fields_to_intake(fields)
    errors = validate_intake(intake) + validate_passphrase(passphrase, passphrase_confirm)
    error_map = {e.field: e.message for e in errors}
    for f in fields:
        f.error = error_map.get(f.name, "")
    return errors


def _field_row(fields: list[FormField], index: int) -> int:
    """Compute the screen row for field at *index*, accounting for multi-row fields."""
    row = 3  # header takes rows 0-2
    for i in range(index):
        fld = fields[i]
        if fld.is_radio:
            row += 1 + len(fld.radio_options)
        else:
            row += 1
            if fld.error:
                row += 1
    return row


# ---------------------------------------------------------------------------
# Main form loop
# ---------------------------------------------------------------------------

def _run_form(
    stdscr: curses.window,
    fields: list[FormField],
) -> tuple[list[FormField], str, str] | None:
    """Run the curses form loop.

    Returns (fields, passphrase, passphrase_confirm) on save, or None on exit.
    """
    _init_colors()
    curses.curs_set(0)
    stdscr.keypad(True)

    current = 0
    scroll_offset = 0
    warnings: list[str] = []
    passphrase = ""
    passphrase_confirm = ""

    while True:
        _draw_form(stdscr, fields, current, scroll_offset, warnings)
        ch = stdscr.getch()
        fld = fields[current]

        # --- Esc: exit with confirmation ---
        if ch == 27:
            has_content = any(f.value.strip() for f in fields if not f.is_radio)
            if has_content:
                max_y, max_x = stdscr.getmaxyx()
                stdscr.addnstr(max_y - 2, 2, "Discard changes and exit? [y/N] ",
                               max_x - 4, curses.color_pair(_COLOR_WARNING))
                stdscr.refresh()
                if stdscr.getch() not in (ord('y'), ord('Y')):
                    continue
            return None

        # --- Ctrl+S: validate and save ---
        if ch == 19:
            errors = _validate_and_apply_errors(fields, passphrase, passphrase_confirm)
            if errors:
                current = next((i for i, f in enumerate(fields) if f.error), 0)
                continue

            # Show passphrase warnings within the curses context
            intake = _fields_to_intake(fields)
            strength = passphrase_strength_warning(passphrase)
            comm = passphrase_communication_warning(intake.recipient_name)
            warning_lines = []
            if strength:
                warning_lines.append(strength)
            warning_lines.append("")
            warning_lines.append(comm)
            _show_warning_screen(stdscr, warning_lines)

            return (fields, passphrase, passphrase_confirm)

        # --- Navigation ---
        if ch in (9, 10, 13, curses.KEY_DOWN):  # Tab, Enter, Down
            current = min(current + 1, len(fields) - 1)
            max_y, _ = stdscr.getmaxyx()
            field_y = _field_row(fields, current) - scroll_offset
            if field_y >= max_y - 3:
                scroll_offset += field_y - (max_y - 4)
            continue

        if ch in (curses.KEY_BTAB, curses.KEY_UP):  # Shift-Tab, Up
            current = max(current - 1, 0)
            field_y = _field_row(fields, current) - scroll_offset
            if field_y < 2:
                scroll_offset = max(0, _field_row(fields, current) - 3)
            continue

        # --- Radio toggle ---
        if fld.is_radio:
            if ch in (ord(' '), 10, 13):
                fld.radio_selected = (fld.radio_selected + 1) % len(fld.radio_options)
            continue

        # --- Text input ---
        passphrase, passphrase_confirm = _handle_text_input(
            ch, fld, passphrase, passphrase_confirm
        )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_intake_tui(
    store: SessionStore,
    existing: IntakeData | None = None,
) -> tuple[IntakeData, str] | None:
    """Run the curses intake form.

    Returns (IntakeData, passphrase) on success, or None if the user exits.
    The passphrase is returned to the caller for in-memory use only.
    """
    fields = _build_fields(existing)

    result = curses.wrapper(lambda stdscr: _run_form(stdscr, fields))

    if result is None:
        return None

    fields, passphrase, _ = result
    intake = _fields_to_intake(fields)

    save_intake(intake, store)

    return (intake, passphrase)
