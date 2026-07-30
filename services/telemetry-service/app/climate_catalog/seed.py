from __future__ import annotations

import json

from sqlalchemy.orm import Session

from app.climate_catalog.repository import PostgresClimateCatalogRepository
from app.config import Settings
from app.security.models import SecurityOrganization
from app.sessions.telemetry_attribution import SessionAwareDatabase


def main() -> int:
    settings = Settings()
    database = SessionAwareDatabase(
        settings.database_url,
        connect_timeout_seconds=settings.database_connect_timeout_seconds,
    )
    try:
        organization_created = _ensure_default_organization(
            database,
            organization_id=settings.auth_default_organization_id,
        )
        result = PostgresClimateCatalogRepository(database).seed_default_catalog(
            organization_id=settings.auth_default_organization_id,
        )
        print(
            json.dumps(
                {
                    "status": "skipped" if result.skipped else "seeded",
                    "changed": result.changed,
                    "organization_created": organization_created,
                    "nodes_created": result.nodes_created,
                    "chambers_created": result.chambers_created,
                    "devices_created": result.devices_created,
                    "channels_created": result.channels_created,
                    "physical_sensors_created": result.physical_sensors_created,
                },
                sort_keys=True,
            )
        )
        return 0
    finally:
        database.dispose()


def _ensure_default_organization(
    database: SessionAwareDatabase,
    *,
    organization_id: str,
) -> bool:
    with Session(database.engine) as session:
        with session.begin():
            organization = session.get(SecurityOrganization, organization_id)
            if organization is not None:
                return False
            session.add(
                SecurityOrganization(
                    id=organization_id,
                    slug="default",
                    name="NEXOLAB",
                    is_active=True,
                )
            )
            return True


if __name__ == "__main__":
    raise SystemExit(main())
