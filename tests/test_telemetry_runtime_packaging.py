from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = ROOT / "services/telemetry-service/Dockerfile"


def test_telemetry_runtime_removes_pip_after_dependency_validation() -> None:
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")

    pip_check = "python -m pip check"
    pip_remove = "python -m pip uninstall --yes pip"
    pip_absent = 'importlib.util.find_spec("pip") is None'

    assert pip_check in dockerfile
    assert pip_remove in dockerfile
    assert pip_absent in dockerfile
    assert dockerfile.index(pip_check) < dockerfile.index(pip_remove)


def test_telemetry_runtime_keeps_fixed_msgpack_and_no_new_security_exception() -> None:
    requirements = (
        ROOT / "services/telemetry-service/requirements.txt"
    ).read_text(encoding="utf-8")
    exceptions = (
        ROOT / "security/vulnerability-exceptions.json"
    ).read_text(encoding="utf-8")

    assert "msgpack==1.2.1" in requirements.splitlines()
    assert "GHSA-6v7p-g79w-8964" not in exceptions
    assert "CVE-2025-47273" not in exceptions
