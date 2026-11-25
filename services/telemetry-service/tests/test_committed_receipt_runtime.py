"""#1762 slice 1: default-OFF committed-receipt runtime wiring.

Fake MQTT modules and synthetic PUBACK callbacks here are NOT broker ACL,
Edge delivery or site evidence. PostgreSQL cases skip without a PostgreSQL
DATABASE_URL and run in the telemetry-service CI workflow.
"""
from __future__ import annotations

import json
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.committed_receipt_publisher import PublishAttempt
from app.committed_receipt_runtime import (
    RECEIPT_CONFLICT_REASON,
    CommittedReceiptIngress,
    CommittedReceiptPublisherLoop,
    CommittedReceiptStats,
    build_committed_receipt_runtime,
)
from app.config import Settings
from app.db import Database
from app.ingestion import TelemetryIngestor
from app.metrics import render_prometheus
from app.state import RuntimeState

ORG = "28dceec5-3a75-4d03-b5ec-b21122b35778"
NODE = "edge-01"
NODE_TOPIC = f"nexolab/v1/{ORG}/{NODE}/telemetry"


def wait_for(predicate, timeout: float = 4.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("condition was not met before timeout")


def payload(*, event_id: str | None = None, sequence: int = 1, node: str = NODE) -> bytes:
    return json.dumps(
        {
            "event_id": event_id or str(uuid4()),
            "node_id": node,
            "node_sequence": sequence,
            "captured_at": datetime.now(UTC).isoformat(),
            "metric": "temperature.probe",
            "value": 3.25,
            "unit": "degC",
            "quality": "valid",
            "source": "synthetic-receipt-runtime",
            "equipment_id": "K106",
            "channel_id": "106-01",
        }
    ).encode("utf-8")


def sqlite_database(tmp_path: Path) -> Database:
    database = Database(f"sqlite:///{tmp_path / 'telemetry.db'}")
    database.create_schema()
    return database


def enabled_settings(tmp_path: Path, **overrides: Any) -> Settings:
    password = tmp_path / "receipt-publisher-password"
    password.write_text("synthetic-test-only\n", encoding="utf-8")
    values: dict[str, Any] = dict(
        database_url="postgresql+psycopg://user:pw@isolated-postgres:5432/nexolab",
        mqtt_enabled=True,
        mqtt_node_registry_enforced=True,
        mqtt_username="ingestion-subscriber",
        mqtt_password_file=str(tmp_path / "ingestion-password"),
        nexolab_committed_receipts="enabled",
        nexolab_receipt_publisher_username="central-receipts-only",
        nexolab_receipt_publisher_password_file=str(password),
    )
    values.update(overrides)
    return Settings(**values)


# ---------------------------------------------------------------- disabled


def test_flag_defaults_to_disabled() -> None:
    settings = Settings()
    assert settings.nexolab_committed_receipts == "disabled"
    assert settings.committed_receipts_enabled is False


def test_disabled_ingestion_uses_legacy_persist_and_no_publisher(tmp_path: Path) -> None:
    from app.main import create_app

    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'telemetry.db'}",
        auto_create_schema=True,
        mqtt_enabled=False,
        retention_enabled=False,
    )
    app = create_app(settings)
    assert app.state.receipt_publisher_loop is None
    assert app.state.ingestor._committed_receipts is None

    calls: list[tuple[Any, ...]] = []
    original = app.state.database.persist

    def spy(*args: Any, **kwargs: Any) -> bool:
        calls.append((args, kwargs))
        return original(*args, **kwargs)

    app.state.database.persist = spy
    with TestClient(app) as client:
        assert app.state.ingestor.submit_payload(payload(), topic=NODE_TOPIC)
        wait_for(lambda: app.state.runtime.snapshot()["persisted_total"] == 1)
        ready = client.get("/health/ready").json()
        metrics_json = client.get("/metrics/json").json()
        metrics_text = client.get("/metrics").text

    # Exactly the legacy call shape: persist(event, raw), no receipt kwargs.
    assert len(calls) == 1
    assert len(calls[0][0]) == 2 and calls[0][1] == {}
    assert "committed_receipts" not in ready
    assert "committed_receipts" not in metrics_json
    assert "committed_receipt" not in metrics_text
    assert not any(thread_name_is_receipt(name) for name in live_thread_names())


