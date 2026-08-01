from __future__ import annotations

import base64
import hashlib
import hmac
import secrets


SCHEME = "scrypt"
DEFAULT_N = 2**14
DEFAULT_R = 8
DEFAULT_P = 1
DEFAULT_DKLEN = 64
SALT_BYTES = 16


class PasswordHashError(ValueError):
    pass


def hash_password(password: str) -> str:
    normalized = _validated_password(password)
    salt = secrets.token_bytes(SALT_BYTES)
    digest = hashlib.scrypt(
        normalized.encode("utf-8"),
        salt=salt,
        n=DEFAULT_N,
        r=DEFAULT_R,
        p=DEFAULT_P,
        dklen=DEFAULT_DKLEN,
    )
    return "$".join(
        (
            SCHEME,
            str(DEFAULT_N),
            str(DEFAULT_R),
            str(DEFAULT_P),
            _encode(salt),
            _encode(digest),
        )
    )


def verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, n_text, r_text, p_text, salt_text, digest_text = encoded.split("$", 5)
        if scheme != SCHEME:
            return False
        n = int(n_text)
        r = int(r_text)
        p = int(p_text)
        if n < 2**14 or n > 2**20 or r < 1 or r > 32 or p < 1 or p > 16:
            return False
        salt = _decode(salt_text)
        expected = _decode(digest_text)
        if len(salt) < 16 or len(expected) < 32:
            return False
        actual = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=n,
            r=r,
            p=p,
            dklen=len(expected),
        )
    except (ValueError, TypeError, MemoryError):
        return False
    return hmac.compare_digest(actual, expected)


def dummy_password_hash() -> str:
    return (
        "scrypt$16384$8$1$"
        "MDAwMDAwMDAwMDAwMDAwMA$"
        "Nq7hWn5mJ4l1YLlW8v0Q8G0dKqHj7Pq7B7P6mE6KjU8J0ZJxjBz3zj1lW1y4G5cW"
        "pYwz4p6QnM7Q0R4K7bM5A"
    )


def _validated_password(password: str) -> str:
    if not isinstance(password, str):
        raise PasswordHashError("password must be a string")
    if len(password) < 12:
        raise PasswordHashError("password must contain at least 12 characters")
    if len(password) > 256:
        raise PasswordHashError("password must not exceed 256 characters")
    if password.strip() != password:
        raise PasswordHashError("password must not start or end with whitespace")
    return password


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)
