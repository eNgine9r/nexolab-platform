from __future__ import annotations

import base64
import hashlib
import os
from dataclasses import dataclass
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class BrokerCommandKeyError(ValueError):
    code = "broker_command_key_invalid"


class BrokerCommandDecryptionError(RuntimeError):
    code = "broker_command_decryption_failed"


@dataclass(frozen=True, slots=True)
class EncryptedBrokerSecret:
    ciphertext: str
    nonce: str
    key_id: str


class BrokerCommandCipher:
    def __init__(self, key: bytes) -> None:
        if len(key) != 32:
            raise BrokerCommandKeyError("broker command encryption key must be 32 bytes")
        self._key = bytes(key)
        self._aead = AESGCM(self._key)
        self.key_id = hashlib.sha256(self._key).hexdigest()[:16]

    @classmethod
    def from_file(cls, path: str) -> "BrokerCommandCipher":
        key_path = Path(path)
        try:
            encoded = key_path.read_bytes().strip()
        except OSError as error:
            raise BrokerCommandKeyError(
                "broker command encryption key file is not readable"
            ) from error
        if not encoded or any(byte in b" \t\r\n" for byte in encoded):
            raise BrokerCommandKeyError(
                "broker command encryption key must be one base64url token"
            )
        try:
            key = base64.urlsafe_b64decode(encoded)
        except (ValueError, TypeError) as error:
            raise BrokerCommandKeyError(
                "broker command encryption key is not valid base64url"
            ) from error
        return cls(key)

    def encrypt(self, secret: str, *, context: str) -> EncryptedBrokerSecret:
        normalized = _required_secret(secret)
        nonce = os.urandom(12)
        ciphertext = self._aead.encrypt(
            nonce,
            normalized.encode("utf-8"),
            _aad(context),
        )
        return EncryptedBrokerSecret(
            ciphertext=base64.urlsafe_b64encode(ciphertext).decode("ascii"),
            nonce=base64.urlsafe_b64encode(nonce).decode("ascii"),
            key_id=self.key_id,
        )

    def decrypt(
        self,
        *,
        ciphertext: str,
        nonce: str,
        context: str,
        key_id: str,
    ) -> str:
        if key_id != self.key_id:
            raise BrokerCommandDecryptionError(
                "broker command was encrypted with a different key"
            )
        try:
            decoded_ciphertext = base64.urlsafe_b64decode(ciphertext.encode("ascii"))
            decoded_nonce = base64.urlsafe_b64decode(nonce.encode("ascii"))
            plaintext = self._aead.decrypt(
                decoded_nonce,
                decoded_ciphertext,
                _aad(context),
            )
            secret = plaintext.decode("utf-8")
        except (InvalidTag, UnicodeDecodeError, ValueError) as error:
            raise BrokerCommandDecryptionError(
                "broker command secret could not be decrypted"
            ) from error
        return _required_secret(secret)


def broker_secret_context(
    *,
    organization_id: str,
    node_record_id: str,
    credential_id: str,
    command_type: str,
) -> str:
    return "|".join(
        (
            "nexolab-broker-command-v1",
            organization_id,
            node_record_id,
            credential_id,
            command_type,
        )
    )


def _aad(context: str) -> bytes:
    normalized = context.strip()
    if not normalized:
        raise ValueError("broker command encryption context is required")
    return normalized.encode("utf-8")


def _required_secret(secret: str) -> str:
    if not isinstance(secret, str) or not secret:
        raise ValueError("broker command secret is required")
    if any(character.isspace() for character in secret):
        raise ValueError("broker command secret must not contain whitespace")
    return secret