def live_thread_names() -> list[str]:
    import threading

    return [thread.name for thread in threading.enumerate()]


def thread_name_is_receipt(name: str) -> bool:
    return name == "committed-receipt-publisher"


# ---------------------------------------------------------- config validation


def test_enabled_configuration_is_accepted(tmp_path: Path) -> None:
    settings = enabled_settings(tmp_path)
    assert settings.committed_receipts_enabled is True


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"mqtt_node_registry_enforced": False}, "MQTT_NODE_REGISTRY_ENFORCED"),
        ({"mqtt_enabled": False}, "MQTT_ENABLED"),
        ({"database_url": "sqlite:///telemetry.db"}, "PostgreSQL DATABASE_URL"),
        ({"nexolab_receipt_publisher_username": None}, "NEXOLAB_RECEIPT_PUBLISHER_USERNAME is required"),
        ({"nexolab_receipt_publisher_password_file": None}, "NEXOLAB_RECEIPT_PUBLISHER_PASSWORD_FILE"),
        ({"nexolab_receipt_publisher_username": "ingestion-subscriber"}, "must differ from MQTT_USERNAME"),
        ({"nexolab_receipt_publisher_client_id": "nexolab-telemetry-ingestion"}, "must differ from MQTT_CLIENT_ID"),
        (
            {
                "nexolab_receipt_publisher_retry_initial_seconds": 30.0,
                "nexolab_receipt_publisher_retry_max_seconds": 10.0,
            },
            "RETRY_MAX_SECONDS",
        ),
    ],
)
def test_enabled_configuration_fails_closed(
    tmp_path: Path, overrides: dict[str, Any], expected: str
) -> None:
    with pytest.raises(ValidationError) as caught:
        enabled_settings(tmp_path, **overrides)
    message = str(caught.value)
    assert expected in message
    assert "synthetic-test-only" not in message


def test_enabled_flag_rejects_unknown_value() -> None:
    with pytest.raises(ValidationError):
        Settings(nexolab_committed_receipts="on")


class FakeMqttClient:
    def __init__(self) -> None:
        self.on_connect = None
        self.on_disconnect = None
        self.credentials: tuple[str, str] | None = None
        self.tls_contexts: list[Any] = []
        self.started = False
        self.stopped = False

    def username_pw_set(self, username: str, password: str) -> None:
        self.credentials = (username, password)

    def tls_set_context(self, context: Any) -> None:
        self.tls_contexts.append(context)

    def connect_async(self, host: str, port: int, keepalive: int) -> None:
        self.target = (host, port, keepalive)

    def loop_start(self) -> None:
        self.started = True

    def loop_stop(self) -> None:
        self.stopped = True

    def disconnect(self) -> None:
        return


def fake_mqtt_module(client: FakeMqttClient, created: list[dict[str, Any]]) -> Any:
    def factory(**kwargs: Any) -> FakeMqttClient:
        created.append(kwargs)
        return client

    return SimpleNamespace(
        CallbackAPIVersion=SimpleNamespace(VERSION2=2),
        MQTTv311=4,
        MQTT_ERR_SUCCESS=0,
        Client=factory,
    )


def fake_postgres_database() -> Any:
    return SimpleNamespace(engine=SimpleNamespace(dialect=SimpleNamespace(name="postgresql")))


def test_runtime_uses_dedicated_identity_from_password_file(tmp_path: Path) -> None:
    settings = enabled_settings(tmp_path)
    client = FakeMqttClient()
    created: list[dict[str, Any]] = []
    authorizer = SimpleNamespace(authorize_and_persist_committed=lambda *a: None)
    ingress, loop = build_committed_receipt_runtime(
        settings,
        fake_postgres_database(),
        authorizer,
        mqtt_module=fake_mqtt_module(client, created),
    )
    assert client.credentials == ("central-receipts-only", "synthetic-test-only")
    assert created[0]["client_id"] == "nexolab-receipt-publisher"
    assert created[0]["client_id"] != settings.mqtt_client_id
    assert isinstance(ingress, CommittedReceiptIngress)
    assert loop.stats.snapshot()["status"] == "stopped"


