from __future__ import annotations

import json
import os
from pathlib import Path
from time import perf_counter
from uuid import uuid4

import pytest
from sqlalchemy import delete, select, text
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
from app.refrigeration.models import RefrigerationEquipmentRecord
from app.security.models import SecurityOrganization
from app.security.repository import SecurityRepository
from tests.live_dashboard_test_support import provision_inventory


pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL", "").startswith("postgresql"),
    reason="PostgreSQL is required for inventory query-plan evidence",
)


def test_postgres_inventory_plan_is_bounded_and_has_latest_identity_index_path(
    capsys: pytest.CaptureFixture[str],
) -> None:
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

        with Session(database.engine) as session:
            chamber_id = session.scalar(
                select(ClimateChamber.id).where(
                    ClimateChamber.organization_id == organization_id,
                    ClimateChamber.code == f"KK-{suffix.upper()}",
                )
            )
            assert chamber_id is not None
            with session.begin_nested():
                session.add(
                    RefrigerationEquipmentRecord(
                        id=str(uuid4()),
                        organization_id=organization_id,
                        code=f"REF-{suffix}",
                        name="Taxonomy source",
                        location="Local",
                        laboratory="Laboratory A",
                        zone="Zone 1",
                        node_id=catalog_node_id,
                        climate_chamber_id=chamber_id,
                        equipment_type="refrigeration",
                        manufacturer="Test",
                        model="T",
                        serial_number=f"SER-{suffix}",
                        temperature_class="M1",
                        installed_at=None,
                        serviced_at=None,
                        lifecycle_status="active",
                        status="normal",
                        average_temperature_c=0.0,
                        min_temperature_c=0.0,
                        max_temperature_c=0.0,
                        online_sensors=0,
                        total_sensors=0,
                        active_alarms=0,
                        last_seen_at=None,
                        version=1,
                        created_by="test-suite",
                        created_at=None,
                        updated_at=None,
                        deleted_by=None,
                        deleted_at=None,
                    )
                )
            session.commit()

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
            connection.execute(text("SET LOCAL enable_seqscan = off"))
            raw_index_plan = connection.execute(
                text(f"EXPLAIN (FORMAT JSON) {compiled}")
            ).scalar_one()
        plan = json.loads(raw_plan) if isinstance(raw_plan, str) else raw_plan
        index_plan = (
            json.loads(raw_index_plan) if isinstance(raw_index_plan, str) else raw_index_plan
        )
        plan_document = json.dumps(plan, indent=2, default=str)
        index_plan_document = json.dumps(index_plan, indent=2, default=str)
        execution_ms = float(plan[0]["Execution Time"])
        latest_lookup_index = "ix_telemetry_latest_lookup"
        planner_selected_latest_lookup_index = latest_lookup_index in plan_document
        index_backed_latest_lookup_path = latest_lookup_index in index_plan_document

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
            "latest_lookup_index": latest_lookup_index,
            "planner_selected_latest_lookup_index": planner_selected_latest_lookup_index,
            "index_backed_latest_lookup_path": index_backed_latest_lookup_path,
            "plan": plan,
            "index_preferred_plan": index_plan,
        }
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        evidence_path.write_text(json.dumps(evidence, indent=2, default=str) + "\n")
        with capsys.disabled():
            print(
                "NEXOLAB_LIVE_DASHBOARD_INVENTORY_POSTGRES_EVIDENCE="
                + json.dumps(
                    {
                        "catalog_channels": page.total,
                        "telemetry_fixture_rows": 50003,
                        "execution_ms": execution_ms,
                        "request_ms": request_ms,
                        "latest_lookup_index": latest_lookup_index,
                        "planner_selected_latest_lookup_index": planner_selected_latest_lookup_index,
                        "index_backed_latest_lookup_path": index_backed_latest_lookup_path,
                    },
                    sort_keys=True,
                ),
                flush=True,
            )

        assert execution_ms < 8000
        assert request_ms < 8000
        assert index_backed_latest_lookup_path
        assert page.total == 2
        by_channel = {item.channel_id: item for item in page.items}
        assert by_channel[catalog_channel_id].latest is not None
        assert by_channel[catalog_channel_id].latest.value == 5.0
        assert by_channel[catalog_channel_id].alarm == "high"
        assert by_channel[catalog_channel_id].laboratory == "Laboratory A"
        assert by_channel[catalog_channel_id].zone == "Zone 1"
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
                    delete(RefrigerationEquipmentRecord).where(
                        RefrigerationEquipmentRecord.organization_id == organization_id
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
