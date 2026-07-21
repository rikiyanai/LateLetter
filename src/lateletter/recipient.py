"""Terminal recipient mode with canonical Garden world ownership."""

from __future__ import annotations

import base64
import curses
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
import json
import os
from pathlib import Path
import textwrap
import time
from typing import Any, Mapping

from .bundle import Bundle, GardenGift, Message, read_bundle, verify_checksum
from .garden.legacy import migrate_legacy_gifts
from .garden.materializer import apply_program, build_runtime_facts, eligible_occurrences
from .garden.program import GardenProgram, parse_program
from .garden.renderer import GardenRenderer
from .garden.terminal import TERMINAL_HELP_LINES, TerminalWorldSession, handle_terminal_key
from .garden.world.engine import CommandResult
from .sealed import open_garden_program, open_gift_sentiment, open_message, verify_bundle_hmac


ITEM_CATALOG: dict[str, tuple[str, str]] = {
    "coffee_mug": ("A coffee mug", "( ~ )"),
    "teacup": ("A teacup", "{ ~ }"),
    "plate_of_food": ("A plate of food", "[o.o]"),
    "pair_of_shoes": ("A pair of shoes", " >,> "),
    "book": ("A book", " [=] "),
    "small_radio": ("A small radio", "[~=~]"),
    "candle": ("A candle", " .*| "),
    "pocket_watch": ("A pocket watch", " (@) "),
    "photo_frame": ("A photo frame", " [ ] "),
    "pressed_flower": ("A pressed flower", " *·* "),
    "fishing_rod": ("A fishing rod", " /~~ "),
    "compass": ("A compass", " (^) "),
    "old_key": ("An old key", " >-) "),
    "small_stone": ("A small stone", " (.) "),
    "ribbon": ("A ribbon", " ~o~ "),
    "cat": ("A cat", "/\\_/\\"),
    "bird": ("A bird", " >o< "),
    "rabbit": ("A rabbit", "(\\ /)"),
    "turtle": ("A turtle", " (~) "),
}
_CATALOG_DEFAULT = ("A small object", " (·) ")


def catalog_entry(catalog_id: str) -> tuple[str, str]:
    return ITEM_CATALOG.get(catalog_id, _CATALOG_DEFAULT)


def gift_catalog_entry(gift: GardenGift) -> tuple[str, str]:
    name, art = catalog_entry(gift.catalog_id)
    if gift.type == "animal" and gift.animal_name:
        name = gift.animal_name
    return name, art


_RECIPIENT_DIR = Path.home() / ".lateletter" / "recipient"
_RECEIPTS_FILE = _RECIPIENT_DIR / "receipts.json"


class RecipientStore:
    """Read-receipt owner only; Garden progression lives in ``WorldState``."""

    def __init__(self, bundle_id: str) -> None:
        self.bundle_id = bundle_id
        _RECIPIENT_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._receipts: dict[str, Any] = self._load(_RECEIPTS_FILE)
        self._receipts.setdefault(bundle_id, {})

    @staticmethod
    def _load(path: Path) -> dict[str, Any]:
        if path.exists():
            try:
                with path.open(encoding="utf-8") as handle:
                    value = json.load(handle)
                return value if isinstance(value, dict) else {}
            except (json.JSONDecodeError, OSError):
                return {}
        return {}

    def _save(self) -> None:
        temporary = _RECEIPTS_FILE.with_suffix(".tmp")
        try:
            with open(
                temporary,
                "w",
                encoding="utf-8",
                opener=lambda path, flags: os.open(path, flags, 0o600),
            ) as handle:
                json.dump(self._receipts, handle, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, _RECEIPTS_FILE)
        except OSError:
            temporary.unlink(missing_ok=True)

    def is_read(self, message_id: str) -> bool:
        return message_id in self._receipts.get(self.bundle_id, {})

    def mark_read(self, message_id: str) -> None:
        self._receipts[self.bundle_id][message_id] = {
            "read_at": date.today().isoformat(),
        }
        self._save()

    def read_set(self) -> set[str]:
        return set(self._receipts.get(self.bundle_id, {}))