def test_runtime_fails_closed_without_readable_password(tmp_path: Path) -> None:
    settings = enabled_settings(
        tmp_path,
        nexolab_receipt_publisher_password_file=str(tmp_path / "missing"),
    )
    authorizer = SimpleNamespace(authorize_and_persist_committed=lambda *a: None)
    with pytest.raises(RuntimeError, match="password file is not readable"):
        build_committed_receipt_runtime(
            settings,
            fake_postgres_database(),
            authorizer,
            mqtt_module=fake_mqtt_module(FakeMqttClient(), []),
        )


def test_runtime_refuses_sqlite_and_missing_registry(tmp_path: Path) -> None:
    settings = enabled_settings(tmp_path)
    database = sqlite_database(tmp_path)
    authorizer = SimpleNamespace(authorize_and_persist_committed=lambda *a: None)
    with pytest.raises(RuntimeError, match="postgresql_required"):
        build_committed_receipt_runtime(settings, database, authorizer)
    with pytest.raises(RuntimeError, match="node_registry"):
        build_committed_receipt_runtime(settings, fake_postgres_database(), None)
    database.dispose()


# -------------------------------------------------------- enabled ingestion


class FakeCommittedPath:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None]] = []
        self.result: Any = (True, "authorized", "ok", True)

    def __call__(self, event, raw, topic, observed_at):
        assert observed_at.tzinfo is not None
        assert raw["node_sequence"] == event.model_extra["node_sequence"]
        self.calls.append((str(event.event_id), topic))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def enabled_ingestor(tmp_path: Path, committed: FakeCommittedPath, **kwargs: Any):
    database = sqlite_database(tmp_path)
    legacy_calls: list[tuple[Any, ...]] = []
    original = database.persist

    def legacy_spy(*args: Any, **kw: Any) -> bool:
        legacy_calls.append((args, kw))
        return original(*args, **kw)

    database.persist = legacy_spy  # type: ignore[method-assign]
    state = RuntimeState()
    stats = CommittedReceiptStats()
    ingestor = TelemetryIngestor(
        database,
        state,
        queue_maxsize=10,
        committed_receipts=CommittedReceiptIngress(committed, stats),
        **kwargs,
    )
    return database, state, stats, ingestor, legacy_calls


def test_enabled_org_scoped_topic_uses_committed_path(tmp_path: Path) -> None:
    committed = FakeCommittedPath()
    published: list[dict[str, Any]] = []
    processed: list[dict[str, Any]] = []
    database, state, stats, ingestor, legacy_calls = enabled_ingestor(
        tmp_path,
        committed,
        on_persisted=published.append,
        after_persist=processed.append,
    )
    ingestor.start()
    assert ingestor.submit_payload(payload(sequence=1), topic=NODE_TOPIC)
    wait_for(lambda: state.snapshot()["persisted_total"] == 1)
    committed.result = (True, "authorized", "ok", False)
    assert ingestor.submit_payload(payload(sequence=2), topic=NODE_TOPIC)
    wait_for(lambda: state.snapshot()["duplicate_total"] == 1)
    ingestor.stop()

    assert [topic for _, topic in committed.calls] == [NODE_TOPIC, NODE_TOPIC]
    assert legacy_calls == []
    assert len(published) == 1
    assert len(processed) == 2
    assert stats.snapshot()["committed_ingress_total"] == 2
    database.dispose()


