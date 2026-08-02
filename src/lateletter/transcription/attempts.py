"""Hash-bound persistence helpers for immutable transcription attempts."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, TypeVar

from .hashing import HashBindingError, resolve_under, sha256_bytes, sha256_file, verify_hash_file
from .model import CandidateBundle, EvidenceRecord
from .schema import canonical_bytes, record_from_dict

T = TypeVar("T", bound=EvidenceRecord)
_ATTEMPT_ID = re.compile(r"^[0-9]{3}-[a-z0-9][a-z0-9-]*$")


class AttemptError(ValueError):
    """Raised when an immutable attempt or binding cannot be created."""


def write_record(path: str | os.PathLike[str], record: EvidenceRecord, *, root: str | os.PathLike[str] | None = None) -> str:
    """Write a record once and return its byte hash; existing files are refused."""

    if isinstance(record, CandidateBundle):
        raise AttemptError("CandidateBundle must be written through write_candidate_bundle")

    target = resolve_under(root, path) if root is not None else Path(path)
    if target.exists():
        raise AttemptError(f"immutable record already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    data = canonical_bytes(record.to_dict()) + b"\n"
    target.write_bytes(data)
    return sha256_bytes(data)


def write_candidate_bundle(
    path: str | os.PathLike[str],
    bundle: CandidateBundle,
    *,
    root: str | os.PathLike[str] | None = None,
) -> str:
    """The sole canonical candidate-bundle writer.

    Candidate bytes are produced by the future orchestrator and bound into the
    bundle before this function is called.  This function only writes the
    immutable hash-bound bundle record once; diagnostic adapters cannot call it
    accidentally through the generic record writer.
    """

    if not isinstance(bundle, CandidateBundle):
        raise AttemptError("write_candidate_bundle requires CandidateBundle")
    target = resolve_under(root, path) if root is not None else Path(path)
    if target.exists():
        raise AttemptError(f"immutable candidate bundle already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    data = canonical_bytes(bundle.to_dict()) + b"\n"
    target.write_bytes(data)
    return sha256_bytes(data)


def read_record(path: str | os.PathLike[str], record_type: type[T], *, root: str | os.PathLike[str] | None = None) -> T:
    target = resolve_under(root, path) if root is not None else Path(path)
    payload = json.loads(target.read_text(encoding="utf-8"))
    return record_from_dict(record_type, payload)


def create_attempt(root: str | os.PathLike[str], attempt_id: str) -> Path:
    if not _ATTEMPT_ID.fullmatch(attempt_id):
        raise AttemptError("attempt id must match NNN-description")
    root_path = Path(root)
    attempt = root_path / attempt_id
    if attempt.exists():
        raise AttemptError(f"attempt directory already exists: {attempt}")
    attempt.mkdir(parents=True)
    return attempt


def verify_candidate_bundle(
    bundle: CandidateBundle,
    artifact_root: str | os.PathLike[str],
    artifact_paths: dict[str, str],
) -> None:
    """Verify every hash binding against immutable files under ``artifact_root``."""

    for key, expected in bundle.bound_hashes.items():
        if key not in artifact_paths:
            raise AttemptError(f"missing artifact path for bound hash {key}")
        target = resolve_under(artifact_root, artifact_paths[key])
        try:
            verify_hash_file(target, expected, field=key)
        except HashBindingError as exc:
            raise AttemptError(str(exc)) from exc


def verify_file_hash(path: str | os.PathLike[str], expected: str) -> bool:
    return sha256_file(path) == expected
