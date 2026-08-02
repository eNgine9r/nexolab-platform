from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey, RSAPublicKey


@dataclass(frozen=True, slots=True)
class LocalSigningKeys:
    private_key_pem: str
    public_key_pem: str


def load_local_signing_keys(
    *,
    private_key_file: str,
    public_key_file: str,
) -> LocalSigningKeys:
    private_path = _validated_path(private_key_file, "private key")
    public_path = _validated_path(public_key_file, "public key")
    if private_path.resolve() == public_path.resolve():
        raise ValueError("local auth private and public key files must be different")

    try:
        private_bytes = private_path.read_bytes()
        public_bytes = public_path.read_bytes()
        private_key = serialization.load_pem_private_key(private_bytes, password=None)
        public_key = serialization.load_pem_public_key(public_bytes)
    except (OSError, ValueError, TypeError) as error:
        raise ValueError("local auth signing key files are missing or invalid") from error

    if not isinstance(private_key, RSAPrivateKey) or not isinstance(public_key, RSAPublicKey):
        raise ValueError("local auth signing keys must be RSA PEM keys")
    if private_key.key_size < 2048 or public_key.key_size < 2048:
        raise ValueError("local auth RSA keys must be at least 2048 bits")

    private_public_der = private_key.public_key().public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    public_der = public_key.public_bytes(
        serialization.Encoding.DER,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    if private_public_der != public_der:
        raise ValueError("local auth private and public keys do not match")

    return LocalSigningKeys(
        private_key_pem=private_bytes.decode("utf-8"),
        public_key_pem=public_bytes.decode("utf-8"),
    )


def load_public_key_file(path: str) -> str:
    public_path = _validated_path(path, "public key")
    try:
        value = public_path.read_text(encoding="utf-8")
        key = serialization.load_pem_public_key(value.encode("utf-8"))
    except (OSError, ValueError, TypeError) as error:
        raise ValueError("JWT public key file is missing or invalid") from error
    if not isinstance(key, RSAPublicKey) or key.key_size < 2048:
        raise ValueError("JWT public key must be an RSA key of at least 2048 bits")
    return value


def _validated_path(value: str, label: str) -> Path:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"local auth {label} file is required")
    return Path(normalized)
