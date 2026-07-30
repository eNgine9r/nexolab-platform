from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.climate_catalog.domain import CLIMATE_CHAMBERS
from app.climate_catalog.repository import PostgresClimateCatalogRepository
from app.config import Settings
from app.nodes.models import CentralNode
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
        nodes_created = _ensure_default_nodes(
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
                    "changed": result.changed or nodes_created > 0,
                    "organization_created": organization_created,
                    "nodes_created": nodes_created + result.nodes_created,
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


def _ensure_default_nodes(
    database: SessionAwareDatabase,
    *,
    organization_id: str,
) -> int:
    now = datetime.now(UTC)
    created = 0
    with Session(database.engine) as session:
        with session.begin():
            existing = {
                item.node_id
                for item in session.scalars(
                    select(CentralNode).where(
                        CentralNode.organization_id == organization_id,
                        CentralNode.node_id.in_(
                            [definition.node_id for definition in CLIMATE_CHAMBERS]
                        ),
                    )
                )
            }
            for definition in CLIMATE_CHAMBERS:
                if definition.node_id in existing:
                    continue
                session.add(
                    CentralNode(
                        id=_stable_uuid(
                            f"central-node:{organization_id}:{definition.node_id}"
                        ),
                        organization_id=organization_id,
                        node_id=definition.node_id,
                        display_name=definition.name,
                        state="active",
                        state_reason="Created by climate chamber catalog seed",
                        clock_warning_ms=30_000,
                        clock_critical_ms=120_000,
                        last_seen_at=None,
                        last_clock_offset_ms=None,
                        clock_status="unknown",
                        clock_observed_at=None,
                        created_by="system:climate-catalog-seed",
                        created_at=now,
                        updated_at=now,
                    )
                )
                created += 1
    return created


def _stable_uuid(value: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"https://nexolab.local/{value}"))


if __name__ == "__main__":
    raise SystemExit(main())
