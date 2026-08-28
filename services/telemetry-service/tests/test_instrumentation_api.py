from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.climate_catalog.models import PhysicalSensor
from app.climate_catalog.repository import PostgresClimateCatalogRepository
from app.config import Settings
from app.db import Database
from app.instrumentation.api import create_instrumentation_router
from app.instrumentation.repository import InstrumentationRepository
from app.main import create_app
from app.model_registry import register_models
from app.security.repository import SecurityRepository


ORGANIZATION_ID = "11111111-1111-1111-1111-111111111111"


def instrument_payload(key: str = "LAB-TEMP-001") -> dict[str, object]:
    return {
        "inventory_key": key,
        "display_name": "Еталонний температурний зонд",
        "instrument_kind": "temperature_probe",
        "manufacturer": "NEXOLAB",
        "model": "T-100",
        "serial_number": "SN-001",
        "lifecycle_state": "active",
        "metadata": {"laboratory": "metrology"},
    }


def signal_payload(key: str = "LAB-TEMP-001.PRIMARY") -> dict[str, object]:
    return {
        "business_key": key,
        "display_name": "Температура зонда",
        "physical_quantity": "temperature",
        "engineering_unit": "degC",
        "lifecycle_state": "active",
        "metadata": {"channel": "primary"},
    }


def build_client(
    tmp_path: Path,
) -> tuple[TestClient, Database, SecurityRepository, InstrumentationRepository]:
    register_models()
    database = Database(f"sqlite:///{tmp_path / 'instrumentation.db'}")
    database.create_schema()
    security = SecurityRepository(database)
    security.provision_organization(
        organization_id=ORGANIZATION_ID,
        slug="nexolab-lab",
        name="NEXOLAB Laboratory",
    )
    repository = InstrumentationRepository(database)
    app = FastAPI()
    app.include_router(
        create_instrumentation_router(
            repository,
            security_repository=security,
            default_organization_id=ORGANIZATION_ID,
        )
    )
    return TestClient(app), database, security, repository


def test_application_composition_mounts_versioned_registry_routes(
    tmp_path: Path,
) -> None:
    app = create_app(
        Settings(
            database_url=f"sqlite:///{tmp_path / 'instrumentation-app.db'}",
            auto_create_schema=True,
            mqtt_enabled=False,
        )
    )
    with TestClient(app) as api:
        paths = api.get("/openapi.json").json()["paths"]

    assert "/api/v1/instrumentation/instruments" in paths
    assert (
        "/api/v1/instrumentation/instruments/{instrument_id}/signals" in paths
    )
    assert (
        "/api/v1/instrumentation/instruments/{instrument_id}/acceptance-history"
        in paths
    )
    assert (
        "/api/v1/instrumentation/instruments/{instrument_id}/calibration-history"
        in paths
    )


def test_instrument_and_signal_crud_use_etags_and_process_neutral_identity(
    tmp_path: Path,
) -> None:
    api, _, _, _ = build_client(tmp_path)

    created = api.post(
        "/api/v1/instrumentation/instruments",
        json=instrument_payload(),
    )
    assert created.status_code == 201
    assert created.headers["etag"] == 'W/"instrument-v1"'
    instrument_id = created.json()["id"]

    assert api.get("/api/v1/instrumentation/instruments").json()["items"] == [
        created.json()
    ]
    fetched = api.get(f"/api/v1/instrumentation/instruments/{instrument_id}")
    assert fetched.status_code == 200
    assert fetched.headers["etag"] == 'W/"instrument-v1"'

    replacement = instrument_payload()
    replacement["display_name"] = "Зонд температури №1"
    updated = api.put(
        f"/api/v1/instrumentation/instruments/{instrument_id}",
        headers={"If-Match": created.headers["etag"]},
        json=replacement,
    )
    assert updated.status_code == 200
    assert updated.headers["etag"] == 'W/"instrument-v2"'
    assert updated.json()["display_name"] == "Зонд температури №1"

    stale = api.put(
        f"/api/v1/instrumentation/instruments/{instrument_id}",
        headers={"If-Match": created.headers["etag"]},
        json=replacement,
    )
    assert stale.status_code == 409
    assert stale.json()["detail"] == {
        "code": "instrument_version_conflict",
        "message": "instrument version conflict: expected 1, actual 2",
        "expected_version": 1,
        "actual_version": 2,
    }

    signal = api.post(
        f"/api/v1/instrumentation/instruments/{instrument_id}/signals",
        json=signal_payload(),
    )
    assert signal.status_code == 201
    assert signal.headers["etag"] == 'W/"signal-v1"'
    signal_id = signal.json()["id"]
    assert signal.json()["instrument_id"] == instrument_id
    assert signal.json()["physical_quantity"] == "temperature"

    signal_replacement = signal_payload()
    signal_replacement["display_name"] = "Температура основного елемента"
    signal_updated = api.put(
        f"/api/v1/instrumentation/instruments/{instrument_id}/signals/{signal_id}",
        headers={"If-Match": signal.headers["etag"]},
        json=signal_replacement,
    )
    assert signal_updated.status_code == 200
    assert signal_updated.headers["etag"] == 'W/"signal-v2"'

    process_role = signal_payload("LAB-TEMP-001.ROLE")
    process_role["physical_quantity"] = "suction_pressure"
    rejected = api.post(
        f"/api/v1/instrumentation/instruments/{instrument_id}/signals",
        json=process_role,
    )
    assert rejected.status_code == 422
    assert "process-neutral" in rejected.text


