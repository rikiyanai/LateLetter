"""
Minimal curses draft editor (§8.4).

A simple text editor for composing or editing message drafts within the app.

Controls:
  - Arrow keys to navigate
  - Standard text editing (backspace, delete, enter for newlines)
  - Ctrl+S to save and return to the message list
  - Ctrl+X to discard the draft and return (with confirmation)
  - After save: lock confirmation "Encrypt this message? [y/N]"

External editor path:
  - If LATELETTER_EDITOR is set, or if --accessible mode is active, the draft
    is written to ~/.lateletter/author/drafts/<uuid>.txt (mode 0600) and opened
    in that editor instead.
  - Warns about editor swap/backup files on first use.

Draft files are stored in ~/.lateletter/author/drafts/ with mode 0600.
"""

from __future__ import annotations

import curses
import os
import subprocess
from pathlib import Path
from typing import Callable

from .session_store import AUTHOR_DIR


# ---------------------------------------------------------------------------
# Draft file management
# ---------------------------------------------------------------------------

_DIR_MODE = 0o700
_FILE_MODE = 0o600

DRAFTS_DIR = AUTHOR_DIR / "drafts"


def _ensure_drafts_dir(base_dir: Path | None = None) -> Path:
    """Create the drafts directory with secure permissions."""
    drafts = (base_dir / "drafts") if base_dir else DRAFTS_DIR
    drafts.mkdir(parents=True, exist_ok=True)
    os.chmod(drafts, _DIR_MODE)
    return drafts


def _draft_path(message_id: str, base_dir: Path | None = None) -> Path:
    """Return the path for a draft file."""
    drafts = _ensure_drafts_dir(base_dir)
    return drafts / f"{message_id}.txt"


def save_draft(message_id: str, content: str, base_dir: Path | None = None) -> Path:
    """Write draft content to a secure file atomically. Returns the file path.

    Uses temp-file + fsync + atomic rename to prevent data loss if
    the process is killed mid-write (same pattern as session_store).
    """
    path = _draft_path(message_id, base_dir)
    tmp = path.with_suffix(".tmp")
    try:
        fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, _FILE_MODE)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
        raise
    return path


def load_draft(message_id: str, base_dir: Path | None = None) -> str | None:
    """Read draft content from file. Returns None if not found."""
    path = _draft_path(message_id, base_dir)
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def delete_draft(message_id: str, base_dir: Path | None = None) -> None:
    """Securely delete a draft file (overwrite with random bytes + unlink).

    Uses O_NOFOLLOW to refuse symlinks — prevents a TOCTOU race where
    a symlink could redirect the overwrite to an arbitrary file.
    """
    path = _draft_path(message_id, base_dir)
    if not path.exists():
        return
    size = path.stat().st_size
    try:
        fd = os.open(str(path), os.O_WRONLY | os.O_NOFOLLOW)
    except OSError:
        # Symlink, permission error, or file vanished — unlink only
        path.unlink(missing_ok=True)
        return
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(os.urandom(max(size, 1)))
            fh.flush()
            os.fsync(fh.fileno())
    except OSError:
        pass  # best-effort overwrite; unlink still happens
    path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Curses editor
# ---------------------------------------------------------------------------

_COLOR_TEXT = 1
_COLOR_STATUS = 2
_COLOR_WARNING = 3


def _init_editor_colors() -> None:
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(_COLOR_TEXT, curses.COLOR_WHITE, -1)
    curses.init_pair(_COLOR_STATUS, curses.COLOR_BLACK, curses.COLOR_WHITE)
    curses.init_pair(_COLOR_WARNING, curses.COLOR_YELLOW, -1)