def test_enabled_legacy_topic_keeps_legacy_path(tmp_path: Path) -> None:
    committed = FakeCommittedPath()
    database, state, _, ingestor, legacy_calls = enabled_ingestor(tmp_path, committed)
    ingestor.start()
    assert ingestor.submit_payload(payload(), topic="nexolab/telemetry")
    assert ingestor.submit_payload(payload(), topic=f"nexolab/v1/{ORG}/{NODE}/health")
    wait_for(lambda: state.snapshot()["persisted_total"] == 2)
    ingestor.stop()
    assert committed.calls == []
    assert len(legacy_calls) == 2 and all(kw == {} for _, kw in legacy_calls)
    database.dispose()


def test_enabled_rejection_dead_letters_like_legacy(tmp_path: Path) -> None:
    committed = FakeCommittedPath()
    committed.result = (False, "node_replay", "node_sequence is lower", None)
    database, state, _, ingestor, legacy_calls = enabled_ingestor(tmp_path, committed)
    ingestor.start()
    assert ingestor.submit_payload(payload(), topic=NODE_TOPIC)
    wait_for(lambda: state.snapshot()["dead_letter_by_reason"].get("node_replay") == 1)
    ingestor.stop()
    assert state.snapshot()["rejected_total"] == 1
    assert state.snapshot()["persisted_total"] == 0
    assert legacy_calls == []
    database.dispose()


def test_enabled_identity_conflict_is_dead_lettered_not_retried(tmp_path: Path) -> None:
    committed = FakeCommittedPath()
    committed.result = ValueError("receipt_duplicate_event_identity_conflict")
    database, state, stats, ingestor, legacy_calls = enabled_ingestor(tmp_path, committed)
    ingestor.start()
    assert ingestor.submit_payload(payload(), topic=NODE_TOPIC)
    wait_for(
        lambda: state.snapshot()["dead_letter_by_reason"].get(RECEIPT_CONFLICT_REASON) == 1
    )
    committed.result = (True, "authorized", "ok", True)
    assert ingestor.submit_payload(payload(sequence=2), topic=NODE_TOPIC)
    wait_for(lambda: state.snapshot()["persisted_total"] == 1)
    ingestor.stop()
    assert state.snapshot()["database_retry_total"] == 0
    assert stats.snapshot()["conflict_dead_letter_total"] == 1
    assert legacy_calls == []
    database.dispose()


def test_enabled_outbox_full_falls_back_to_legacy_persist(tmp_path: Path) -> None:
    committed = FakeCommittedPath()
    committed.result = RuntimeError("receipt_outbox_capacity_reached")
    database, state, stats, ingestor, legacy_calls = enabled_ingestor(tmp_path, committed)
    ingestor.start()
    assert ingestor.submit_payload(payload(), topic=NODE_TOPIC)
    wait_for(lambda: state.snapshot()["persisted_total"] == 1)
    ingestor.stop()
    assert len(legacy_calls) == 1 and legacy_calls[0][1] == {}
    assert stats.snapshot()["outbox_full_fallback_total"] == 1
    database.dispose()


def test_enabled_database_failure_is_retried(tmp_path: Path) -> None:
    committed = FakeCommittedPath()
    committed.result = RuntimeError("database unavailable")
    database, state, _, ingestor, legacy_calls = enabled_ingestor(
        tmp_path,
        committed,
        database_retry_initial_seconds=0.05,
        database_retry_max_seconds=0.05,
    )
    ingestor.start()
    assert ingestor.submit_payload(payload(), topic=NODE_TOPIC)
    wait_for(lambda: state.snapshot()["database_retry_total"] >= 1)
    committed.result = (True, "authorized", "ok", True)
    wait_for(lambda: state.snapshot()["persisted_total"] == 1)
    ingestor.stop()
    assert legacy_calls == []
    database.dispose()


# ----------------------------------------------------------- publisher loop


class FakePublisher:
    def __init__(self, outcomes: list[Any]) -> None:
        self.outcomes = list(outcomes)
        self.calls = 0

    def run_once(self, *, now=None) -> PublishAttempt:
        self.calls += 1
        outcome = self.outcomes.pop(0) if self.outcomes else "idle"
        if isinstance(outcome, Exception):
            raise outcome
        return PublishAttempt(outcome, str(uuid4()) if outcome != "idle" else None, 1)

    def pending_stats(self, *, now=None):
        return {"pending": 3, "oldest_pending_age_seconds": 12.5}


