from pathlib import Path

root = Path(__file__).resolve().parents[2]


def replace(path: Path, old: str, new: str, label: str) -> None:
    content = path.read_text()
    if old not in content:
        raise SystemExit(f"{label} marker not found in {path}")
    path.write_text(content.replace(old, new, 1))


repository = root / "services/telemetry-service/app/sessions/repository.py"
replace(
    repository,
    "from dataclasses import dataclass\n",
    "from copy import copy\nfrom dataclasses import dataclass\n",
    "repository copy import",
)
replace(
    repository,
    "from typing import Any\n",
    "from typing import Any, Self\n",
    "repository Self import",
)
replace(
    repository,
    "from app.sessions.models import AuditLog, SessionEvent, TestSession\n",
    '''from app.sessions.models import (
    DEFAULT_ORGANIZATION_ID,
    AuditLog,
    SessionEvent,
    TestSession,
)
''',
    "repository model import",
)
replace(
    repository,
    '''class SessionRepository:
    def __init__(self, database: Database) -> None:
        self._engine = database.engine

    def create(
''',
    '''class SessionRepository:
    def __init__(self, database: Database) -> None:
        self._engine = database.engine
        self._organization_id = DEFAULT_ORGANIZATION_ID

    def for_organization(self, organization_id: str) -> Self:
        normalized = organization_id.strip()
        if not normalized or len(normalized) > 36:
            raise SessionRepositoryError(
                "invalid_organization_id",
                "organization_id must be a non-empty identifier up to 36 characters",
            )
        scoped = copy(self)
        scoped._organization_id = normalized
        return scoped

    def create(
''',
    "repository organization factory",
)
replace(
    repository,
    '''        record = TestSession(
            id=session_id,
            session_number=payload.session_number,
''',
    '''        record = TestSession(
            id=session_id,
            organization_id=self._organization_id,
            session_number=payload.session_number,
''',
    "repository create ownership",
)
replace(
    repository,
    '''                    select(TestSession).where(
                        TestSession.session_number == payload.session_number
                    )
''',
    '''                    select(TestSession).where(
                        TestSession.organization_id == self._organization_id,
                        TestSession.session_number == payload.session_number,
                    )
''',
    "repository create conflict scope",
)
replace(
    repository,
    '''    def get(self, session_id: str) -> TestSession:
        with Session(self._engine, expire_on_commit=False) as db_session:
            record = db_session.get(TestSession, session_id)
            if record is None:
                raise SessionNotFoundError(session_id)
            db_session.expunge(record)
            return record
''',
    '''    def get(self, session_id: str) -> TestSession:
        with Session(self._engine, expire_on_commit=False) as db_session:
            record = self._require_session(db_session, session_id)
            db_session.expunge(record)
            return record
''',
    "repository get scope",
)
replace(
    repository,
    "        filters = []\n",
    "        filters = [TestSession.organization_id == self._organization_id]\n",
    "repository list scope",
)
replace(
    repository,
    '''                    select(TestSession)
                    .where(TestSession.id == session_id)
                    .with_for_update()
''',
    '''                    select(TestSession)
                    .where(
                        TestSession.id == session_id,
                        TestSession.organization_id == self._organization_id,
                    )
                    .with_for_update()
''',
    "repository patch scope",
)
replace(
    repository,
    '''                        select(TestSession)
                        .where(TestSession.id == session_id)
                        .with_for_update()
''',
    '''                        select(TestSession)
                        .where(
                            TestSession.id == session_id,
                            TestSession.organization_id == self._organization_id,
                        )
                        .with_for_update()
''',
    "repository transition scope",
)
replace(
    repository,
    "                record = db_session.get(TestSession, session_id)\n",
    '''                record = db_session.scalar(
                    select(TestSession).where(
                        TestSession.id == session_id,
                        TestSession.organization_id == self._organization_id,
                    )
                )
''',
    "repository transition replay scope",
)
replace(
    repository,
    '''        with Session(self._engine, expire_on_commit=False) as db_session:
            if db_session.get(TestSession, session_id) is None:
                raise SessionNotFoundError(session_id)

            count = int(
''',
    '''        with Session(self._engine, expire_on_commit=False) as db_session:
            self._require_session(db_session, session_id)

            count = int(
''',
    "repository events scope",
)
replace(
    repository,
    '''    @staticmethod
    def _normalize_idempotency_key(value: str) -> str:
''',
    '''    def _require_session(
        self,
        db_session: Session,
        session_id: str,
    ) -> TestSession:
        record = db_session.scalar(
            select(TestSession).where(
                TestSession.id == session_id,
                TestSession.organization_id == self._organization_id,
            )
        )
        if record is None:
            raise SessionNotFoundError(session_id)
        return record

    @staticmethod
    def _normalize_idempotency_key(value: str) -> str:
''',
    "repository require helper",
)

