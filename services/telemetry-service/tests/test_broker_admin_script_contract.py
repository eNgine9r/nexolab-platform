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
