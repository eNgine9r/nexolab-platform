"""Isolated transactional receipt intent tests (NOT site / MQTT acceptance)."""
from __future__ import annotations

from datetime import datetime, UTC
from uuid import UUID, uuid4
import pytest
from sqlalchemy import func, select

from app.committed_receipts import CommittedReceiptIdentity
from app.contracts import TelemetryEvent
from app.db import Database, TelemetryCommittedReceipt, TelemetrySample


ORG = "28dceec5-3a75-4d03-b5ec-b21122b35778"


def make_event(sequence: int = 1, *, event_id: str | None = None):
    raw = dict(
        event_id=event_id or str(uuid4()),
        node_id="edge-01",
        node_sequence=sequence,
        captured_at=datetime(2026, 10, 30, 12, 0, tzinfo=UTC).isoformat(),
        metric="electrical.voltage",
        value=231.3,
        unit="V",
        quality="valid",
        source="meter",
        equipment_id="meter-200",
        channel_id="200-v",
    )
    return TelemetryEvent.model_validate(raw), raw


@pytest.fixture
def database(tmp_path):
    db = Database(f"sqlite:///{tmp_path / 'committed-receipts.db'}")
    db.create_schema()
    yield db
    db.dispose()


def identity(sequence: int = 1):
    return CommittedReceiptIdentity(ORG, "edge-01", sequence)


def rows(db):
    with db.engine.connect() as connection:
        return list(connection.execute(
            select(TelemetryCommittedReceipt.__table__)
        ).mappings())


def test_default_unchanged_no_new_receipt(database):
    event, raw = make_event()
    assert database.persist(event, raw) is True
    assert rows(database) == []


def test_committed_receipt_same_transaction_and_schema(database):
    event, raw = make_event()
    assert database.persist(event, raw, receipt_identity=identity()) is True
    receipt = rows(database)[0]
    assert receipt["event_id"] == raw["event_id"]
    assert receipt["organization_id"] == ORG
    assert receipt["topic"] == f"nexolab/v1/{ORG}/edge-01/receipts"
    assert receipt["payload"]["receipt_level"] == "postgres_committed"
    assert receipt["payload"]["node_sequence"] == 1
    assert str(UUID(receipt["receipt_id"])) == receipt["receipt_id"]
    assert receipt["published_at"] is None


def test_idempotent_duplicate_keeps_original_receipt(database):
    event, raw = make_event()
    assert database.persist(event, raw, receipt_identity=identity()) is True
    original = rows(database)[0]["receipt_id"]
    assert database.persist(event, raw, receipt_identity=identity()) is False
    assert len(rows(database)) == 1
    assert rows(database)[0]["receipt_id"] == original


def test_unauthorized_identity_conflict_does_not_respond(database):
    event, raw = make_event()
    assert database.persist(event, raw, receipt_identity=identity()) is True
    forged = dict(raw, value=999.0)
    with pytest.raises(ValueError, match="receipt_duplicate_event_identity_conflict"):
        database.persist(event, forged, receipt_identity=identity())
    assert len(rows(database)) == 1


def test_capacity_blocks_telemetry_commit_without_receipt(database):
    first, one = make_event()
    second, two = make_event(2)
    assert database.persist(first, one, receipt_identity=identity(), receipt_outbox_max_pending=1)
    with pytest.raises(RuntimeError, match="receipt_outbox_capacity_reached"):
        database.persist(second, two, receipt_identity=identity(2), receipt_outbox_max_pending=1)
    with database.engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(TelemetrySample)) == 1
    assert len(rows(database)) == 1


def test_mismatched_node_sequence_rejected_before_database(database):
    event, raw = make_event()
    with pytest.raises(ValueError, match="receipt_sequence_unverified"):
        database.persist(event, raw, receipt_identity=identity(2))
    assert rows(database) == []


def test_mismatched_tenant_payload_rejected(database):
    event, raw = make_event()
    raw["organization_id"] = str(uuid4())
    with pytest.raises(ValueError, match="receipt_organization_mismatch"):
        database.persist(event, raw, receipt_identity=identity())
    assert rows(database) == []


def test_rollback_does_not_leave_phantom_receipt(database, monkeypatch):
    event, raw = make_event()

    def fail_projection(*args, **kwargs):
        raise RuntimeError("forced_projection_failure")

    monkeypatch.setattr(database, "_upsert_latest", fail_projection)
    with pytest.raises(RuntimeError, match="forced_projection_failure"):
        database.persist(event, raw, receipt_identity=identity())
    with database.engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(TelemetrySample)) == 0
    assert rows(database) == []


def test_identity_fails_closed_on_noncanonical_and_bool_sequence():
    with pytest.raises(ValueError, match="invalid_receipt_sequence"):
        CommittedReceiptIdentity(ORG, "edge-01", True)
    with pytest.raises(ValueError, match="noncanonical_receipt_organization"):
        CommittedReceiptIdentity(ORG.upper(), "edge-01", 1)
