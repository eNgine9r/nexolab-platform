"""Saved analysis view settings of Saved Live Dashboards (#1666)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.live_dashboard.models import LiveDashboard
from app.live_dashboard.repository import LiveDashboardRepository
from app.live_dashboard.schemas import LiveDashboardViewSettings, LiveDashboardWrite
from app.security.authorization import Role
from tests.live_dashboard_test_support import ORG_A, database_with_inventory
from tests.test_live_dashboard_api import auth_headers, payload, secured_client


VIEW = {
    "schema_version": 1,
    "hidden_items": ["edge-1:K106:a-temperature-02:temperature"],
    "range_kind": "custom",
    "range_from": "2026-11-20T08:00:00Z",
    "range_to": "2026-11-20T12:00:00Z",
    "viewport_from": "2026-11-20T09:00:00Z",
    "viewport_to": "2026-11-20T10:00:00Z",
    "density": 1000,
}


def write(view: object = ..., name: str = "Аналіз") -> LiveDashboardWrite:
    body: dict[str, object] = {
        "name": name,
        "refresh_seconds": 5,
        "time_window": "15m",
        "items": [
            {"channel_id": "a-temperature-01", "metric": "temperature", "visualization": "line"},
        ],
    }
    if view is not ...:
        body["view_settings"] = view
    return LiveDashboardWrite.model_validate(body)


def test_view_settings_round_trip_and_survive_a_reread(tmp_path: Path) -> None:
    database, _ = database_with_inventory(tmp_path)
    repository = LiveDashboardRepository(database)
    created = repository.create(write(VIEW), actor_id="operator", organization_id=ORG_A)
    assert created.view_settings is not None
    assert created.view_settings["density"] == 1000
    assert created.view_settings["hidden_items"] == ["edge-1:K106:a-temperature-02:temperature"]

    reread = repository.get(created.id, organization_id=ORG_A)
    assert reread.view_settings == created.view_settings


def test_omitted_view_settings_preserve_and_explicit_null_clears(tmp_path: Path) -> None:
    database, _ = database_with_inventory(tmp_path)
    repository = LiveDashboardRepository(database)
    created = repository.create(write(VIEW), actor_id="operator", organization_id=ORG_A)

    # An older client that never sends the field must not wipe the saved analysis view.
    renamed = repository.update(
        created.id,
        write(name="Перейменовано"),
        expected_version=1,
        actor_id="operator",
        organization_id=ORG_A,
    )
    assert renamed.name == "Перейменовано"
    assert renamed.view_settings == created.view_settings

    cleared = repository.update(
        created.id,
        write(None),
        expected_version=2,
        actor_id="operator",
        organization_id=ORG_A,
    )
    assert cleared.view_settings is None


def test_unreadable_stored_value_is_ignored_not_an_error(tmp_path: Path) -> None:
    database, _ = database_with_inventory(tmp_path)
    repository = LiveDashboardRepository(database)
    created = repository.create(write(VIEW), actor_id="operator", organization_id=ORG_A)
    with Session(database.engine) as session:
        with session.begin():
            row = session.execute(select(LiveDashboard).where(LiveDashboard.id == created.id)).scalar_one()
            row.view_settings = {"schema_version": 99, "density": "warp"}
    assert repository.get(created.id, organization_id=ORG_A).view_settings is None


def test_legacy_rows_without_the_column_value_read_as_no_view(tmp_path: Path) -> None:
    database, _ = database_with_inventory(tmp_path)
    repository = LiveDashboardRepository(database)
    created = repository.create(write(), actor_id="operator", organization_id=ORG_A)
    with Session(database.engine) as session:
        with session.begin():
            session.execute(text("UPDATE live_dashboards SET view_settings = NULL"))
    assert repository.get(created.id, organization_id=ORG_A).view_settings is None


@pytest.mark.parametrize(
    "bad",
    [
        {"schema_version": 2},
        {"density": 123},
        {"range_kind": "custom"},
        {"range_kind": "custom", "range_from": "2026-11-20T10:00:00Z", "range_to": "2026-11-20T09:00:00Z"},
        {"range_kind": "custom", "range_from": "2026-01-01T00:00:00Z", "range_to": "2026-03-01T00:00:00Z"},
        {"range_kind": "24h", "range_from": "2026-11-20T09:00:00Z", "range_to": "2026-11-20T10:00:00Z"},
        {"viewport_from": "2026-11-20T09:00:00Z"},
        {"viewport_from": "2026-11-20T10:00:00Z", "viewport_to": "2026-11-20T09:00:00Z"},
        {"hidden_items": [""]},
        {"hidden_items": ["x" * 513]},
        {"hidden_items": [str(index) for index in range(65)]},
    ],
)
def test_invalid_view_settings_are_rejected(bad: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        LiveDashboardViewSettings.model_validate(bad)


def test_duplicate_hidden_items_are_collapsed_and_unknown_fields_ignored() -> None:
    parsed = LiveDashboardViewSettings.model_validate(
        {"hidden_items": ["a", "a", "b"], "future_field": "ignored"}
    )
    assert parsed.hidden_items == ["a", "b"]
    assert not hasattr(parsed, "future_field")


def test_api_round_trip_etag_and_backward_compatible_update(tmp_path: Path) -> None:
    api, _ = secured_client(tmp_path, subject="operator", roles={Role.OPERATOR})
    headers = auth_headers("operator")
    body = {**payload(), "view_settings": VIEW}
    created = api.post(
        "/api/v1/live-dashboards",
        headers={**headers, "X-Audit-Reason": "Create analysed workspace"},
        json=body,
    )
    assert created.status_code == 201
    assert created.json()["view_settings"]["density"] == 1000
    dashboard_id = created.json()["id"]

    # Older client: same payload without the field keeps the saved analysis view.
    legacy = api.put(
        f"/api/v1/live-dashboards/{dashboard_id}",
        headers={**headers, "If-Match": created.headers["etag"], "X-Audit-Reason": "Rename"},
        json=payload(name="Перейменований"),
    )
    assert legacy.status_code == 200
    assert legacy.json()["view_settings"]["range_kind"] == "custom"

    invalid = api.put(
        f"/api/v1/live-dashboards/{dashboard_id}",
        headers={**headers, "If-Match": legacy.headers["etag"], "X-Audit-Reason": "Bad view"},
        json={**payload(), "view_settings": {"density": 123}},
    )
    assert invalid.status_code == 422

    cleared = api.put(
        f"/api/v1/live-dashboards/{dashboard_id}",
        headers={**headers, "If-Match": legacy.headers["etag"], "X-Audit-Reason": "Clear view"},
        json={**payload(), "view_settings": None},
    )
    assert cleared.status_code == 200
    assert cleared.json()["view_settings"] is None