def _b64decode(value: str) -> str:
    if not value:
        return ""
    try:
        return base64.b64decode(value).decode("utf-8")
    except Exception:
        return ""


def _decode_message(message: Message) -> tuple[str, str]:
    try:
        payload = json.loads(_b64decode(message.ciphertext))
        return str(payload.get("label", "")), str(payload.get("body", ""))
    except (json.JSONDecodeError, AttributeError):
        return "", ""


def _verify_passphrase(passphrase: str, bundle: Bundle, is_dev: bool) -> bool:
    if is_dev:
        return True
    try:
        return verify_bundle_hmac(bundle, passphrase)
    except Exception:
        return False


def _unlock_content(
    passphrase: str,
    bundle: Bundle,
    is_dev: bool,
) -> tuple[list[tuple[str, str]], dict[str, str]]:
    if is_dev:
        return (
            [_decode_message(message) for message in bundle.messages],
            {
                gift.id: _b64decode(gift.sentiment_ciphertext)
                for gift in bundle.garden_gifts
            },
        )
    messages = []
    for message in bundle.messages:
        opened = open_message(passphrase, message)
        messages.append((opened["label"], opened["body"]))
    gifts = {
        gift.id: open_gift_sentiment(passphrase, gift)
        for gift in bundle.garden_gifts
        if gift.sentiment_ciphertext
    }
    return messages, gifts


def _compute_due(bundle: Bundle, today: date, read_ids: set[str]) -> list[int]:
    due: list[int] = []
    for index, message in enumerate(bundle.messages):
        try:
            available = today >= date.fromisoformat(message.date)
        except ValueError:
            available = False
        if available and message.id not in read_ids:
            due.append(index)
    return due


def _is_post_complete(bundle: Bundle, read_ids: set[str]) -> bool:
    return bool(bundle.messages) and all(message.id in read_ids for message in bundle.messages)


def _sync_story_completion(
    session: TerminalWorldSession,
    bundle: Bundle,
    read_ids: set[str],
) -> bool:
    """Transfer authenticated receipt completion into canonical Garden state."""
    if not _is_post_complete(bundle, read_ids):
        return False
    return session.mark_story_complete()


_ArchiveRow = tuple[str, Any, Any]


def _build_archive_rows(
    bundle: Bundle,
    eligible_gift_ids: set[str],
    *,
    post_complete: bool = False,
) -> list[_ArchiveRow]:
    """Build archive rows from canonical eligibility receipts only."""
    rows: list[_ArchiveRow] = [
        ("letter", index, message)
        for index, message in enumerate(bundle.messages)
    ]
    gifts = [
        gift for gift in bundle.garden_gifts
        if post_complete or gift.id in eligible_gift_ids
    ]
    if gifts:
        rows.append(("divider", None, None))
        rows.extend(("gift", gift.id, gift) for gift in gifts)
    return rows


def _selectable(rows: list[_ArchiveRow]) -> list[int]:
    return [index for index, row in enumerate(rows) if row[0] != "divider"]


def _clamp_scroll(
    selected: int,
    selectable: list[int],
    scroll: int,
    visible_count: int,
) -> int:
    if not selectable:
        return 0
    absolute = selectable[selected]
    if absolute < scroll:
        return absolute
    if absolute >= scroll + visible_count:
        return absolute - visible_count + 1
    return scroll


def _eligible_legacy_gift_ids(program_state: Mapping[str, Any]) -> set[str]:
    result: set[str] = set()
    for receipt in program_state.get("applied_occurrences", []):
        event_id = str(receipt).split("@", 1)[0]
        if event_id.startswith("legacy."):
            result.add(event_id[len("legacy."):])
    return result


