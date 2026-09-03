from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.identity_link_provisioning import (
    IdentityLinkProvisioningError,
    TargetIdentity,
    find_challenge_user_id,
    resolve_target_identity,
    write_identity_link,
)

ORGANIZATION_ID = "11111111-1111-1111-1111-111111111111"
IDENTITY_ID = "22222222-2222-2222-2222-222222222222"
OTHER_IDENTITY_ID = "33333333-3333-3333-3333-333333333333"
TELEGRAM_USER_ID = 987654321


class FakeAdminClient:
    def __init__(self, users: list[dict[str, object]]) -> None:
        self.users = users

    def list_users(self, access_token: str, organization_id: str) -> list[dict[str, object]]:
        assert access_token == "admin-access"
        assert organization_id == ORGANIZATION_ID
        return self.users


def user_record(*, permissions: list[str] | None = None) -> dict[str, object]:
    return {
        "username": "serhii",
        "identity_id": IDENTITY_ID,
        "is_active": True,
        "effective_permissions": permissions or ["reports.read"],
    }


def test_target_identity_requires_existing_active_reports_reader() -> None:
    client = FakeAdminClient([user_record()])
    target = resolve_target_identity(
        client,  # type: ignore[arg-type]
        access_token="admin-access",
        organization_id=ORGANIZATION_ID,
        username="SERHII",
    )
    assert target == TargetIdentity(
        organization_id=ORGANIZATION_ID,
        username="serhii",
        identity_id=IDENTITY_ID,
    )

    missing_permission = FakeAdminClient([user_record(permissions=["dashboard.read"])])
    with pytest.raises(IdentityLinkProvisioningError, match="target_nexolab_user_missing_reports_read"):
        resolve_target_identity(
            missing_permission,  # type: ignore[arg-type]
            access_token="admin-access",
            organization_id=ORGANIZATION_ID,
            username="serhii",
        )


def test_challenge_accepts_only_fresh_exact_private_sender() -> None:
    command = "/nexolab_link nonce-123"
    updates = [
        {
            "update_id": 10,
            "message": {
                "date": 200,
                "text": command,
                "chat": {"id": -1001, "type": "supergroup"},
                "from": {"id": TELEGRAM_USER_ID},
            },
        },
        {
            "update_id": 11,
            "message": {
                "date": 99,
                "text": command,
                "chat": {"id": TELEGRAM_USER_ID, "type": "private"},
                "from": {"id": TELEGRAM_USER_ID},
            },
        },
        {
            "update_id": 12,
            "message": {
                "date": 200,
                "text": "/nexolab_link wrong",
                "chat": {"id": TELEGRAM_USER_ID, "type": "private"},
                "from": {"id": TELEGRAM_USER_ID},
            },
        },
        {
            "update_id": 13,
            "message": {
                "date": 200,
                "text": command,
                "chat": {"id": TELEGRAM_USER_ID, "type": "private"},
                "from": {"id": TELEGRAM_USER_ID},
            },
        },
    ]
    assert (
        find_challenge_user_id(
            updates,
            expected_text=command,
            min_message_date=100,
        )
        == TELEGRAM_USER_ID
    )


def test_identity_link_write_is_private_idempotent_and_conflict_safe(tmp_path: Path) -> None:
    path = tmp_path / "identity-links.json"
    target = TargetIdentity(
        organization_id=ORGANIZATION_ID,
        username="serhii",
        identity_id=IDENTITY_ID,
    )
    write_identity_link(path, telegram_user_id=TELEGRAM_USER_ID, target=target)
    write_identity_link(path, telegram_user_id=TELEGRAM_USER_ID, target=target)

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload == {
        "version": 1,
        "links": [
            {
                "telegram_user_id": TELEGRAM_USER_ID,
                "organization_id": ORGANIZATION_ID,
                "identity_id": IDENTITY_ID,
            }
        ],
    }
    assert path.stat().st_mode & 0o777 == 0o600

    conflicting_user = TargetIdentity(
        organization_id=ORGANIZATION_ID,
        username="other",
        identity_id=OTHER_IDENTITY_ID,
    )
    with pytest.raises(IdentityLinkProvisioningError, match="telegram_user_already_linked_elsewhere"):
        write_identity_link(
            path,
            telegram_user_id=TELEGRAM_USER_ID,
            target=conflicting_user,
        )

    with pytest.raises(IdentityLinkProvisioningError, match="nexolab_identity_already_linked_elsewhere"):
        write_identity_link(
            path,
            telegram_user_id=TELEGRAM_USER_ID + 1,
            target=target,
        )


def test_identity_link_rejects_invalid_values_before_write(tmp_path: Path) -> None:
    path = tmp_path / "identity-links.json"
    invalid_target = TargetIdentity(
        organization_id=ORGANIZATION_ID,
        username="serhii",
        identity_id="not-a-uuid",
    )
    with pytest.raises(IdentityLinkProvisioningError, match="nexolab_identity_link_invalid"):
        write_identity_link(
            path,
            telegram_user_id=TELEGRAM_USER_ID,
            target=invalid_target,
        )
    assert not path.exists()

    valid_target = TargetIdentity(
        organization_id=ORGANIZATION_ID,
        username="serhii",
        identity_id=IDENTITY_ID,
    )
    with pytest.raises(IdentityLinkProvisioningError, match="telegram_user_id_invalid"):
        write_identity_link(
            path,
            telegram_user_id=(1 << 52),
            target=valid_target,
        )
    assert not path.exists()
