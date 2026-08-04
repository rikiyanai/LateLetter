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
import getpass
import sys
from typing import Callable

from .intake import check_session_corruption, load_intake
from .session_store import SessionStore


def main(argv: list[str] | None = None) -> int:
    command_args = list(sys.argv[1:] if argv is None else argv)
    if command_args and command_args[0] in {"transcribe", "accept"}:
        return _transcription_command(command_args)
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

    args = parser.parse_args(command_args)

    if args.wipe_session:
        return _wipe_session()

    if args.write:
        return _author_mode(accessible=args.accessible)

    if args.garden:
        return _garden_mode(season=args.season)

    parser.print_help()
    return 0


def _transcription_command(argv: list[str]) -> int:
    """Run the canonical screenshot-transcription command surface."""

    import json

    from .transcription import AttemptError, accept, transcribe

    command = argv[0]
    if command == "transcribe":
        parser = argparse.ArgumentParser(prog="lateletter transcribe")
        parser.add_argument("source_png")
        parser.add_argument("--attempt-root", required=True)
        parser.add_argument("--attempt-id", required=True)
        args = parser.parse_args(argv[1:])
        try:
            result = transcribe(args.source_png, args.attempt_root, args.attempt_id)
        except (AttemptError, OSError, ValueError) as exc:
            print(f"transcribe rejected: {exc}", file=sys.stderr)
            return 2
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0

    parser = argparse.ArgumentParser(prog="lateletter accept")
    parser.add_argument("attempt_dir")
    parser.add_argument("--receipt", required=True)
    args = parser.parse_args(argv[1:])
    try:
        result = accept(args.attempt_dir, args.receipt)
    except (AttemptError, OSError, ValueError) as exc:
        print(f"accept rejected: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


def _author_mode(
    accessible: bool = False,
    *,
    input_fn: Callable[[str], str] = input,
    password_fn: Callable[[str], str] = getpass.getpass,
    output_fn: Callable[[str], None] = print,
) -> int:
    """Run the author mode flow."""
    store = SessionStore()

    if check_session_corruption(store):
        output_fn("")
        output_fn("  WARNING: Your session file was corrupted and could not be read.")
        output_fn("  A backup was saved with a .corrupt extension.")
        output_fn("  Starting with a fresh intake form. Your prior data may be")
        output_fn("  recoverable from the backup file.")
        output_fn("")

    existing = load_intake(store)

    if accessible:
        from .intake_accessible import run_intake_accessible
        result = run_intake_accessible(
            store,
            existing,
            input_fn=input_fn,
            password_fn=password_fn,
            output_fn=output_fn,
        )
    else:
        try:
            from .intake_tui import run_intake_tui
            result = run_intake_tui(store, existing)
        except (ImportError, curses.error):
            # Curses unavailable — fall back to accessible mode
            from .intake_accessible import run_intake_accessible
            result = run_intake_accessible(
                store,
                existing,
                input_fn=input_fn,
                password_fn=password_fn,
                output_fn=output_fn,
            )

    if result is None:
        output_fn("  Exited without saving.")
        return 0

    data, passphrase = result
    output_fn(f"  Welcome, {data.author_name}.")
    output_fn(f"  Writing letters for {data.recipient_name}.")
    output_fn("")
    from .author import run_author_workflow
    return run_author_workflow(
        store,
        data,
        passphrase,
        accessible=accessible,
        input_fn=input_fn,
        password_fn=password_fn,
        output_fn=output_fn,
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
