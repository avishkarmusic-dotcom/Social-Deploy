"""Envelope encryption for anything that would be catastrophic in a dump.

Two things live here: OAuth tokens and message bodies. Both are encrypted with
a per-workspace data key, which is itself encrypted with the master key from the
environment. Rotating the master key rewraps N workspace keys, not N million
rows — which is the difference between a rotation you actually perform and one
you keep postponing.
"""
from __future__ import annotations

import base64
import os
from functools import lru_cache

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import settings


class EncryptionUnavailable(RuntimeError):
    pass


@lru_cache(maxsize=1)
def _master() -> AESGCM:
    if not settings.data_encryption_key:
        raise EncryptionUnavailable(
            "DATA_ENCRYPTION_KEY isn't set. Generate one with "
            "`openssl rand -base64 32` before connecting any channel."
        )
    return AESGCM(base64.b64decode(settings.data_encryption_key))


def new_workspace_key() -> tuple[bytes, bytes]:
    """Returns (plaintext_key, wrapped_key). Only the wrapped one is stored."""
    key = AESGCM.generate_key(bit_length=256)
    nonce = os.urandom(12)
    return key, nonce + _master().encrypt(nonce, key, None)


def unwrap(wrapped: bytes) -> bytes:
    return _master().decrypt(wrapped[:12], wrapped[12:], None)


def seal(plaintext: str, key: bytes, *, aad: str = "") -> bytes:
    """AAD binds the ciphertext to its context, so a token stolen from one
    account's row can't be replayed into another's."""
    nonce = os.urandom(12)
    return nonce + AESGCM(key).encrypt(nonce, plaintext.encode(), aad.encode() or None)


def open_sealed(blob: bytes, key: bytes, *, aad: str = "") -> str:
    return AESGCM(key).decrypt(blob[:12], blob[12:], aad.encode() or None).decode()
