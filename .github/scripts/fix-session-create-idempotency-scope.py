from pathlib import Path

root = Path(__file__).resolve().parents[2]


def replace(path: Path, old: str, new: str, label: str) -> None:
    content = path.read_text()
    if old not in content:
        raise SystemExit(f"{label} marker not found in {path}")
    path.write_text(content.replace(old, new, 1))


migration = root / "services/telemetry-service/migrations/versions/20260726_0009_scope_test_sessions_to_organizations.py"
replace(
    migration,
    '''    op.add_column(
        "test_sessions",
        sa.Column("organization_id", sa.String(length=36), nullable=True),
    )
''',
    '''    op.add_column(
        "test_sessions",
        sa.Column("organization_id", sa.String(length=36), nullable=True),
    )
    op.add_column(
        "test_sessions",
        sa.Column(
            "create_idempotency_key",
            sa.String(length=128),
            nullable=True,
        ),
    )
''',
    "migration add create key",
)
replace(
    migration,
    '''    op.alter_column(
        "test_sessions",
        "organization_id",
        existing_type=sa.String(length=36),
        nullable=False,
    )
''',
    '''    op.execute(
        """
        UPDATE test_sessions
        SET create_idempotency_key = COALESCE(
            (
                SELECT session_events.idempotency_key
                FROM session_events
                WHERE session_events.session_id = test_sessions.id
                  AND session_events.event_type = 'session_created'
                ORDER BY session_events.inserted_at, session_events.id
                LIMIT 1
            ),
            'legacy:' || test_sessions.id
        )
        WHERE create_idempotency_key IS NULL
        """
    )
    op.alter_column(
        "test_sessions",
        "organization_id",
        existing_type=sa.String(length=36),
        nullable=False,
    )
    op.alter_column(
        "test_sessions",
        "create_idempotency_key",
        existing_type=sa.String(length=128),
        nullable=False,
    )
''',
    "migration backfill create key",
)
replace(
    migration,
    '''    op.drop_constraint(
        "uq_test_sessions_session_number",
        "test_sessions",
        type_="unique",
    )
''',
    '''    op.drop_index(
        "uq_session_created_idempotency_key",
        table_name="session_events",
    )
    op.drop_constraint(
        "uq_test_sessions_session_number",
        "test_sessions",
        type_="unique",
    )
''',
    "migration drop global create key index",
)
replace(
    migration,
    '''    op.create_unique_constraint(
        "uq_test_sessions_organization_number",
        "test_sessions",
        ["organization_id", "session_number"],
    )
''',
    '''    op.create_unique_constraint(
        "uq_test_sessions_organization_number",
        "test_sessions",
        ["organization_id", "session_number"],
    )
    op.create_unique_constraint(
        "uq_test_sessions_organization_create_key",
        "test_sessions",
        ["organization_id", "create_idempotency_key"],
    )
''',
    "migration create scoped create key constraint",
)
replace(
    migration,
    '''    op.drop_constraint(
        "uq_test_sessions_organization_number",
        "test_sessions",
        type_="unique",
    )
''',
    '''    op.drop_constraint(
        "uq_test_sessions_organization_create_key",
        "test_sessions",
        type_="unique",
    )
    op.drop_constraint(
        "uq_test_sessions_organization_number",
        "test_sessions",
        type_="unique",
    )
''',
    "migration downgrade scoped create key",
)
replace(
    migration,
    '''    op.create_unique_constraint(
        "uq_test_sessions_session_number",
        "test_sessions",
        ["session_number"],
    )
''',
    '''    op.create_unique_constraint(
        "uq_test_sessions_session_number",
        "test_sessions",
        ["session_number"],
    )
    op.create_index(
        "uq_session_created_idempotency_key",
        "session_events",
        ["idempotency_key"],
        unique=True,
        postgresql_where=sa.text("event_type = 'session_created'"),
        sqlite_where=sa.text("event_type = 'session_created'"),
    )
''',
    "migration downgrade global create key index",
)
replace(
    migration,
    '''    op.drop_column("test_sessions", "organization_id")
''',
    '''    op.drop_column("test_sessions", "create_idempotency_key")
    op.drop_column("test_sessions", "organization_id")
''',
    "migration drop create key column",
)

