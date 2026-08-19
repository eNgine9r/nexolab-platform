from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import jwt
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.contracts import TelemetryEvent
from app.live_dashboard.api import create_live_dashboard_router
from app.live_dashboard.repository import LiveDashboardRepository
from app.security.authentication import JwtAuthenticator, VerifiedIdentityClaims
from app.security.authorization import Role
from app.security.dependencies import SecurityDependencies
from app.security.repository import SecurityRepository
from tests.live_dashboard_test_support import ORG_A, database_with_inventory


SECRET = "test-only-secret-with-sufficient-length"
ISSUER = "https://identity.example.test"
AUDIENCE = "nexolab-api"


def payload(
    *,
    name: str = "Температурний контроль",
    channels: list[str] | None = None,
    refresh_seconds: int = 5,
    time_window: str = "15m",
) -> dict[str, object]:
    selected = channels or ["a-temperature-02", "a-temperature-01"]
    return {
        "name": name,
        "description": "Операторський Live Dashboard",
        "refresh_seconds": refresh_seconds,
        "time_window": time_window,
        "items": [
            {
                "channel_id": channel_id,
                "metric": "temperature",
                "visualization": "line",
                "color": "#2468AC",
                "display_unit": "°C",
            }
            for channel_id in selected
        ],
    }


def token(subject: str) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": subject,
            "email": f"{subject}@example.test",
            "name": subject,
            "iss": ISSUER,
            "aud": AUDIENCE,
            "iat": now,
            "exp": now + timedelta(minutes=5),
        },
        SECRET,
        algorithm="HS256",
    )


def auth_headers(subject: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token(subject)}",
        "X-Organization-ID": ORG_A,
    }


def secured_client(
    tmp_path: Path,
    *,
    subject: str,
    roles: set[Role],
    export_max_rows: int = 100_000,
) -> tuple[TestClient, SecurityRepository]:
    database, security = database_with_inventory(
        tmp_path,
        filename=f"live-dashboard-{subject}.db",
    )
    security.provision_membership(
        organization_id=ORG_A,
        claims=VerifiedIdentityClaims(
            provider="test-oidc",
            subject=subject,
            email=f"{subject}@example.test",
            display_name=subject,
        ),
        roles=roles,
    )
    dependencies = SecurityDependencies(
        security,
        mode="jwt",
        authenticator=JwtAuthenticator(
            public_key=SECRET,
            algorithm="HS256",
            issuer=ISSUER,
            audience=AUDIENCE,
            provider="test-oidc",
        ),
        default_organization_id=ORG_A,
    )
    app = FastAPI()
    app.include_router(
        create_live_dashboard_router(
            LiveDashboardRepository(database),
            security_dependencies=dependencies,
            security_repository=security,
            default_organization_id=ORG_A,
            database=database,
            max_history_days=31,
            export_max_rows=export_max_rows,
        )
    )
    app.state.database = database
    return TestClient(app), security


def test_crud_etag_ordering_archive_and_pagination(tmp_path: Path) -> None:
    api, _ = secured_client(
        tmp_path,
        subject="operator",
        roles={Role.OPERATOR},
    )
    headers = auth_headers("operator")

    created = api.post(
        "/api/v1/live-dashboards",
        headers={**headers, "X-Audit-Reason": "Create operator workspace"},
        json=payload(),
    )
    assert created.status_code == 201
    assert created.headers["etag"] == 'W/"live-dashboard-v1"'
    dashboard_id = created.json()["id"]
    assert created.headers["location"].endswith(dashboard_id)
    assert [item["channel_id"] for item in created.json()["items"]] == [
        "a-temperature-02",
        "a-temperature-01",
    ]
    assert created.json()["refresh_seconds"] == 5
    assert created.json()["time_window"] == "15m"

    listed = api.get(
        "/api/v1/live-dashboards?limit=1&offset=0",
        headers=headers,
    )
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert listed.json()["has_more"] is False

    fetched = api.get(
        f"/api/v1/live-dashboards/{dashboard_id}",
        headers=headers,
    )
    assert fetched.status_code == 200
    assert fetched.headers["etag"] == created.headers["etag"]

    missing_precondition = api.put(
        f"/api/v1/live-dashboards/{dashboard_id}",
        headers=headers,
        json=payload(channels=["a-temperature-01"]),
    )
    assert missing_precondition.status_code == 428
    assert (
        missing_precondition.json()["detail"]["code"]
        == "live_dashboard_version_required"
    )

    updated = api.put(
        f"/api/v1/live-dashboards/{dashboard_id}",
        headers={
            **headers,
            "If-Match": created.headers["etag"],
            "X-Audit-Reason": "Focus on one channel",
        },
        json=payload(
            name="Оновлений контроль",
            channels=["a-temperature-01"],
            refresh_seconds=10,
            time_window="1h",
        ),
    )
    assert updated.status_code == 200
    assert updated.headers["etag"] == 'W/"live-dashboard-v2"'
    assert [item["position"] for item in updated.json()["items"]] == [1]
    assert updated.json()["refresh_seconds"] == 10
    assert updated.json()["time_window"] == "1h"

    stale = api.put(
        f"/api/v1/live-dashboards/{dashboard_id}",
        headers={**headers, "If-Match": created.headers["etag"]},
        json=payload(channels=["a-temperature-02"]),
    )
    assert stale.status_code == 409
    assert stale.json()["detail"] == {
        "code": "live_dashboard_version_conflict",
        "message": "live dashboard version conflict: expected 1, actual 2",
        "expected_version": 1,
        "actual_version": 2,
    }

    archived = api.delete(
        f"/api/v1/live-dashboards/{dashboard_id}",
        headers={
            **headers,
            "If-Match": updated.headers["etag"],
            "X-Audit-Reason": "Archive unused workspace",
        },
    )
    assert archived.status_code == 204
    assert archived.headers["etag"] == 'W/"live-dashboard-v3"'
    assert api.get(
        "/api/v1/live-dashboards",
        headers=headers,
    ).json()["total"] == 0
    archived_list = api.get(
        "/api/v1/live-dashboards?include_archived=true",
        headers=headers,
    )
    assert archived_list.json()["total"] == 1
    assert archived_list.json()["items"][0]["status"] == "archived"

    assert api.get(
        "/api/v1/live-dashboards?limit=101",
        headers=headers,
    ).status_code == 422
    assert api.get(
        "/api/v1/live-dashboards?offset=10001",
        headers=headers,
    ).status_code == 422