class FakeTransport:
    def __init__(self, fail_start: bool = False) -> None:
        self.fail_start = fail_start
        self.started = 0
        self.stopped = 0

    def start(self) -> None:
        self.started += 1
        if self.fail_start:
            raise OSError("broker unreachable")

    def stop(self) -> None:
        self.stopped += 1


def test_loop_iteration_backoff_and_metrics() -> None:
    publisher = FakePublisher(["retry", "retry", "published", "idle", OSError("db down")])
    stats = CommittedReceiptStats()
    loop = CommittedReceiptPublisherLoop(
        publisher,
        stats,
        idle_seconds=0.5,
        retry_initial_seconds=1.0,
        retry_max_seconds=4.0,
    )
    assert loop.run_iteration(1.0) == ("retry", 1.0)
    assert stats.snapshot()["consecutive_failures"] == 1
    assert loop.run_iteration(2.0) == ("retry", 2.0)
    assert loop.run_iteration(4.0) == ("published", 0.0)
    snapshot = stats.snapshot()
    assert snapshot["consecutive_failures"] == 0
    assert snapshot["publish_attempts_total"] == 3
    assert snapshot["publish_failures_total"] == 2
    assert snapshot["published_total"] == 1
    assert snapshot["pending"] == 3
    assert snapshot["oldest_pending_age_seconds"] == 12.5
    assert loop.run_iteration(1.0) == ("idle", 0.5)
    assert loop.run_iteration(1.0) == ("error", 1.0)
    snapshot = stats.snapshot()
    assert snapshot["loop_errors_total"] == 1
    assert snapshot["last_error"] == "OSError"


def test_loop_thread_bounded_backoff_and_graceful_shutdown() -> None:
    publisher = FakePublisher([OSError("db down")] * 3 + ["published"])
    stats = CommittedReceiptStats()
    transport = FakeTransport()
    loop = CommittedReceiptPublisherLoop(
        publisher,
        stats,
        transport=transport,
        connected=lambda: True,
        idle_seconds=0.05,
        retry_initial_seconds=0.05,
        retry_max_seconds=0.1,
        stop_timeout_seconds=2.0,
    )
    loop.start()
    assert transport.started == 1
    wait_for(lambda: stats.snapshot()["published_total"] == 1)
    assert stats.snapshot()["status"] == "ready"
    assert stats.snapshot()["transport_connected"] is True
    started = time.monotonic()
    loop.stop()
    assert time.monotonic() - started < 2.0
    assert transport.stopped == 1
    assert stats.snapshot()["status"] == "stopped"
    assert not any(thread_name_is_receipt(name) for name in live_thread_names())


def test_loop_transport_start_failure_does_not_raise() -> None:
    stats = CommittedReceiptStats()
    loop = CommittedReceiptPublisherLoop(
        FakePublisher([]),
        stats,
        transport=FakeTransport(fail_start=True),
        idle_seconds=0.05,
    )
    loop.start()
    assert stats.snapshot()["last_error"] == "OSError"
    loop.stop()


def test_loop_rejects_invalid_policy() -> None:
    with pytest.raises(ValueError):
        CommittedReceiptPublisherLoop(
            FakePublisher([]),
            CommittedReceiptStats(),
            retry_initial_seconds=5.0,
            retry_max_seconds=1.0,
        )


# ------------------------------------------------ readiness / metrics split


