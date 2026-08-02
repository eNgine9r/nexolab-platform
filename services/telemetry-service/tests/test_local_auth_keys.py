from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.security.local_keys import load_local_signing_keys


def write_key_pair(directory: Path, *, prefix: str) -> tuple[Path, Path]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_path = directory / f"{prefix}-private.pem"
    public_path = directory / f"{prefix}-public.pem"
    private_path.write_bytes(
        private_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    public_path.write_bytes(
        private_key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    return private_path, public_path


def test_matching_external_rsa_key_pair_is_loaded(tmp_path: Path) -> None:
    private_path, public_path = write_key_pair(tmp_path, prefix="local")

    keys = load_local_signing_keys(
        private_key_file=str(private_path),
        public_key_file=str(public_path),
    )

    assert "BEGIN PRIVATE KEY" in keys.private_key_pem
    assert "BEGIN PUBLIC KEY" in keys.public_key_pem


def test_missing_or_mismatched_key_pair_fails_closed(tmp_path: Path) -> None:
    first_private, _ = write_key_pair(tmp_path, prefix="first")
    _, second_public = write_key_pair(tmp_path, prefix="second")

    with pytest.raises(ValueError, match="do not match"):
        load_local_signing_keys(
            private_key_file=str(first_private),
            public_key_file=str(second_public),
        )

    with pytest.raises(ValueError, match="missing or invalid"):
        load_local_signing_keys(
            private_key_file=str(tmp_path / "missing-private.pem"),
            public_key_file=str(second_public),
        )
