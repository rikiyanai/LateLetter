#!/usr/bin/env python3
"""
garden.py — Procedural ASCII flower garden
  python garden.py             interactive TUI (curses, animated wind)
  python garden.py --ansi      static ANSI frame to stdout
  python garden.py --seed N    reproducible garden
  python garden.py --season S  override season (spring/summer/autumn/winter)
  python garden.py --width W --height H  (with --ansi)
Keys: q quit · o objects · a actions · semantic command help is always visible
"""

import argparse
import curses
import shutil
import sys
from pathlib import Path

# Ensure src/ is importable when running from project root
sys.path.insert(0, str(Path(__file__).resolve().parent / 'src'))

from lateletter.garden.renderer import print_ansi, run_curses  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description='Procedural ASCII flower garden')
    ap.add_argument('file', nargs='?', default=None,
                    help='.lateletter bundle file (recipient mode)')
    ap.add_argument('--seed', type=int, default=42301)
    ap.add_argument('--ansi', action='store_true', help='print static frame to stdout')
    ap.add_argument('--season', type=str, default=None,
                    choices=['spring', 'summer', 'autumn', 'winter'],
                    help='override season (default: from system date)')
    term = shutil.get_terminal_size()
    ap.add_argument('--width', type=int, default=term.columns)
    ap.add_argument('--height', type=int, default=term.lines)
    args = ap.parse_args()

    if args.file:
        from lateletter.recipient import run_recipient_file
        run_recipient_file(args.file, season=args.season)
    elif args.ansi:
        print_ansi(args.width, args.height, args.seed, season=args.season)
    else:
        curses.wrapper(run_curses, args.seed, args.season)


if __name__ == '__main__':
    main()
