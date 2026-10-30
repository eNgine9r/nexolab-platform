"""Isolated transactional receipt intent tests (NOT site / MQTT acceptance)."""
from __future__ import annotations

from datetime import datetime, UTC
import os
from uuid import UUID, uuid4
import pytest
from sqlalchemy import delete, func, select

from app.committed_receipts import CommittedReceiptIdentity
from app.contracts import TelemetryEvent
from app.db import Database, TelemetryCommittedReceipt, TelemetryLatest, TelemetrySample


ORG = "28dceec5-3a75-4d03-b5ec-b21122b35778"
NODE = f"receipt-{uuid4().hex[:20]}"


def make_event(sequence: int = 1, *, event_id: str | None = None):
    raw = dict(
        event_id=event_id or str(uuid4()),
        node_id=NODE,
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
def database():
    # A PostgreSQL-committed receipt cannot be proven by SQLite fixtures.
    url = os.environ.get("DATABASE_URL", "")
    if not url.startswith("postgresql"):
        pytest.skip("PostgreSQL integration database required for committed receipts")
    db = Database(url)
    db.create_schema()
    yield db
    with db.engine.begin() as connection:
        connection.execute(
            delete(TelemetryCommittedReceipt).where(TelemetryCommittedReceipt.node_id == NODE)
        )
        connection.execute(delete(TelemetryLatest).where(TelemetryLatest.node_id == NODE))
        connection.execute(delete(TelemetrySample).where(TelemetrySample.node_id == NODE))
    db.dispose()


def identity(sequence: int = 1):
    return CommittedReceiptIdentity(ORG, NODE, sequence)


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
    assert receipt["topic"] == f"nexolab/v1/{ORG}/{NODE}/receipts"
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


def test_non_postgres_cannot_claim_postgresql_commit(tmp_path):
    fake = Database(f"sqlite:///{tmp_path / 'refuse.db'}")
    fake.create_schema()
    event, raw = make_event()
    with pytest.raises(RuntimeError, match="postgresql_required_for_committed_receipt"):
        fake.persist(event, raw, receipt_identity=identity())
    assert rows(fake) == []
    fake.dispose()


def test_identity_fails_closed_on_noncanonical_and_bool_sequence():
    with pytest.raises(ValueError, match="invalid_receipt_sequence"):
        CommittedReceiptIdentity(ORG, NODE, True)
    with pytest.raises(ValueError, match="noncanonical_receipt_organization"):
        CommittedReceiptIdentity(ORG.upper(), NODE, 1)



def test_broker_ack_failure_keeps_durable_pending_and_retry(database):
    from datetime import timedelta
    from app.committed_receipt_publisher import CommittedReceiptPublisher

    event, raw = make_event()
    assert database.persist(event, raw, receipt_identity=identity())
    delivered = []
    def sender(topic, payload):
        delivered.append((topic, payload))
        return len(delivered) > 1

    publisher = CommittedReceiptPublisher(database, sender)
    start = datetime.now(UTC)
    first = publisher.run_once(now=start)
    assert first.status == "retry"
    assert rows(database)[0]["published_at"] is None
    assert publisher.run_once(now=start + timedelta(seconds=1)).status == "idle"
    second = publisher.run_once(now=start + timedelta(seconds=3))
    assert second.status == "published"
    assert len(delivered) == 2
    assert delivered[0][1] == delivered[1][1]
    assert rows(database)[0]["published_at"] is not None


def test_restart_before_ack_claim_expires_and_replays(database):
    from datetime import timedelta
    from app.committed_receipt_publisher import CommittedReceiptPublisher

    event, raw = make_event()
    assert database.persist(event, raw, receipt_identity=identity())
    first = CommittedReceiptPublisher(database, lambda *_: False)
    start = datetime.now(UTC)
    assert first.run_once(now=start).status == "retry"
    recovered = CommittedReceiptPublisher(database, lambda *_: True)
    assert recovered.run_once(now=start + timedelta(seconds=3)).status == "published"
    assert rows(database)[0]["attempts"] == 2


def test_duplicate_replay_requeues_confirmed_receipt_with_fresh_identity(database):
    from app.committed_receipt_publisher import CommittedReceiptPublisher

    event, raw = make_event()
    assert database.persist(event, raw, receipt_identity=identity())
    assert CommittedReceiptPublisher(database, lambda *_: True).run_once().status == "published"
    receipt = rows(database)[0]["receipt_id"]
    assert database.persist(event, raw, receipt_identity=identity()) is False
    current = rows(database)[0]
    assert current["published_at"] is None
    assert current["receipt_id"] != receipt
    assert current["payload"]["event_id"] == raw["event_id"]


def test_sender_cannot_claim_postgres_from_sqlite(tmp_path):
    from app.committed_receipt_publisher import CommittedReceiptPublisher

    db = Database(f"sqlite:///{tmp_path / 'sender-refuse.db'}")
    with pytest.raises(RuntimeError, match="postgresql_required_for_committed_receipt"):
        CommittedReceiptPublisher(db, lambda *_: True)
    db.dispose()