models = root / "services/telemetry-service/app/sessions/models.py"
replace(
    models,
    '''        UniqueConstraint(
            "organization_id",
            "session_number",
            name="uq_test_sessions_organization_number",
        ),
''',
    '''        UniqueConstraint(
            "organization_id",
            "session_number",
            name="uq_test_sessions_organization_number",
        ),
        UniqueConstraint(
            "organization_id",
            "create_idempotency_key",
            name="uq_test_sessions_organization_create_key",
        ),
''',
    "model create key unique constraint",
)
replace(
    models,
    '''    session_number: Mapped[str] = mapped_column(String(64), nullable=False)
''',
    '''    create_idempotency_key: Mapped[str] = mapped_column(
        String(128), nullable=False
    )
    session_number: Mapped[str] = mapped_column(String(64), nullable=False)
''',
    "model create key field",
)

audit_repository = root / "services/telemetry-service/app/sessions/audit_repository.py"
replace(
    audit_repository,
    '''                        organization_id=self._organization_id,
                        session_number=payload.session_number,
''',
    '''                        organization_id=self._organization_id,
                        create_idempotency_key=normalized_key,
                        session_number=payload.session_number,
''',
    "audited create stores scoped key",
)

repository = root / "services/telemetry-service/app/sessions/repository.py"
replace(
    repository,
    '''            organization_id=self._organization_id,
            session_number=payload.session_number,
''',
    '''            organization_id=self._organization_id,
            create_idempotency_key=normalized_key,
            session_number=payload.session_number,
''',
    "base create stores scoped key",
)

immutability = root / "services/telemetry-service/app/sessions/audit_immutability.py"
replace(
    immutability,
    '''    event.listen(
        SessionEvent.__table__,
        "after_create",
        DDL(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS
                uq_session_created_idempotency_key
            ON session_events(idempotency_key)
            WHERE event_type = 'session_created'
            """
        ).execute_if(dialect="sqlite"),
    )

''',
    "",
    "remove sqlite global create idempotency index",
)

schema_test = root / "services/telemetry-service/tests/test_session_schema.py"
replace(
    schema_test,
    '''    assert unique_constraints["uq_test_sessions_organization_number"] == (
        "organization_id",
        "session_number",
    )

    indexes = {index.name: index for index in table.indexes}
''',
    '''    assert unique_constraints["uq_test_sessions_organization_number"] == (
        "organization_id",
        "session_number",
    )
    assert unique_constraints[
        "uq_test_sessions_organization_create_key"
    ] == (
        "organization_id",
        "create_idempotency_key",
    )

    indexes = {index.name: index for index in table.indexes}
''',
    "schema metadata create key assertion",
)
replace(
    schema_test,
    '''        assert session_unique_constraints[
            "uq_test_sessions_organization_number"
        ] == ("organization_id", "session_number")

        session_indexes = {
''',
    '''        assert session_unique_constraints[
            "uq_test_sessions_organization_number"
        ] == ("organization_id", "session_number")
        assert session_unique_constraints[
            "uq_test_sessions_organization_create_key"
        ] == ("organization_id", "create_idempotency_key")

        session_indexes = {
''',
    "schema migration create key assertion",
)

api_test = root / "services/telemetry-service/tests/test_session_api_organization_scope.py"
replace(
    api_test,
    '''from app.main import create_app
''',
    '''from app.main import create_app
from app.model_registry import register_models
''',
    "api test model registry import",
)
replace(
    api_test,
    '''    app = create_app(settings)
    with Session(app.state.database.engine) as session:
''',
    '''    register_models()
    app = create_app(settings)
    app.state.database.create_schema()
    with Session(app.state.database.engine) as session:
''',
    "api test create complete schema",
)
