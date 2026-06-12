"""Round-trip tests for the Go-compatible password obfuscation."""

import pytest

from cf_tool.crypto import decrypt_password, encrypt_password
from cf_tool.errors import CFError


def test_round_trip():
    enc = encrypt_password("tourist", "s3cret!")
    assert enc != "s3cret!"
    assert decrypt_password("tourist", enc) == "s3cret!"


def test_nonce_randomized():
    assert encrypt_password("h", "p") != encrypt_password("h", "p")


def test_wrong_handle_fails():
    enc = encrypt_password("tourist", "s3cret!")
    with pytest.raises(CFError):
        decrypt_password("petr", enc)


def test_invalid_hex():
    with pytest.raises(CFError, match="Cannot decode"):
        decrypt_password("h", "not-hex!")


def test_go_compatible_format():
    # 12-byte nonce + ciphertext + 16-byte GCM tag, hex-encoded
    enc = encrypt_password("h", "abc")
    assert len(bytes.fromhex(enc)) == 12 + 3 + 16
