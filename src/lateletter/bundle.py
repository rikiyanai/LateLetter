"""
.lateletter bundle format — schema, reader, writer, and validation.

The bundle is a single portable JSON file the author gives to the recipient.
It contains encrypted messages, optional garden gifts, and plaintext metadata
for delivery scheduling and structural integrity checking.

Format defined in docs/SPEC.md §3 (outer structure), §4 (encryption model),
and §6.8.6 (garden gifts).

Encryption (Argon2id + AES-256-GCM) is handled by a separate module
(step 13).  This module handles the container format: serialization,
canonical JSON, checksum, schema validation, and read/write.

All binary fields are stored as standard base64 with padding (RFC 4648 §4).
Canonical JSON: sorted keys (recursive), compact separators, UTF-8.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BUNDLE_VERSION = 1
BUNDLE_VERSION_WITH_GARDEN_PROGRAM = 2
SUPPORTED_BUNDLE_VERSIONS = (BUNDLE_VERSION, BUNDLE_VERSION_WITH_GARDEN_PROGRAM)
_FILE_MODE = 0o600

PBKDF2_MIN_ITERATIONS = 600_000
PBKDF2_MAX_ITERATIONS = 2_000_000
PBKDF2_PARAM_FIELDS = frozenset({"name", "hash", "iterations"})

# Fields included in the checksum/HMAC visible payload (SPEC §3).
_VISIBLE_PAYLOAD_FIELDS = (
    "version",
    "bundle_id",
    "author_name",
    "passphrase_hint",
    "bundle_auth_salt",
    "garden_seed",
    "messages",
    "garden_gifts",
    "notification",
)

_VISIBLE_PAYLOAD_FIELDS_V2 = (
    "version",
    "bundle_id",
    "author_name",
    "passphrase_hint",
    "bundle_auth_salt",
    "bundle_auth_kdf_params",
    "garden_seed",
    "messages",
    "garden_gifts",
    "garden_program",
    "notification",
)


# ---------------------------------------------------------------------------
# Canonical JSON
# ---------------------------------------------------------------------------

def canonical_json(obj: Any) -> bytes:
    """Canonical JSON bytes for checksum/HMAC computation.

    Sorted keys (recursive), compact separators, UTF-8 encoding.
    Equivalent to: json.dumps(obj, sort_keys=True, separators=(',', ':'),
                              ensure_ascii=False).encode('utf-8')
    """
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class Trigger:
    """When an authored garden element appears (SPEC §6.8.4)."""
    type: str       # "date" | "cumulative_visits" | "post_letter"
    value: str      # ISO date | visit count (str) | message_id

    def to_dict(self) -> dict[str, str]:
        return {"type": self.type, "value": self.value}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Trigger:
        return cls(type=str(data["type"]), value=str(data["value"]))


@dataclass
class GardenGift:
    """An author-programmed garden element (SPEC §6.8.5, §6.8.6).

    Sentiment is encrypted with the bundle passphrase.  In dev fixtures
    the sentiment fields hold plaintext placeholders.
    """
    id: str
    type: str                       # "item" | "plant" | "animal" | "landmark" | "nudge"
    catalog_id: str                 # e.g. "plate_of_food", "sapling", "cat"
    trigger: Trigger
    placement_hint: str = "random"  # "near_tallest_tree" | "by_edge" | "random"
    animal_name: str | None = None
    animal_collar_color: str | None = None
    # Encrypted fields (plaintext in dev fixtures)
    sentiment_ciphertext: str = ""  # base64 ciphertext (or plaintext in fixtures)
    salt: str = ""                  # base64
    nonce: str = ""                 # base64

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "catalog_id": self.catalog_id,
            "sentiment_ciphertext": self.sentiment_ciphertext,
            "salt": self.salt,
            "nonce": self.nonce,
            "trigger": self.trigger.to_dict(),
            "placement_hint": self.placement_hint,
            "animal_name": self.animal_name,
            "animal_collar_color": self.animal_collar_color,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GardenGift:
        return cls(
            id=data["id"],
            type=data["type"],
            catalog_id=data["catalog_id"],
            trigger=Trigger.from_dict(data["trigger"]),
            placement_hint=data.get("placement_hint", "random"),
            animal_name=data.get("animal_name"),
            animal_collar_color=data.get("animal_collar_color"),
            sentiment_ciphertext=data.get("sentiment_ciphertext", ""),
            salt=data.get("salt", ""),
            nonce=data.get("nonce", ""),
        )


@dataclass
class Message:
    """A single encrypted letter in the bundle (SPEC §3)."""
    id: str
    date: str               # ISO 8601 (plaintext — anyone can see *when*)
    ciphertext: str = ""    # base64
    salt: str = ""          # base64
    nonce: str = ""         # base64
    kdf_params: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "id": self.id,
            "date": self.date,
            "ciphertext": self.ciphertext,
            "salt": self.salt,
            "nonce": self.nonce,
            "kdf_params": self.kdf_params,
        }
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Message:
        return cls(
            id=data["id"],
            date=data["date"],
            ciphertext=data.get("ciphertext", ""),
            salt=data.get("salt", ""),
            nonce=data.get("nonce", ""),
            kdf_params=data.get("kdf_params"),
        )


@dataclass
class Notification:
    """Optional email notification config (SPEC §13.3)."""
    email: str | None = None
    method: str | None = None   # "self-hosted" | None

    def to_dict(self) -> dict[str, Any] | None:
        if self.email is None and self.method is None:
            return None
        return {"email": self.email, "method": self.method}

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> Notification:
        if data is None:
            return cls()
        return cls(email=data.get("email"), method=data.get("method"))


@dataclass
class GardenProgramEnvelope:
    """Encrypted author-directed Garden program carried by v2 bundles.

    Narrative-bearing program data stays inside ``ciphertext``.  The envelope
    contains only the fields required to select the deterministic evaluator and
    decrypt the inner program after bundle authentication.
    """

    version: int = 1
    ciphertext: str = ""
    salt: str = ""
    nonce: str = ""
    kdf_params: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "ciphertext": self.ciphertext,
            "salt": self.salt,
            "nonce": self.nonce,
            "kdf_params": self.kdf_params,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GardenProgramEnvelope:
        return cls(
            version=int(data.get("version", 1)),
            ciphertext=str(data.get("ciphertext", "")),
            salt=str(data.get("salt", "")),
            nonce=str(data.get("nonce", "")),
            kdf_params=data.get("kdf_params"),
        )


@dataclass
class Bundle:
    """The complete .lateletter bundle (SPEC §3).

    This is the root data structure — one Bundle = one .lateletter file.
    """
    version: int = BUNDLE_VERSION
    bundle_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    author_name: str = ""
    passphrase_hint: str | None = None
    bundle_auth_salt: str = ""          # base64 (16 bytes)
    bundle_auth_kdf_params: dict[str, Any] | None = None
    garden_seed: int = 0
    messages: list[Message] = field(default_factory=list)
    garden_gifts: list[GardenGift] = field(default_factory=list)
    garden_program: GardenProgramEnvelope | None = None
    notification: Notification = field(default_factory=Notification)
    # Computed fields — not part of the visible payload
    checksum: str = ""
    hmac: str = ""

    def visible_payload(self) -> dict[str, Any]:
        """Return the visible payload dict for checksum/HMAC computation.

        Includes all top-level fields except checksum and hmac (SPEC §3).
        """
        payload: dict[str, Any] = {
            "version": self.version,
            "bundle_id": self.bundle_id,
            "author_name": self.author_name,
            "passphrase_hint": self.passphrase_hint,
            "bundle_auth_salt": self.bundle_auth_salt,
            "garden_seed": self.garden_seed,
            "messages": [m.to_dict() for m in self.messages],
            "garden_gifts": [g.to_dict() for g in self.garden_gifts],
            "notification": self.notification.to_dict(),
        }
        # Version 1's authenticated payload is frozen.  Adding even a null
        # field would invalidate every existing checksum and HMAC.
        if self.version >= BUNDLE_VERSION_WITH_GARDEN_PROGRAM:
            payload["bundle_auth_kdf_params"] = self.bundle_auth_kdf_params
            payload["garden_program"] = (
                self.garden_program.to_dict() if self.garden_program else None
            )
        return payload

    def compute_checksum(self) -> str:
        """SHA-256 over canonical JSON of the visible payload.

        Unkeyed — detects corruption, not tampering (SPEC §3).
        """
        payload_bytes = canonical_json(self.visible_payload())
        return hashlib.sha256(payload_bytes).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        """Full bundle dict including checksum and hmac."""
        d = self.visible_payload()
        d["checksum"] = self.checksum
        d["hmac"] = self.hmac
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Bundle:
        """Parse a bundle dict into a Bundle instance.

        Raises BundleValidationError on structural problems.
        """
        errors = validate_bundle_dict(data)
        if errors:
            raise BundleValidationError(errors)
        return cls(
            version=data["version"],
            bundle_id=data["bundle_id"],
            author_name=data.get("author_name", ""),
            passphrase_hint=data.get("passphrase_hint"),
            bundle_auth_salt=data.get("bundle_auth_salt", ""),
            bundle_auth_kdf_params=data.get("bundle_auth_kdf_params"),
            garden_seed=data.get("garden_seed", 0),
            messages=[Message.from_dict(m) for m in data.get("messages", [])],
            garden_gifts=[
                GardenGift.from_dict(g) for g in data.get("garden_gifts", [])
            ],
            garden_program=(
                GardenProgramEnvelope.from_dict(data["garden_program"])
                if data.get("garden_program") is not None else None
            ),
            notification=Notification.from_dict(data.get("notification")),
            checksum=data.get("checksum", ""),
            hmac=data.get("hmac", ""),
        )


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class BundleValidationError(Exception):
    """Raised when a bundle dict fails structural validation."""
    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__(f"Bundle validation failed: {'; '.join(errors)}")


def validate_pbkdf2_params(
    params: Any,
    *,
    field_name: str = "kdf_params",
) -> list[str]:
    """Return validation errors for the one supported KDF profile.

    Keeping this validation beside bundle parsing gives every reader a cheap
    rejection point before untrusted work factors can reach PBKDF2.
    """
    if not isinstance(params, dict):
        return [f"{field_name} must be an object."]
    fields = set(params)
    if fields != PBKDF2_PARAM_FIELDS:
        return [
            f"{field_name} must contain exactly "
            f"{sorted(PBKDF2_PARAM_FIELDS)!r}."
        ]
    if params.get("name") != "PBKDF2":
        return [f"{field_name}.name must be 'PBKDF2'."]
    if params.get("hash") != "SHA-256":
        return [f"{field_name}.hash must be 'SHA-256'."]
    iterations = params.get("iterations")
    if isinstance(iterations, bool) or not isinstance(iterations, int):
        return [f"{field_name}.iterations must be an integer, not a boolean."]
    if not PBKDF2_MIN_ITERATIONS <= iterations <= PBKDF2_MAX_ITERATIONS:
        return [
            f"{field_name}.iterations must be between "
            f"{PBKDF2_MIN_ITERATIONS} and {PBKDF2_MAX_ITERATIONS}."
        ]
    return []


def _validate_base64_field(
    value: Any,
    *,
    field_name: str,
    expected_length: int | None = None,
    minimum_length: int | None = None,
    required: bool = False,
) -> list[str]:
    if value in (None, ""):
        return [f"{field_name} must not be empty."] if required else []
    if not isinstance(value, str):
        return [f"{field_name} must be a base64 string."]
    try:
        decoded = base64.b64decode(value, validate=True)
    except (ValueError, TypeError):
        return [f"{field_name} must be valid padded base64."]
    if expected_length is not None and len(decoded) != expected_length:
        return [f"{field_name} must decode to exactly {expected_length} bytes."]
    if minimum_length is not None and len(decoded) < minimum_length:
        return [f"{field_name} must decode to at least {minimum_length} bytes."]
    return []


def validate_bundle_dict(data: dict[str, Any]) -> list[str]:
    """Validate the raw bundle dict structure.  Returns list of error strings."""
    errors: list[str] = []

    if not isinstance(data, dict):
        return ["Bundle must be a JSON object."]

    # Version
    version = data.get("version")
    if version is None:
        errors.append("Missing required field: version.")
    elif (
        isinstance(version, bool)
        or not isinstance(version, int)
        or version not in SUPPORTED_BUNDLE_VERSIONS
    ):
        errors.append(
            f"Unsupported bundle version {version} "
            f"(expected one of {SUPPORTED_BUNDLE_VERSIONS})."
        )

    # Required string fields
    if not data.get("bundle_id"):
        errors.append("Missing required field: bundle_id.")

    # Messages
    messages = data.get("messages")
    encrypted_messages_required = bool(data.get("hmac")) or (
        version == BUNDLE_VERSION_WITH_GARDEN_PROGRAM
    )
    if messages is not None:
        if not isinstance(messages, list):
            errors.append("Field 'messages' must be a list.")
        else:
            for i, m in enumerate(messages):
                if not isinstance(m, dict):
                    errors.append(f"messages[{i}] must be an object.")
                elif not m.get("id") or not m.get("date"):
                    errors.append(f"messages[{i}] missing required field 'id' or 'date'.")
                else:
                    if m.get("kdf_params") is not None:
                        errors.extend(validate_pbkdf2_params(
                            m.get("kdf_params"),
                            field_name=f"messages[{i}].kdf_params",
                        ))
                    elif encrypted_messages_required:
                        errors.append(
                            f"messages[{i}].kdf_params must contain the supported "
                            "PBKDF2 profile."
                        )
                    errors.extend(_validate_base64_field(
                        m.get("salt"), field_name=f"messages[{i}].salt",
                        expected_length=16, required=True,
                    ))
                    errors.extend(_validate_base64_field(
                        m.get("nonce"), field_name=f"messages[{i}].nonce",
                        expected_length=12, required=True,
                    ))
                    errors.extend(_validate_base64_field(
                        m.get("ciphertext"), field_name=f"messages[{i}].ciphertext",
                        minimum_length=16, required=True,
                    ))

    # Garden gifts
    gifts = data.get("garden_gifts")
    if gifts is not None:
        if not isinstance(gifts, list):
            errors.append("Field 'garden_gifts' must be a list.")
        else:
            for i, g in enumerate(gifts):
                if not isinstance(g, dict):
                    errors.append(f"garden_gifts[{i}] must be an object.")
                elif not g.get("id") or not g.get("type") or not g.get("trigger"):
                    errors.append(
                        f"garden_gifts[{i}] missing required field "
                        "'id', 'type', or 'trigger'."
                    )
                else:
                    errors.extend(_validate_base64_field(
                        g.get("salt"), field_name=f"garden_gifts[{i}].salt",
                        expected_length=16,
                    ))
                    errors.extend(_validate_base64_field(
                        g.get("nonce"), field_name=f"garden_gifts[{i}].nonce",
                        expected_length=12,
                    ))
                    errors.extend(_validate_base64_field(
                        g.get("sentiment_ciphertext"),
                        field_name=f"garden_gifts[{i}].sentiment_ciphertext",
                        minimum_length=16,
                    ))

    # Garden seed
    seed = data.get("garden_seed")
    if seed is not None and (isinstance(seed, bool) or not isinstance(seed, int)):
        errors.append("Field 'garden_seed' must be an integer.")

    errors.extend(_validate_base64_field(
        data.get("bundle_auth_salt"), field_name="bundle_auth_salt",
        expected_length=16,
        required=bool(data.get("hmac")) or version == BUNDLE_VERSION_WITH_GARDEN_PROGRAM,
    ))

    # Version 2 moves author-directed world ownership into one encrypted
    # program.  It must never run beside plaintext legacy gift triggers.
    if version == BUNDLE_VERSION_WITH_GARDEN_PROGRAM:
        if data.get("garden_gifts"):
            errors.append(
                "Version 2 bundles must leave 'garden_gifts' empty; "
                "author direction belongs to 'garden_program'."
            )
        auth_params = data.get("bundle_auth_kdf_params")
        if not isinstance(auth_params, dict):
            errors.append(
                "Version 2 bundles require 'bundle_auth_kdf_params'."
            )
        else:
            errors.extend(validate_pbkdf2_params(
                auth_params, field_name="bundle_auth_kdf_params",
            ))
        program = data.get("garden_program")
        if not isinstance(program, dict):
            errors.append("Version 2 bundles require an encrypted 'garden_program'.")
        else:
            for field_name in ("version", "ciphertext", "salt", "nonce", "kdf_params"):
                if field_name not in program:
                    errors.append(
                        f"garden_program missing required field '{field_name}'."
                    )
            if (
                isinstance(program.get("version"), bool)
                or not isinstance(program.get("version"), int)
                or program.get("version") != 1
            ):
                errors.append("Unsupported garden_program version.")
            for field_name in ("ciphertext", "salt", "nonce"):
                if not program.get(field_name):
                    errors.append(f"garden_program field '{field_name}' must not be empty.")
            errors.extend(validate_pbkdf2_params(
                program.get("kdf_params"),
                field_name="garden_program.kdf_params",
            ))
            errors.extend(_validate_base64_field(
                program.get("salt"), field_name="garden_program.salt",
                expected_length=16, required=True,
            ))
            errors.extend(_validate_base64_field(
                program.get("nonce"), field_name="garden_program.nonce",
                expected_length=12, required=True,
            ))
            errors.extend(_validate_base64_field(
                program.get("ciphertext"), field_name="garden_program.ciphertext",
                minimum_length=16, required=True,
            ))
    elif version == BUNDLE_VERSION and "garden_program" in data:
        errors.append(
            "Version 1 bundles cannot contain 'garden_program'; use version 2."
        )

    return errors


def verify_checksum(bundle: Bundle) -> bool:
    """Return True if the bundle's stored checksum matches recomputation."""
    if not bundle.checksum:
        return False
    return bundle.compute_checksum() == bundle.checksum