def test_readiness_reports_receipts_separately_and_never_blocks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.main as main_module

    stats = CommittedReceiptStats()
    loop = CommittedReceiptPublisherLoop(
        FakePublisher([OSError("broker down")] * 1000),
        stats,
        transport=FakeTransport(),
        connected=lambda: False,
        idle_seconds=0.05,
        retry_initial_seconds=0.05,
        retry_max_seconds=0.05,
    )
    ingress = CommittedReceiptIngress(FakeCommittedPath(), stats)

    def fake_build(settings, database, authorizer, **kwargs):
        assert authorizer is not None
        return ingress, loop

    monkeypatch.setattr(main_module, "build_committed_receipt_runtime", fake_build)
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'telemetry.db'}",
        auto_create_schema=True,
        mqtt_enabled=False,
        retention_enabled=False,
        mqtt_node_registry_enforced=True,
    )
    # Validation for the real flag requires PostgreSQL; this only exercises
    # the readiness/metrics composition with an injected fake runtime.
    settings.nexolab_committed_receipts = "enabled"
    app = main_module.create_app(settings)
    assert app.state.ingestor._committed_receipts is ingress
    with TestClient(app) as client:
        wait_for(lambda: stats.snapshot()["loop_errors_total"] >= 2)
        response = client.get("/health/ready")
        body = response.json()
        metrics_json = client.get("/metrics/json").json()
        metrics_text = client.get("/metrics").text

    assert response.status_code == 200
    assert body["status"] == "ready"
    assert body["committed_receipts"]["status"] == "degraded"
    assert body["committed_receipts"]["transport_connected"] is False
    assert metrics_json["committed_receipts"]["pending"] == 3
    assert "nexolab_telemetry_committed_receipt_pending 3" in metrics_text
    assert "nexolab_telemetry_committed_receipt_oldest_pending_age_seconds 12.5" in metrics_text
    assert "nexolab_telemetry_committed_receipt_loop_errors_total" in metrics_text
    assert stats.snapshot()["status"] == "stopped"


def test_prometheus_without_receipt_section_is_unchanged() -> None:
    snapshot = RuntimeState().snapshot()
    baseline = render_prometheus(snapshot)
    assert "committed_receipt" not in baseline
    with_section = render_prometheus(
        {**snapshot, "committed_receipts": CommittedReceiptStats().snapshot()}
    )
    assert with_section.startswith(baseline.rstrip("\n"))


# ------------------------------------------------- PostgreSQL (CI) end-to-end


@pytest.fixture
def postgres_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url.startswith("postgresql"):
        pytest.skip("PostgreSQL integration database required for committed receipts")
    return url


