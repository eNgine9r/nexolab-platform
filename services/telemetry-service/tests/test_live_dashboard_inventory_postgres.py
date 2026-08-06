from __future__ import annotations

import json
import os
from pathlib import Path
from time import perf_counter
from uuid import uuid4

import pytest
from sqlalchemy import delete, text
from sqlalchemy.orm import Session

from app.climate_catalog.models import (
    ClimateChamber,
    MeasurementBus,
    MeasurementChannel,
    MeasurementDevice,
)
from app.db import Database, TelemetrySample
from app.live_dashboard.inventory import (
    inventory_query_plan_statement,
    list_live_dashboard_inventory,
)
from app.live_dashboard.repository import LiveDashboardRepository
from app.nodes.models import CentralNode
from app.security.models import SecurityOrganization
from app.security.repository import SecurityRepository
from tests.live_dashboard_test_support import provision_inventory


pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL", "").startswith("postgresql"),
    reason="PostgreSQL is required for inventory query-plan evidence",
)


def test_postgres_inventory_plan_is_bounded_and_uses_latest_identity_index() -> None:
    database = Database(os.environ["DATABASE_URL"])
    repository = LiveDashboardRepository(database)
    security = SecurityRepository(database)
    suffix = f"plan-{uuid4().hex[:8]}"
    organization_id = str(uuid4())
    unrelated_node_id = f"unrelated-{suffix}"
    catalog_node_id = f"edge-{suffix}"
    catalog_equipment_id = f"controller-{suffix}"
    catalog_channel_id = f"{suffix}-temperature-01"
    evidence_path = Path(
        os.environ.get(
            "NEXOLAB_INVENTORY_PLAN_EVIDENCE_PATH",
            "/tmp/live-dashboard-inventory-postgres-plan.json",
        )
    )

    try:
        security.provision_organization(
            organization_id=organization_id,
            slug=f"inventory-{suffix}",
            name="Inventory query-plan laboratory",
        )
        provision_inventory(database, organization_id, suffix)

        with database.engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO telemetry_samples (
                        event_id, node_id, captured_at, metric, value, unit,
                        quality, source, equipment_id, channel_id, alarm,
                        raw_value, raw_status, raw_payload, raw_payload_retained,
                        received_at
                    )
                    SELECT
                        '91' || lpad(series::text, 34, '0'),
                        :unrelated_node_id,
                        NOW() - (series * INTERVAL '1 millisecond'),
                        'temperature',
                        (series % 100)::double precision,
                        '°C',
                        'valid',
                        'query-plan-fixture',
                        'unrelated-equipment',
                        'unrelated-channel-' || (series % 250)::text,
                        NULL,
                        NULL,
                        NULL,
                        '{}'::json,
                        true,
                        NOW()
                    FROM generate_series(1, 50000) AS series
                    """
                ),
                {"unrelated_node_id": unrelated_node_id},
            )
            connection.execute(
                text(
                    """
                    INSERT INTO telemetry_samples (
                        event_id, node_id, captured_at, metric, value, unit,
                        quality, source, equipment_id, channel_id, alarm,
                        raw_value, raw_status, raw_payload, raw_payload_retained,
                        received_at
                    )
                    SELECT
                        '92' || lpad(series::text, 34, '0'),
                        :node_id,
                        NOW() + (series * INTERVAL '1 second'),
                        'temperature',
                        2.0 + series,
                        '°C',
                        'valid',
                        'query-plan-fixture',
                        :equipment_id,
                        :channel_id,
                        CASE WHEN series = 3 THEN 'high' ELSE NULL END,
                        NULL,
                        NULL,
                        '{}'::json,
                        true,
                        NOW()
                    FROM generate_series(1, 3) AS series
                    """
                ),
                {
                    "node_id": catalog_node_id,
                    "equipment_id": catalog_equipment_id,
                    "channel_id": catalog_channel_id,
                },
            )
            connection.execute(text("ANALYZE telemetry_samples"))

        statement = inventory_query_plan_statement(
            repository,
            organization_id=organization_id,
            limit=500,
            offset=0,
        )
        compiled = statement.compile(
            database.engine,
            compile_kwargs={"literal_binds": True},
        )
        with database.engine.connect() as connection:
            raw_plan = connection.execute(
                text(f"EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) {compiled}")
            ).scalar_one()
        plan = json.loads(raw_plan) if isinstance(raw_plan, str) else raw_plan
        plan_document = json.dumps(plan, indent=2, default=str)
        execution_ms = float(plan[0]["Execution Time"])

        started = perf_counter()
        page = list_live_dashboard_inventory(
            repository,
            organization_id=organization_id,
            limit=500,
            offset=0,
        )
        request_ms = (perf_counter() - started) * 1000

        evidence = {
            "organization_id": organization_id,
            "catalog_channels": page.total,
            "telemetry_fixture_rows": 50003,
            "execution_ms": execution_ms,
            "request_ms": request_ms,
            "latest_lookup_index": "ix_telemetry_latest_lookup",
            "plan": plan,
        }
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        evidence_path.write_text(json.dumps(evidence, indent=2, default=str) + "\n")

        assert execution_ms < 8000
        assert request_ms < 8000
        assert "ix_telemetry_latest_lookup" in plan_document
        assert page.total == 2
        by_channel = {item.channel_id: item for item in page.items}
        assert by_channel[catalog_channel_id].latest is not None
        assert by_channel[catalog_channel_id].latest.value == 5.0
        assert by_channel[catalog_channel_id].alarm == "high"
        assert by_channel[f"{suffix}-temperature-02"].latest is None
    finally:
        with Session(database.engine) as session:
            with session.begin():
                session.execute(
                    delete(TelemetrySample).where(
                        TelemetrySample.node_id.in_([unrelated_node_id, catalog_node_id])
                    )
                )
                session.execute(
                    delete(MeasurementChannel).where(
                        MeasurementChannel.organization_id == organization_id
                    )
                )
                session.execute(
                    delete(MeasurementDevice).where(
                        MeasurementDevice.organization_id == organization_id
                    )
                )
                session.execute(
                    delete(ClimateChamber).where(
                        ClimateChamber.organization_id == organization_id
                    )
                )
                session.execute(
                    delete(MeasurementBus).where(
                        MeasurementBus.organization_id == organization_id
                    )
                )
                session.execute(
                    delete(CentralNode).where(
                        CentralNode.organization_id == organization_id
                    )
                )
                session.execute(
                    delete(SecurityOrganization).where(
                        SecurityOrganization.id == organization_id
                    )
                )
        database.dispose()
