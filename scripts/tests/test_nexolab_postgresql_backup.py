from __future__ import annotations

import os
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[2]
POLICY = ROOT / "scripts/lib/postgresql-backup-client.sh"


def client(tmp_path: Path, source: str, **limits: str) -> subprocess.CompletedProcess[str]:
    binary = tmp_path / "pg_dump"
    binary.write_text(source, encoding="utf-8")
    binary.chmod(0o755)
    env = {**os.environ, "PATH": str(tmp_path) + os.pathsep + os.environ["PATH"],
           "POSTGRES_USER": "fixture", "POSTGRES_DB": "fixture", **limits}
    return subprocess.run(["sh", str(POLICY), "dump"], env=env,
                          capture_output=True, text=True, timeout=15, check=False)


def test_limits_and_readonly_options_reach_actual_client(tmp_path: Path) -> None:
    result = client(tmp_path, """#!/bin/sh
printf 'memory=%s cpu=%s\n' "$(ulimit -v)" "$(ulimit -t)"
printf '%s\n' "$PGOPTIONS" "$*"
""")
    assert result.returncode == 0, result.stderr
    assert "memory=524288 cpu=600" in result.stdout
    assert "default_transaction_read_only=on" in result.stdout
    assert "statement_timeout=900000" in result.stdout
    assert "-Fc -Z 3 --lock-wait-timeout=15000" in result.stdout


@pytest.mark.parametrize("value", ["0", "unlimited", "-1", "1000000000000000000000", "901"])
def test_invalid_or_unbounded_timeout_fails_before_client(tmp_path: Path, value: str) -> None:
    result = client(tmp_path, "#!/bin/sh\nprintf 'must not execute'\n",
                    NEXOLAB_BACKUP_CLIENT_TIMEOUT_SECONDS=value)
    assert result.returncode == 78
    assert not result.stdout


def test_timer_terminates_client_and_reaps_it(tmp_path: Path) -> None:
    pid_file = tmp_path / "client.pid"
    result = client(tmp_path, f"#!/bin/sh\nprintf '%s' \"$$\" > '{pid_file}'\nexec sleep 30\n",
                    NEXOLAB_BACKUP_CLIENT_TIMEOUT_SECONDS="1")
    assert result.returncode in (124, 143), result.stderr
    pid = int(pid_file.read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_address_space_limit_prevents_large_allocation(tmp_path: Path) -> None:
    python = shutil.which("python3")
    assert python
    result = client(tmp_path, f"""#!{python}
import sys
try:
    bytearray(128 * 1024 * 1024)
except MemoryError:
    print('allocation refused')
    sys.exit(0)
sys.exit(3)
""", NEXOLAB_BACKUP_CLIENT_MEMORY_KIB="65536")
    assert result.returncode == 0, result.stderr
    assert "allocation refused" in result.stdout


def test_cpu_limit_terminates_runaway_client(tmp_path: Path) -> None:
    python = shutil.which("python3")
    assert python
    result = client(tmp_path, f"#!{python}\nwhile True:\n    pass\n",
                    NEXOLAB_BACKUP_CLIENT_CPU_SECONDS="1",
                    NEXOLAB_BACKUP_CLIENT_TIMEOUT_SECONDS="10")
    assert result.returncode in (137, -9), result.stderr


def test_missing_priority_tool_fails_before_client(tmp_path: Path) -> None:
    for name in ("nice", "timeout", "pg_dump"):
        binary = tmp_path / name
        binary.write_text("#!/bin/sh\nprintf 'must not execute'\n")
        binary.chmod(0o755)
    result = subprocess.run(["/bin/sh", str(POLICY), "dump"],
                            env={"PATH": str(tmp_path)}, capture_output=True, text=True)
    assert result.returncode == 78
    assert "ionice" in result.stderr
    assert not result.stdout


def test_required_installed_and_packaged_policy_is_bound_to_inventory() -> None:
    builder = (ROOT / "scripts/build-offline-bundle.sh").read_text()
    installer = (ROOT / "scripts/deploy-version-manager-service.sh").read_text()
    assert 'cp scripts/lib/postgresql-backup-client.sh "$STAGING/scripts/lib/"' in builder
    assert '"$SOURCE_ROOT/scripts/lib/postgresql-backup-client.sh" \\' in installer
    assert '/usr/local/lib/nexolab/lib/postgresql-backup-client.sh' in installer
    assert '"bounded-postgresql-backup"' in builder


def test_new_bundle_capability_requires_policy_in_verified_inventory(tmp_path: Path) -> None:
    spec = importlib.util.spec_from_file_location("backup_bundle_verifier", ROOT / "scripts/verify-offline-bundle.py")
    verifier = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verifier)
    (tmp_path / "evidence").mkdir()
    provenance = tmp_path / "evidence/provenance.json"
    provenance.write_text(json.dumps({"tooling_capabilities": ["bounded-postgresql-backup"]}))
    with pytest.raises(SystemExit, match="not digest-bound"):
        verifier.verify_backup_policy_inventory(tmp_path, set())
    verifier.verify_backup_policy_inventory(tmp_path, {"scripts/lib/postgresql-backup-client.sh"})
    provenance.write_text(json.dumps({"tooling_capabilities": ["split-runtime-tooling"]}))
    verifier.verify_backup_policy_inventory(tmp_path, set())
    provenance.write_text(json.dumps({"tooling_capabilities": None}))
    with pytest.raises(SystemExit, match="Invalid tooling capabilities"):
        verifier.verify_backup_policy_inventory(tmp_path, set())