def _program_now(session: TerminalWorldSession, today: date) -> datetime:
    observed = session.world.last_observed_wall_time
    current = datetime.fromtimestamp(
        observed if observed is not None else int(time.time()), tz=timezone.utc,
    )
    return current.replace(year=today.year, month=today.month, day=today.day)


def _apply_program_to_session(
    session: TerminalWorldSession,
    program: GardenProgram,
    *,
    today: date,
    read_ids: set[str],
    due_letter_ids: tuple[str, ...] = (),
) -> None:
    now = _program_now(session, today)
    absence = max(0, session.offline_report.elapsed_seconds)
    last_seen = now - timedelta(seconds=max(60, absence))
    scheduled = eligible_occurrences(
        program, last_seen_utc=last_seen, now_utc=now,
    )
    facts = build_runtime_facts(
        session.world,
        program,
        now_utc=now,
        total_visits=session.total_visits,
        absence_seconds=absence,
        read_ids=read_ids,
        due_letter_ids=due_letter_ids,
    )
    result = apply_program(session.world, program, facts=facts, eligible=scheduled)
    session.world = result.world
    session.save()


def _apply_legacy_gifts(
    session: TerminalWorldSession,
    bundle: Bundle,
    gift_content: Mapping[str, str],
    today: date,
    read_ids: set[str],
) -> set[str]:
    """Compatibility wrapper: migrate v1 then use the general program adapter."""
    program = migrate_legacy_gifts(
        bundle.garden_gifts,
        authenticated=True,
        decrypted_sentiments=gift_content,
        message_ids=[message.id for message in bundle.messages],
    )
    return _apply_open_program(
        session, bundle, program, today=today, read_ids=read_ids,
    )


def _apply_open_program(
    session: TerminalWorldSession,
    bundle: Bundle,
    program: GardenProgram,
    *,
    today: date,
    read_ids: set[str],
    due_letter_ids: tuple[str, ...] = (),
) -> set[str]:
    """Apply an already-authenticated v1 or v2 program through one owner."""
    old_ledger = [
        receipt for receipt in session.world.milestone_receipts
        if receipt.startswith("legacy.")
    ]
    if old_ledger and not session.world.program_state.get("applied_occurrences"):
        session.world = replace(
            session.world,
            program_state={"applied_occurrences": old_ledger},
        )
    _apply_program_to_session(
        session, program, today=today, read_ids=read_ids,
        due_letter_ids=due_letter_ids,
    )
    if bundle.version < 2:
        return _eligible_legacy_gift_ids(session.world.program_state)
    return set()


def _open_authenticated_program(
    passphrase: str,
    bundle: Bundle,
    gift_content: Mapping[str, str],
) -> GardenProgram:
    if bundle.version >= 2:
        if bundle.garden_program is None:
            raise ValueError("version 2 bundle is missing its Garden program")
        return parse_program(open_garden_program(passphrase, bundle.garden_program))
    return migrate_legacy_gifts(
        bundle.garden_gifts,
        authenticated=True,
        decrypted_sentiments=gift_content,
        message_ids=[message.id for message in bundle.messages],
    )


def _reapply_after_semantic_change(
    session: TerminalWorldSession,
    bundle: Bundle,
    program: GardenProgram,
    result: CommandResult,
    *,
    today: date,
    read_ids: set[str],
    due_letter_ids: tuple[str, ...] = (),
) -> set[str] | None:
    if not result.accepted or not result.changed:
        return None
    return _apply_open_program(
        session, bundle, program, today=today, read_ids=read_ids,
        due_letter_ids=due_letter_ids,
    )


