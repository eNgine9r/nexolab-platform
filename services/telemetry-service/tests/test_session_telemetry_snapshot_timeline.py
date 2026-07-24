from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient

from app.config import Settings
from app.contracts import TelemetryEvent
from app.main import create_app


def build_client(tmp_path: Path) -> TestClient:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'snapshot-timeline.db'}",
        auto_create_schema=True,
        mqtt_enabled=False,
        retention_enabled=False,
    )
    return TestClient(create_app(settings))


def command(
    client: TestClient,
    path: str,
    *,
    key: str,
    payload: dict[str, object],
    expected_status: int = 200,
) -> dict:
    response = client.post(
        path,
        headers={"Idempotency-Key": key},
        json=payload,
    )
    assert response.status_code == expected_status, response.text
    return response.json()


def telemetry(captured_at: datetime) -> TelemetryEvent:
    return TelemetryEvent(
        event_id=uuid4(),
        node_id="edge-01",
        captured_at=captured_at,
        metric="temperature.probe",
        value=4.2,
        unit="degC",
        quality="valid",
        source="test-source",
        equipment_id="K106",
        channel_id="106-03",
    )


def test_late_backlog_uses_immutable_binding_snapshot_timeline(
    tmp_path: Path,
) -> None:
    base = datetime(2026, 7, 24, 14, 0, tzinfo=UTC)
    start_at = base + timedelta(minutes=1)
    remove_at = base + timedelta(minutes=2)
    readd_at = base + timedelta(minutes=3)

    with build_client(tmp_path) as client:
        created = command(
            client,
            "/api/v1/sessions",
            key="create-snapshot-timeline",
            expected_status=201,
            payload={
                "session_number": "NXL-ATTR-SNAPSHOT-001",
                "title": "Snapshot timeline test",
                "test_object": "K106",
                "node_id": "edge-01",
                "actor_id": "operator-1",
                "occurred_at": base.isoformat(),
            },
        )
        session_id = str(created["session"]["id"])

        added = command(
            client,
            f"/api/v1/sessions/{session_id}/bindings",
            key="add-initial-binding",
            expected_status=201,
            payload={
                "actor_id": "operator-1",
                "occurred_at": base.isoformat(),
                "node_id": "edge-01",
                "equipment_id": "K106",
                "channel_id": "106-03",
                "metric": "temperature.probe",
                "unit": "degC",
            },
        )
        binding_id = str(added["binding"]["id"])

        command(
            client,
            f"/api/v1/sessions/{session_id}/prepare",
            key="prepare-snapshot-timeline",
            payload={
                "actor_id": "operator-1",
                "occurred_at": (base + timedelta(seconds=10)).isoformat(),
            },
        )
        started = command(
            client,
            f"/api/v1/sessions/{session_id}/start",
            key="start-snapshot-timeline",
            payload={
                "actor_id": "operator-1",
                "occurred_at": start_at.isoformat(),
            },
        )
        start_snapshot_id = str(
            started["session"]["active_config_snapshot_id"]
        )

        removed = command(
            client,
            f"/api/v1/sessions/{session_id}/bindings/{binding_id}/remove",
            key="remove-active-binding",
            payload={
                "actor_id": "operator-1",
                "occurred_at": remove_at.isoformat(),
                "allow_active_change": True,
                "reason": "Controlled channel relocation",
            },
        )
        remove_snapshot_id = str(removed["active_config_snapshot_id"])

        readded = command(
            client,
            f"/api/v1/sessions/{session_id}/bindings",
            key="readd-active-binding",
            expected_status=201,
            payload={
                "actor_id": "operator-1",
                "occurred_at": readd_at.isoformat(),
                "allow_active_change": True,
                "reason": "Channel returned to validated position",
                "node_id": "edge-01",
                "equipment_id": "K106",
                "channel_id": "106-03",
                "metric": "temperature.probe",
                "unit": "degC",
            },
        )
        assert readded["binding"]["id"] == binding_id
        readd_snapshot_id = str(readded["active_config_snapshot_id"])
        assert len(
            {start_snapshot_id, remove_snapshot_id, readd_snapshot_id}
        ) == 3

        before_removal = telemetry(remove_at - timedelta(microseconds=1))
        while_removed = telemetry(remove_at + timedelta(seconds=30))
        after_readd = telemetry(readd_at)

        for event in (before_removal, while_removed, after_readd):
            assert client.app.state.database.persist(
                event,
                event.normalized_payload(),
            ) is True

        response = client.get(
            f"/api/v1/sessions/{session_id}/telemetry/history",
            params={
                "from": start_at.isoformat(),
                "to": (readd_at + timedelta(minutes=1)).isoformat(),
            },
        )
        assert response.status_code == 200, response.text
        items = response.json()["items"]
        by_event = {item["event_id"]: item for item in items}

        assert set(by_event) == {
            str(before_removal.event_id),
            str(after_readd.event_id),
        }
        assert by_event[str(before_removal.event_id)]["binding_id"] == binding_id
        assert (
            by_event[str(before_removal.event_id)]["config_snapshot_id"]
            == start_snapshot_id
        )
        assert by_event[str(after_readd.event_id)]["binding_id"] == binding_id
        assert (
            by_event[str(after_readd.event_id)]["config_snapshot_id"]
            == readd_snapshot_id
        )
        assert {item["resolver_version"] for item in items} == {
            "snapshot-timeline-v1"
        }

        regular = client.get(
            "/api/v1/telemetry/history",
            params={
                "from": start_at.isoformat(),
                "to": (readd_at + timedelta(minutes=1)).isoformat(),
            },
        )
        assert regular.status_code == 200, regular.text
        assert regular.json()["count"] == 3
        assert str(while_removed.event_id) not in by_event
