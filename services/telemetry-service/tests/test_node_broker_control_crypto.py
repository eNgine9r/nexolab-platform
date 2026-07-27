from __future__ import annotations

import base64
from pathlib import Path

import pytest

from app.nodes.broker_control import (
    BrokerControlCryptoError,
    BrokerControlEnvelope,
    BrokerControlOperation,
    BrokerControlSecretCipher,
    broker_control_associated_data,
)


def _cipher(byte: int = 7, *, key_id: str = "broker-key-v1") -> BrokerControlSecretCipher:
    return BrokerControlSecretCipher(bytes([byte]) * 32, key_id=key_id)


def _associated_data(*, command_id: str = "command-01") -> bytes:
    return broker_control_associated_data(
        command_id=command_id,
        organization_id="00000000-0000-0000-0000-000000000001",
        node_id="edge-01",
        operation=BrokerControlOperation.PROVISION,
    )


def test_encrypt_round_trip_never_contains_plaintext() -> None:
    cipher = _cipher()
    secret = "nxl-node-secret-value"

    envelope = cipher.encrypt(secret, associated_data=_associated_data())

    assert envelope.key_id == "broker-key-v1"
    assert secret not in envelope.nonce_b64
    assert secret not in envelope.ciphertext_b64
    assert cipher.decrypt(envelope, associated_data=_associated_data()) == secret


def test_encryption_uses_a_unique_nonce() -> None:
    cipher = _cipher()

    first = cipher.encrypt("same-secret", associated_data=_associated_data())
    second = cipher.encrypt("same-secret", associated_data=_associated_data())

    assert first.nonce_b64 != second.nonce_b64
    assert first.ciphertext_b64 != second.ciphertext_b64


def test_associated_data_prevents_command_rebinding() -> None:
    cipher = _cipher()
    envelope = cipher.encrypt("node-secret", associated_data=_associated_data())

    with pytest.raises(BrokerControlCryptoError, match="authentication failed"):
        cipher.decrypt(
            envelope,
            associated_data=_associated_data(command_id="command-02"),
        )


def test_tampered_ciphertext_fails_closed() -> None:
    cipher = _cipher()
    envelope = cipher.encrypt("node-secret", associated_data=_associated_data())
    raw = bytearray(base64.urlsafe_b64decode(envelope.ciphertext_b64))
    raw[-1] ^= 1
    tampered = BrokerControlEnvelope(
        key_id=envelope.key_id,
        nonce_b64=envelope.nonce_b64,
        ciphertext_b64=base64.urlsafe_b64encode(raw).decode("ascii"),
    )

    with pytest.raises(BrokerControlCryptoError, match="authentication failed"):
        cipher.decrypt(tampered, associated_data=_associated_data())


def test_wrong_key_id_fails_before_decryption() -> None:
    first = _cipher(key_id="broker-key-v1")
    second = _cipher(8, key_id="broker-key-v2")
    envelope = first.encrypt("node-secret", associated_data=_associated_data())

    with pytest.raises(BrokerControlCryptoError, match="key ID is not available"):
        second.decrypt(envelope, associated_data=_associated_data())


def test_key_file_requires_exactly_32_decoded_bytes(tmp_path: Path) -> None:
    key_file = tmp_path / "broker-control-key"
    key_file.write_text(
        base64.urlsafe_b64encode(b"too-short").decode("ascii"),
        encoding="ascii",
    )

    with pytest.raises(BrokerControlCryptoError, match="exactly 32 bytes"):
        BrokerControlSecretCipher.from_key_file(
            key_file,
            key_id="broker-key-v1",
        )


def test_key_file_accepts_one_trailing_newline(tmp_path: Path) -> None:
    key_file = tmp_path / "broker-control-key"
    key_file.write_text(
        base64.urlsafe_b64encode(bytes(range(32))).decode("ascii") + "\n",
        encoding="ascii",
    )

    cipher = BrokerControlSecretCipher.from_key_file(
        key_file,
        key_id="broker-key-v1",
    )
    envelope = cipher.encrypt("node-secret", associated_data=_associated_data())

    assert cipher.decrypt(envelope, associated_data=_associated_data()) == "node-secret"


@pytest.mark.parametrize("secret", ["", "line-one\nline-two", "nul\x00value"])
def test_forbidden_secret_values_are_rejected(secret: str) -> None:
    with pytest.raises(BrokerControlCryptoError):
        _cipher().encrypt(secret, associated_data=_associated_data())
