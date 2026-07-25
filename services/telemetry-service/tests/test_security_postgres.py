from __future__ import annotations

import os
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.db import Database
from app.security.authentication import VerifiedIdentityClaims
from app.security.authorization import Role
from app.security.repository import AuditEventInput, SecurityRepository


pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL", "").startswith("postgresql"),
    reason="PostgreSQL is required for trigger validation",
)


def test_security_audit_events_are_append_only_in_postgres() -> None:
    database = Database(os.environ["DATABASE_URL"])
    repository = SecurityRepository(database)
    suffix = uuid4().hex
    organization_id = str(uuid4())
    claims = VerifiedIdentityClaims(
        provider="test-oidc",
        subject=f"auditor-{suffix}",
        email=f"auditor-{suffix}@example.test",
    )

    try:
        repository.provision_organization(
            organization_id=organization_id,
            slug=f"audit-{suffix}",
            name="Audit trigger laboratory",
        )
        security_session = repository.provision_membership(
            organization_id=organization_id,
            claims=claims,
            roles={Role.AUDITOR},
        )
        event = repository.append_audit_event(
            AuditEventInput(
                organization_id=organization_id,
                actor_identity_id=security_session.identity_id,
                actor_subject=claims.subject,
                actor_roles=frozenset({Role.AUDITOR}),
                action="security.audit.verified",
                entity_type="security_test",
                entity_id=suffix,
                after_snapshot={"status": "created"},
            )
        )

        with pytest.raises(DBAPIError):
            with database.engine.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE security_audit_events SET reason = 'tampered' "
                        "WHERE id = :event_id"
                    ),
                    {"event_id": event.id},
                )
        with pytest.raises(DBAPIError):
            with database.engine.begin() as connection:
                connection.execute(
                    text("DELETE FROM security_audit_events WHERE id = :event_id"),
                    {"event_id": event.id},
                )

        rows = repository.list_audit_events(
            organization_id=organization_id,
            limit=10,
        )
        assert [row.id for row in rows] == [event.id]
    finally:
        database.dispose()
