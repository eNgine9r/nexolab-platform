"""Isolated tests for the source-only NEXOLAB emergency PG dump gate."""

import os
from pathlib import Path
import subprocess

import pytest

SOURCE = Path(__file__).resolve().parents[1] / "nexolab-safe-pg-incident-backup.sh"


def test_source_syntax_and_guardrails() -> None:
    result = subprocess.run(["bash", "-n", str(SOURCE)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    code = SOURCE.read_text()
    for safeguard in (
        "(( EUID == 0 ))",
        "backup_dir=/var/backups/nexolab",
        "nexolab-central/postgres",
        "8#$dir_mode & 0022",
        "reserve_bytes=$((20 * 1024 * 1024 * 1024))",
        "max_bytes=$((4 * 1024 * 1024 * 1024))",
        "default_transaction_read_only=on",
        "pg_dump",
        "-Fc -Z 3",
        "iflag=fullblock",
        "pg_restore --list",
        "PG_RESTORE_ACTUAL=NOT_PERFORMED",
        "trap cleanup EXIT",
    ):
        assert safeguard in code
    for unsafe in ("docker network connect", "docker compose down", "docker restart", "docker volume rm"):
        assert unsafe not in code


def _fixture(tmp_path: Path, *, mode: str, avail: int = 30 * 1024**3, identity: str = "nexolab-central/postgres"):
    """Replace only host/privilege probes in an *isolated copy*, never the product script."""
    backup = tmp_path / "backups"
    backup.mkdir(mode=0o700)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = inspect ]; then\n"
        "  case \"$3\" in\n"
        "    *State.Running*) printf 'true\\n' ;;\n"
        "    *Config.Labels*) printf '%s\\n' \"$MOCK_IDENTITY\" ;;\n"
        "    *) exit 2 ;;\n"
        "  esac\n"
        "elif [ \"$1\" = exec ]; then\n"
        "  if [ \"$2\" = -i ]; then cat >/dev/null; else printf 'fixture archive data'; fi\n"
        "else exit 2; fi\n"
    )
    docker.chmod(0o755)
    df = bin_dir / "df"
    df.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = -B1 ]; then printf 'Avail\\n%s\\n' \"$MOCK_AVAIL\";\n"
        "else printf 'fixture filesystem\\n'; fi\n"
    )
    df.chmod(0o755)
    script = SOURCE.read_text()
    script = script.replace("(( EUID == 0 )) || fail \"root required\"", ": # injected isolated privilege fixture")
    script = script.replace(
        '[[ $(stat -c %u -- "$backup_dir") == 0 ]] || fail "backup directory must be root-owned"',
        ': # injected isolated ownership fixture',
    )
    script = script.replace("backup_dir=/var/backups/nexolab", f"backup_dir={backup}")
    script = script.replace("export PATH=/usr/sbin:/usr/bin:/sbin:/bin", f"export PATH={bin_dir}:/usr/sbin:/usr/bin:/sbin:/bin")
    test_script = tmp_path / "isolated-script.sh"
    test_script.write_text(script)
    env = {**os.environ, "MOCK_AVAIL": str(avail), "MOCK_IDENTITY": identity}
    result = subprocess.run(
        ["bash", str(test_script), *(["--check"] if mode == "check" else [])],
        env=env, capture_output=True, text=True, timeout=15,
    )
    return result, backup


def test_preflight_does_not_create_backup(tmp_path: Path) -> None:
    result, backup = _fixture(tmp_path, mode="check")
    assert result.returncode == 0, result.stderr
    assert "PG_BACKUP_PERFORMED=NO" in result.stdout
    assert list(backup.iterdir()) == []


def test_dump_is_promoted_after_toc_check(tmp_path: Path) -> None:
    result, backup = _fixture(tmp_path, mode="create")
    assert result.returncode == 0, result.stderr
    assert "PG_RESTORE_TOC=PASS" in result.stdout
    assert "PG_RESTORE_ACTUAL=NOT_PERFORMED" in result.stdout
    files = list(backup.iterdir())
    assert len(files) == 1 and files[0].suffix == ".dump"
    assert files[0].read_bytes() == b"fixture archive data"
    assert (files[0].stat().st_mode & 0o777) == 0o600


def test_insufficient_capacity_fails_before_archive(tmp_path: Path) -> None:
    result, backup = _fixture(tmp_path, mode="create", avail=23 * 1024**3)
    assert result.returncode == 78
    assert "reserve" in result.stderr
    assert list(backup.iterdir()) == []


def test_wrong_compose_identity_fails_closed(tmp_path: Path) -> None:
    result, backup = _fixture(tmp_path, mode="create", identity="other/postgres")
    assert result.returncode == 78
    assert "not the accepted" in result.stderr
    assert list(backup.iterdir()) == []


@pytest.mark.parametrize("flag", ["--execute", "--force", "--delete"])
def test_unsupported_flags_fail_closed(tmp_path: Path, flag: str) -> None:
    result = subprocess.run(["bash", str(SOURCE), flag], capture_output=True, text=True, timeout=5)
    assert result.returncode == 78
