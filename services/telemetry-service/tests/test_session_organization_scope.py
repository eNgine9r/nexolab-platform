from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.db import Database
from app.model_registry import register_models
from app.security.models import SecurityOrganization
from app.sessions.audit_repository import AuditedSessionRepository
from app.sessions.repository import SessionNotFoundError
from app.sessions.schemas import SessionCreate

ORGANIZATION_A = "aaaaaaaa-0000-4000-8000-000000000001"
ORGANIZATION_B = "bbbbbbbb-0000-4000-8000-000000000002"


def payload(number: str) -> SessionCreate:
    return SessionCreate(
        session_number=number,
        title="Organization-scoped session",
        test_object="K106",
        node_id="edge-01",
        actor_id="engineer-acceptance",
        actor_source="test-oidc",
        occurred_at=datetime(2026, 7, 26, 9, 0, tzinfo=UTC),
    )


def build_repository(database_path: Path) -> AuditedSessionRepository:
    register_models()
    database = Database(f"sqlite:///{database_path}")
    database.create_schema()
    with Session(database.engine) as session:
        session.add_all(
            [
                SecurityOrganization(
                    id=ORGANIZATION_A,
                    slug="organization-a",
                    name="Organization A",
                ),
                SecurityOrganization(
                    id=ORGANIZATION_B,
                    slug="organization-b",
                    name="Organization B",
                ),
            ]
        )
        session.commit()
    return AuditedSessionRepository(database)


def test_session_numbers_and_create_idempotency_are_scoped_by_organization(
    tmp_path: Path,
) -> None:
    repository = build_repository(tmp_path / "organization-scope.db")
    organization_a = repository.for_organization(ORGANIZATION_A)
    organization_b = repository.for_organization(ORGANIZATION_B)
    command = payload("NXL-SHARED-001")

    created_a = organization_a.create(command, idempotency_key="same-create-key")
    replayed_a = organization_a.create(command, idempotency_key="same-create-key")
    created_b = organization_b.create(command, idempotency_key="same-create-key")

    assert replayed_a.replayed is True
    assert replayed_a.session.id == created_a.session.id
    assert created_b.replayed is False
    assert created_b.session.id != created_a.session.id
    assert created_a.session.organization_id == ORGANIZATION_A
    assert created_b.session.organization_id == ORGANIZATION_B

    page_a = organization_a.list(
        state=None,
        node_id=None,
        limit=10,
        offset=0,
    )
    page_b = organization_b.list(
        state=None,
        node_id=None,
        limit=10,
        offset=0,
    )
    assert [item.id for item in page_a.items] == [created_a.session.id]
    assert [item.id for item in page_b.items] == [created_b.session.id]


def test_foreign_session_identifiers_are_indistinguishable_from_missing_sessions(
    tmp_path: Path,
) -> None:
    repository = build_repository(tmp_path / "organization-nondisclosure.db")
    organization_a = repository.for_organization(ORGANIZATION_A)
    organization_b = repository.for_organization(ORGANIZATION_B)
    created = organization_a.create(
        payload("NXL-PRIVATE-001"),
        idempotency_key="private-create-key",
    )

    with pytest.raises(SessionNotFoundError) as foreign_get:
        organization_b.get(created.session.id)
    with pytest.raises(SessionNotFoundError) as missing_get:
        organization_b.get("00000000-0000-4000-8000-000000000099")
    with pytest.raises(SessionNotFoundError):
        organization_b.events(created.session.id, limit=10, offset=0)
    with pytest.raises(SessionNotFoundError):
        organization_b.configuration(created.session.id)

    assert foreign_get.value.code == missing_get.value.code == "session_not_found"
    assert str(foreign_get.value) != ""