def test_organization_unique_business_keys_return_conflict(tmp_path: Path) -> None:
    api, _, _, _ = build_client(tmp_path)
    first = api.post(
        "/api/v1/instrumentation/instruments",
        json=instrument_payload(),
    )
    duplicate = api.post(
        "/api/v1/instrumentation/instruments",
        json=instrument_payload(),
    )
    assert first.status_code == 201
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["code"] == "instrument_inventory_key_conflict"

    instrument_id = first.json()["id"]
    assert (
        api.post(
            f"/api/v1/instrumentation/instruments/{instrument_id}/signals",
            json=signal_payload(),
        ).status_code
        == 201
    )
    signal_duplicate = api.post(
        f"/api/v1/instrumentation/instruments/{instrument_id}/signals",
        json=signal_payload(),
    )
    assert signal_duplicate.status_code == 409
    assert signal_duplicate.json()["detail"]["code"] == "signal_business_key_conflict"


def test_acceptance_and_calibration_histories_are_half_open_and_revision_ordered(
    tmp_path: Path,
) -> None:
    api, _, _, repository = build_client(tmp_path)
    instrument_id = api.post(
        "/api/v1/instrumentation/instruments",
        json=instrument_payload(),
    ).json()["id"]
    start = datetime(2026, 8, 1, 8, 0, tzinfo=UTC)
    transition = start + timedelta(days=1)

    first = api.post(
        f"/api/v1/instrumentation/instruments/{instrument_id}/acceptance-history",
        json={
            "accepted_for_calculation": True,
            "effective_from": start.isoformat(),
            "state_label": "commissioned",
        },
    )
    second = api.post(
        f"/api/v1/instrumentation/instruments/{instrument_id}/acceptance-history",
        json={
            "accepted_for_calculation": False,
            "effective_from": transition.isoformat(),
            "state_label": "maintenance",
        },
    )
    final_same_timestamp = api.post(
        f"/api/v1/instrumentation/instruments/{instrument_id}/acceptance-history",
        json={
            "accepted_for_calculation": True,
            "effective_from": transition.isoformat(),
            "state_label": "released",
        },
    )
    assert [first.status_code, second.status_code, final_same_timestamp.status_code] == [
        201,
        201,
        201,
    ]

    history = api.get(
        f"/api/v1/instrumentation/instruments/{instrument_id}/acceptance-history"
    ).json()["items"]
    assert [item["revision"] for item in history] == [1, 2, 3]
    assert history[0]["effective_to"] == transition.isoformat().replace("+00:00", "Z")
    assert history[1]["effective_from"] == history[1]["effective_to"]
    assert history[2]["effective_to"] is None
    assert repository.resolve_acceptance(
        instrument_id, start, organization_id=ORGANIZATION_ID
    ).revision == 1
    assert repository.resolve_acceptance(
        instrument_id, transition, organization_id=ORGANIZATION_ID
    ).revision == 3

    out_of_order = api.post(
        f"/api/v1/instrumentation/instruments/{instrument_id}/acceptance-history",
        json={
            "accepted_for_calculation": False,
            "effective_from": (start - timedelta(seconds=1)).isoformat(),
        },
    )
    assert out_of_order.status_code == 409
    assert out_of_order.json()["detail"]["code"] == "history_effective_time_conflict"

    valid = api.post(
        f"/api/v1/instrumentation/instruments/{instrument_id}/calibration-history",
        json={
            "state": "valid",
            "valid_from": start.isoformat(),
            "certificate_reference": "local://certificates/CERT-001",
        },
    )
    expired = api.post(
        f"/api/v1/instrumentation/instruments/{instrument_id}/calibration-history",
        json={
            "state": "expired",
            "valid_from": transition.isoformat(),
        },
    )
    revoked_same_timestamp = api.post(
        f"/api/v1/instrumentation/instruments/{instrument_id}/calibration-history",
        json={
            "state": "revoked",
            "valid_from": transition.isoformat(),
        },
    )
    assert valid.status_code == 201
    assert expired.status_code == 201
    assert revoked_same_timestamp.status_code == 201
    calibration = api.get(
        f"/api/v1/instrumentation/instruments/{instrument_id}/calibration-history"
    ).json()["items"]
    assert [item["state"] for item in calibration] == [
        "valid",
        "expired",
        "revoked",
    ]
    assert calibration[0]["valid_to"] == transition.isoformat().replace("+00:00", "Z")
    assert calibration[1]["valid_from"] == calibration[1]["valid_to"]
    assert repository.resolve_calibration(
        instrument_id, start, organization_id=ORGANIZATION_ID
    ).state == "valid"
    assert repository.resolve_calibration(
        instrument_id, transition, organization_id=ORGANIZATION_ID
    ).state == "revoked"

    unsupported = api.post(
        f"/api/v1/instrumentation/instruments/{instrument_id}/calibration-history",
        json={"state": "current", "valid_from": transition.isoformat()},
    )
    assert unsupported.status_code == 422


def test_registry_does_not_reinterpret_legacy_physical_sensor_calibration(
    tmp_path: Path,
) -> None:
    api, database, _, _ = build_client(tmp_path)
    climate = PostgresClimateCatalogRepository(database)
    climate.seed_default_catalog(organization_id=ORGANIZATION_ID)
    with Session(database.engine) as session:
        legacy = session.scalar(
            select(PhysicalSensor).where(
                PhysicalSensor.organization_id == ORGANIZATION_ID
            )
        )
        assert legacy is not None
        legacy_id = legacy.id
        legacy_status = legacy.calibration_status

    instrument_id = api.post(
        "/api/v1/instrumentation/instruments",
        json=instrument_payload("INDEPENDENT-REGISTRY-001"),
    ).json()["id"]
    assert api.get(
        f"/api/v1/instrumentation/instruments/{instrument_id}/calibration-history"
    ).json() == {"items": []}

    with Session(database.engine) as session:
        unchanged = session.get(PhysicalSensor, legacy_id)
        assert unchanged is not None
        assert unchanged.calibration_status == legacy_status
