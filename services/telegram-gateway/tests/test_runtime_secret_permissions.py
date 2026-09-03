from __future__ import annotations

import os
from pathlib import Path
import stat

import pytest

from app.runtime_secret_permissions import (
    RuntimeSecretPermissionError,
    prepare_gateway_secret_permissions,
)


def create_runtime_secrets(path: Path) -> None:
    path.mkdir(mode=0o700)
    for name in ("bot-token", "nexolab-backend-password", "identity-links.json"):
        secret = path / name
        secret.write_text("fixture", encoding="utf-8")
        secret.chmod(0o600)


def test_prepares_root_owned_shape_for_nonroot_runtime_group(tmp_path: Path) -> None:
    secret_dir = tmp_path / "telegram"
    create_runtime_secrets(secret_dir)
    uid = os.getuid()
    runtime_gid = 65532

    files = prepare_gateway_secret_permissions(
        secret_dir, runtime_gid=runtime_gid, expected_owner_uid=uid
    )

    assert files == ("bot-token", "nexolab-backend-password", "identity-links.json")
    assert stat.S_IMODE(secret_dir.stat().st_mode) == 0o750
    assert secret_dir.stat().st_uid == uid
    assert secret_dir.stat().st_gid == runtime_gid
    for name in files:
        current = (secret_dir / name).stat()
        assert stat.S_IMODE(current.st_mode) == 0o640
        assert current.st_uid == uid
        assert current.st_gid == runtime_gid


def test_refuses_symlinked_or_missing_runtime_secret(tmp_path: Path) -> None:
    secret_dir = tmp_path / "telegram"
    create_runtime_secrets(secret_dir)
    (secret_dir / "identity-links.json").unlink()
    (secret_dir / "identity-links.json").symlink_to(secret_dir / "bot-token")

    with pytest.raises(RuntimeSecretPermissionError, match="runtime_secret_permissions_invalid"):
        prepare_gateway_secret_permissions(
            secret_dir, runtime_gid=65532, expected_owner_uid=os.getuid()
        )


def test_refuses_group_or_other_writable_secret(tmp_path: Path) -> None:
    secret_dir = tmp_path / "telegram"
    create_runtime_secrets(secret_dir)
    (secret_dir / "bot-token").chmod(0o660)

    with pytest.raises(RuntimeSecretPermissionError, match="runtime_secret_permissions_invalid"):
        prepare_gateway_secret_permissions(
            secret_dir, runtime_gid=65532, expected_owner_uid=os.getuid()
        )
