"""Color management for curses and ANSI rendering."""
from __future__ import annotations

import curses

# ── ANSI escape codes (fg only, no backgrounds) ─────────────────────
ANSI_CODES: dict[str, str] = {
    'sky':            '',
    'green':          '\033[32m',
    'bright_green':   '\033[1;32m',
    'yellow':         '\033[33m',
    'bright_yellow':  '\033[1;33m',
    'red':            '\033[31m',
    'bright_red':     '\033[1;31m',
    'magenta':        '\033[35m',
    'bright_magenta': '\033[1;35m',
    'cyan':           '\033[36m',
    'bright_cyan':    '\033[1;36m',
    'white':          '\033[37m',
    'bright_white':   '\033[1;37m',
    'ground':         '\033[1;32m',
    'dim_green':      '\033[2;32m',
    'brown':          '\033[33m',
}

ANSI_RESET = '\033[0m'

# ── Curses color pairs ──────────────────────────────────────────────
_pair_ids: dict[str, int] = {}

_CURSES_FG = {
    'green':          curses.COLOR_GREEN,
    'bright_green':   curses.COLOR_GREEN,
    'yellow':         curses.COLOR_YELLOW,
    'bright_yellow':  curses.COLOR_YELLOW,
    'red':            curses.COLOR_RED,
    'bright_red':     curses.COLOR_RED,
    'magenta':        curses.COLOR_MAGENTA,
    'bright_magenta': curses.COLOR_MAGENTA,
    'cyan':           curses.COLOR_CYAN,
    'bright_cyan':    curses.COLOR_CYAN,
    'white':          curses.COLOR_WHITE,
    'bright_white':   curses.COLOR_WHITE,
    'brown':          curses.COLOR_YELLOW,
    'ground':         curses.COLOR_GREEN,
    'dim_green':      curses.COLOR_GREEN,
}


def init_curses_colors() -> None:
    """Initialize curses color pairs. Call once after curses.initscr()."""
    curses.start_color()
    curses.use_default_colors()
    pid = 1
    for name, fg in _CURSES_FG.items():
        curses.init_pair(pid, fg, -1)
        _pair_ids[name] = pid
        pid += 1


def curses_attr(color_name: str) -> int:
    """Return the curses attribute integer for a named color."""
    pid = _pair_ids.get(color_name, 1)
    bold = 'bright' in color_name or color_name == 'ground'
    return curses.color_pair(pid) | (curses.A_BOLD if bold else 0)
