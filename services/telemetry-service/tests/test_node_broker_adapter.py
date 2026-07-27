from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.nodes.broker_adapter import (
    BrokerControlAdapterError,
    DynamicSecurityAdminAdapter,
    parse_dynamic_security_client,
)
from app.nodes.broker_control import BrokerControlOperation


ORGANIZATION_ID = "00000000-0000-0000-0000-000000000001"
NODE_ID = "edge-01"
USERNAME = f"node:{ORGANIZATION_ID}:{NODE_ID}"
CLIENT_ID = f"nexolab-{ORGANIZATION_ID}-{NODE_ID}"
ROLE = f"nexolab-node-{ORGANIZATION_ID}-{NODE_ID}"
SECRET = "nxl_node_adapter_secret"


def write_adapter_fixture(tmp_path: Path, script_body: str) -> tuple[Path, Path, Path]:
    executable = tmp_path / "nexolab-dynsec-admin"
    executable.write_text("#!/bin/sh\nset -eu\n" + script_body, encoding="utf-8")
    executable.chmod(0o700)

    admin_password = tmp_path / "admin-password"
    admin_password.write_text("nxl_mqtt_admin_secret", encoding="utf-8")
    admin_password.chmod(0o600)

    log_file = tmp_path / "admin-argv.log"
    return executable, admin_password, log_file


def build_adapter(
    executable: Path,
    admin_password: Path,
) -> DynamicSecurityAdminAdapter:
    return DynamicSecurityAdminAdapter(
        executable=str(executable),
        broker_host="mqtt",
        broker_port=1883,
        admin_username="nexolab-security-admin",
        admin_client_id="nexolab-broker-control-worker",
        admin_password_file=str(admin_password),
        timeout_seconds=2,
    )


def command(operation: BrokerControlOperation):
    return SimpleNamespace(
        id="00000000-0000-0000-0000-000000000010",
        organization_id=ORGANIZATION_ID,
        node_id=NODE_ID,
        operation=operation.value,
    )


def test_provision_uses_ephemeral_secret_file_and_strict_reconciliation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable, admin_password, log_file = write_adapter_fixture(
        tmp_path,
        f"""
printf '%s\\n' "$*" >> "$TEST_DYNSEC_LOG"
case "$1" in
  create-node)
    test -r "$6"
    test "$(cat "$6")" = "$TEST_EXPECTED_SECRET"
    ;;
  get-client)
    printf '%s\\n' \
      'Clientid: {CLIENT_ID}' \
      'Disabled: false' \
      'Roles:' \
      '  {ROLE} (priority: 100)'
    ;;
  *) exit 64 ;;
esac
""",
    )
    monkeypatch.setenv("TEST_DYNSEC_LOG", str(log_file))
    monkeypatch.setenv("TEST_EXPECTED_SECRET", SECRET)
    adapter = build_adapter(executable, admin_password)

    adapter.apply(command(BrokerControlOperation.PROVISION), SECRET)

    invocations = log_file.read_text(encoding="utf-8").splitlines()
    assert len(invocations) == 2
    assert SECRET not in " ".join(invocations)
    secret_path = Path(invocations[0].split()[-1])
    assert secret_path.exists() is False
    assert f"create-node {USERNAME} {CLIENT_ID}" in invocations[0]


def test_malformed_client_response_fails_terminally() -> None:
    with pytest.raises(BrokerControlAdapterError) as captured:
        parse_dynamic_security_client("Disabled: false\n")

    assert captured.value.code == "broker_response_invalid"
    assert captured.value.retryable is False


def test_enable_requires_confirmed_enabled_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable, admin_password, log_file = write_adapter_fixture(
        tmp_path,
        f"""
printf '%s\\n' "$*" >> "$TEST_DYNSEC_LOG"
case "$1" in
  enable-client) ;;
  get-client)
    printf '%s\\n' 'Clientid: {CLIENT_ID}' 'Disabled: false'
    ;;
  *) exit 64 ;;
esac
""",
    )
    monkeypatch.setenv("TEST_DYNSEC_LOG", str(log_file))
    adapter = build_adapter(executable, admin_password)

    adapter.apply(command(BrokerControlOperation.ENABLE), None)

    invocations = log_file.read_text(encoding="utf-8").splitlines()
    assert invocations == [f"enable-client {USERNAME}", f"get-client {USERNAME}"]


