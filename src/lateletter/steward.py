"""
Steward and incapacitation handling (§5.6).

The author dying or losing capacity before finishing is the expected primary
scenario, not an edge case.

This module provides:
  - Steward info extraction from session state
  - Handoff summary generation (for README, display, or steward notification)
  - Session compaction after export (removes encrypted message Q&A content
    while preserving unfinished notes and intake context)

Design mitigations (from SPEC §5.6):
  1. Incremental export — each message is encrypted as soon as finalized.
  2. Steward role — designated during intake, recorded in session.json.
  3. Session file as handoff artifact — contains intake + Q&A but never passphrase.
  4. No unfinished-message exposure — unfinished messages stay as Q&A notes only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .session_store import SessionStore


# ---------------------------------------------------------------------------
# Steward info
# ---------------------------------------------------------------------------

@dataclass
class StewardInfo:
    """Steward designation extracted from session state."""
    name: str
    contact: str
    release_unfinished: bool
    release_date: str | None
    allow_access: bool

    @classmethod
    def from_session(cls, session: dict[str, Any]) -> "StewardInfo | None":
        """Extract steward info from session.json data. Returns None if no steward."""
        name = session.get("steward_name", "")
        if not name:
            return None
        consent = session.get("consent", {})
        return cls(
            name=name,
            contact=session.get("steward_contact", ""),
            release_unfinished=consent.get("release_unfinished", False),
            release_date=consent.get("default_release_date"),
            allow_access=consent.get("allow_steward_access", True),
        )


# ---------------------------------------------------------------------------
# Handoff summary
# ---------------------------------------------------------------------------

@dataclass
class HandoffSummary:
    """Information for the steward handoff package README."""
    author_name: str
    recipient_name: str
    steward: StewardInfo | None
    total_messages: int
    completed_messages: int
    pending_messages: int
    has_unfinished_notes: bool
    passphrase_hint: str

    @classmethod
    def from_session(cls, session: dict[str, Any]) -> "HandoffSummary":
        """Build handoff summary from session.json data."""
        messages = session.get("messages", [])
        completed = sum(
            1 for m in messages if m.get("status") == "encrypted"
        )
        pending = sum(
            1 for m in messages if m.get("status") in ("pending", "written")
        )
        has_notes = any(
            m.get("qa_answers") or m.get("qa_answers_draft")
            for m in messages
            if m.get("status") != "encrypted"
        )
        return cls(
            author_name=session.get("author_name", ""),
            recipient_name=session.get("recipient_name", ""),
            steward=StewardInfo.from_session(session),
            total_messages=len(messages),
            completed_messages=completed,
            pending_messages=pending,
            has_unfinished_notes=has_notes,
            passphrase_hint=session.get("passphrase_hint", ""),
        )


def format_handoff_text(summary: HandoffSummary) -> str:
    """Generate human-readable handoff text for the steward."""
    lines = [
        "LateLetter — Steward Handoff",
        "=" * 40,
        "",
        f"Author: {summary.author_name}",
        f"Recipient: {summary.recipient_name}",
        "",
    ]

    if summary.steward:
        lines.append(f"Steward: {summary.steward.name}")
        if summary.steward.contact:
            lines.append(f"Contact: {summary.steward.contact}")
        lines.append("")

    lines.append(f"Messages: {summary.total_messages} total")
    lines.append(f"  Completed and encrypted: {summary.completed_messages}")
    lines.append(f"  Pending: {summary.pending_messages}")
    lines.append("")

    if summary.has_unfinished_notes:
        lines.append(
            "Unfinished notes exist in the session file. The steward can "
            "review these and choose to complete or discard them."
        )
        lines.append("")

    if summary.steward and summary.steward.release_unfinished:
        release = summary.steward.release_date or "(date not set)"
        lines.append(f"Author's wish: Release all messages on {release}")
    else:
        lines.append("Author's wish: Only deliver completed letters")

    lines.append("")
    lines.append(f"Passphrase hint: {summary.passphrase_hint}")
    lines.append("")
    lines.append(
        "The passphrase is NOT stored anywhere in this file or the session. "
        "The steward must already know it or the author must have communicated "
        "it separately."
    )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Session compaction (§5.4 / §9.1)
# ---------------------------------------------------------------------------

def compact_session(store: SessionStore) -> int:
    """Remove Q&A content for encrypted messages from session.json.

    Preserves: schema_version, author/recipient info, steward, passphrase_hint,
    consent, and any message with status != "encrypted".

    Returns the number of message entries removed.
    """
    session = store.load_session()
    messages = session.get("messages", [])
    if not messages:
        return 0

    kept = []
    removed = 0
    for msg in messages:
        if msg.get("status") == "encrypted":
            removed += 1
        else:
            kept.append(msg)

    if removed > 0:
        session["messages"] = kept
        store.save_session(session)

    return removed
