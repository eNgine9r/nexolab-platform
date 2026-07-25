from __future__ import annotations

from pathlib import Path

from app.db import Database
from app.security.authentication import VerifiedIdentityClaims
from app.security.authorization import Role
from app.security.repository import AuditEventInput, SecurityRepository


ORGANIZATION_ID = "11111111-1111-1111-1111-111111111111"


def repository(tmp_path: Path) -> SecurityRepository:
    database = Database(f"sqlite:///{tmp_path / 'security.db'}")
    database.create_schema()
    return SecurityRepository(database)


def claims(subject: str = "user-1") -> VerifiedIdentityClaims:
    return VerifiedIdentityClaims(
        provider="test-oidc",
        subject=subject,
        email=f"{subject}@example.test",
        display_name=subject,
    )


def test_membership_resolves_principal_with_database_roles(tmp_path: Path) -> None:
    repo = repository(tmp_path)
    repo.provision_organization(
        organization_id=ORGANIZATION_ID,
        slug="nexolab-lab",
        name="NEXOLAB Laboratory",
    )
    repo.provision_membership(
        organization_id=ORGANIZATION_ID,
        claims=claims(),
        roles={Role.OPERATOR, Role.AUDITOR},
        assigned_by="bootstrap",
    )

    identity_id, principal = repo.resolve_principal(
        claims(),
        organization_id=ORGANIZATION_ID,
    )

    assert identity_id
    assert principal.organization_id == ORGANIZATION_ID
    assert principal.roles == frozenset({Role.OPERATOR, Role.AUDITOR})


def test_reprovisioning_replaces_role_assignments(tmp_path: Path) -> None:
    repo = repository(tmp_path)
    repo.provision_organization(
        organization_id=ORGANIZATION_ID,
        slug="nexolab-lab",
        name="NEXOLAB Laboratory",
    )
    repo.provision_membership(
        organization_id=ORGANIZATION_ID,
        claims=claims(),
        roles={Role.OPERATOR, Role.AUDITOR},
    )
    session = repo.provision_membership(
        organization_id=ORGANIZATION_ID,
        claims=claims(),
        roles={Role.VIEWER},
    )

    assert session.memberships[0].roles == frozenset({Role.VIEWER})


def test_audit_event_is_returned_newest_first(tmp_path: Path) -> None:
    repo = repository(tmp_path)
    repo.provision_organization(
        organization_id=ORGANIZATION_ID,
        slug="nexolab-lab",
        name="NEXOLAB Laboratory",
    )
    security_session = repo.provision_membership(
        organization_id=ORGANIZATION_ID,
        claims=claims(),
        roles={Role.AUDITOR},
    )
    actor = security_session.identity_id

    first = repo.append_audit_event(
        AuditEventInput(
            organization_id=ORGANIZATION_ID,
            actor_identity_id=actor,
            actor_subject="user-1",
            actor_roles=frozenset({Role.AUDITOR}),
            action="layout.draft.updated",
            entity_type="equipment_layout",
            entity_id="showcase-1",
            after_snapshot={"version": 2},
        )
    )
    second = repo.append_audit_event(
        AuditEventInput(
            organization_id=ORGANIZATION_ID,
            actor_identity_id=actor,
            actor_subject="user-1",
            actor_roles=frozenset({Role.AUDITOR}),
            action="layout.published",
            entity_type="equipment_layout",
            entity_id="showcase-1",
            before_snapshot={"version": 2},
            after_snapshot={"revision": 1},
        )
    )

    rows = repo.list_audit_events(
        organization_id=ORGANIZATION_ID,
        entity_type="equipment_layout",
        entity_id="showcase-1",
        limit=10,
    )

    assert [row.id for row in rows] == [second.id, first.id]
    assert rows[0].actor_roles == ["auditor"]
