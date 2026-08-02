"""Hash and path-safety primitives used by the transcription evidence IR."""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path
from typing import BinaryIO

SHA256_HEX_LENGTH = 64


class HashBindingError(ValueError):
    """Raised when an evidence hash is missing, malformed, or stale."""


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str | os.PathLike[str]) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        _update_from_file(digest, handle)
    return digest.hexdigest()


def _update_from_file(digest: "hashlib._Hash", handle: BinaryIO) -> None:
    while True:
        block = handle.read(1024 * 1024)
        if not block:
            return
        digest.update(block)


def is_sha256(value: object) -> bool:
    return isinstance(value, str) and len(value) == SHA256_HEX_LENGTH and all(
        character in "0123456789abcdef" for character in value
    )


def require_sha256(value: object, *, field: str = "hash") -> str:
    if not is_sha256(value):
        raise HashBindingError(f"{field} must be a lowercase SHA-256 hex digest")
    return str(value)


def verify_hash_bytes(data: bytes, expected: str, *, field: str = "artifact") -> None:
    require_sha256(expected, field=f"{field} expected hash")
    actual = sha256_bytes(data)
    if actual != expected:
        raise HashBindingError(f"stale {field}: expected {expected}, got {actual}")


def verify_hash_file(path: str | os.PathLike[str], expected: str, *, field: str = "artifact") -> None:
    require_sha256(expected, field=f"{field} expected hash")
    actual = sha256_file(path)
    if actual != expected:
        raise HashBindingError(f"stale {field}: expected {expected}, got {actual}")


def safe_relative_path(value: str | os.PathLike[str], *, field: str = "path") -> str:
    """Return a normalized relative path or reject traversal/absolute paths."""

    raw = os.fspath(value)
    if not isinstance(raw, str) or not raw or "\x00" in raw:
        raise ValueError(f"{field} must be a non-empty path without NUL bytes")
    path = Path(raw)
    if path.is_absolute() or path.drive or re.match(r"^[A-Za-z]:[\\/]", raw):
        raise ValueError(f"{field} must be relative")
    parts = path.parts
    # A POSIX runner does not split Windows separators, so inspect both forms.
    if any(part in {"", ".", ".."} for part in re.split(r"[\\/]", raw)):
        raise ValueError(f"{field} contains unsafe traversal")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError(f"{field} contains unsafe traversal")
    return "/".join(parts)


def resolve_under(root: str | os.PathLike[str], relative: str | os.PathLike[str]) -> Path:
    safe = safe_relative_path(relative)
    root_path = Path(root).resolve()
    target = (root_path / safe).resolve()
    try:
        target.relative_to(root_path)
    except ValueError as exc:
        raise ValueError("path escapes artifact root") from exc
    return target
