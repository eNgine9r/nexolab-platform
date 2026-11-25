"""Evidence-aware, bounded 30-day telemetry retention (#1551)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import text

from app import retention as retention_module
from app.config import Settings
from app.db import Database
from app.model_registry import register_models
from app.retention import RetentionWorker
from app.state import RuntimeState
from tests.test_retention import event

register_models()

NOW = datetime(2026, 11, 23, 12, 0, tzinfo=UTC)


def _uuid(number: int) -> str:
    return f"{number:08d}-0000-4000-8000-{number:012d}"


def _database(tmp_path: Path) -> Database:
    database = Database(f"sqlite:///{tmp_path / 'retention.db'}")
    database.create_schema()
    return database


def _persist(database: Database, number: int, age: timedelta) -> str:
    sample = event(_uuid(number), NOW - age)
    assert database.persist(sample, sample.normalized_payload())
    return str(sample.event_id)


def _link_to_session(database: Database, event_id: str) -> None:
    with database.engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO telemetry_session_contexts "
                "(telemetry_event_id, session_id, binding_id, config_snapshot_id, captured_at, resolver_version) "
                "VALUES (:event_id, :session, :binding, :snapshot, :captured_at, 'test')"
            ),
            {
                "event_id": event_id,
                "session": _uuid(900),
                "binding": _uuid(901),
                "snapshot": _uuid(902),
                "captured_at": NOW - timedelta(days=60),
            },
        )


def _event_ids(database: Database) -> set[str]:
    with database.engine.connect() as connection:
        return {row[0] for row in connection.execute(text("SELECT event_id FROM telemetry_samples"))}


def _worker(database: Database, **overrides: object) -> RetentionWorker:
    values: dict[str, object] = dict(
        database=database,
        state=RuntimeState(),
        interval_seconds=3600,
        batch_size=2,
        telemetry_retention_days=30,
        raw_payload_retention_days=3650,
        dead_letter_retention_days=3650,
        telemetry_delete_enabled=True,
        max_batches_per_cycle=100,
        cycle_budget_seconds=60.0,
        batch_pause_seconds=0.0,
        backlog_interval_seconds=300,
    )
    values.update(overrides)
    return RetentionWorker(**values)  # type: ignore[arg-type]


def test_policy_defaults_are_30_days_and_deletion_off_until_enabled() -> None:
    fields = Settings.model_fields
    assert fields["telemetry_retention_days"].default == 30
    assert fields["retention_telemetry_delete_enabled"].default is False
    assert fields["retention_batch_size"].default == 2000
    assert fields["retention_backlog_interval_seconds"].default < fields["retention_interval_seconds"].default


def test_session_evidence_survives_and_ordinary_history_is_deleted(tmp_path: Path) -> None:
    database = _database(tmp_path)
    linked = _persist(database, 1, timedelta(days=60))
    old = [_persist(database, number, timedelta(days=40 + number)) for number in range(2, 7)]
    recent = _persist(database, 7, timedelta(days=1))
    _link_to_session(database, linked)

    result = _worker(database).run_once(now=NOW)

    assert result.telemetry_deleted == len(old)
    assert _event_ids(database) == {linked, recent}
    with database.engine.connect() as connection:
        contexts = {row[0] for row in connection.execute(text("SELECT telemetry_event_id FROM telemetry_session_contexts"))}
    assert contexts == {linked}
    # The current reading lives in its own projection and survives history retention.
    assert database.count_latest_samples() == 1
    database.dispose()


def test_disabled_deletion_keeps_every_sample(tmp_path: Path) -> None:
    database = _database(tmp_path)
    ids = {_persist(database, number, timedelta(days=100)) for number in range(1, 4)}
    result = _worker(database, telemetry_delete_enabled=False).run_once(now=NOW)
    assert result.telemetry_deleted == 0
    assert _event_ids(database) == ids
    database.dispose()


def test_backlog_is_drained_over_cycles_and_reported(tmp_path: Path) -> None:
    database = _database(tmp_path)
    for number in range(1, 6):
        _persist(database, number, timedelta(days=50))
    worker = _worker(database, batch_size=2, max_batches_per_cycle=2)

    first = worker.run_once(now=NOW)
    assert (first.telemetry_deleted, first.batches, first.backlog_remaining) == (4, 2, True)
    assert worker.next_delay(first) == 300

    second = worker.run_once(now=NOW)
    assert (second.telemetry_deleted, second.backlog_remaining) == (1, False)
    assert worker.next_delay(second) == 3600
    assert database.count_samples() == 0
    database.dispose()


def test_time_budget_ends_the_cycle_with_backlog(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database = _database(tmp_path)
    for number in range(1, 6):
        _persist(database, number, timedelta(days=50))
    clock = iter(float(second) for second in range(0, 1000, 10))
    monkeypatch.setattr(retention_module, "monotonic", lambda: next(clock))
    worker = _worker(database, batch_size=1, cycle_budget_seconds=5.0)

    result = worker.run_once(now=NOW)

    assert (result.batches, result.telemetry_deleted, result.backlog_remaining) == (1, 1, True)
    assert worker.next_delay(result) == 300
    assert database.count_samples() == 4
    database.dispose()


def test_runtime_state_exposes_cycle_observability(tmp_path: Path) -> None:
    database = _database(tmp_path)
    _persist(database, 1, timedelta(days=50))
    state = RuntimeState()
    _worker(database, state=state).run_once(now=NOW)
    snapshot = state.snapshot()
    assert snapshot["retention_deleted_telemetry_total"] == 1
    assert snapshot["retention_last_batches"] == 1
    assert snapshot["retention_backlog_remaining"] is False
    assert snapshot["retention_telemetry_delete_enabled"] is True
    assert snapshot["retention_last_duration_seconds"] >= 0
    database.dispose()


def test_inventory_counts_eligible_and_preserved_without_changes(tmp_path: Path) -> None:
    database = _database(tmp_path)
    linked = _persist(database, 1, timedelta(days=60))
    for number in range(2, 5):
        _persist(database, number, timedelta(days=45))
    _persist(database, 5, timedelta(days=2))
    _link_to_session(database, linked)
    before = _event_ids(database)

    inventory = database.retention_inventory(now=NOW, telemetry_retention_days=30)

    assert (inventory.older_than_cutoff, inventory.eligible, inventory.preserved_session_evidence) == (4, 3, 1)
    assert _event_ids(database) == before
    database.dispose()


def test_dry_run_cli_prints_counts_and_changes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    url = f"sqlite:///{tmp_path / 'cli.db'}"
    database = Database(url)
    database.create_schema()
    old = event(_uuid(1), datetime.now(UTC) - timedelta(days=90))
    assert database.persist(old, old.normalized_payload())
    database.dispose()
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("RETENTION_TELEMETRY_DELETE_ENABLED", "true")

    retention_module.main(["--dry-run"])

    output = json.loads(capsys.readouterr().out)
    assert output["eligible"] == 1
    assert output["telemetry_retention_days"] == 30
    check = Database(url)
    assert check.count_samples() == 1
    check.dispose()
