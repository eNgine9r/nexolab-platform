from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def build_client(tmp_path: Path, name: str = "configuration.db") -> TestClient:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / name}",
        auto_create_schema=True,
        mqtt_enabled=False,
        retention_enabled=False,
        cors_allowed_origins="http://127.0.0.1:3000",
    )
    return TestClient(create_app(settings))


def create_session(
    client: TestClient,
    *,
    number: str,
) -> str:
    response = client.post(
        "/api/v1/sessions",
        headers={"Idempotency-Key": f"create-{number}"},
        json={
            "session_number": number,
            "title": f"Laboratory session {number}",
            "test_object": "K106 display cabinet",
            "node_id": "edge-01",
            "actor_id": "operator-1",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["session"]["id"]


def transition(
    client: TestClient,
    session_id: str,
    action: str,
    *,
    key: str,
    reason: str | None = None,
) -> dict:
    payload: dict[str, str] = {
        "actor_id": "operator-1",
        "actor_source": "dashboard",
    }
    if reason is not None:
        payload["reason"] = reason
    response = client.post(
        f"/api/v1/sessions/{session_id}/{action}",
        headers={"Idempotency-Key": key},
        json=payload,
    )
    assert response.status_code == 200, response.text
    return response.json()


def apply_production_bindings(
    client: TestClient,
    session_id: str,
    *,
    key: str,
) -> dict:
    response = client.post(
        f"/api/v1/sessions/{session_id}/bindings/production",
        headers={"Idempotency-Key": key},
        json={
            "actor_id": "operator-1",
            "actor_source": "dashboard",
            "binding_metadata": {"laboratory": "Laboratory 1"},
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_production_preset_freezes_34_series_at_start(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        session_id = create_session(client, number="NXL-M4-001")

        applied = apply_production_bindings(
            client,
            session_id,
            key="production-bindings-1",
        )
        replayed = apply_production_bindings(
            client,
            session_id,
            key="production-bindings-1",
        )

        assert applied["replayed"] is False
        assert replayed["replayed"] is True
        assert replayed["event"]["id"] == applied["event"]["id"]
        assert applied["expected_series_count"] == 34
        assert len(applied["bindings"]) == 34

        identities = {
            (
                item["equipment_id"],
                item["channel_id"],
                item["metric"],
                item["unit"],
            )
            for item in applied["bindings"]
        }
        assert ("K106", "106-03", "temperature.probe", "degC") in identities
        assert ("K106", "106-04", "temperature.probe", "degC") in identities
        assert (
            "LE01MP-200",
            "200-active-power",
            "electrical.power.active",
            "W",
        ) in identities
        assert (
            "LE01MP-203",
            "203-internal-temperature",
            "temperature.internal",
            "degC",
        ) in identities

        transition(client, session_id, "prepare", key="prepare-1")
        started = transition(client, session_id, "start", key="start-1")
        assert started["event"]["payload"]["production_complete"] is True

        response = client.get(f"/api/v1/sessions/{session_id}/configuration")
        assert response.status_code == 200, response.text
        configuration = response.json()

        assert len(configuration["bindings"]) == 34
        assert all(item["activated_at"] for item in configuration["bindings"])
        assert configuration["active_snapshot"]["source"] == "session_start"
        assert len(configuration["active_snapshot"]["content_sha256"]) == 64
        contract = configuration["active_snapshot"]["payload"][
            "production_contract"
        ]
        assert contract == {
            "expected_series_count": 34,
            "bound_series_count": 34,
            "complete": True,
        }


def test_unknown_and_duplicate_bindings_are_rejected(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        session_id = create_session(client, number="NXL-M4-002")
        unknown = client.post(
            f"/api/v1/sessions/{session_id}/bindings",
            headers={"Idempotency-Key": "unknown-binding"},
            json={
                "actor_id": "operator-1",
                "equipment_id": "K106",
                "channel_id": "106-99",
                "metric": "temperature.probe",
                "unit": "degC",
            },
        )
        assert unknown.status_code == 409
        assert unknown.json()["detail"]["code"] == "unknown_production_channel"

        payload = {
            "actor_id": "operator-1",
            "equipment_id": "K106",
            "channel_id": "106-03",
            "metric": "temperature.probe",
            "unit": "degC",
        }
        first = client.post(
            f"/api/v1/sessions/{session_id}/bindings",
            headers={"Idempotency-Key": "binding-1"},
            json=payload,
        )
        duplicate = client.post(
            f"/api/v1/sessions/{session_id}/bindings",
            headers={"Idempotency-Key": "binding-2"},
            json=payload,
        )

        assert first.status_code == 201, first.text
        assert duplicate.status_code == 409
        assert duplicate.json()["detail"]["code"] == "duplicate_session_binding"


def test_limit_sets_are_append_only_and_versioned(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        session_id = create_session(client, number="NXL-M4-003")
        bindings = apply_production_bindings(
            client,
            session_id,
            key="production-bindings-3",
        )["bindings"]
        temperature_binding = next(
            item for item in bindings if item["channel_id"] == "106-03"
        )

        first_payload = {
            "actor_id": "engineer-1",
            "limits": [
                {
                    "binding_id": temperature_binding["id"],
                    "metric": "temperature.probe",
                    "unit": "degC",
                    "lower_limit": -5.0,
                    "upper_limit": 8.0,
                    "hysteresis": 0.5,
                    "duration_seconds": 60,
                },
                {
                    "metric": "electrical.power.active",
                    "unit": "W",
                    "upper_limit": 5000.0,
                },
            ],
        }
        first = client.post(
            f"/api/v1/sessions/{session_id}/limits",
            headers={"Idempotency-Key": "limits-v1"},
            json=first_payload,
        )
        assert first.status_code == 201, first.text
        assert first.json()["version"] == 1
        assert len(first.json()["limits"]) == 2

        second_payload = {
            **first_payload,
            "reason": "Tighten validated temperature band",
            "limits": [
                {
                    **first_payload["limits"][0],
                    "upper_limit": 7.0,
                },
                first_payload["limits"][1],
            ],
        }
        second = client.post(
            f"/api/v1/sessions/{session_id}/limits",
            headers={"Idempotency-Key": "limits-v2"},
            json=second_payload,
        )
        replayed = client.post(
            f"/api/v1/sessions/{session_id}/limits",
            headers={"Idempotency-Key": "limits-v2"},
            json=second_payload,
        )

        assert second.status_code == 201, second.text
        assert second.json()["version"] == 2
        assert replayed.status_code == 201
        assert replayed.json()["replayed"] is True
        assert replayed.json()["event"]["id"] == second.json()["event"]["id"]

        version_one = client.get(
            f"/api/v1/sessions/{session_id}/limits?version=1"
        )
        active = client.get(f"/api/v1/sessions/{session_id}/limits")
        assert version_one.status_code == 200
        assert active.status_code == 200
        first_temperature = next(
            item
            for item in version_one.json()
            if item["metric"] == "temperature.probe"
        )
        active_temperature = next(
            item for item in active.json() if item["metric"] == "temperature.probe"
        )
        assert first_temperature["upper_limit"] == 8.0
        assert active_temperature["version"] == 2
        assert active_temperature["upper_limit"] == 7.0
        assert active_temperature["supersedes_limit_id"] == first_temperature["id"]


def test_active_binding_change_is_audited_and_creates_new_snapshot(
    tmp_path: Path,
) -> None:
    with build_client(tmp_path) as client:
        session_id = create_session(client, number="NXL-M4-004")
        bindings = apply_production_bindings(
            client,
            session_id,
            key="production-bindings-4",
        )["bindings"]
        binding = next(item for item in bindings if item["channel_id"] == "106-04")
        transition(client, session_id, "prepare", key="prepare-4")
        transition(client, session_id, "start", key="start-4")

        rejected = client.post(
            f"/api/v1/sessions/{session_id}/bindings/{binding['id']}/remove",
            headers={"Idempotency-Key": "remove-active-rejected"},
            json={"actor_id": "operator-1"},
        )
        assert rejected.status_code == 409
        assert rejected.json()["detail"]["code"] == (
            "active_configuration_change_requires_ack"
        )

        removed = client.post(
            f"/api/v1/sessions/{session_id}/bindings/{binding['id']}/remove",
            headers={"Idempotency-Key": "remove-active-accepted"},
            json={
                "actor_id": "operator-1",
                "allow_active_change": True,
                "reason": "Probe isolated after physical inspection",
            },
        )
        assert removed.status_code == 200, removed.text
        assert removed.json()["event"]["event_type"] == "session_binding_removed"
        assert removed.json()["active_config_snapshot_id"] is not None

        configuration = client.get(
            f"/api/v1/sessions/{session_id}/configuration"
        ).json()
        assert len(configuration["snapshots"]) == 2
        assert configuration["snapshots"][0]["payload"]["production_contract"][
            "complete"
        ] is True
        assert configuration["active_snapshot"]["version"] == 2
        assert configuration["active_snapshot"]["payload"]["production_contract"] == {
            "expected_series_count": 34,
            "bound_series_count": 33,
            "complete": False,
        }
        released = next(
            item for item in configuration["bindings"] if item["id"] == binding["id"]
        )
        assert released["released_at"] is not None

        transition(client, session_id, "complete", key="complete-4")
        immutable = client.post(
            f"/api/v1/sessions/{session_id}/limits",
            headers={"Idempotency-Key": "limits-after-complete"},
            json={
                "actor_id": "engineer-1",
                "limits": [
                    {
                        "metric": "temperature.probe",
                        "unit": "degC",
                        "upper_limit": 6.0,
                    }
                ],
            },
        )
        assert immutable.status_code == 409
        assert immutable.json()["detail"]["code"] == "session_immutable"


def test_active_channel_lease_blocks_second_session_until_release(
    tmp_path: Path,
) -> None:
    with build_client(tmp_path) as client:
        first_id = create_session(client, number="NXL-M4-005-A")
        second_id = create_session(client, number="NXL-M4-005-B")
        apply_production_bindings(client, first_id, key="production-first")
        apply_production_bindings(client, second_id, key="production-second")
        transition(client, first_id, "prepare", key="prepare-first")
        transition(client, second_id, "prepare", key="prepare-second")
        transition(client, first_id, "start", key="start-first")

        blocked = client.post(
            f"/api/v1/sessions/{second_id}/start",
            headers={"Idempotency-Key": "start-second-blocked"},
            json={"actor_id": "operator-1"},
        )
        assert blocked.status_code == 409
        assert blocked.json()["detail"]["code"] == "active_channel_lease_conflict"

        transition(client, first_id, "complete", key="complete-first")
        started = transition(
            client,
            second_id,
            "start",
            key="start-second-after-release",
        )
        assert started["session"]["state"] == "running"
        assert started["event"]["payload"]["production_complete"] is True