def test_viewer_is_read_only_and_operator_mutations_are_audited(tmp_path: Path) -> None:
    viewer, _ = secured_client(
        tmp_path,
        subject="viewer",
        roles={Role.VIEWER},
    )
    denied = viewer.post(
        "/api/v1/live-dashboards",
        headers=auth_headers("viewer"),
        json=payload(),
    )
    assert denied.status_code == 403
    assert denied.json()["detail"]["code"] == "permission_denied"
    assert viewer.get(
        "/api/v1/live-dashboards",
        headers=auth_headers("viewer"),
    ).status_code == 200

    operator, security = secured_client(
        tmp_path,
        subject="engineer",
        roles={Role.ENGINEER},
    )
    headers = auth_headers("engineer")
    created = operator.post(
        "/api/v1/live-dashboards",
        headers={**headers, "X-Audit-Reason": "Create dashboard"},
        json=payload(),
    )
    dashboard_id = created.json()["id"]
    updated = operator.put(
        f"/api/v1/live-dashboards/{dashboard_id}",
        headers={
            **headers,
            "If-Match": created.headers["etag"],
            "X-Audit-Reason": "Update dashboard",
        },
        json=payload(channels=["a-temperature-01"]),
    )
    operator.delete(
        f"/api/v1/live-dashboards/{dashboard_id}",
        headers={
            **headers,
            "If-Match": updated.headers["etag"],
            "X-Audit-Reason": "Archive dashboard",
        },
    )

    events = security.list_audit_events(
        organization_id=ORG_A,
        entity_type="live_dashboard",
        entity_id=dashboard_id,
        limit=10,
    )
    assert [event.action for event in events] == [
        "live_dashboard.archived",
        "live_dashboard.updated",
        "live_dashboard.created",
    ]
    assert all(event.actor_subject == "engineer" for event in events)
    assert [event.reason for event in events] == [
        "Archive dashboard",
        "Update dashboard",
        "Create dashboard",
    ]
    assert events[-1].before_snapshot is None
    assert events[-1].after_snapshot["items"][0]["channel_id"] == (
        "a-temperature-02"
    )


def test_unknown_channel_metric_mismatch_and_unit_conversion_are_explicit(
    tmp_path: Path,
) -> None:
    api, _ = secured_client(
        tmp_path,
        subject="operator-errors",
        roles={Role.OPERATOR},
    )
    headers = auth_headers("operator-errors")

    unknown = api.post(
        "/api/v1/live-dashboards",
        headers=headers,
        json=payload(channels=["missing-channel"]),
    )
    assert unknown.status_code == 422
    assert unknown.json()["detail"]["code"] == "live_dashboard_channel_not_found"

    mismatch_payload = payload(channels=["a-temperature-01"])
    mismatch_payload["items"][0]["metric"] = "humidity"
    mismatch = api.post(
        "/api/v1/live-dashboards",
        headers=headers,
        json=mismatch_payload,
    )
    assert mismatch.status_code == 422
    assert (
        mismatch.json()["detail"]["code"]
        == "live_dashboard_channel_metric_mismatch"
    )

    unit_payload = payload(channels=["a-temperature-01"])
    unit_payload["items"][0]["display_unit"] = "°F"
    unsupported = api.post(
        "/api/v1/live-dashboards",
        headers=headers,
        json=unit_payload,
    )
    assert unsupported.status_code == 422
    assert (
        unsupported.json()["detail"]["code"]
        == "live_dashboard_unit_conversion_unsupported"
    )


