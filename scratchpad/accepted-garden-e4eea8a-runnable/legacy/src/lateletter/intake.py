"""
Author intake form data model and validation.

Manages the §5.1 intake form fields: author name, relationship, recipient,
key dates, shared memories, steward, incapacitation wishes, passphrase hint.

The passphrase is NEVER persisted — it is held in memory only and passed
to the encryption layer when needed.  This module validates passphrase
matching and emits soft strength warnings, but never stores the value.

Intake data is stored in session.json via SessionStore.  The intake
screen is re-enterable — the author can update steward, wishes, or any
field at any time (SPEC §5.1).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .session_store import SessionStore


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class KeyDate:
    label: str
    date: str   # free text — no format enforcement (SPEC §5.1)


@dataclass
class IntakeData:
    author_name: str = ""
    relationship: str = ""
    recipient_name: str = ""
    recipient_relationship: str = ""
    key_dates: list[KeyDate] = field(default_factory=list)
    memory_tags: list[str] = field(default_factory=list)
    steward_name: str = ""
    steward_contact: str = ""
    release_unfinished: bool = False
    release_date: str | None = None        # ISO 8601 or None
    passphrase_hint: str = ""

    def to_session_dict(self) -> dict[str, Any]:
        """Serialize to session.json shape (SPEC §9.1).

        Never includes the passphrase.
        """
        return {
            "schema_version": 1,
            "author_name": self.author_name,
            "relationship": self.relationship,
            "recipient_name": self.recipient_name,
            "recipient_relationship": self.recipient_relationship,
            "key_dates": [
                {"label": kd.label, "date": kd.date} for kd in self.key_dates
            ],
            "memory_tags": self.memory_tags,
            "steward_name": self.steward_name,
            "steward_contact": self.steward_contact,
            "passphrase_hint": self.passphrase_hint,
            "consent": {
                "release_unfinished": self.release_unfinished,
                "default_release_date": self.release_date,
                "allow_steward_access": bool(self.steward_name),
            },
        }

    @classmethod
    def from_session_dict(cls, data: dict[str, Any]) -> "IntakeData":
        """Load from session.json shape.  Missing fields get defaults."""
        consent = data.get("consent", {})
        return cls(
            author_name=data.get("author_name", ""),
            relationship=data.get("relationship", ""),
            recipient_name=data.get("recipient_name", ""),
            recipient_relationship=data.get("recipient_relationship", ""),
            key_dates=[
                KeyDate(label=kd.get("label", ""), date=kd.get("date", ""))
                for kd in data.get("key_dates", [])
            ],
            memory_tags=data.get("memory_tags", []),
            steward_name=data.get("steward_name", ""),
            steward_contact=data.get("steward_contact", ""),
            release_unfinished=consent.get("release_unfinished", False),
            release_date=consent.get("default_release_date"),
            passphrase_hint=data.get("passphrase_hint", ""),
        )


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

@dataclass
class ValidationError:
    field: str
    message: str


def validate_intake(data: IntakeData) -> list[ValidationError]:
    """Return validation errors for intake data.

    All fields except memory_tags and steward are required (SPEC §5.1).
    Passphrase validation is handled separately by validate_passphrase()
    since the passphrase is never part of IntakeData.
    """
    errors: list[ValidationError] = []
    if not data.author_name.strip():
        errors.append(ValidationError("author_name", "Your name is required."))
    if not data.relationship.strip():
        errors.append(ValidationError("relationship", "Your relationship is required."))
    if not data.recipient_name.strip():
        errors.append(ValidationError("recipient_name", "Recipient's name is required."))
    if not data.recipient_relationship.strip():
        errors.append(ValidationError("recipient_relationship", "Recipient's relationship is required."))
    if not data.key_dates:
        errors.append(ValidationError("key_dates", "At least one key date is required."))
    if not data.passphrase_hint.strip():
        errors.append(ValidationError("passphrase_hint", "Passphrase hint is required."))
    if data.release_unfinished and not data.release_date:
        errors.append(ValidationError("release_date", "Release date is required when releasing unfinished letters."))
    return errors


def validate_passphrase(passphrase: str, confirm: str) -> list[ValidationError]:
    """Validate passphrase fields.  Returns errors list.

    The passphrase is validated but never stored in IntakeData.
    """
    errors: list[ValidationError] = []
    if not passphrase:
        errors.append(ValidationError("passphrase", "Passphrase is required."))
        return errors
    if passphrase != confirm:
        errors.append(ValidationError("passphrase_confirm", "Passphrases do not match."))
    return errors


# Common passphrases — a short list for the soft strength warning.
_COMMON_PASSPHRASES = frozenset({
    "password", "123456", "12345678", "1234567890", "qwerty",
    "abc123", "letmein", "welcome", "monkey", "dragon",
    "master", "login", "princess", "passw0rd", "shadow",
})


def passphrase_strength_warning(passphrase: str) -> str | None:
    """Return a soft warning string if the passphrase is weak, else None.

    No minimum length is enforced — memorability is valid (SPEC §5.1).
    """
    if not passphrase:
        return None
    if len(passphrase) < 8:
        return "This passphrase is short. Someone who finds this file could guess it."
    if passphrase.lower() in _COMMON_PASSPHRASES:
        return "This passphrase is very common. Someone who finds this file could guess it."
    if len(set(passphrase)) <= 2:
        return "This passphrase is too simple. Someone who finds this file could guess it."
    return None


def passphrase_communication_warning(recipient_name: str) -> str:
    """Return the passphrase communication warning text (SPEC §5.1).

    Shown immediately after passphrase is confirmed during intake.
    """
    return (
        f"Important: If {recipient_name} cannot remember this passphrase, "
        "these letters are lost forever. Consider writing it down for "
        "someone you trust."
    )


# ---------------------------------------------------------------------------
# Session integration
# ---------------------------------------------------------------------------

def save_intake(data: IntakeData, store: SessionStore) -> None:
    """Persist intake data to session.json, merging with existing state.

    Merges into the existing session dict so that unknown top-level keys
    (from future schema versions or other modules) are preserved.
    """
    session = store.load_session()
    session.update(data.to_session_dict())
    # Preserve existing messages — intake update should not clobber them
    if "messages" not in session:
        session["messages"] = []
    store.save_session(session)


def load_intake(store: SessionStore) -> IntakeData | None:
    """Load intake data from session.json.  Returns None if no session exists."""
    session = store.load_session()
    if not session:
        return None
    if session.get("_was_corrupt"):
        return None
    return IntakeData.from_session_dict(session)


def check_session_corruption(store: SessionStore) -> bool:
    """Return True if session.json was found to be corrupt on last load."""
    session = store.load_session()
    return bool(session.get("_was_corrupt"))