def _draw_centered(screen: curses.window, row: int, text: str, attr: int = 0) -> None:
    height, width = screen.getmaxyx()
    if not 0 <= row < height:
        return
    value = text[:max(0, width - 2)]
    try:
        screen.addstr(row, max(0, (width - len(value)) // 2), value, attr)
    except curses.error:
        pass


def _draw_panel(
    screen: curses.window,
    title: str,
    lines: list[str],
    footer: str,
) -> None:
    height, width = screen.getmaxyx()
    panel_width = min(68, max(20, width - 4))
    wrapped: list[str] = []
    for line in lines:
        wrapped.extend(textwrap.wrap(line, max(1, panel_width - 4)) or [""])
    visible = wrapped[:max(1, height - 8)]
    top = max(1, (height - len(visible) - 5) // 2)
    _draw_centered(screen, top, title, curses.A_BOLD)
    for index, line in enumerate(visible, start=1):
        _draw_centered(screen, top + index + 1, line)
    _draw_centered(screen, min(height - 2, top + len(visible) + 3), footer, curses.A_DIM)


def _save_to_text(bundle: Bundle, message: Message, label: str, body: str) -> Path:
    desktop = Path.home() / "Desktop"
    desktop.mkdir(exist_ok=True)
    safe_label = "".join(char if char.isalnum() else "-" for char in label).strip("-") or message.id
    path = desktop / f"{safe_label}.txt"
    path.write_text(f"From {bundle.author_name}\n{label}\n\n{body}\n", encoding="utf-8")
    return path


_ST_GARDEN = "garden"
_ST_PASSPHRASE = "passphrase"
_ST_SELECTION = "selection"
_ST_READING = "reading"
_ST_ARCHIVE = "archive"
_ST_MEMORY = "memory"
_ST_CORRUPTED = "corrupted"


def run_recipient(
    stdscr: curses.window,
    bundle: Bundle,
    store: RecipientStore,
    season: str | None = None,
    is_dev_fixture: bool = False,
    corrupted: bool = False,
    *,
    world_path: str | Path | None = None,
    observed_wall_time: int | None = None,
) -> None:
    """Run letters over a persistent canonical Garden terminal session."""
    del season
    curses.curs_set(0)
    stdscr.timeout(100)
    height, width = stdscr.getmaxyx()
    session = TerminalWorldSession.open(
        world_id=bundle.bundle_id,
        seed=bundle.garden_seed,
        width=width,
        height=height,
        path=world_path,
        observed_wall_time=observed_wall_time,
    )
    renderer = GardenRenderer(width, height)
    today = date.today()
    state = _ST_CORRUPTED if corrupted else _ST_GARDEN
    authenticated = False
    passphrase = ""
    error = ""
    status = "e unlocks letters · o selects a Garden object"
    message_content: list[tuple[str, str]] = [("", "") for _ in bundle.messages]
    gift_content: dict[str, str] = {}
    read_ids = store.read_set()
    due: list[int] = []
    eligible_gifts: set[str] = set()
    active_program: GardenProgram | None = None
    selected = 0
    reading_index = 0
    reading_scroll = 0
    archive_rows: list[_ArchiveRow] = []
    archive_selected = 0
    memory_gift: GardenGift | None = None

    while True:
        new_height, new_width = stdscr.getmaxyx()
        if (new_height, new_width) != (height, width):
            height, width = new_height, new_width
            session.resize(width, height)
            renderer.resize(width, height)
        stdscr.erase()
        renderer.blit_curses(stdscr, session.world)

        if state == _ST_CORRUPTED:
            _draw_panel(stdscr, "This file appears damaged.", ["The letters inside may not be readable."], "q quit")
        elif state == _ST_PASSPHRASE:
            lines = [f"Passphrase: {'*' * len(passphrase)}"]
            if bundle.passphrase_hint:
                lines.append(f"Hint: {bundle.passphrase_hint}")
            if error:
                lines.append(error)
            _draw_panel(stdscr, f"Letters from {bundle.author_name}", lines, "enter unlock · esc cancel")
        elif state == _ST_SELECTION:
            lines = [
                ("> " if index == selected else "  ") + bundle.messages[msg_index].date
                for index, msg_index in enumerate(due)
            ]
            _draw_panel(stdscr, "Letters waiting", lines, "↑/↓ select · enter read · esc return")
        elif state == _ST_READING:
            label, body = message_content[reading_index]
            lines = body.splitlines()[reading_scroll:]
            _draw_panel(stdscr, f"From {bundle.author_name}: {label}", lines, "↑/↓ scroll · p save · esc return")
        elif state == _ST_ARCHIVE:
            selectable = _selectable(archive_rows)
            lines = []
            selected_row = selectable[archive_selected] if selectable else -1
            for index, row in enumerate(archive_rows):
                if row[0] == "divider":
                    lines.append("-- Memories --")
                elif row[0] == "letter":
                    marker = "> " if index == selected_row else "  "
                    lines.append(f"{marker}{row[2].date}")
                else:
                    marker = "> " if index == selected_row else "  "
                    lines.append(f"{marker}{gift_catalog_entry(row[2])[0]}")
            _draw_panel(stdscr, "Letters and memories", lines, "↑/↓ select · enter open · esc return")
        elif state == _ST_MEMORY and memory_gift is not None:
            _draw_panel(
                stdscr,
                gift_catalog_entry(memory_gift)[0],
                [gift_content.get(memory_gift.id, "(no memory text)")],
                "any key returns",
            )

        if state == _ST_GARDEN:
            lines = [
                status + (f" · {len(due)} letter(s) waiting" if due else ""),
                TERMINAL_HELP_LINES[0],
                TERMINAL_HELP_LINES[1] + (" · e letters · l archive" if authenticated else " · e unlock"),
            ]
        else:
            lines = ["", "", "q quit · esc return"]
        for offset, line in enumerate(lines):
            row = height - len(lines) + offset
            if row >= 0:
                try:
                    stdscr.addstr(row, 0, line[:width].ljust(width), curses.A_REVERSE)
                except curses.error:
                    pass
        stdscr.refresh()
        key = stdscr.getch()
        if key == -1:
            continue
        if state == _ST_CORRUPTED:
            if key == ord("q"):
                break
            continue
        if state == _ST_PASSPHRASE:
            if key == 27:
                state = _ST_GARDEN
            elif key in (10, 13):
                if _verify_passphrase(passphrase, bundle, is_dev_fixture):
                    try:
                        message_content, gift_content = _unlock_content(passphrase, bundle, is_dev_fixture)
                        active_program = _open_authenticated_program(passphrase, bundle, gift_content)
                        authenticated = True
                        read_ids = store.read_set()
                        due = _compute_due(bundle, today, read_ids)
                        eligible_gifts = _apply_open_program(
                            session,
                            bundle,
                            active_program,
                            today=today,
                            read_ids=read_ids,
                            due_letter_ids=tuple(bundle.messages[index].id for index in due),
                        )
                        _sync_story_completion(session, bundle, read_ids)
                        status = "Letters unlocked; Garden actions use the canonical command trace."
                        error = ""
                        state = _ST_GARDEN
                    except Exception:
                        error = "Could not unlock this bundle."
                else:
                    error = "Incorrect passphrase, or this file was modified."
                passphrase = ""
            elif key in (curses.KEY_BACKSPACE, 127, 8):
                passphrase = passphrase[:-1]
            elif 32 <= key < 127:
                passphrase += chr(key)
            continue
        if state == _ST_SELECTION:
            if key == 27:
                state = _ST_GARDEN
            elif key in (curses.KEY_UP, ord("k")):
                selected = max(0, selected - 1)
            elif key in (curses.KEY_DOWN, ord("j")):
                selected = min(len(due) - 1, selected + 1)
            elif key in (10, 13) and due:
                reading_index = due[selected]
                reading_scroll = 0
                state = _ST_READING
            continue
        if state == _ST_READING:
            if key in (27, ord("q")):
                store.mark_read(bundle.messages[reading_index].id)
                read_ids = store.read_set()
                due = _compute_due(bundle, today, read_ids)
                if active_program is not None:
                    eligible_gifts = _apply_open_program(
                        session,
                        bundle,
                        active_program,
                        today=today,
                        read_ids=read_ids,
                        due_letter_ids=tuple(bundle.messages[index].id for index in due),
                    )
                _sync_story_completion(session, bundle, read_ids)
                state = _ST_SELECTION if due else _ST_GARDEN
            elif key == ord("p"):
                label, body = message_content[reading_index]
                try:
                    path = _save_to_text(bundle, bundle.messages[reading_index], label, body)
                    status = f"Saved {path.name}"
                except OSError:
                    status = "Could not save the letter."
            elif key in (curses.KEY_DOWN, ord("j")):
                reading_scroll += 1
            elif key in (curses.KEY_UP, ord("k")):
                reading_scroll = max(0, reading_scroll - 1)
            continue
        if state == _ST_ARCHIVE:
            selectable = _selectable(archive_rows)
            if key == 27:
                state = _ST_GARDEN
            elif key in (curses.KEY_UP, ord("k")):
                archive_selected = max(0, archive_selected - 1)
            elif key in (curses.KEY_DOWN, ord("j")):
                archive_selected = min(max(0, len(selectable) - 1), archive_selected + 1)
            elif key in (10, 13) and selectable:
                row = archive_rows[selectable[archive_selected]]
                if row[0] == "letter":
                    reading_index = row[1]
                    reading_scroll = 0
                    state = _ST_READING
                else:
                    memory_gift = row[2]
                    session.dispatch("inspect", target_id=f"legacy-entity.{memory_gift.id}")
                    state = _ST_MEMORY
            continue
        if state == _ST_MEMORY:
            state = _ST_ARCHIVE
            continue

        if key == ord("q"):
            break
        if key == ord("e"):
            if not authenticated:
                state = _ST_PASSPHRASE
                error = ""
            elif due:
                if len(due) == 1:
                    reading_index = due[0]
                    reading_scroll = 0
                    state = _ST_READING
                else:
                    selected = 0
                    state = _ST_SELECTION
            else:
                status = "No letters today. This Garden is still yours."
            continue
        if key == ord("l") and authenticated:
            archive_rows = _build_archive_rows(
                bundle,
                eligible_gifts,
                post_complete=_is_post_complete(bundle, read_ids),
            )
            archive_selected = 0
            state = _ST_ARCHIVE
            continue
        result = handle_terminal_key(session, key)
        if result is not None:
            status = result.summary if result.accepted else result.reason
            if authenticated and active_program is not None:
                updated_eligibility = _reapply_after_semantic_change(
                    session,
                    bundle,
                    active_program,
                    result,
                    today=today,
                    read_ids=read_ids,
                    due_letter_ids=tuple(bundle.messages[index].id for index in due),
                )
                if updated_eligibility is not None:
                    eligible_gifts = updated_eligibility
            if key == ord("i") and session.focused_id() and session.focused_id().startswith("legacy-entity."):
                gift_id = session.focused_id()[len("legacy-entity."):]
                memory_gift = next((gift for gift in bundle.garden_gifts if gift.id == gift_id), None)
                if memory_gift is not None and gift_id in eligible_gifts:
                    state = _ST_MEMORY


def run_recipient_file(path: str | Path, season: str | None = None) -> None:
    bundle_path = Path(path)
    if not bundle_path.exists():
        print(f"  Error: file not found: {bundle_path}")
        raise SystemExit(1)
    try:
        bundle = read_bundle(bundle_path)
    except Exception as exc:
        print(f"  Error: could not read bundle: {exc}")
        raise SystemExit(1) from exc
    if not bundle.hmac:
        print(
            "  Error: unsigned bundles are accepted only through the "
            "explicit trusted development-fixture harness."
        )
        raise SystemExit(1)
    checksum_ok = verify_checksum(bundle)
    store = RecipientStore(bundle.bundle_id)
    curses.wrapper(
        run_recipient,
        bundle,
        store,
        season,
        False,
        not checksum_ok,
    )
