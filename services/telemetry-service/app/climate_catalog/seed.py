from __future__ import annotations

import json
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.climate_catalog.models import ClimateChamber
from app.climate_catalog.repository import CatalogSeedResult, PostgresClimateCatalogRepository
from app.config import Settings
from app.security.models import SecurityOrganization
from app.sessions.telemetry_attribution import SessionAwareDatabase


SEED_ACTOR = "system:climate-catalog-seed"


def main() -> int:
    settings = Settings()
    database = SessionAwareDatabase(
        settings.database_url,
        connect_timeout_seconds=settings.database_connect_timeout_seconds,
    )
    organization_id = settings.auth_default_organization_id
    try:
        organization_created = _ensure_default_organization(
            database,
            organization_id=organization_id,
        )
        result = _seed_catalogs(
            database,
            default_organization_id=organization_id,
        )
        print(
            json.dumps(
                {
                    "status": "skipped" if result.skipped else "seeded",
                    "changed": organization_created or result.changed,
                    "organization_created": organization_created,
                    "nodes_created": result.nodes_created,
                    "buses_created": result.buses_created,
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


def _catalog_seed_organization_ids(
    database: SessionAwareDatabase,
    *,
    default_organization_id: str,
) -> tuple[str, ...]:
    """Seed the default tenant plus every tenant that already owns a KK2 catalog."""
    with Session(database.engine) as session:
        existing = tuple(
            session.scalars(
                select(ClimateChamber.organization_id)
                .where(ClimateChamber.code == "KK2")
                .distinct()
                .order_by(ClimateChamber.organization_id.asc())
            )
        )
    return tuple(dict.fromkeys((default_organization_id, *existing)))


def _seed_catalogs(
    database: SessionAwareDatabase,
    *,
    default_organization_id: str,
) -> CatalogSeedResult:
    repository = PostgresClimateCatalogRepository(database)
    results = [
        repository.seed_default_catalog(
            organization_id=organization_id,
            actor_subject=SEED_ACTOR,
        )
        for organization_id in _catalog_seed_organization_ids(
            database,
            default_organization_id=default_organization_id,
        )
    ]
    return CatalogSeedResult(
        skipped=all(result.skipped for result in results),
        nodes_created=sum(result.nodes_created for result in results),
        buses_created=sum(result.buses_created for result in results),
        chambers_created=sum(result.chambers_created for result in results),
        devices_created=sum(result.devices_created for result in results),
        channels_created=sum(result.channels_created for result in results),
        physical_sensors_created=sum(result.physical_sensors_created for result in results),
    )


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
                    slug=_bootstrap_organization_slug(organization_id),
                    name="NEXOLAB",
                    is_active=True,
                )
            )
            return True


def _bootstrap_organization_slug(organization_id: str) -> str:
    compact = "".join(
        character for character in organization_id.lower() if character.isalnum()
    )
    suffix = compact[:24] or _stable_uuid(organization_id).replace("-", "")[:24]
    return f"nexolab-{suffix}"


def _stable_uuid(value: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"https://nexolab.local/{value}"))


if __name__ == "__main__":
    raise SystemExit(main())
