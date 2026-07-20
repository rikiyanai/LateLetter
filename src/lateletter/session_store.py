"""
Author-local session state storage.

Manages three files under ~/.lateletter/author/:

  session.json          Intake context + per-message Q&A answers.
                        The passphrase is NEVER written here.

  questions_asked.json  Cross-session question dedup log.
                        Stores question ID, hash, text, timestamp, message ID.

  selector_state.json   Optional disposable selector cache.
                        Rebuilt from session.json + questions_asked.json on loss.

All writes are atomic: temp file (created mode 0o600) → fsync → rename (docs/SPEC.md §9.1).
Directory is created mode 0700; all files are mode 0600.

From docs/SPEC.md §9.1:
  "selector_state.json, if present, may be deleted and rebuilt from
   session.json plus questions_asked.json; losing it is recoverable
   and must not destroy authored progress."
"""

from __future__ import annotations

import hashlib
import json
import os
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Storage paths
# ---------------------------------------------------------------------------

AUTHOR_DIR = Path.home() / ".lateletter" / "author"
SESSION_FILE = AUTHOR_DIR / "session.json"
QUESTIONS_ASKED_FILE = AUTHOR_DIR / "questions_asked.json"
SELECTOR_STATE_FILE = AUTHOR_DIR / "selector_state.json"

_DIR_MODE = 0o700
_FILE_MODE = 0o600

# Keys that must never be persisted to session.json (defence-in-depth).
_PASSPHRASE_DENY = frozenset({"passphrase", "passphrase_confirm", "key", "secret", "password"})


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------

def _ensure_author_dir(author_dir: Path) -> None:
    """Create *author_dir* and its parent with secure permissions if absent."""
    for d in (author_dir.parent, author_dir):
        d.mkdir(exist_ok=True)
        os.chmod(d, _DIR_MODE)


def _atomic_write(path: Path, data: dict[str, Any], *, author_dir: Path) -> None:
    """Write *data* as JSON to *path* atomically.

    Strategy: write to .tmp sibling (created mode 0o600) → fsync → os.replace
    (atomic rename).  The file is never world-readable because the opener
    sets permissions at creation — no chmod-after-open race window.
    On any failure the original file is left untouched.
    """
    _ensure_author_dir(author_dir)
    tmp = path.with_suffix(".tmp")
    try:
        with open(tmp, "w", encoding="utf-8",
                  opener=lambda p, flags: os.open(p, flags, _FILE_MODE)) as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
        raise


def _read_json(path: Path) -> dict[str, Any]:
    """Return parsed JSON from *path*, or an empty dict if absent or corrupt.

    On parse failure the corrupt file is renamed to *.corrupt* for later
    diagnosis and {} is returned with a ``_was_corrupt`` marker so callers
    can detect the recovery and warn the user before overwriting data.
    """
    if not path.exists():
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except json.JSONDecodeError:
        corrupt = path.with_suffix(".corrupt")
        try:
            path.rename(corrupt)
        except OSError:
            pass
        warnings.warn(
            f"Corrupt JSON at {path} — moved to {corrupt} and treating as empty.",
            RuntimeWarning,
            stacklevel=2,
        )
        return {"_was_corrupt": True}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class SessionStore:
    """Read/write author-local session state.

    Thin wrapper around the three session files.  Business logic lives in
    the Q&A loop and selector, not here.

    Can be pointed at a non-default base directory for testing:
        store = SessionStore(base_dir=tmp_path)
    """

    def __init__(self, base_dir: Path | None = None) -> None:
        if base_dir is not None:
            self._author_dir = base_dir
            self._session_file = base_dir / "session.json"
            self._asked_file = base_dir / "questions_asked.json"
            self._selector_file = base_dir / "selector_state.json"
        else:
            self._author_dir = AUTHOR_DIR
            self._session_file = SESSION_FILE
            self._asked_file = QUESTIONS_ASKED_FILE
            self._selector_file = SELECTOR_STATE_FILE

    # ---- session.json ----

    def load_session(self) -> dict[str, Any]:
        return _read_json(self._session_file)

    def save_session(self, data: dict[str, Any]) -> None:
        blocked = _PASSPHRASE_DENY & data.keys()
        if blocked:
            raise ValueError(
                f"Refusing to persist sensitive key(s) to disk: {sorted(blocked)}"
            )
        _atomic_write(self._session_file, data, author_dir=self._author_dir)

    # ---- questions_asked.json ----

    def load_questions_asked(self) -> list[dict[str, Any]]:
        return _read_json(self._asked_file).get("questions", [])

    def save_questions_asked(self, entries: list[dict[str, Any]]) -> None:
        _atomic_write(self._asked_file, {"questions": entries}, author_dir=self._author_dir)

    def asked_question_ids(self) -> set[str]:
        """Return all question IDs asked in any session."""
        return {e["question_id"] for e in self.load_questions_asked()}

    def record_question_asked(
        self,
        question_id: str,
        question_text: str,
        message_id: str,
    ) -> None:
        """Append one entry to questions_asked.json."""
        entries = self.load_questions_asked()
        entries.append({
            "question_id": question_id,
            "question_hash": hashlib.sha256(question_text.encode()).hexdigest(),
            "question_text": question_text,
            "asked_at": _now_iso(),
            "message_id": message_id,
        })
        self.save_questions_asked(entries)

    # ---- selector_state.json ----

    def load_selector_state(self, message_id: str) -> dict[str, Any] | None:
        """Return saved SelectorSession dict for *message_id*, or None."""
        data = _read_json(self._selector_file)
        if data.get("message_id") == message_id:
            return data.get("session_state")
        return None

    def save_selector_state(self, message_id: str, state: dict[str, Any]) -> None:
        _atomic_write(self._selector_file, {
            "message_id": message_id,
            "session_state": state,
            "saved_at": _now_iso(),
        }, author_dir=self._author_dir)

    def clear_selector_state(self) -> None:
        if self._selector_file.exists():
            self._selector_file.unlink()

    # ---- message helpers ----

    def get_message(self, message_id: str) -> dict[str, Any] | None:
        """Return the message sub-object from session.json, or None."""
        session = self.load_session()
        return next(
            (m for m in session.get("messages", []) if m["id"] == message_id),
            None,
        )

    def upsert_message(self, message_id: str, updates: dict[str, Any]) -> None:
        """Merge *updates* into the message record with *message_id*.

        Creates the message record if it doesn't exist.
        Raises ValueError if *updates* contains any passphrase-family key —
        the passphrase must never be written to session.json (SPEC §9.1).
        """
        blocked = _PASSPHRASE_DENY & updates.keys()
        if blocked:
            raise ValueError(
                f"Refusing to persist sensitive key(s) to disk: {sorted(blocked)}"
            )
        session = self.load_session()
        messages = session.setdefault("messages", [])
        msg = next((m for m in messages if m["id"] == message_id), None)
        if msg is None:
            msg = {"id": message_id}
            messages.append(msg)
        msg.update(updates)
        self.save_session(session)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
