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
