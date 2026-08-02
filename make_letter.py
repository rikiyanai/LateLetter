#!/usr/bin/env python3
"""
make_letter.py — seal a real, passcode-gated .lateletter bundle.

Usage:
    python3 make_letter.py /safe/private/source.json /safe/private/out.lateletter
    python3 make_letter.py --verify out.lateletter        # prompts for passcode

The source file is plain JSON you edit by hand:

    {
      "author_name": "Riki",
      "passphrase_hint": "the word we always say instead of goodbye",
      "garden_seed": 20260719,
      "messages": [
        {"date": "2026-07-20", "label": "Open me", "body": "Dear ...\n..."}
      ],
      "garden_program": {
        "version": 1,
        "evaluator_version": 1,
        "world_state_version": 1,
        "atlas_version": "garden-atlas-1",
        "astronomy_catalog_version": "bright-stars-1",
        "author_timezone": "UTC",
        "variables": {}, "entities": [], "animals": [], "events": []
      }
    }

The passphrase is requested twice at runtime and is never accepted in the
source JSON.  The builder refuses tracked/unignored repository paths and
existing output files.  Keep real plaintext and recipient bundles in ignored
private storage; never use the tracked example or public output paths.
"""

from __future__ import annotations

import getpass
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from lateletter.author_service import (  # noqa: E402
    AuthorServiceError, write_bundle_file,
)
from lateletter.bundle import read_bundle  # noqa: E402
from lateletter.garden.program import (  # noqa: E402
    ProgramValidationError, parse_program,
)
from lateletter.intake import passphrase_strength_warning  # noqa: E402
from lateletter.sealed import (  # noqa: E402
    open_garden_program, open_gift_sentiment, open_message, verify_bundle_hmac,
)


_REPOSITORY_ROOT = Path(__file__).resolve().parent


def _repo_relative(path: Path) -> str | None:
    try:
        return path.resolve().relative_to(_REPOSITORY_ROOT).as_posix()
    except ValueError:
        return None