def test_enable_mismatch_remains_retryable(
    tmp_path: Path,
) -> None:
    executable, admin_password, _ = write_adapter_fixture(
        tmp_path,
        f"""
case "$1" in
  enable-client) ;;
  get-client)
    printf '%s\\n' 'Clientid: {CLIENT_ID}' 'Disabled: true'
    ;;
  *) exit 64 ;;
esac
""",
    )
    adapter = build_adapter(executable, admin_password)

    with pytest.raises(BrokerControlAdapterError) as captured:
        adapter.apply(command(BrokerControlOperation.ENABLE), None)

    assert captured.value.code == "broker_reconciliation_mismatch"
    assert captured.value.retryable is True


def test_disable_requires_confirmed_disabled_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable, admin_password, log_file = write_adapter_fixture(
        tmp_path,
        f"""
printf '%s\\n' "$*" >> "$TEST_DYNSEC_LOG"
case "$1" in
  disable-client) ;;
  get-client)
    printf '%s\\n' 'Clientid: {CLIENT_ID}' 'Disabled: false'
    ;;
  *) exit 64 ;;
esac
""",
    )
    monkeypatch.setenv("TEST_DYNSEC_LOG", str(log_file))
    adapter = build_adapter(executable, admin_password)

    with pytest.raises(BrokerControlAdapterError) as captured:
        adapter.apply(command(BrokerControlOperation.DISABLE), None)

    assert captured.value.code == "broker_reconciliation_mismatch"
    assert captured.value.retryable is True


def test_delete_is_idempotent_when_client_is_already_absent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable, admin_password, log_file = write_adapter_fixture(
        tmp_path,
        """
printf '%s\\n' "$*" >> "$TEST_DYNSEC_LOG"
case "$1" in
  list-clients) printf '%s\\n' 'nexolab-central-ingestion' ;;
  delete-client) exit 72 ;;
  *) exit 64 ;;
esac
""",
    )
    monkeypatch.setenv("TEST_DYNSEC_LOG", str(log_file))
    adapter = build_adapter(executable, admin_password)

    adapter.apply(command(BrokerControlOperation.DELETE), None)

    assert log_file.read_text(encoding="utf-8").splitlines() == ["list-clients"]


def test_delete_requires_confirmed_absence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    counter_file = tmp_path / "list-count"
    executable, admin_password, log_file = write_adapter_fixture(
        tmp_path,
        f"""
printf '%s\\n' "$*" >> "$TEST_DYNSEC_LOG"
case "$1" in
  list-clients)
    count=0
    test ! -f "$TEST_COUNTER" || count="$(cat "$TEST_COUNTER")"
    count=$((count + 1))
    printf '%s' "$count" > "$TEST_COUNTER"
    printf '%s\\n' '{USERNAME}'
    ;;
  delete-client) ;;
  *) exit 64 ;;
esac
""",
    )
    monkeypatch.setenv("TEST_DYNSEC_LOG", str(log_file))
    monkeypatch.setenv("TEST_COUNTER", str(counter_file))
    adapter = build_adapter(executable, admin_password)

    with pytest.raises(BrokerControlAdapterError) as captured:
        adapter.apply(command(BrokerControlOperation.DELETE), None)

    assert captured.value.code == "broker_reconciliation_mismatch"
    assert captured.value.retryable is True
    assert log_file.read_text(encoding="utf-8").splitlines() == [
        "list-clients",
        f"delete-client {USERNAME}",
        "list-clients",
    ]


def test_transport_failure_is_retryable_without_stderr_disclosure(
    tmp_path: Path,
) -> None:
    executable, admin_password, _ = write_adapter_fixture(
        tmp_path,
        "echo 'sensitive broker diagnostic' >&2\nexit 1\n",
    )
    adapter = build_adapter(executable, admin_password)

    with pytest.raises(BrokerControlAdapterError) as captured:
        adapter.apply(command(BrokerControlOperation.DELETE), None)

    assert captured.value.code == "broker_unavailable"
    assert captured.value.retryable is True
    assert "sensitive" not in captured.value.detail


def test_client_id_drift_is_permanent(
    tmp_path: Path,
) -> None:
    executable, admin_password, _ = write_adapter_fixture(
        tmp_path,
        "exit 70\n",
    )
    adapter = build_adapter(executable, admin_password)

    with pytest.raises(BrokerControlAdapterError) as captured:
        adapter.apply(command(BrokerControlOperation.PROVISION), SECRET)

    assert captured.value.code == "broker_command_rejected"
    assert captured.value.retryable is False