class _EditorState:
    """Mutable editor state: lines of text + cursor position."""

    def __init__(self, initial_text: str = "") -> None:
        if initial_text:
            self.lines = initial_text.split("\n")
        else:
            self.lines = [""]
        self.cy = 0   # cursor row
        self.cx = 0   # cursor column
        self.scroll_y = 0
        self.dirty = False

    @property
    def text(self) -> str:
        return "\n".join(self.lines)

    def _clamp_cursor(self) -> None:
        """Ensure cursor is within valid bounds."""
        self.cy = max(0, min(self.cy, len(self.lines) - 1))
        self.cx = max(0, min(self.cx, len(self.lines[self.cy])))

    def insert_char(self, ch: str) -> None:
        line = self.lines[self.cy]
        self.lines[self.cy] = line[:self.cx] + ch + line[self.cx:]
        self.cx += 1
        self.dirty = True

    def insert_newline(self) -> None:
        line = self.lines[self.cy]
        self.lines[self.cy] = line[:self.cx]
        self.lines.insert(self.cy + 1, line[self.cx:])
        self.cy += 1
        self.cx = 0
        self.dirty = True

    def backspace(self) -> None:
        if self.cx > 0:
            line = self.lines[self.cy]
            self.lines[self.cy] = line[:self.cx - 1] + line[self.cx:]
            self.cx -= 1
            self.dirty = True
        elif self.cy > 0:
            # Merge with previous line
            prev = self.lines[self.cy - 1]
            self.cx = len(prev)
            self.lines[self.cy - 1] = prev + self.lines[self.cy]
            del self.lines[self.cy]
            self.cy -= 1
            self.dirty = True

    def delete(self) -> None:
        line = self.lines[self.cy]
        if self.cx < len(line):
            self.lines[self.cy] = line[:self.cx] + line[self.cx + 1:]
            self.dirty = True
        elif self.cy < len(self.lines) - 1:
            # Merge with next line
            self.lines[self.cy] = line + self.lines[self.cy + 1]
            del self.lines[self.cy + 1]
            self.dirty = True

    def move_up(self) -> None:
        if self.cy > 0:
            self.cy -= 1
            self._clamp_cursor()

    def move_down(self) -> None:
        if self.cy < len(self.lines) - 1:
            self.cy += 1
            self._clamp_cursor()

    def move_left(self) -> None:
        if self.cx > 0:
            self.cx -= 1
        elif self.cy > 0:
            self.cy -= 1
            self.cx = len(self.lines[self.cy])

    def move_right(self) -> None:
        if self.cx < len(self.lines[self.cy]):
            self.cx += 1
        elif self.cy < len(self.lines) - 1:
            self.cy += 1
            self.cx = 0


def _draw_editor(
    stdscr: curses.window,
    state: _EditorState,
    status_msg: str = "",
) -> None:
    """Redraw the editor screen."""
    stdscr.erase()
    max_y, max_x = stdscr.getmaxyx()
    text_height = max_y - 2  # reserve 2 lines for status bar

    # Adjust scroll
    if state.cy < state.scroll_y:
        state.scroll_y = state.cy
    if state.cy >= state.scroll_y + text_height:
        state.scroll_y = state.cy - text_height + 1

    # Draw text
    for screen_row in range(text_height):
        line_idx = state.scroll_y + screen_row
        if line_idx < len(state.lines):
            line = state.lines[line_idx]
            stdscr.addnstr(screen_row, 0, line, max_x - 1, curses.color_pair(_COLOR_TEXT))

    # Status bar
    status_y = max_y - 2
    modified = " [modified]" if state.dirty else ""
    left = f" Line {state.cy + 1}, Col {state.cx + 1}{modified}"
    right = " Ctrl+S: save  Ctrl+X: discard "
    bar = left.ljust(max_x - len(right)) + right
    stdscr.addnstr(status_y, 0, bar[:max_x], max_x,
                   curses.color_pair(_COLOR_STATUS) | curses.A_BOLD)

    # Message line
    if status_msg:
        stdscr.addnstr(max_y - 1, 0, status_msg, max_x - 1,
                       curses.color_pair(_COLOR_WARNING))

    # Position cursor
    screen_cy = state.cy - state.scroll_y
    screen_cx = min(state.cx, max_x - 1)
    if 0 <= screen_cy < text_height:
        stdscr.move(screen_cy, screen_cx)

    stdscr.refresh()


def _confirm_prompt(stdscr: curses.window, prompt: str) -> bool:
    """Show a y/N prompt on the bottom line. Returns True for 'y'."""
    max_y, max_x = stdscr.getmaxyx()
    stdscr.addnstr(max_y - 1, 0, prompt, max_x - 1,
                   curses.color_pair(_COLOR_WARNING))
    stdscr.refresh()
    ch = stdscr.getch()
    return ch in (ord('y'), ord('Y'))