def _git_path_status(path: Path) -> tuple[bool, bool]:
    """Return ``(tracked, ignored)`` without opening the target file."""
    relative = _repo_relative(path)
    if relative is None or not (_REPOSITORY_ROOT / ".git").exists():
        return False, False
    tracked = subprocess.run(
        [
            "git", "-C", str(_REPOSITORY_ROOT), "ls-files",
            "--error-unmatch", "--", relative,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    ).returncode == 0
    ignored = subprocess.run(
        [
            "git", "-C", str(_REPOSITORY_ROOT), "check-ignore",
            "--quiet", "--", relative,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    ).returncode == 0
    return tracked, ignored


def _validate_private_paths(source_path: Path, out_path: Path) -> tuple[Path, Path]:
    """Reject paths likely to expose personal plaintext or recipient output."""
    source = source_path.expanduser().resolve()
    output = out_path.expanduser().resolve()
    if source == output:
        raise ValueError("source and output paths must be different")
    if source.suffix.lower() != ".json":
        raise ValueError("source path must end in .json")
    if output.suffix.lower() != ".lateletter":
        raise ValueError("output path must end in .lateletter")
    if not source.is_file():
        raise ValueError(f"source file does not exist: {source}")
    if output.exists():
        raise ValueError(
            "output already exists; choose a new path for this fresh bundle"
        )
    if not output.parent.is_dir():
        raise ValueError(f"output folder does not exist: {output.parent}")

    source_tracked, source_ignored = _git_path_status(source)
    output_tracked, output_ignored = _git_path_status(output)
    if source_tracked:
        raise ValueError("refusing to read a Git-tracked plaintext letter source")
    if output_tracked:
        raise ValueError("refusing to overwrite a Git-tracked recipient bundle")
    if _repo_relative(source) is not None and not source_ignored:
        raise ValueError(
            "plaintext source is inside the repository and is not ignored by Git"
        )
    if _repo_relative(output) is not None and not output_ignored:
        raise ValueError(
            "recipient output is inside the repository and is not ignored by Git"
        )
    return source, output


def _fresh_passphrase(password_fn=getpass.getpass) -> str:
    try:
        passphrase = password_fn(
            "fresh passphrase (never committed or used for a compromised bundle): "
        )
        confirmation = password_fn("confirm fresh passphrase: ")
    except (EOFError, KeyboardInterrupt) as exc:
        raise ValueError("passphrase entry cancelled") from exc
    if passphrase != confirmation:
        raise ValueError("passphrases do not match")
    if len(passphrase) < 12:
        raise ValueError("fresh passphrase must contain at least 12 characters")
    warning = passphrase_strength_warning(passphrase)
    if warning is not None:
        raise ValueError(warning)
    return passphrase


def build(
    source_path: Path,
    out_path: Path,
    *,
    passphrase: str | None = None,
    password_fn=getpass.getpass,
) -> None:
    """Seal a private source file into a private bundle.

    This function owns only the two things that are specific to running from a
    terminal: proving the paths are private, and collecting the passphrase
    without echoing it. Everything about what a bundle IS — its metadata, its
    messages, its Garden program, its sealing and its round-trip proof — belongs
    to lateletter.author_service, which the HTML author UI also calls. Keeping
    one owner is what stops the two front ends drifting into two bundle formats.
    """
    try:
        source_path, out_path = _validate_private_paths(source_path, out_path)
        src = json.loads(source_path.read_text(encoding="utf-8"))
        if not isinstance(src, dict):
            raise ValueError("source JSON must be an object")
        if "passphrase" in src:
            raise ValueError(
                "remove 'passphrase' from the plaintext source; it is requested privately"
            )
        passphrase = _fresh_passphrase(password_fn) if passphrase is None else passphrase
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        sys.exit(f"error: {exc}")

    try:
        summary = write_bundle_file(src, passphrase, out_path)
    except AuthorServiceError as exc:
        # The service reports every problem it found at once; the command line
        # shows them all rather than making the author rerun to find the next.
        sys.exit("error: " + "; ".join(exc.issues))
    except (ValueError, ProgramValidationError) as exc:
        sys.exit(f"error: invalid source or garden program: {exc}")

    bundle = read_bundle(out_path)
    print(f"sealed  {out_path}")
    print(f"  author: {bundle.author_name}   seed: {bundle.garden_seed}")
    print(
        f"  messages: {summary['message_count']}   legacy gifts: 0   "
        f"garden program: yes"
    )
    print(f"  hint shown to recipient: {bundle.passphrase_hint!r}")
    print("  passcode is NOT stored in the file — share it in person.")
    if out_path.parent.name == "public_letters":
        name = out_path.stem
        print("  publishable — after commit to main + Pages deploy:")
        print(f"    https://rikiworld.com/lateletter/{name}/")
        print(f"    https://rikiworld.com/lateletter/?l={name}")
        print("  note: author name, hint, and dates are plaintext in the")
        print("  bundle and visible to anyone with the URL or the repo.")


def verify(path: Path) -> None:
    bundle = read_bundle(path)
    passphrase = getpass.getpass("passcode: ")
    if not verify_bundle_hmac(bundle, passphrase):
        sys.exit("HMAC verification FAILED — wrong passcode or modified file")
    print("HMAC ok")
    for msg in bundle.messages:
        content = open_message(passphrase, msg)
        print(f"  {msg.date}  {content['label']!r}  ({len(content['body'])} chars)")
    for gift in bundle.garden_gifts:
        text = open_gift_sentiment(passphrase, gift)
        print(f"  gift {gift.type}/{gift.catalog_id}: {text!r}")
    if bundle.garden_program is not None:
        try:
            program = parse_program(
                open_garden_program(passphrase, bundle.garden_program),
                known_letter_ids={message.id for message in bundle.messages},
            )
        except ProgramValidationError as exc:
            raise SystemExit(f"garden verification FAILED — {exc}") from exc
        print(
            f"  garden program v{program.version}: "
            f"{len(program.events)} event(s), {len(program.animals)} animal(s)"
        )


def main() -> None:
    args = sys.argv[1:]
    if len(args) == 2 and args[0] == "--verify":
        verify(Path(args[1]))
    elif len(args) == 2:
        build(Path(args[0]), Path(args[1]))
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
