from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest


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


def test_receipt_acl_commands_are_opt_in_and_no_legacy_acl_is_changed() -> None:
    source = PACKAGED_ADMIN.read_text(encoding="utf-8")
    node = source.split("create_node() {", 1)[1].split("create_ingestion() {", 1)[0]
    ingestion = source.split("create_ingestion() {", 1)[1].split(
        "# Receipt permissions are explicit,", 1
    )[0]
    assert "/receipts" not in node
    assert "/receipts" not in ingestion
    assert "create-receipt-publisher)" in source
    assert "grant-node-receipts)" in source
    assert "subscribeLiteral" in source
    assert "publishClientReceive" in source
    assert "receipt_acls" in source
    assert "Unexpected existing receipt-role ACL" in source
    assert "nexolab-central-receipts-only" in source


def test_isolated_broker_receipt_acceptance_has_real_negative_controls() -> None:
    source = (
        REPOSITORY_ROOT / "scripts" / "run-mqtt-broker-security-acceptance.sh"
    ).read_text(encoding="utf-8")
    for required in (
        "receipt-node-publish-denied",
        "receipt-ingestion-publish-denied",
        "receipt-foreign-node-subscribe-denied",
        "receipt-foreign-org-subscribe-denied",
        "receipt-central-telemetry-publish-denied",
        "receipt-publisher-client-collision",
        "receipt-grant-topic-injection",
        "receipt-after-restart.txt",
    ):
        assert required in source



def test_receipt_security_requires_default_deny_and_exact_existing_node_role() -> None:
    source = PACKAGED_ADMIN.read_text(encoding="utf-8")
    assert "verify_receipt_default_deny" in source
    assert "Receipt ACL requires all broker defaults to deny." in source
    assert 'verify_receipt_role "$base_role" "$base_acl"' in source
    assert "subscribeLiteral" in source
    assert "subscribePattern" not in source.split("grant_node_receipts() {", 1)[1].split(
        "command=", 1
    )[0]


def test_receipt_publisher_has_dedicated_namespace_and_secret_mode_guard() -> None:
    source = PACKAGED_ADMIN.read_text(encoding="utf-8")
    assert 'nexolab-central-receipts-*)' in source
    assert "Receipt client ID must use dedicated namespace." in source
    assert "Receipt publisher username must use dedicated namespace." in source
    assert "Receipt publisher password file permissions must be 0400 or 0600." in source
    assert 'stat -c' in source

    acceptance = (
        REPOSITORY_ROOT / "scripts" / "run-mqtt-broker-security-acceptance.sh"
    ).read_text(encoding="utf-8")
    assert "receipt-publisher-node-client-id-collision" in acceptance
    assert "receipt-publisher-world-readable-secret" in acceptance


def test_receipt_provisioning_fails_closed_for_remote_plaintext_broker() -> None:
    source = PACKAGED_ADMIN.read_text(encoding="utf-8")
    assert "require_secure_receipt_admin" in source
    assert "Receipt ACL provisioning requires TLS for a non-loopback broker." in source
    assert 'require_receipt_identity "$cid"' in source
    acceptance = (
        REPOSITORY_ROOT / "scripts" / "run-mqtt-broker-security-acceptance.sh"
    ).read_text(encoding="utf-8")
    assert "receipt-plaintext-remote-provisioning" in acceptance
    assert "receipt-plaintext-remote-node-grant" in acceptance
    assert "receipt-publisher-unsafe-identifier" in acceptance


# #1762 slice 3: dedicated receipt identities. The fake ``mosquitto_ctrl``
# records every broker call and fails, so these tests prove that unsafe input
# is refused BEFORE any broker administration happens. Real ACL behaviour is
# proved against a disposable Mosquitto in run-mqtt-broker-security-acceptance.sh.

ORG = "00000000-0000-0000-0000-000000000001"
NODE = "edge-01"
SUBSCRIBER = f"receipts:{ORG}:{NODE}"
SUBSCRIBER_CLIENT_ID = f"nexolab-{ORG}-{NODE}-receipts"
PUBLISHER = "nexolab-central-receipts-org-fixture"