# ---------------------------------------------------------------------------
# Reader / Writer
# ---------------------------------------------------------------------------

def write_bundle(bundle: Bundle, path: Path) -> None:
    """Write a bundle to disk with computed checksum.

    Uses atomic write: temp file (mode 0600) -> fsync -> rename.
    HMAC is set by the encryption layer (step 13) — this module
    computes and writes the checksum only.
    """
    errors = validate_bundle_dict(bundle.to_dict())
    if errors:
        raise BundleValidationError(errors)
    bundle.checksum = bundle.compute_checksum()
    data = bundle.to_dict()
    json_bytes = json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")

    tmp = path.with_suffix(".tmp")
    try:
        with open(tmp, "wb",
                  opener=lambda p, flags: os.open(p, flags, _FILE_MODE)) as fh:
            fh.write(json_bytes)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
        raise


def read_bundle(path: Path) -> Bundle:
    """Read and validate a .lateletter bundle from disk.

    Raises:
        FileNotFoundError: if path does not exist.
        json.JSONDecodeError: if file is not valid JSON.
        BundleValidationError: if structure is invalid.
    """
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    return Bundle.from_dict(data)


# ---------------------------------------------------------------------------
# Dev fixtures
# ---------------------------------------------------------------------------

def _b64(raw: bytes) -> str:
    """Encode bytes as standard base64 with padding."""
    return base64.b64encode(raw).decode("ascii") if raw else ""