def _run_curses_editor(
    stdscr: curses.window,
    initial_text: str,
) -> tuple[str | None, bool]:
    """Run the curses editor loop.

    Returns (text, should_encrypt):
      - (text, True)  if the author saved and confirmed encryption
      - (text, False) if the author saved but declined encryption
      - (None, False) if the author discarded
    """
    _init_editor_colors()
    curses.curs_set(1)
    stdscr.keypad(True)

    state = _EditorState(initial_text)
    status_msg = ""

    while True:
        _draw_editor(stdscr, state, status_msg)
        status_msg = ""

        ch = stdscr.getch()

        # Ctrl+S — save
        if ch == 19:
            should_encrypt = _confirm_prompt(
                stdscr,
                "Encrypt this message? Once encrypted, it cannot be edited. [y/N] ",
            )
            return (state.text, should_encrypt)

        # Ctrl+X — discard
        if ch == 24:
            if state.dirty:
                if _confirm_prompt(stdscr, "Discard this draft? [y/N] "):
                    return (None, False)
            else:
                return (None, False)
            continue

        # Arrow keys
        if ch == curses.KEY_UP:
            state.move_up()
        elif ch == curses.KEY_DOWN:
            state.move_down()
        elif ch == curses.KEY_LEFT:
            state.move_left()
        elif ch == curses.KEY_RIGHT:
            state.move_right()

        # Home / End
        elif ch == curses.KEY_HOME:
            state.cx = 0
        elif ch == curses.KEY_END:
            state.cx = len(state.lines[state.cy])

        # Backspace
        elif ch in (curses.KEY_BACKSPACE, 127, 8):
            state.backspace()

        # Delete
        elif ch == curses.KEY_DC:
            state.delete()

        # Enter
        elif ch in (10, 13):
            state.insert_newline()

        # Printable characters
        elif 32 <= ch <= 126:
            state.insert_char(chr(ch))

        # Tab -> spaces
        elif ch == 9:
            for _ in range(4):
                state.insert_char(" ")


# ---------------------------------------------------------------------------
# External editor
# ---------------------------------------------------------------------------

_editor_warned = False


def _run_external_editor(
    message_id: str,
    initial_text: str,
    editor: str,
    base_dir: Path | None = None,
    output_fn: Callable[[str], None] | None = None,
) -> tuple[str | None, bool]:
    """Write draft to file, open in external editor, read back.

    Returns (text, should_encrypt) or (None, False) on discard.
    """
    out = output_fn or print

    # Warn about swap files on first use (best effort via env marker)
    global _editor_warned
    if not _editor_warned:
        out("")
        out("  Note: Your external editor may create swap or backup files.")
        out("  These could contain unencrypted draft text.")
        out("  Consider disabling editor backup artifacts for this directory.")
        out("")
        _editor_warned = True

    path = save_draft(message_id, initial_text, base_dir)
    out(f"  Draft saved to {path}")
    out(f"  Opening in {editor}...")

    try:
        subprocess.run([editor, str(path)], check=True, timeout=7200)
    except subprocess.TimeoutExpired:
        out("  Editor timed out after 2 hours. Draft is saved on disk.")
        out(f"  You can recover it from: {path}")
        return (None, False)
    except (subprocess.CalledProcessError, OSError) as exc:
        out(f"  Error opening editor: {exc}")
        return (None, False)

    # Read back
    content = load_draft(message_id, base_dir)
    if content is None:
        out("  Draft file was deleted by editor.")
        return (None, False)

    out("  Draft loaded from editor.")
    out("")

    # Encrypt confirmation (line mode)
    while True:
        try:
            answer = input("  Encrypt this message? Once encrypted, it cannot be edited. [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            answer = "n"
        if answer in ("y", "n", ""):
            break
    should_encrypt = (answer == "y")

    return (content, should_encrypt)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def edit_draft(
    message_id: str,
    initial_text: str = "",
    *,
    accessible: bool = False,
    base_dir: Path | None = None,
    output_fn: Callable[[str], None] | None = None,
) -> tuple[str | None, bool]:
    """Open the draft editor for a message.

    Uses the curses editor by default.  Falls back to external editor when:
      - LATELETTER_EDITOR is set
      - accessible=True (--accessible mode)

    Returns (saved_text, should_encrypt):
      - (text, True)  → author saved and confirmed encryption
      - (text, False) → author saved but declined encryption
      - (None, False) → author discarded the draft
    """
    editor = os.environ.get("LATELETTER_EDITOR", "")

    if editor or accessible:
        if not editor:
            editor = os.environ.get("EDITOR", "vi")
        return _run_external_editor(
            message_id, initial_text, editor, base_dir, output_fn
        )

    # Curses editor
    def _main(stdscr):
        return _run_curses_editor(stdscr, initial_text)

    return curses.wrapper(_main)
