from __future__ import annotations

import subprocess
from pathlib import Path


SERVICE_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = SERVICE_ROOT.parents[1]
PACKAGED_ADMIN = SERVICE_ROOT / "bin" / "nexolab-dynsec-admin"
BROKER_ADMIN = (
    REPOSITORY_ROOT
    / "infrastructure"
    / "mqtt"
    / "dynamic-security"
    / "dynsec-admin.sh"
)


def test_packaged_broker_admin_matches_broker_image_contract() -> None:
    assert PACKAGED_ADMIN.read_bytes() == BROKER_ADMIN.read_bytes()


def test_broker_admin_scripts_are_valid_posix_shell() -> None:
    for script in (PACKAGED_ADMIN, BROKER_ADMIN):
        completed = subprocess.run(
            ["sh", "-n", str(script)],
            check=False,
            capture_output=True,
            text=True,
        )
        assert completed.returncode == 0, completed.stderr
