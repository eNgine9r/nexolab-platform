from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from uuid import uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
import sqlalchemy as sa

from app.security.authorization import Permission


MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "migrations/versions/20261106_0038_add_navigation_grants.py"
)
spec = importlib.util.spec_from_file_location("navigation_grants_migration", MIGRATION_PATH)
assert spec and spec.loader
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)


def test_migration_values_match_the_closed_authorization_contract() -> None:
    assert set(migration._OLD_PERMISSIONS + migration._NAVIGATION_PERMISSIONS) == {
        item.value for item in Permission
    }
    assert len(migration._NAVIGATION_PERMISSIONS) == len(set(migration._NAVIGATION_PERMISSIONS))


def legacy_grants(metadata: sa.MetaData) -> sa.Table:
    return sa.Table(
        "security_membership_permissions", metadata,
        sa.Column("membership_id", sa.String(36), primary_key=True),
        sa.Column("permission", sa.String(128), primary_key=True),
        sa.Column("assigned_by", sa.String(255)),
        sa.Column("assigned_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "permission IN (" + ", ".join(f"'{value}'" for value in migration._OLD_PERMISSIONS) + ")",
            name="ck_security_membership_permission_known",
        ),
    )


def test_upgrade_preserves_resource_grants_and_backfills_only_existing_visibility(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    metadata = sa.MetaData()
    grants = legacy_grants(metadata)
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(grants.insert(), [
            {"membership_id": "one", "permission": "dashboard.read", "assigned_by": "original"},
            {"membership_id": "one", "permission": "reports.read", "assigned_by": "original"},
            {"membership_id": "two", "permission": "telemetry.read", "assigned_by": "original"},
        ])
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
        migration.upgrade()
        # Repeating the backfill must never create duplicate grants.
        migration.upgrade()
        rows = connection.execute(sa.text(
            "SELECT membership_id, permission, assigned_by FROM security_membership_permissions"
        )).all()
        by_user = {user: {permission for member, permission, _ in rows if member == user}
                   for user in ("one", "two")}
        assert by_user["one"] == {
            "dashboard.read", "reports.read", "navigation.overview", "navigation.sessions",
            "navigation.equipment_layouts", "navigation.refrigeration", "navigation.equipment",
            "navigation.reports",
        }
        assert by_user["two"] == {"telemetry.read", "navigation.live", "navigation.energy"}
        assert all("navigation.cameras" not in values and "navigation.lockers" not in values
                   for values in by_user.values())
        assert {(member, permission, actor) for member, permission, actor in rows if not permission.startswith("navigation.")} == {
            ("one", "dashboard.read", "original"), ("one", "reports.read", "original"),
            ("two", "telemetry.read", "original"),
        }
        assert all(actor == migration._ACTOR for _, permission, actor in rows if permission.startswith("navigation."))
        with pytest.raises(RuntimeError, match="separately verified recovery"):
            migration.downgrade()
        assert connection.scalar(sa.text("SELECT count(*) FROM security_membership_permissions")) == len(rows)
    engine.dispose()


def test_postgresql_upgrade_uses_a_rolled_back_isolated_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    database_url = os.environ.get("DATABASE_URL", "")
    try:
        url = sa.engine.make_url(database_url)
    except (sa.exc.ArgumentError, TypeError):
        pytest.skip("loopback PostgreSQL test database not configured")
    if (url.get_backend_name() != "postgresql" or url.host not in {"localhost", "127.0.0.1", "::1"}
            or not (url.database or "").endswith("_test")):
        pytest.skip("requires a loopback PostgreSQL database explicitly named *_test")
    engine = sa.create_engine(url)
    schema = f"nav_grants_fixture_{uuid4().hex}"
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
            connection.exec_driver_sql(f'SET LOCAL search_path TO "{schema}"')
            metadata = sa.MetaData()
            grants = legacy_grants(metadata)
            metadata.create_all(connection)
            connection.execute(grants.insert(), [
                {"membership_id": "one", "permission": "dashboard.read", "assigned_by": "original"},
                {"membership_id": "two", "permission": "telemetry.read", "assigned_by": "original"},
            ])
            monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
            migration.upgrade()
            rows = connection.execute(sa.text(
                "SELECT membership_id, permission FROM security_membership_permissions"
            )).all()
            assert ("one", "navigation.sessions") in rows
            assert ("two", "navigation.energy") in rows
            assert ("two", "navigation.sessions") not in rows
            assert ("one", "navigation.cameras") not in rows
            with pytest.raises(sa.exc.IntegrityError):
                with connection.begin_nested():
                    connection.execute(sa.text(
                        "INSERT INTO security_membership_permissions "
                        "(membership_id, permission, assigned_at) "
                        "VALUES ('one', 'navigation.unknown', CURRENT_TIMESTAMP)"
                    ))
            with pytest.raises(RuntimeError, match="separately verified recovery"):
                migration.downgrade()
        finally:
            # The schema and every test row are transactional PostgreSQL DDL.
            transaction.rollback()
    engine.dispose()
