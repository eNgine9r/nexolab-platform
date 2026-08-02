from __future__ import annotations

import pytest

from app.security.passwords import (
    PasswordHashError,
    dummy_password_hash,
    hash_password,
    verify_password,
)


def test_scrypt_password_hash_round_trip() -> None:
    encoded = hash_password("Correct-Horse-Battery-47")

    assert encoded.startswith("scrypt$16384$8$1$")
    assert verify_password("Correct-Horse-Battery-47", encoded)
    assert not verify_password("incorrect-password", encoded)


def test_password_hash_rejects_weak_or_ambiguous_input() -> None:
    with pytest.raises(PasswordHashError, match="at least 12"):
        hash_password("too-short")
    with pytest.raises(PasswordHashError, match="whitespace"):
        hash_password(" leading-password-value")


def test_password_verifier_rejects_malformed_and_excessive_parameters() -> None:
    assert not verify_password("anything", "not-a-password-hash")
    assert not verify_password(
        "anything",
        "scrypt$2097152$8$1$MDAwMDAwMDAwMDAwMDAwMA$YWJjZGVmZ2hpamtsbW5vcHFyc3R1dnd4eXo",
    )


def test_dummy_password_hash_is_valid_for_constant_work_unknown_users() -> None:
    assert verify_password("nexolab-dummy-password", dummy_password_hash())
    assert not verify_password("another-password", dummy_password_hash())
