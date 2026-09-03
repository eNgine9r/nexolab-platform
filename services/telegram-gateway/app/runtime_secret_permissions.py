from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat

_DEFAULT_SECRET_DIR = "/etc/nexolab/telegram"
_DEFAULT_RUNTIME_GID = 65532
_RUNTIME_SECRET_FILES = (
    "bot-token",
    "nexolab-backend-password",
    "identity-links.json",
)


class RuntimeSecretPermissionError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def prepare_gateway_secret_permissions(
    secret_dir: Path,
    *,
    runtime_gid: int = _DEFAULT_RUNTIME_GID,
    expected_owner_uid: int = 0,
) -> tuple[str, ...]:
    if runtime_gid < 1:
        raise RuntimeSecretPermissionError("runtime_gid_invalid")
    try:
        directory_stat = secret_dir.lstat()
    except OSError as error:
        raise RuntimeSecretPermissionError("secret_directory_unavailable") from error
    if not stat.S_ISDIR(directory_stat.st_mode) or directory_stat.st_uid != expected_owner_uid:
        raise RuntimeSecretPermissionError("secret_directory_ownership_invalid")

    paths: list[Path] = []
    for name in _RUNTIME_SECRET_FILES:
        path = secret_dir / name
        try:
            file_stat = path.lstat()
        except OSError as error:
            raise RuntimeSecretPermissionError("runtime_secret_unavailable") from error
        if (
            not stat.S_ISREG(file_stat.st_mode)
            or file_stat.st_uid != expected_owner_uid
            or file_stat.st_nlink != 1
            or stat.S_IMODE(file_stat.st_mode) & 0o022
        ):
            raise RuntimeSecretPermissionError("runtime_secret_permissions_invalid")
        paths.append(path)

    for path in paths:
        os.chown(path, expected_owner_uid, runtime_gid, follow_symlinks=False)
        os.chmod(path, 0o640, follow_symlinks=False)
    os.chown(secret_dir, expected_owner_uid, runtime_gid, follow_symlinks=False)
    os.chmod(secret_dir, 0o750, follow_symlinks=False)
    return _RUNTIME_SECRET_FILES


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Grant the pinned nonroot Telegram Gateway runtime group read-only secret access."
    )
    parser.add_argument("--secret-dir", default=_DEFAULT_SECRET_DIR)
    parser.add_argument("--runtime-gid", type=int, default=_DEFAULT_RUNTIME_GID)
    args = parser.parse_args()
    if os.geteuid() != 0:
        print(json.dumps({"ok": False, "error": "root_required"}))
        return 2
    try:
        files = prepare_gateway_secret_permissions(
            Path(args.secret_dir),
            runtime_gid=args.runtime_gid,
        )
    except RuntimeSecretPermissionError as error:
        print(json.dumps({"ok": False, "error": error.code}, sort_keys=True))
        return 2
    print(
        json.dumps(
            {"ok": True, "runtime_gid": args.runtime_gid, "files": list(files)},
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
