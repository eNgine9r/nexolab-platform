import csv
import json
import threading
import time
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import insert

from app.contracts import TelemetryEvent
from app.db import TelemetrySample
from app.energy_export.jobs import ExportJobs, ExportPolicy, _mutate
from app.energy_export.schemas import ExportError, ExportOptions
from app.ingestion import TelemetryIngestor
from app.state import RuntimeState
from tests.live_dashboard_test_support import ORG_A
from tests.test_energy_export_source import BASE, source_fixture


OWNER = (ORG_A, "isolated-test", "owner", "identity")


def wait_job(jobs, job_id, wanted, *, timeout=90):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = jobs.get(OWNER, job_id)
        if value["status"] == wanted:
            return value
        assert value["status"] not in {"failed", "expired", "canceled"}, value
        time.sleep(0.02)
    raise AssertionError(f"Export did not become {wanted}")


def test_more_than_100000_original_events_and_ingestion_advances(tmp_path):
    database, original = source_fixture(tmp_path)
    count = 100001
    series = original.series[0]
    for offset in range(0, count, 1000):
        rows = [{"event_id": f"00000000-0000-0000-0000-{index:012}", "node_id": series.node_id, "equipment_id": series.equipment_id, "channel_id": series.channel_id, "metric": series.metric, "unit": series.unit,
                 "captured_at": BASE + timedelta(seconds=index * 5), "received_at": BASE, "value": 220 + index % 5, "quality": "valid", "source": "isolated-large-fixture", "raw_payload": {}}
                for index in range(offset, min(count, offset + 1000))]
        with database.engine.begin() as connection:
            connection.execute(insert(TelemetrySample), rows)
    options = ExportOptions(**{**original.model_dump(), "to_at": BASE + timedelta(days=7), "format": "csv"})
    jobs = ExportJobs(database, tmp_path / "exports", policy=ExportPolicy(reserve_bytes=1024 * 1024))
    state = RuntimeState()
    ingestor = TelemetryIngestor(database, state, queue_maxsize=100)
    ingestor.start()
    submitted = []
    try:
        job_id = jobs.create(OWNER, options)["job_id"]
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            value = jobs.get(OWNER, job_id)
            if value["status"] == "running" and value["progress"]["processed"] >= 1000:
                break
            assert value["status"] not in {"failed", "expired"}, value
            time.sleep(0.02)
        else:
            raise AssertionError("Did not observe active source extraction")
        for index in range(20):
            event = TelemetryEvent(event_id=uuid4(), **series.model_dump(), captured_at=BASE + timedelta(seconds=42), value=999, quality="valid", source="isolated-concurrent-ingestion")
            submitted.append(ingestor.submit_payload(json.dumps(event.normalized_payload()).encode()))
            time.sleep(0.01)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and state.snapshot()["persisted_total"] < 20:
            time.sleep(0.02)
        assert all(submitted) and state.snapshot()["persisted_total"] == 20
        assert jobs.get(OWNER, job_id)["status"] == "running"  # Collection advanced during the scan.
        prepared = wait_job(jobs, job_id, "preview_ready")
        assert prepared["preview"]["source_events"] == count + 4
        assert prepared["preview"]["output_rows"] == count + 4
        jobs.confirm(OWNER, job_id)
        ready = wait_job(jobs, job_id, "ready")
        token = jobs.ticket(OWNER, job_id)["ticket"]
        path, _, _ = jobs.consume_ticket(job_id, token)
        actual_count = 0
        value_sum = 0
        with path.open(encoding="utf-8", newline="") as stream:
            for row in csv.DictReader(stream):
                actual_count += 1; value_sum += float(row["U, V"])
        assert actual_count == count + 4 == ready["artifact"]["output_rows"]
        assert value_sum == sum(220 + index % 5 for index in range(count)) + 911
        assert state.snapshot()["persisted_total"] == 20
    finally:
        jobs.stop(); ingestor.stop(); database.dispose()


