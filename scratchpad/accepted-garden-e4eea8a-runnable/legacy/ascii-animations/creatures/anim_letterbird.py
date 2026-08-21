#!/usr/bin/env python3
"""Letter-bird delivery animation.

The letter-bird flies in from the right, carrying [✉],
and perches on a tree branch.

Per docs/SPEC.md §6.3: "Visually distinct from ambient bird,
carrying [✉] or folded letter glyph, perching on tree top."

Press 'q' to quit.
Run: python3 ascii-animations/creatures/anim_letterbird.py
"""
from __future__ import annotations
import curses
import time


FRAME_MS = 80

# Letter-bird flight frames (flying right to left)
BIRD_FLIGHT = [
    # Frame 0: wings up
    [
        r"  \( )/   ",
        r"   (o>    ",
        r"   /|[✉]  ",
        r"  / \     ",
    ],
    # Frame 1: wings level
    [
        r"           ",
        r"  __(o>_   ",
        r"   /|[✉]   ",
        r"  / \      ",
    ],
    # Frame 2: wings down
    [
        r"           ",
        r"   (o>     ",
        r"  /|\\[✉]  ",
        r"  / \\     ",
    ],
    # Frame 3: wings level
    [
        r"           ",
        r"  __(o>_   ",
        r"   /|[✉]   ",
        r"  / \      ",
    ],
]

# Perched bird
BIRD_PERCHED = [
    r"   (o>     ",
    r"  /| [✉]   ",
    r"  / \      ",
]

# Tree
TREE = [
    '       .~=~.       ',
    '      /:::::\\      ',
    '     /:::::::\\     ',
    '    |::::::::::|    ',
    '     \\:::::::/     ',
    '      \\:::::/      ',
    '    ~~~\\===/~~~    ',
    '        |||        ',
    '        |||        ',
    '        |||        ',
    '        |||        ',
]

PERCH_ROW = 6  # row in TREE where bird perches (the branch line)


class LetterBird:
    def __init__(self, start_x: int, target_x: int, target_y: int):
        self.x = float(start_x)
        self.y = float(target_y - 3)
        self.target_x = target_x
        self.target_y = target_y
        self.vx = -1.2
        self.frame_idx = 0
        self.frame_count = 0
        self.perched = False
        self.perch_time = 0.0

    def update(self) -> None:
        self.frame_count += 1

        if self.perched:
            return

        # Fly toward perch
        self.x += self.vx

        # Slow down as approaching
        dist = abs(self.x - self.target_x)
        if dist < 15:
            self.vx = max(-0.4, self.vx + 0.03)
        if dist < 5:
            self.vx = max(-0.2, self.vx + 0.02)

        # Approach vertically
        if self.y < self.target_y:
            self.y += 0.15

        # Flap
        if self.frame_count % 3 == 0:
            self.frame_idx = (self.frame_idx + 1) % len(BIRD_FLIGHT)

        # Check if perched
        if dist < 2:
            self.perched = True
            self.x = float(self.target_x)
            self.y = float(self.target_y)
            self.perch_time = time.monotonic()


def main(stdscr):
    curses.curs_set(0)
    stdscr.timeout(FRAME_MS)
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_GREEN, -1)     # tree
    curses.init_pair(2, curses.COLOR_YELLOW, -1)     # bird
    curses.init_pair(3, curses.COLOR_RED, -1)        # letter
    curses.init_pair(4, curses.COLOR_CYAN, -1)       # message

    h, w = stdscr.getmaxyx()
    ground = h - 3
    tree_x = w // 2
    tree_top = ground - len(TREE)
    perch_y = tree_top + PERCH_ROW - 1
    perch_x = tree_x + 8

    bird = LetterBird(w + 10, perch_x, perch_y)

    message_shown = False
    message_alpha = 0.0

    while True:
        key = stdscr.getch()
        if key in (ord('q'), ord('Q'), 27, 32):  # q/esc/space
            return
        # Reset with 'r'
        if key in (ord('r'), ord('R')):
            bird = LetterBird(w + 10, perch_x, perch_y)
            message_shown = False
            message_alpha = 0.0

        bird.update()

        stdscr.erase()

        # Ground
        for c in range(w):
            try:
                stdscr.addch(ground, c, '_', curses.A_DIM)
            except curses.error:
                pass

        # Tree
        for i, line in enumerate(TREE):
            r = tree_top + i
            cx = tree_x - len(line) // 2
            for j, ch in enumerate(line):
                cc = cx + j
                if ch != ' ' and 0 <= r < h and 0 <= cc < w:
                    attr = curses.color_pair(1)
                    if ch in '|':
                        attr = curses.color_pair(1) | curses.A_DIM
                    elif ch in '.~=':
                        attr = curses.color_pair(1) | curses.A_BOLD
                    try:
                        stdscr.addch(r, cc, ch, attr)
                    except curses.error:
                        pass

        # Bird
        ix, iy = int(bird.x), int(bird.y)
        if bird.perched:
            for di, line in enumerate(BIRD_PERCHED):
                r = iy - 1 + di
                for j, ch in enumerate(line):
                    cc = ix - 3 + j
                    if ch != ' ' and 0 <= r < h and 0 <= cc < w:
                        attr = curses.color_pair(3) if ch in '✉[]' else curses.color_pair(2)
                        try:
                            stdscr.addch(r, cc, ch, attr | curses.A_BOLD)
                        except curses.error:
                            pass

            # Show message after perching for 2 seconds
            now = time.monotonic()
            if now - bird.perch_time > 2.0 and not message_shown:
                message_shown = True

            if message_shown:
                msg_lines = [
                    '╔══════════════════════════════╗',
                    '║   a letter has arrived       ║',
                    '║                              ║',
                    '║   press i to read            ║',
                    '╚══════════════════════════════╝',
                ]
                msg_y = h // 2 - 2
                msg_x = w // 2 - 16
                for mi, ml in enumerate(msg_lines):
                    r = msg_y + mi
                    if 0 <= r < h:
                        try:
                            stdscr.addstr(r, max(0, msg_x), ml[:w-1],
                                          curses.color_pair(4) | curses.A_BOLD)
                        except curses.error:
                            pass
        else:
            # Flying bird
            frame = BIRD_FLIGHT[bird.frame_idx]
            for di, line in enumerate(frame):
                r = iy - 1 + di
                for j, ch in enumerate(line):
                    cc = ix - 4 + j
                    if ch != ' ' and 0 <= r < h and 0 <= cc < w:
                        attr = curses.color_pair(3) if ch in '✉[]' else curses.color_pair(2)
                        try:
                            stdscr.addch(r, cc, ch, attr | curses.A_BOLD)
                        except curses.error:
                            pass

        # Status bar
        state = 'perched' if bird.perched else 'flying'
        status = f' Letter-Bird · {state} · r=replay · q=quit '
        try:
            stdscr.addstr(h - 1, 0, status[:w-1], curses.A_DIM)
        except curses.error:
            pass

        stdscr.refresh()


if __name__ == '__main__':
    curses.wrapper(main)
