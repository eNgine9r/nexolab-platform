from __future__ import annotations

import importlib.util
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
HARNESS_PATH = REPO_ROOT / "infrastructure" / "compose" / "m4-session-acceptance.py"


def load_harness():
    spec = importlib.util.spec_from_file_location("m4_session_acceptance", HARNESS_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_harness_contract_is_explicit_and_deterministic(tmp_path: Path) -> None:
    harness = load_harness()

    parser = harness.build_parser()
    args = parser.parse_args(["pre-reboot", "--confirm-real-hardware"])
    assert args.phase == "pre-reboot"
    assert args.confirm_real_hardware is True

    env_file = tmp_path / "edge.env"
    env_file.write_text(
        "# comment\n"
        "RS485_HOST_DEVICE=/dev/serial/by-id/usb-nexolab\n"
        "HARDWARE_DEVICE_MODE=xjp60d\n",
        encoding="utf-8",
    )
    assert harness.load_env(env_file) == {
        "RS485_HOST_DEVICE": "/dev/serial/by-id/usb-nexolab",
        "HARDWARE_DEVICE_MODE": "xjp60d",
    }

    first = harness.digest({"series": 34, "state": "running"})
    second = harness.digest({"state": "running", "series": 34})
    assert first == second
    assert len(first) == 64

    source = HARNESS_PATH.read_text(encoding="utf-8")
    assert "/dev/serial/by-id/" in source
    assert "--confirm-real-hardware" in source
    assert "docker compose down --volumes" not in source
    assert "docker compose down -v" not in source