support = root / "services/telemetry-service/app/sessions/configuration_support.py"
replace(
    support,
    '''class ConfigurationSupportMixin:
    _engine: Any
''',
    '''class ConfigurationSupportMixin:
    _engine: Any
    _organization_id: str
''',
    "configuration scope attribute",
)
replace(
    support,
    '''    @staticmethod
    def _locked_session(db_session: Session, session_id: str) -> TestSession:
        record = db_session.scalar(
            select(TestSession)
            .where(TestSession.id == session_id)
            .with_for_update()
        )
        if record is None:
            raise SessionNotFoundError(session_id)
        return record

    @staticmethod
    def _require_session(db_session: Session, session_id: str) -> TestSession:
        record = db_session.get(TestSession, session_id)
        if record is None:
            raise SessionNotFoundError(session_id)
        return record

    @staticmethod
    def _event_by_key(
        db_session: Session,
        session_id: str,
        idempotency_key: str,
    ) -> SessionEvent | None:
        return db_session.scalar(
            select(SessionEvent).where(
                SessionEvent.session_id == session_id,
                SessionEvent.idempotency_key == idempotency_key,
            )
        )
''',
    '''    def _locked_session(
        self,
        db_session: Session,
        session_id: str,
    ) -> TestSession:
        record = db_session.scalar(
            select(TestSession)
            .where(
                TestSession.id == session_id,
                TestSession.organization_id == self._organization_id,
            )
            .with_for_update()
        )
        if record is None:
            raise SessionNotFoundError(session_id)
        return record

    def _require_session(
        self,
        db_session: Session,
        session_id: str,
    ) -> TestSession:
        record = db_session.scalar(
            select(TestSession).where(
                TestSession.id == session_id,
                TestSession.organization_id == self._organization_id,
            )
        )
        if record is None:
            raise SessionNotFoundError(session_id)
        return record

    def _event_by_key(
        self,
        db_session: Session,
        session_id: str,
        idempotency_key: str,
    ) -> SessionEvent | None:
        return db_session.scalar(
            select(SessionEvent)
            .join(TestSession, TestSession.id == SessionEvent.session_id)
            .where(
                SessionEvent.session_id == session_id,
                SessionEvent.idempotency_key == idempotency_key,
                TestSession.organization_id == self._organization_id,
            )
        )
''',
    "configuration scoped helpers",
)

configured = root / "services/telemetry-service/app/sessions/configuration.py"
replace(
    configured,
    "                record = db_session.get(TestSession, session_id)\n",
    '''                record = db_session.scalar(
                    select(TestSession).where(
                        TestSession.id == session_id,
                        TestSession.organization_id == self._organization_id,
                    )
                )
''',
    "configured transition replay scope",
)

audited = root / "services/telemetry-service/app/sessions/audit_repository.py"
replace(
    audited,
    '''            {
                "session_number": payload.session_number,
''',
    '''            {
                "organization_id": self._organization_id,
                "session_number": payload.session_number,
''',
    "audited create fingerprint scope",
)
replace(
    audited,
    '''                    record = TestSession(
                        id=session_id,
                        session_number=payload.session_number,
''',
    '''                    record = TestSession(
                        id=session_id,
                        organization_id=self._organization_id,
                        session_number=payload.session_number,
''',
    "audited create ownership",
)
replace(
    audited,
    '''                    select(TestSession).where(
                        TestSession.session_number == payload.session_number
                    )
''',
    '''                    select(TestSession).where(
                        TestSession.organization_id == self._organization_id,
                        TestSession.session_number == payload.session_number,
                    )
''',
    "audited create conflict scope",
)
replace(
    audited,
    "                record = db_session.get(TestSession, session_id)\n",
    '''                record = db_session.scalar(
                    select(TestSession).where(
                        TestSession.id == session_id,
                        TestSession.organization_id == self._organization_id,
                    )
                )
''',
    "audited stage replay scope",
)
replace(
    audited,
    '''    @staticmethod
    def _create_event_by_key(
        db_session: Session,
        idempotency_key: str,
    ) -> SessionEvent | None:
        return db_session.scalar(
            select(SessionEvent).where(
                SessionEvent.event_type == "session_created",
                SessionEvent.idempotency_key == idempotency_key,
            )
        )
''',
    '''    def _create_event_by_key(
        self,
        db_session: Session,
        idempotency_key: str,
    ) -> SessionEvent | None:
        return db_session.scalar(
            select(SessionEvent)
            .join(TestSession, TestSession.id == SessionEvent.session_id)
            .where(
                SessionEvent.event_type == "session_created",
                SessionEvent.idempotency_key == idempotency_key,
                TestSession.organization_id == self._organization_id,
            )
        )
''',
    "audited create replay key scope",
)
replace(
    audited,
    "        record = db_session.get(TestSession, event.session_id)\n",
    '''        record = db_session.scalar(
            select(TestSession).where(
                TestSession.id == event.session_id,
                TestSession.organization_id == self._organization_id,
            )
        )
''',
    "audited create replay ownership",
)

models = root / "services/telemetry-service/app/sessions/models.py"
replace(
    models,
    '''        nullable=False,
        default=DEFAULT_ORGANIZATION_ID,
    )
''',
    '''        nullable=False,
    )
''',
    "remove temporary model organization default",
)

schemas = root / "services/telemetry-service/app/sessions/schemas.py"
replace(
    schemas,
    '''    id: str
    session_number: str
''',
    '''    id: str
    organization_id: str
    session_number: str
''',
    "session response organization",
)

types = root / "src/lib/sessions/types.ts"
replace(
    types,
    '''export interface LaboratorySession {
  id: string;
  session_number: string;
''',
    '''export interface LaboratorySession {
  id: string;
  organization_id: string;
  session_number: string;
''',
    "frontend session organization",
)

telemetry = root / "services/telemetry-service/app/sessions/telemetry_attribution.py"
replace(
    telemetry,
    '''    def session_exists(self, session_id: str) -> bool:
        with self.engine.connect() as connection:
            return (
                connection.execute(
                    select(TestSession.id).where(TestSession.id == session_id)
                ).scalar_one_or_none()
                is not None
            )
''',
    '''    def session_exists(
        self,
        session_id: str,
        organization_id: str,
    ) -> bool:
        with self.engine.connect() as connection:
            return (
                connection.execute(
                    select(TestSession.id).where(
                        TestSession.id == session_id,
                        TestSession.organization_id == organization_id,
                    )
                ).scalar_one_or_none()
                is not None
            )
''',
    "session telemetry existence scope",
)

test_path = root / "services/telemetry-service/tests/test_session_organization_scope.py"
test_path.write_text('''from __future__ import annotations

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
''')
