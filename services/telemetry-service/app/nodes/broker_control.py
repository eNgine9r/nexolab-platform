from __future__ import annotations

import base64
import binascii
import json
import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class BrokerControlOperation(str, Enum):
    PROVISION = "provision"
    ROTATE = "rotate"
    ENABLE = "enable"
    DISABLE = "disable"
    DELETE = "delete"


class BrokerControlState(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    RETRYING = "retrying"
    APPLIED = "applied"
    FAILED = "failed"


class BrokerControlCryptoError(RuntimeError):
    """Raised when broker-control secret material cannot be handled safely."""


@dataclass(frozen=True, slots=True)
class BrokerControlEnvelope:
    key_id: str
    nonce_b64: str
    ciphertext_b64: str


class BrokerControlSecretCipher:
    def __init__(self, key: bytes, *, key_id: str) -> None:
        if len(key) != 32:
            raise BrokerControlCryptoError(
                "broker-control encryption key must decode to exactly 32 bytes"
            )
        normalized_key_id = key_id.strip()
        if not normalized_key_id or len(normalized_key_id) > 64:
            raise BrokerControlCryptoError(
                "broker-control encryption key ID must be 1..64 characters"
            )
        self._cipher = AESGCM(bytes(key))
        self._key_id = normalized_key_id

    @classmethod
    def from_key_file(
        cls,
        key_file: str | Path,
        *,
        key_id: str,
    ) -> "BrokerControlSecretCipher":
        path = Path(key_file)
        try:
            encoded = path.read_text(encoding="ascii").rstrip("\r\n")
        except (OSError, UnicodeError) as error:
            raise BrokerControlCryptoError(
                "broker-control encryption key file is not readable"
            ) from error
        if not encoded or "\r" in encoded or "\n" in encoded:
            raise BrokerControlCryptoError(
                "broker-control encryption key file must contain one key"
            )
        try:
            key = base64.b64decode(
                encoded,
                altchars=b"-_",
                validate=True,
            )
        except (binascii.Error, ValueError) as error:
            raise BrokerControlCryptoError(
                "broker-control encryption key file is not valid base64url"
            ) from error
        return cls(key, key_id=key_id)

    @property
    def key_id(self) -> str:
        return self._key_id

    def encrypt(self, secret: str, *, associated_data: bytes) -> BrokerControlEnvelope:
        normalized_secret = _validate_secret(secret)
        if not associated_data:
            raise BrokerControlCryptoError("broker-control associated data is required")
        nonce = os.urandom(12)
        ciphertext = self._cipher.encrypt(
            nonce,
            normalized_secret.encode("utf-8"),
            associated_data,
        )
        return BrokerControlEnvelope(
            key_id=self._key_id,
            nonce_b64=_base64url_encode(nonce),
            ciphertext_b64=_base64url_encode(ciphertext),
        )

    def decrypt(
        self,
        envelope: BrokerControlEnvelope,
        *,
        associated_data: bytes,
    ) -> str:
        if envelope.key_id != self._key_id:
            raise BrokerControlCryptoError(
                "broker-control envelope key ID is not available"
            )
        if not associated_data:
            raise BrokerControlCryptoError("broker-control associated data is required")
        try:
            nonce = _base64url_decode(envelope.nonce_b64)
            ciphertext = _base64url_decode(envelope.ciphertext_b64)
            if len(nonce) != 12:
                raise ValueError("invalid AES-GCM nonce length")
            plaintext = self._cipher.decrypt(nonce, ciphertext, associated_data)
            secret = plaintext.decode("utf-8")
        except (binascii.Error, UnicodeError, ValueError, InvalidTag) as error:
            raise BrokerControlCryptoError(
                "broker-control envelope authentication failed"
            ) from error
        return _validate_secret(secret)


def broker_control_associated_data(
    *,
    command_id: str,
    organization_id: str,
    node_id: str,
    operation: BrokerControlOperation | str,
) -> bytes:
    values = {
        "command_id": _required_text(command_id, "command_id", 36),
        "node_id": _required_text(node_id, "node_id", 64),
        "operation": BrokerControlOperation(operation).value,
        "organization_id": _required_text(
            organization_id,
            "organization_id",
            36,
        ),
        "schema_version": 1,
    }
    return json.dumps(
        values,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")


def _validate_secret(secret: str) -> str:
    if not isinstance(secret, str):
        raise BrokerControlCryptoError("broker-control secret must be text")
    if not secret or len(secret) > 1024:
        raise BrokerControlCryptoError(
            "broker-control secret must contain 1..1024 characters"
        )
    if any(character in secret for character in ("\r", "\n", "\x00")):
        raise BrokerControlCryptoError(
            "broker-control secret contains forbidden control characters"
        )
    return secret


def _required_text(value: str, field: str, maximum: int) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > maximum:
        raise BrokerControlCryptoError(
            f"broker-control {field} must contain 1..{maximum} characters"
        )
    return normalized


def _base64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii")


def _base64url_decode(value: str) -> bytes:
    return base64.b64decode(
        value.encode("ascii"),
        altchars=b"-_",
        validate=True,
    )