def _admin_env(tmp_path: Path) -> tuple[dict[str, str], Path, Path]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    calls = tmp_path / "ctrl-calls.log"
    fake = bin_dir / "mosquitto_ctrl"
    fake.write_text(
        "#!/bin/sh\n" f"printf '%s\\n' \"$*\" >> '{calls}'\n" "exit 1\n",
        encoding="utf-8",
    )
    fake.chmod(0o755)
    admin_secret = tmp_path / "admin-password"
    admin_secret.write_text("fixture-admin-secret", encoding="utf-8")
    admin_secret.chmod(0o600)
    secret = tmp_path / "identity-password"
    secret.write_text("fixture-identity-secret", encoding="utf-8")
    secret.chmod(0o600)
    env = {
        "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '/usr/bin:/bin')}",
        "NEXOLAB_MQTT_ADMIN_PASSWORD_FILE": str(admin_secret),
        "NEXOLAB_MQTT_BROKER_HOST": "127.0.0.1",
    }
    return env, calls, secret


def _run_admin(env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["sh", str(PACKAGED_ADMIN), *args],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


def _broker_calls(calls: Path) -> list[str]:
    return calls.read_text(encoding="utf-8").splitlines() if calls.exists() else []


@pytest.mark.parametrize(
    ("label", "args", "exit_code"),
    [
        ("noncanonical-org", (PUBLISHER, PUBLISHER, "ORG-1"), 78),
        ("uppercase-org", (PUBLISHER, PUBLISHER, ORG.replace("0", "A")), 78),
        ("outside-namespace", ("nexolab-central-ingestion", PUBLISHER, ORG), 81),
        ("telemetry-principal", (f"node:{ORG}:{NODE}", PUBLISHER, ORG), 81),
        ("wildcard-client-id", (PUBLISHER, "nexolab-central-receipts-+/x", ORG), 81),
    ],
)
def test_org_receipt_publisher_refuses_unsafe_input_before_broker_calls(
    tmp_path: Path, label: str, args: tuple[str, ...], exit_code: int
) -> None:
    env, calls, secret = _admin_env(tmp_path)
    completed = _run_admin(env, "create-org-receipt-publisher", *args, str(secret))
    assert completed.returncode == exit_code, (label, completed.stderr)
    assert _broker_calls(calls) == [], label
    assert "fixture-identity-secret" not in completed.stderr


@pytest.mark.parametrize(
    ("label", "args", "exit_code"),
    [
        ("telemetry-principal", (f"node:{ORG}:{NODE}", SUBSCRIBER_CLIENT_ID, ORG, NODE), 81),
        ("telemetry-client-id", (SUBSCRIBER, f"nexolab-{ORG}-{NODE}", ORG, NODE), 81),
        ("other-node-username", (f"receipts:{ORG}:edge-02", SUBSCRIBER_CLIENT_ID, ORG, NODE), 81),
        ("topic-injection", (SUBSCRIBER, SUBSCRIBER_CLIENT_ID, ORG, "edge-01/#"), 78),
        ("wildcard-node", (SUBSCRIBER, SUBSCRIBER_CLIENT_ID, ORG, "+"), 78),
        ("uppercase-node", (SUBSCRIBER, SUBSCRIBER_CLIENT_ID, ORG, "Edge-01"), 78),
        ("noncanonical-org", (SUBSCRIBER, SUBSCRIBER_CLIENT_ID, "org", NODE), 78),
    ],
)
def test_node_receipt_subscriber_refuses_unsafe_input_before_broker_calls(
    tmp_path: Path, label: str, args: tuple[str, ...], exit_code: int
) -> None:
    env, calls, secret = _admin_env(tmp_path)
    completed = _run_admin(env, "create-node-receipt-subscriber", *args, str(secret))
    assert completed.returncode == exit_code, (label, completed.stderr)
    assert _broker_calls(calls) == [], label


@pytest.mark.parametrize("mode", [0o644, 0o640, 0o604])
def test_dedicated_receipt_identities_refuse_readable_secret(tmp_path: Path, mode: int) -> None:
    env, calls, secret = _admin_env(tmp_path)
    secret.chmod(mode)
    publisher = _run_admin(
        env, "create-org-receipt-publisher", PUBLISHER, PUBLISHER, ORG, str(secret)
    )
    subscriber = _run_admin(
        env,
        "create-node-receipt-subscriber",
        SUBSCRIBER,
        SUBSCRIBER_CLIENT_ID,
        ORG,
        NODE,
        str(secret),
    )
    assert publisher.returncode == 82
    assert subscriber.returncode == 82
    assert _broker_calls(calls) == []


def test_dedicated_receipt_identities_refuse_symlinked_secret(tmp_path: Path) -> None:
    env, calls, secret = _admin_env(tmp_path)
    link = tmp_path / "linked-password"
    link.symlink_to(secret)
    subscriber = _run_admin(
        env,
        "create-node-receipt-subscriber",
        SUBSCRIBER,
        SUBSCRIBER_CLIENT_ID,
        ORG,
        NODE,
        str(link),
    )
    assert subscriber.returncode == 82
    assert _broker_calls(calls) == []


def test_dedicated_receipt_identities_refuse_remote_plaintext_administration(
    tmp_path: Path,
) -> None:
    env, calls, secret = _admin_env(tmp_path)
    env["NEXOLAB_MQTT_BROKER_HOST"] = "broker.example.invalid"
    publisher = _run_admin(
        env, "create-org-receipt-publisher", PUBLISHER, PUBLISHER, ORG, str(secret)
    )
    subscriber = _run_admin(
        env,
        "create-node-receipt-subscriber",
        SUBSCRIBER,
        SUBSCRIBER_CLIENT_ID,
        ORG,
        NODE,
        str(secret),
    )
    assert publisher.returncode == 83
    assert subscriber.returncode == 83
    assert _broker_calls(calls) == []


def test_valid_dedicated_identity_checks_default_deny_first(tmp_path: Path) -> None:
    env, calls, secret = _admin_env(tmp_path)
    assert stat.S_IMODE(secret.stat().st_mode) == 0o600
    subscriber = _run_admin(
        env,
        "create-node-receipt-subscriber",
        SUBSCRIBER,
        SUBSCRIBER_CLIENT_ID,
        ORG,
        NODE,
        str(secret),
    )
    # The fake broker answers nothing, so the default-deny gate must refuse.
    assert subscriber.returncode == 82
    assert "Receipt ACL requires all broker defaults to deny." in subscriber.stderr
    assert _broker_calls(calls)[0].endswith("dynsec getDefaultACLAccess")


def test_dedicated_receipt_acls_are_exact_and_least_privilege() -> None:
    source = PACKAGED_ADMIN.read_text(encoding="utf-8")
    publisher = source.split("create_org_receipt_publisher() {", 1)[1].split(
        "# Edge receipt subscriber for exactly one node", 1
    )[0]
    subscriber = source.split("create_node_receipt_subscriber() {", 1)[1].split(
        "command=", 1
    )[0]
    assert 'topic="nexolab/v1/$org/+/receipts"' in publisher
    assert "publishClientSend" in publisher
    for forbidden in ("subscribe", "publishClientReceive", "/telemetry", "nexolab/v1/+/"):
        assert forbidden not in publisher
    assert 'topic="nexolab/v1/$org/$node/receipts"' in subscriber
    assert "subscribeLiteral" in subscriber
    for forbidden in ("publishClientSend", "subscribePattern", "+/receipts"):
        assert forbidden not in subscriber
    assert '[ "$user" = "receipts:$org:$node" ]' in subscriber
    assert '[ "$cid" = "nexolab-$org-$node-receipts" ]' in subscriber
    # The #1450 commands are unchanged and still present.
    assert "create-receipt-publisher)" in source
    assert "grant-node-receipts)" in source


def test_isolated_broker_acceptance_covers_dedicated_identity_denials() -> None:
    acceptance = (
        REPOSITORY_ROOT / "scripts" / "run-mqtt-broker-security-acceptance.sh"
    ).read_text(encoding="utf-8")
    for required in (
        "dedicated-subscriber-publish-not-delivered",
        "dedicated-subscriber-other-node-denied",
        "dedicated-subscriber-wildcard-denied",
        "dedicated-subscriber-foreign-org-denied",
        "org-publisher-subscribe-denied",
        "org-publisher-foreign-org-not-delivered",
        "org-publisher-telemetry-not-delivered",
        "org-publisher-all-org-principal-reuse",
        "subscriber-telemetry-principal-reuse",
        "subscriber-world-readable-secret",
    ):
        assert required in acceptance