def test_restart_preserves_prepared_snapshot_and_fails_interrupted_job(tmp_path):
    database, options = source_fixture(tmp_path)
    jobs = ExportJobs(database, tmp_path / "exports", policy=ExportPolicy(reserve_bytes=1024 * 1024))
    successor = None
    try:
        job_id = jobs.create(OWNER, options)["job_id"]
        wait_job(jobs, job_id, "preview_ready")
        time.sleep(0.25)
        jobs.stop()
        successor = ExportJobs(database, jobs.root, policy=jobs.policy)
        successor.start()
        assert successor.get(OWNER, job_id)["status"] == "preview_ready"
        successor.confirm(OWNER, job_id)
        wait_job(successor, job_id, "ready")
        successor.stop()
        _mutate(jobs.root / job_id, {"status": "running", "phase": "render"})
        restarted = ExportJobs(database, jobs.root, policy=jobs.policy)
        successor = restarted; restarted.start()
        assert restarted.get(OWNER, job_id)["status"] == "failed"
        assert restarted.get(OWNER, job_id)["error"]["code"] == "interrupted"
        assert not (jobs.root / job_id / "source.sqlite").exists()
    finally:
        jobs.stop()
        if successor is not None:
            successor.stop()
        database.dispose()


def test_disk_capacity_rejection_and_owner_limit_are_explicit(tmp_path, monkeypatch):
    database, options = source_fixture(tmp_path)
    jobs = ExportJobs(database, tmp_path / "exports", policy=ExportPolicy(reserve_bytes=1024 * 1024))
    try:
        import shutil
        original = shutil.disk_usage
        monkeypatch.setattr(shutil, "disk_usage", lambda _: type(original(tmp_path))(total=1000, used=999, free=1))
        with pytest.raises(ExportError, match="вільного місця"):
            jobs.create(OWNER, options)
        monkeypatch.setattr(shutil, "disk_usage", original)
        for _ in range(2):
            wait_job(jobs, jobs.create(OWNER, options)["job_id"], "preview_ready")
        with pytest.raises(ExportError, match="незавершені"):
            jobs.create(OWNER, options)
    finally:
        jobs.stop(); database.dispose()


def test_canceled_records_cannot_exhaust_shared_manifest_capacity(tmp_path):
    database, options = source_fixture(tmp_path)
    jobs = ExportJobs(database, tmp_path / "exports", policy=ExportPolicy(max_records=3, reserve_bytes=1024 * 1024))
    try:
        for _ in range(15):
            job_id = jobs.create(OWNER, options)["job_id"]
            jobs.cancel(OWNER, job_id)
            assert len(list(jobs.root.glob("*/manifest.json"))) <= jobs.policy.max_records
        other_owner = (ORG_A, "isolated-test", "other-reader", "other-identity")
        job_id = jobs.create(other_owner, options)["job_id"]
        assert jobs.get(other_owner, job_id)["status"] in {"queued", "running"}
    finally:
        jobs.stop(); database.dispose()


def test_manifest_reclamation_preserves_prepared_snapshots(tmp_path):
    database, options = source_fixture(tmp_path)
    jobs = ExportJobs(database, tmp_path / "exports", policy=ExportPolicy(max_records=2, reserve_bytes=1024 * 1024))
    try:
        prepared_id = jobs.create(OWNER, options)["job_id"]
        wait_job(jobs, prepared_id, "preview_ready")
        canceled_id = jobs.create(OWNER, options)["job_id"]
        jobs.cancel(OWNER, canceled_id)
        successor_id = jobs.create(OWNER, options)["job_id"]
        assert jobs.get(OWNER, prepared_id)["status"] == "preview_ready"
        assert (jobs.root / prepared_id / "source.sqlite").is_file()
        assert jobs.get(OWNER, successor_id)["status"] in {"queued", "running"}
        with pytest.raises(ExportError, match="Черга"):
            jobs.create((ORG_A, "isolated-test", "third", "third"), options)
    finally:
        jobs.stop(); database.dispose()
