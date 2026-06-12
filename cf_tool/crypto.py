"""Password obfuscation, byte-compatible with xalanq/cf-tool.

AES-128-GCM with key = MD5("glhf" + handle + "233"), hex(nonce + ciphertext).
The key derives only from the handle, so this is obfuscation against casual
file reads, not real security — same trade-off the Go tool documents.
"""

from __future__ import annotations

import hashlib
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from cf_tool.errors import CFError

_NONCE_SIZE = 12


def _key(handle_or_email: str) -> bytes:
    return hashlib.md5(f"glhf{handle_or_email}233".encode()).digest()


def encrypt_password(handle_or_email: str, password: str) -> str:
    nonce = os.urandom(_NONCE_SIZE)
    sealed = AESGCM(_key(handle_or_email)).encrypt(nonce, password.encode(), None)
    return (nonce + sealed).hex()


def decrypt_password(handle_or_email: str, encrypted: str) -> str:
    try:
        data = bytes.fromhex(encrypted)
    except ValueError as e:
        raise CFError("Cannot decode the password") from e
    try:
        plain = AESGCM(_key(handle_or_email)).decrypt(data[:_NONCE_SIZE], data[_NONCE_SIZE:], None)
    except (InvalidTag, ValueError) as e:
        raise CFError("Cannot decrypt the password (wrong handle?)") from e
    return plain.decode()
