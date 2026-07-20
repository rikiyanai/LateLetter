"""
Real encryption layer for .lateletter bundles (SPEC §4, "step 13").

Primitive: PBKDF2-HMAC-SHA256 key derivation + AES-256-GCM, recorded
per-message in ``kdf_params``.  The spec's default primitive (Argon2id,
``kdf_params: null``) needs a WASM port in the browser viewer; PBKDF2 is
native to WebCrypto on both sides, so it ships first.  A bundle sealed by
this module is openable by ``viewer-bnw.html`` with no network access.

Layout parity with the dev fixtures:
- message plaintext is UTF-8 JSON ``{"label": ..., "body": ...}``
- gift sentiment plaintext is raw UTF-8 text
- GCM tag is appended to the ciphertext (both `cryptography` and WebCrypto
  do this natively)
- bundle ``hmac`` is HMAC-SHA256 over the canonical visible payload, keyed
  by PBKDF2(passphrase, bundle_auth_salt)

Passphrase loss means permanent loss of all messages — by design.
"""

from __future__ import annotations

import base64
import hashlib
import hmac as hmac_mod
import json
import os
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .bundle import (
    BUNDLE_VERSION_WITH_GARDEN_PROGRAM,
    Bundle,
    GardenGift,
    GardenProgramEnvelope,
    Message,
    canonical_json,
)

# Recorded in every sealed message so the viewer knows how to derive keys.
KDF_PARAMS_V0: dict[str, Any] = {
    "name": "PBKDF2",
    "hash": "SHA-256",
    "iterations": 600_000,
}

_SALT_LEN = 16
_NONCE_LEN = 12
_KEY_LEN = 32
_GARDEN_PROGRAM_AAD = b"lateletter:garden-program:v1"


def _b64e(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _b64d(text: str) -> bytes:
    return base64.b64decode(text)


def derive_key(passphrase: str, salt: bytes,
               params: dict[str, Any] | None = None) -> bytes:
    params = params or KDF_PARAMS_V0
    if params.get("name") != "PBKDF2" or params.get("hash") != "SHA-256":
        raise ValueError(f"Unsupported kdf_params: {params!r}")
    return hashlib.pbkdf2_hmac(
        "sha256", passphrase.encode("utf-8"), salt,
        int(params["iterations"]), dklen=_KEY_LEN,
    )


def seal_message(passphrase: str, *, message_id: str, date: str,
                 label: str, body: str) -> Message:
    salt = os.urandom(_SALT_LEN)
    nonce = os.urandom(_NONCE_LEN)
    key = derive_key(passphrase, salt)
    plaintext = json.dumps(
        {"label": label, "body": body}, ensure_ascii=False,
    ).encode("utf-8")
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, None)
    return Message(
        id=message_id, date=date,
        ciphertext=_b64e(ciphertext), salt=_b64e(salt), nonce=_b64e(nonce),
        kdf_params=dict(KDF_PARAMS_V0),
    )


def open_message(passphrase: str, message: Message) -> dict[str, str]:
    key = derive_key(passphrase, _b64d(message.salt), message.kdf_params)
    plaintext = AESGCM(key).decrypt(
        _b64d(message.nonce), _b64d(message.ciphertext), None,
    )
    return json.loads(plaintext.decode("utf-8"))


def seal_gift_sentiment(passphrase: str, gift: GardenGift,
                        sentiment: str) -> None:
    """Encrypt sentiment text in place using the bundle-wide KDF params."""
    salt = os.urandom(_SALT_LEN)
    nonce = os.urandom(_NONCE_LEN)
    key = derive_key(passphrase, salt)
    ciphertext = AESGCM(key).encrypt(nonce, sentiment.encode("utf-8"), None)
    gift.sentiment_ciphertext = _b64e(ciphertext)
    gift.salt = _b64e(salt)
    gift.nonce = _b64e(nonce)


def open_gift_sentiment(passphrase: str, gift: GardenGift) -> str:
    key = derive_key(passphrase, _b64d(gift.salt))
    plaintext = AESGCM(key).decrypt(
        _b64d(gift.nonce), _b64d(gift.sentiment_ciphertext), None,
    )
    return plaintext.decode("utf-8")


def seal_garden_program(
    passphrase: str,
    program: dict[str, Any],
) -> GardenProgramEnvelope:
    """Encrypt a validated inner Garden program for a version 2 bundle."""
    salt = os.urandom(_SALT_LEN)
    nonce = os.urandom(_NONCE_LEN)
    params = dict(KDF_PARAMS_V0)
    key = derive_key(passphrase, salt, params)
    ciphertext = AESGCM(key).encrypt(
        nonce, canonical_json(program), _GARDEN_PROGRAM_AAD,
    )
    return GardenProgramEnvelope(
        version=1,
        ciphertext=_b64e(ciphertext),
        salt=_b64e(salt),
        nonce=_b64e(nonce),
        kdf_params=params,
    )


def open_garden_program(
    passphrase: str,
    envelope: GardenProgramEnvelope,
) -> dict[str, Any]:
    """Authenticate and decrypt a version 2 Garden program envelope."""
    if envelope.version != 1:
        raise ValueError(f"Unsupported garden program version: {envelope.version}")
    key = derive_key(passphrase, _b64d(envelope.salt), envelope.kdf_params)
    plaintext = AESGCM(key).decrypt(
        _b64d(envelope.nonce), _b64d(envelope.ciphertext), _GARDEN_PROGRAM_AAD,
    )
    program = json.loads(plaintext.decode("utf-8"))
    if not isinstance(program, dict):
        raise ValueError("Garden program plaintext must be a JSON object.")
    return program


def compute_bundle_hmac(bundle: Bundle, passphrase: str) -> str:
    params = (
        bundle.bundle_auth_kdf_params
        if bundle.version >= BUNDLE_VERSION_WITH_GARDEN_PROGRAM else None
    )
    key = derive_key(passphrase, _b64d(bundle.bundle_auth_salt), params)
    payload = canonical_json(bundle.visible_payload())
    return hmac_mod.new(key, payload, hashlib.sha256).hexdigest()


def seal_bundle(bundle: Bundle, passphrase: str) -> None:
    """Finalize a bundle: set bundle_auth_salt if missing, hmac, checksum."""
    if not bundle.bundle_auth_salt:
        bundle.bundle_auth_salt = _b64e(os.urandom(_SALT_LEN))
    if bundle.version >= BUNDLE_VERSION_WITH_GARDEN_PROGRAM:
        if bundle.garden_program is None:
            raise ValueError("Version 2 bundles require an encrypted garden program.")
        if bundle.garden_gifts:
            raise ValueError("Version 2 bundles cannot carry legacy garden gifts.")
        if bundle.bundle_auth_kdf_params is None:
            bundle.bundle_auth_kdf_params = dict(KDF_PARAMS_V0)
    bundle.hmac = compute_bundle_hmac(bundle, passphrase)
    bundle.checksum = bundle.compute_checksum()


def verify_bundle_hmac(bundle: Bundle, passphrase: str) -> bool:
    if not bundle.hmac:
        return False
    expected = compute_bundle_hmac(bundle, passphrase)
    return hmac_mod.compare_digest(expected, bundle.hmac)