def create_dev_fixture(
    *,
    author_name: str = "Robert",
    recipient_name: str = "Maya",
    passphrase_hint: str = "The name of our first dog",
    garden_seed: int = 42301,
    message_dates: list[str] | None = None,
    include_gifts: bool = True,
    notification_email: str | None = "maya@example.com",
) -> Bundle:
    """Create a dev-fixture bundle with plaintext placeholder content.

    Ciphertext fields hold readable plaintext wrapped in base64 so the
    schema shape is correct.  Salts and nonces are random bytes.
    Real encryption replaces these in step 13.
    """
    if message_dates is None:
        message_dates = ["2027-06-15", "2027-12-25", "2028-03-10"]

    messages: list[Message] = []
    labels = [
        f"Letter for {recipient_name} — {d}" for d in message_dates
    ]
    bodies = [
        f"Dear {recipient_name},\n\nThis is a placeholder letter for {d}.\n"
        f"The real content will be encrypted.\n\nLove,\n{author_name}"
        for d in message_dates
    ]
    for d, label, body in zip(message_dates, labels, bodies):
        # In dev fixtures, "ciphertext" is base64-encoded plaintext
        # containing both label and body (matching the real format where
        # label is inside the ciphertext).
        plaintext = json.dumps({"label": label, "body": body})
        messages.append(Message(
            id=str(uuid.uuid4()),
            date=d,
            ciphertext=_b64(plaintext.encode("utf-8")),
            salt=_b64(os.urandom(16)),
            nonce=_b64(os.urandom(12)),
            kdf_params=None,
        ))

    gifts: list[GardenGift] = []
    if include_gifts:
        gifts = [
            GardenGift(
                id=str(uuid.uuid4()),
                type="item",
                catalog_id="plate_of_food",
                trigger=Trigger(type="date", value="2027-06-15"),
                placement_hint="near_tallest_tree",
                sentiment_ciphertext=_b64(
                    b"Blueberry muffin from Mary's bakery on 20th st."
                ),
                salt=_b64(os.urandom(16)),
                nonce=_b64(os.urandom(12)),
            ),
            GardenGift(
                id=str(uuid.uuid4()),
                type="plant",
                catalog_id="rosebush",
                trigger=Trigger(type="post_letter", value=messages[0].id),
                placement_hint="by_edge",
                sentiment_ciphertext=_b64(
                    b"I planted this the day you were born."
                ),
                salt=_b64(os.urandom(16)),
                nonce=_b64(os.urandom(12)),
            ),
            GardenGift(
                id=str(uuid.uuid4()),
                type="animal",
                catalog_id="cat",
                trigger=Trigger(type="cumulative_visits", value="7"),
                animal_name="Whiskers",
                animal_collar_color="blue",
                sentiment_ciphertext=_b64(
                    b"She always loved cats. This one's for her."
                ),
                salt=_b64(os.urandom(16)),
                nonce=_b64(os.urandom(12)),
            ),
            GardenGift(
                id=str(uuid.uuid4()),
                type="nudge",
                catalog_id="task_prompt",
                trigger=Trigger(type="date", value="2027-12-25"),
                sentiment_ciphertext=_b64(
                    b"Plant something new today."
                ),
                salt=_b64(os.urandom(16)),
                nonce=_b64(os.urandom(12)),
            ),
        ]

    notification = Notification(
        email=notification_email,
        method="self-hosted" if notification_email else None,
    )

    return Bundle(
        bundle_id=str(uuid.uuid4()),
        author_name=author_name,
        passphrase_hint=passphrase_hint,
        bundle_auth_salt=_b64(os.urandom(16)),
        garden_seed=garden_seed,
        messages=messages,
        garden_gifts=gifts,
        notification=notification,
    )
