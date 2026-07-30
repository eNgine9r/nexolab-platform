from __future__ import annotations

import json

from app.climate_catalog.repository import PostgresClimateCatalogRepository
from app.config import Settings
from app.sessions.telemetry_attribution import SessionAwareDatabase


def main() -> int:
    settings = Settings()
    database = SessionAwareDatabase(
        settings.database_url,
        connect_timeout_seconds=settings.database_connect_timeout_seconds,
    )
    try:
        result = PostgresClimateCatalogRepository(database).seed_default_catalog(
            organization_id=settings.auth_default_organization_id,
        )
        print(
            json.dumps(
                {
                    "status": "skipped" if result.skipped else "seeded",
                    "changed": result.changed,
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


if __name__ == "__main__":
    raise SystemExit(main())