def test_postgres_enabled_ingestion_commits_receipt_and_publishes(postgres_url: str) -> None:
    """Real PostgreSQL transaction; the sender is a synthetic PUBACK (no ACL proof)."""
    from sqlalchemy import delete, select
    from sqlalchemy.orm import Session

    from app.committed_receipt_publisher import CommittedReceiptPublisher
    from app.db import TelemetryCommittedReceipt, TelemetryLatest, TelemetrySample
    from app.model_registry import register_models
    from app.nodes.ingress import NodeIngressAuthorizer
    from app.nodes.models import (
        CentralNode,
        CentralNodeCredential,
        CentralNodeIngressCursor,
    )
    from app.security.models import SecurityOrganization
    from app.sessions.telemetry_attribution import SessionAwareDatabase

    register_models()
    database = SessionAwareDatabase(postgres_url)
    database.create_schema()
    org = str(uuid4())
    node = f"receipt-rt-{uuid4().hex[:16]}"
    node_record_id = str(uuid4())
    credential_id = str(uuid4())
    observed = datetime.now(UTC)
    with Session(database.engine) as session:
        with session.begin():
            session.add(
                SecurityOrganization(
                    id=org, slug=f"receipt-rt-{uuid4().hex[:12]}", name="Receipt runtime CI"
                )
            )
            session.flush()
            session.add(
                CentralNode(
                    id=node_record_id,
                    organization_id=org,
                    node_id=node,
                    display_name="Receipt runtime node",
                    state="active",
                    state_reason="isolated PostgreSQL test",
                    created_by="test",
                    created_at=observed,
                    updated_at=observed,
                )
            )
            session.flush()
            session.add(
                CentralNodeCredential(
                    id=credential_id,
                    organization_id=org,
                    node_record_id=node_record_id,
                    generation=1,
                    secret_salt="0" * 64,
                    secret_hash="0" * 64,
                    secret_fingerprint="0" * 16,
                    idempotency_key=f"receipt-rt-{uuid4()}",
                    command_sha256="0" * 64,
                    issued_by="test",
                    issued_at=observed,
                )
            )

    topic = f"nexolab/v1/{org}/{node}/telemetry"
    event_id = str(uuid4())
    authorizer = NodeIngressAuthorizer(database)
    stats = CommittedReceiptStats()
    state = RuntimeState()
    ingestor = TelemetryIngestor(
        database,
        state,
        queue_maxsize=10,
        authorize_ingress=authorizer.authorize,
        committed_receipts=CommittedReceiptIngress(
            authorizer.authorize_and_persist_committed, stats
        ),
    )
    sent: list[tuple[str, dict[str, Any]]] = []
    try:
        ingestor.start()
        body = payload(event_id=event_id, sequence=1, node=node)
        assert ingestor.submit_payload(body, topic=topic)
        assert ingestor.submit_payload(body, topic=topic)
        wait_for(
            lambda: state.snapshot()["persisted_total"] == 1
            and state.snapshot()["duplicate_total"] == 1,
            timeout=10.0,
        )
        ingestor.stop()

        with database.engine.connect() as connection:
            receipts = list(
                connection.execute(
                    select(TelemetryCommittedReceipt.__table__).where(
                        TelemetryCommittedReceipt.node_id == node
                    )
                ).mappings()
            )
        assert len(receipts) == 1
        assert receipts[0]["event_id"] == event_id
        assert receipts[0]["published_at"] is None

        def sender(receipt_topic: str, raw: bytes) -> bool:
            sent.append((receipt_topic, json.loads(raw)))
            return True

        loop = CommittedReceiptPublisherLoop(
            CommittedReceiptPublisher(database, sender), stats, idle_seconds=0.05
        )
        outcome = "idle"
        for _ in range(50):
            outcome, _ = loop.run_iteration(1.0)
            if outcome == "published" and any(
                body["event_id"] == event_id for _, body in sent
            ):
                break
        assert any(
            receipt_topic == f"nexolab/v1/{org}/{node}/receipts"
            and body["event_id"] == event_id
            and body["receipt_level"] == "postgres_committed"
            for receipt_topic, body in sent
        )
        with database.engine.connect() as connection:
            published_at = connection.scalar(
                select(TelemetryCommittedReceipt.published_at).where(
                    TelemetryCommittedReceipt.event_id == event_id
                )
            )
        assert published_at is not None
    finally:
        ingestor.stop()
        with Session(database.engine) as session:
            with session.begin():
                session.execute(
                    delete(TelemetryCommittedReceipt).where(
                        TelemetryCommittedReceipt.node_id == node
                    )
                )
                session.execute(delete(TelemetryLatest).where(TelemetryLatest.node_id == node))
                session.execute(delete(TelemetrySample).where(TelemetrySample.node_id == node))
                session.query(CentralNodeIngressCursor).filter_by(
                    node_record_id=node_record_id
                ).delete()
                session.query(CentralNodeCredential).filter_by(id=credential_id).delete()
                session.query(CentralNode).filter_by(id=node_record_id).delete()
                session.query(SecurityOrganization).filter_by(id=org).delete()
        database.dispose()


def test_session_aware_persist_joins_caller_transaction(tmp_path: Path) -> None:
    """The committed path hands SessionAwareDatabase the registry transaction."""
    from app.contracts import TelemetryEvent
    from app.model_registry import register_models
    from app.sessions.telemetry_attribution import SessionAwareDatabase

    register_models()
    database = SessionAwareDatabase(f"sqlite:///{tmp_path / 'telemetry.db'}")
    database.create_schema()
    raw = json.loads(payload())
    event = TelemetryEvent.model_validate(raw)

    class Abort(Exception):
        pass

    with pytest.raises(Abort):
        with database.engine.begin() as connection:
            assert database.persist(event, raw, connection=connection) is True
            raise Abort()
    assert database.count_samples() == 0

    with database.engine.begin() as connection:
        assert database.persist(event, raw, connection=connection) is True
    assert database.count_samples() == 1
    assert database.persist(event, raw) is False
    database.dispose()
