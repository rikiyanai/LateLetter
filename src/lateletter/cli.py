"""
LateLetter CLI entry point.

Usage:
  lateletter --write              Start or resume author mode
  lateletter --write --accessible Use accessible line-mode (no curses)
  lateletter --garden [--season]  Show the garden animation (existing)

Author mode flow:
  1. Intake form (§5.1) — first launch or returning to edit
  2. Message list (§5.2) — pick a slot
  3. Q&A session (§5.3) — guided interview
  4. Draft editor (§8.4) — compose/edit the letter
  5. Export (§5.4) — encrypt and bundle
"""

from __future__ import annotations

import argparse
import curses
import sys

from .intake import check_session_corruption, load_intake
from .session_store import SessionStore


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="lateletter",
        description="Letters for people you love, delivered after you're gone.",
    )
    parser.add_argument(
        "--write", action="store_true",
        help="Start or resume author mode",
    )
    parser.add_argument(
        "--accessible", action="store_true",
        help="Use accessible line-mode (no curses)",
    )
    parser.add_argument(
        "--garden", action="store_true",
        help="Show the garden animation",
    )
    parser.add_argument(
        "--season", type=str, default=None,
        help="Override garden season (spring, summer, autumn, winter)",
    )
    parser.add_argument(
        "--wipe-session", action="store_true",
        help="Delete all author storage",
    )

    args = parser.parse_args(argv)

    if args.wipe_session:
        return _wipe_session()

    if args.write:
        return _author_mode(accessible=args.accessible)

    if args.garden:
        return _garden_mode(season=args.season)

    parser.print_help()
    return 0


def _author_mode(accessible: bool = False) -> int:
    """Run the author mode flow."""
    store = SessionStore()

    if check_session_corruption(store):
        print()
        print("  WARNING: Your session file was corrupted and could not be read.")
        print("  A backup was saved with a .corrupt extension.")
        print("  Starting with a fresh intake form. Your prior data may be")
        print("  recoverable from the backup file.")
        print()

    existing = load_intake(store)

    if accessible:
        from .intake_accessible import run_intake_accessible
        result = run_intake_accessible(store, existing)
    else:
        try:
            from .intake_tui import run_intake_tui
            result = run_intake_tui(store, existing)
        except (ImportError, curses.error):
            # Curses unavailable — fall back to accessible mode
            from .intake_accessible import run_intake_accessible
            result = run_intake_accessible(store, existing)

    if result is None:
        print("  Exited without saving.")
        return 0

    data, passphrase = result
    print(f"  Welcome, {data.author_name}.")
    print(f"  Writing letters for {data.recipient_name}.")
    print()
    from .author import run_author_workflow
    return run_author_workflow(
        store, data, passphrase, accessible=accessible,
    )


def _garden_mode(season: str | None = None) -> int:
    """Run the garden animation."""
    try:
        from .garden import run_garden
        run_garden(season_override=season)
    except ImportError:
        print("  Garden module not available.")
        return 1
    return 0


def _wipe_session() -> int:
    """Delete all author storage."""
    import shutil
    from .session_store import AUTHOR_DIR
    if not AUTHOR_DIR.exists():
        print("  No author storage found.")
        return 0
    print(f"  This will permanently delete: {AUTHOR_DIR}")
    try:
        confirm = input("  Are you sure? [y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return 0
    if confirm != "y":
        print("  Cancelled.")
        return 0
    shutil.rmtree(AUTHOR_DIR)
    print("  Author storage deleted.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
