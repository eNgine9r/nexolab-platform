from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.sessions.configuration_schemas import ProductionBindingsCreate
from app.sessions.repository import SessionConflictError
from app.sessions.schemas import SessionCreate


def test_report_original_production_binding_integrity_error(tmp_path: Path) -> None:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'attribution-diagnostic.db'}",
        auto_create_schema=True,
        mqtt_enabled=False,
        retention_enabled=False,
    )
    app = create_app(settings)

    with TestClient(app):
        repository = app.state.session_repository
        created = repository.create(
            SessionCreate(
                session_number="NXL-M4-DIAGNOSTIC",
                title="Attribution diagnostic",
                test_object="K106 display cabinet",
                actor_id="diagnostic",
            ),
            idempotency_key="create-attribution-diagnostic",
        )
        try:
            repository.add_production_bindings(
                created.session.id,
                ProductionBindingsCreate(actor_id="diagnostic"),
                idempotency_key="production-attribution-diagnostic",
            )
        except SessionConflictError as error:
            pytest.fail(
                "original integrity error: "
                f"{error.__cause__!r}; "
                f"context={error.__context__!r}"
            )
