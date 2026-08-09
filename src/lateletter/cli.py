"""
LateLetter CLI entry point.

Usage:
  lateletter --garden [--season]  Show the garden animation (existing)

Browser authoring is served by the separate ``lateletter-author`` entrypoint.
This command deliberately has no author/export mode: sealed bundle construction
belongs exclusively to ``lateletter.author_service``.
"""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    command_args = list(sys.argv[1:] if argv is None else argv)
    if command_args and command_args[0] in {"transcribe", "accept"}:
        return _transcription_command(command_args)
    parser = argparse.ArgumentParser(
        prog="lateletter",
        description="Letters for people you love, delivered after you're gone.",
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