@pytest.mark.parametrize("failure", ["none", "dump", "list"])
def test_source_backup_promotes_only_verified_archive_and_preserves_failure(
    tmp_path: Path, failure: str,
) -> None:
    binary_dir = tmp_path / "bin"
    binary_dir.mkdir()
    commands = {
        "docker": """#!/bin/sh
[ "$1" = exec ] || exit 2
shift
[ "$1" != -i ] || shift
shift
exec "$@"
""",
        "pg_dump": "#!/bin/sh\nprintf 'fixture archive'\n" + ("exit 1\n" if failure == "dump" else ""),
        "pg_restore": "#!/bin/sh\ncat >/dev/null\n" + ("exit 1\n" if failure == "list" else ""),
    }
    for name, source in commands.items():
        binary = binary_dir / name
        binary.write_text(source)
        binary.chmod(0o755)
    audit = tmp_path / "audit"
    audit.mkdir()
    deploy = (ROOT / "scripts/deploy-current-head-raspberry-pi.sh").read_text()
    start = deploy.index('if [[ -n "$PG_CONTAINER" ]]; then\n  log "Creating PostgreSQL pre-upgrade backup"')
    block = deploy[start:deploy.index('\nif ! git diff --quiet', start)]
    script = f'''set -eu
umask 077
source '{ROOT / "scripts/deploy-capacity-guard.sh"}'
log() {{ :; }}
fail() {{ printf '%s\\n' "$*" >&2; exit 1; }}
PG_CONTAINER=fixture
AUDIT_DIR='{audit}'
{block}
'''
    result = subprocess.run(["bash", "-c", script], timeout=15, capture_output=True, text=True,
                            env={**os.environ, "PATH": str(binary_dir)+os.pathsep+os.environ["PATH"],
                                 "POSTGRES_USER": "fixture", "POSTGRES_DB": "fixture"})
    archive = audit / "postgresql-pre-upgrade.dump"
    partial = audit / ".postgresql-pre-upgrade.dump.partial"
    if failure == "none":
        assert result.returncode == 0, result.stderr
        assert archive.read_bytes() == b"fixture archive"
        assert not partial.exists()
    else:
        assert result.returncode != 0
        assert not archive.exists()
        assert partial.read_bytes() == b"fixture archive"
    assert (audit / "postgresql-backup.err").stat().st_mode & 0o777 == 0o600


def test_historical_checkout_cannot_remove_pinned_client_policy(tmp_path: Path) -> None:
    helper = tmp_path / "deploy-capacity-guard.sh"
    helper.write_text((ROOT / "scripts/deploy-capacity-guard.sh").read_text())
    (tmp_path / "lib").mkdir()
    policy = tmp_path / "lib/postgresql-backup-client.sh"
    policy.write_text(POLICY.read_text())
    result = subprocess.run(["bash", "-c", f"source '{helper}'; mv '{policy}' '{policy}.preserved'; nexolab_postgresql_client_policy"],
                            env={**os.environ, "NEXOLAB_POSTGRESQL_CLIENT_POLICY": "inherited-unsafe-code"},
                            text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr
    assert result.stdout == POLICY.read_text()
    assert "inherited-unsafe-code" not in result.stdout


def test_missing_policy_cannot_be_replaced_by_inherited_environment(tmp_path: Path) -> None:
    helper = tmp_path / "deploy-capacity-guard.sh"
    helper.write_text((ROOT / "scripts/deploy-capacity-guard.sh").read_text())
    result = subprocess.run(["bash", "-c", f"source '{helper}'; nexolab_postgresql_client_policy"],
                            env={**os.environ, "NEXOLAB_POSTGRESQL_CLIENT_POLICY": "inherited-unsafe-code"},
                            text=True, capture_output=True, check=False)
    assert result.returncode == 78
    assert not result.stdout
