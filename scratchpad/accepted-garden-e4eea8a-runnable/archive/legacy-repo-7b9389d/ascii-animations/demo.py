#!/usr/bin/env python3
"""LateLetter ASCII Animation Demo.

Plays each animation in sequence with title cards between them.
Press SPACE to start the next animation. Inside an animation,
press SPACE to skip to the next one. Press 'q' to quit entirely.

Run: python3 ascii-animations/demo.py
"""
from __future__ import annotations
import curses
import os
import subprocess
import sys
import time

DEMOS = [
    ('Falling Leaves',        'nature/anim_leaves.py',       'Autumn'),
    ('Rain + Lightning',      'weather/anim_rain.py',        'Storm'),
    ('Snow',                  'weather/anim_snow.py',        'Winter'),
    ('Fireflies',             'creatures/anim_fireflies.py', 'Summer Night'),
    ('Birds Flying',          'creatures/anim_birds.py',     'Ambient'),
    ('Butterfly',             'creatures/anim_butterfly.py', 'Spring'),
    ('Letter-Bird Delivery',  'creatures/anim_letterbird.py','Recipient Mode'),
    ('Cloud Drift',           'weather/anim_clouds.py',      'Sky'),
    ('Garden Scene',          'anim_garden.py',              'All Seasons'),
]

BASE = os.path.dirname(os.path.abspath(__file__))

TITLE_ART = r"""
          .
    _/ \ / \ / \_        LateLetter
  _\ \ .'- -'. / /_      ASCII Animation Demo
 \_ \,___   ___,/ _/
< _ ( \__)-(__/ ) _ >    {count} animations
 /_  -  .___.  -  _\
  /_ / -.. ..- \ _\      SPACE = play next
     \ / \ / \ /          q     = quit
"""

CARD_BORDER = '═'


def draw_title(stdscr, h: int, w: int) -> None:
    """Draw the main title screen."""
    stdscr.erase()

    art = TITLE_ART.format(count=len(DEMOS))
    lines = art.strip('\n').split('\n')

    start_r = max(0, (h - len(lines) - 6) // 2)

    # Top border
    border = CARD_BORDER * min(50, w - 2)
    try:
        stdscr.addstr(start_r, max(0, (w - len(border)) // 2),
                      border, curses.A_DIM)
    except curses.error:
        pass

    # Art
    for i, line in enumerate(lines):
        r = start_r + 1 + i
        c = max(0, (w - len(line)) // 2)
        if 0 <= r < h:
            try:
                stdscr.addstr(r, c, line[:w - 1],
                              curses.color_pair(1) | curses.A_BOLD)
            except curses.error:
                pass

    # Demo list
    list_r = start_r + len(lines) + 2
    for idx, (name, _, season) in enumerate(DEMOS):
        r = list_r + idx
        if 0 <= r < h - 2:
            num = f'  {idx + 1}. '
            label = f'{name}  ({season})'
            try:
                stdscr.addstr(r, max(0, (w - 40) // 2), num[:w - 1],
                              curses.A_DIM)
                stdscr.addstr(r, max(0, (w - 40) // 2) + len(num),
                              label[:w - len(num) - 1],
                              curses.color_pair(2))
            except curses.error:
                pass

    # Bottom border
    br = list_r + len(DEMOS) + 1
    if 0 <= br < h:
        try:
            stdscr.addstr(br, max(0, (w - len(border)) // 2),
                          border, curses.A_DIM)
        except curses.error:
            pass

    stdscr.refresh()


def draw_card(stdscr, h: int, w: int, idx: int,
              name: str, season: str) -> None:
    """Draw a title card before an animation starts."""
    stdscr.erase()

    mid_r = h // 2

    # Number / total
    counter = f'{idx + 1} / {len(DEMOS)}'
    try:
        stdscr.addstr(mid_r - 4, (w - len(counter)) // 2,
                      counter, curses.A_DIM)
    except curses.error:
        pass

    # Season tag
    try:
        stdscr.addstr(mid_r - 2, (w - len(season)) // 2,
                      season, curses.color_pair(2) | curses.A_DIM)
    except curses.error:
        pass

    # Name
    try:
        stdscr.addstr(mid_r, (w - len(name)) // 2,
                      name, curses.color_pair(1) | curses.A_BOLD)
    except curses.error:
        pass

    # Separator
    sep = '─' * min(30, w - 4)
    try:
        stdscr.addstr(mid_r + 2, (w - len(sep)) // 2, sep, curses.A_DIM)
    except curses.error:
        pass

    # Hint
    hint = 'SPACE  play  ·  q  quit'
    try:
        stdscr.addstr(mid_r + 4, (w - len(hint)) // 2,
                      hint, curses.A_DIM)
    except curses.error:
        pass

    stdscr.refresh()


def draw_end(stdscr, h: int, w: int) -> None:
    """Draw the end screen."""
    stdscr.erase()
    mid_r = h // 2

    msg = 'All animations complete.'
    try:
        stdscr.addstr(mid_r - 1, (w - len(msg)) // 2,
                      msg, curses.color_pair(1) | curses.A_BOLD)
    except curses.error:
        pass
    hint = 'SPACE  replay  ·  q  quit'
    try:
        stdscr.addstr(mid_r + 1, (w - len(hint)) // 2, hint, curses.A_DIM)
    except curses.error:
        pass
    stdscr.refresh()


def run_demo(script: str) -> None:
    """Run an animation script as a subprocess."""
    path = os.path.join(BASE, script)
    if os.path.exists(path):
        subprocess.run([sys.executable, path])


def main(stdscr) -> None:
    curses.curs_set(0)
    stdscr.timeout(-1)  # blocking
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_GREEN, -1)
    curses.init_pair(2, curses.COLOR_YELLOW, -1)
    curses.init_pair(3, curses.COLOR_CYAN, -1)

    h, w = stdscr.getmaxyx()
    idx = 0

    # Title screen
    draw_title(stdscr, h, w)
    while True:
        key = stdscr.getch()
        if key in (ord('q'), ord('Q'), 27):
            return
        if key == 32:  # space
            break

    # Play through demos
    while idx < len(DEMOS):
        h, w = stdscr.getmaxyx()
        name, script, season = DEMOS[idx]

        # Show title card
        draw_card(stdscr, h, w, idx, name, season)

        # Wait for space or q
        while True:
            key = stdscr.getch()
            if key in (ord('q'), ord('Q'), 27):
                return
            if key == 32:  # space
                break

        # Run the animation (curses.endwin lets subprocess take over)
        curses.endwin()
        run_demo(script)
        # Re-init curses after subprocess
        stdscr = curses.initscr()
        curses.curs_set(0)
        curses.noecho()
        curses.cbreak()
        stdscr.keypad(True)
        stdscr.timeout(-1)
        curses.start_color()
        curses.use_default_colors()
        curses.init_pair(1, curses.COLOR_GREEN, -1)
        curses.init_pair(2, curses.COLOR_YELLOW, -1)
        curses.init_pair(3, curses.COLOR_CYAN, -1)

        idx += 1

    # End screen
    h, w = stdscr.getmaxyx()
    draw_end(stdscr, h, w)
    while True:
        key = stdscr.getch()
        if key in (ord('q'), ord('Q'), 27):
            return
        if key == 32:  # space — replay
            idx = 0
            draw_title(stdscr, h, w)
            while True:
                key = stdscr.getch()
                if key in (ord('q'), ord('Q'), 27):
                    return
                if key == 32:
                    break


if __name__ == '__main__':
    curses.wrapper(main)