def export_event(
    *,
    captured_at: datetime,
    channel_id: str,
    value: float | None,
    quality: str = "valid",
    node_id: str = "edge-a",
    equipment_id: str = "controller-a",
) -> TelemetryEvent:
    return TelemetryEvent(
        event_id=uuid4(),
        node_id=node_id,
        captured_at=captured_at,
        metric="temperature",
        value=value,
        unit="°C",
        quality=quality,
        source="test-xjp60d",
        equipment_id=equipment_id,
        channel_id=channel_id,
        alarm=None,
        raw_value=None if value is None else int(value * 10),
        raw_status=None,
    )


def test_saved_dashboard_csv_export_is_persisted_deterministic_and_bounded(
    tmp_path: Path,
) -> None:
    api, _ = secured_client(
        tmp_path,
        subject="export-operator",
        roles={Role.OPERATOR},
        export_max_rows=3,
    )
    headers = auth_headers("export-operator")
    created = api.post(
        "/api/v1/live-dashboards",
        headers=headers,
        json=payload(channels=["a-temperature-01"]),
    )
    assert created.status_code == 201
    dashboard_id = created.json()["id"]
    database = api.app.state.database
    base = datetime(2026, 8, 18, 9, 0, tzinfo=UTC)
    samples = [
        export_event(
            captured_at=base + timedelta(seconds=20),
            channel_id="a-temperature-01",
            value=None,
            quality="communication_error",
        ),
        export_event(
            captured_at=base,
            channel_id="a-temperature-01",
            value=4.2,
        ),
        export_event(
            captured_at=base + timedelta(seconds=10),
            channel_id="a-temperature-01",
            value=4.3,
        ),
    ]
    for sample in samples:
        assert database.persist(sample, sample.normalized_payload())

    foreign_same_series = export_event(
        captured_at=base + timedelta(seconds=15),
        channel_id="a-temperature-01",
        value=99.9,
        node_id="edge-b",
        equipment_id="controller-b",
    )
    assert database.persist(
        foreign_same_series, foreign_same_series.normalized_payload()
    )

    exported = api.get(
        f"/api/v1/live-dashboards/{dashboard_id}/telemetry.csv",
        headers=headers,
        params={
            "from": (base - timedelta(seconds=1)).isoformat(),
            "to": (base + timedelta(seconds=30)).isoformat(),
            "timezone": "Europe/Kyiv",
        },
    )
    assert exported.status_code == 200, exported.text
    assert exported.headers["content-type"].startswith("text/csv")
    assert "live-dashboard-" in exported.headers["content-disposition"]
    lines = exported.content.decode("utf-8").splitlines()
    assert lines[0] == (
        "timestamp_utc,timestamp_local,node,device,channel,metric,value,unit,quality,event_id"
    )
    assert [line.split(",")[0] for line in lines[1:]] == [
        "2026-08-18T09:00:00Z",
        "2026-08-18T09:00:10Z",
        "2026-08-18T09:00:20Z",
    ]
    assert "+03:00" in lines[1]
    assert ",communication_error," in lines[-1]
    assert ",,°C,communication_error," in lines[-1]

    too_many = export_event(
        captured_at=base + timedelta(seconds=25),
        channel_id="a-temperature-01",
        value=4.4,
    )
    assert database.persist(too_many, too_many.normalized_payload())
    oversized_rows = api.get(
        f"/api/v1/live-dashboards/{dashboard_id}/telemetry.csv",
        headers=headers,
        params={
            "from": (base - timedelta(seconds=1)).isoformat(),
            "to": (base + timedelta(seconds=30)).isoformat(),
            "timezone": "UTC",
        },
    )
    assert oversized_rows.status_code == 422
    assert oversized_rows.json()["detail"]["code"] == "live_dashboard_export_row_limit"
    assert oversized_rows.json()["detail"]["maximum_rows"] == 3

    oversized_range = api.get(
        f"/api/v1/live-dashboards/{dashboard_id}/telemetry.csv",
        headers=headers,
        params={
            "from": base.isoformat(),
            "to": (base + timedelta(days=32)).isoformat(),
            "timezone": "UTC",
        },
    )
    assert oversized_range.status_code == 422
    assert oversized_range.json()["detail"]["code"] == "live_dashboard_export_range_too_large"

    invalid_timezone = api.get(
        f"/api/v1/live-dashboards/{dashboard_id}/telemetry.csv",
        headers=headers,
        params={
            "from": base.isoformat(),
            "to": (base + timedelta(minutes=1)).isoformat(),
            "timezone": "Mars/Olympus_Mons",
        },
    )
    assert invalid_timezone.status_code == 422
    assert invalid_timezone.json()["detail"]["code"] == "live_dashboard_export_invalid_timezone"
