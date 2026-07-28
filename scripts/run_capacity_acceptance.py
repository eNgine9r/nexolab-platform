#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
import statistics
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Iterable

import websockets

from validate_capacity_policy import load_policy, validate_policy

NAMESPACE = uuid.UUID("0a156cbc-3cee-4e84-b08d-785bb5903dd9")
REPOSITORY = "eNgine9r/nexolab-platform"


class GateError(RuntimeError):
    pass


def now() -> datetime:
    return datetime.now(UTC)


def iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def percentile(values: list[float], q: float) -> float:
    if not values:
        raise GateError("percentile sample is empty")
    ordered = sorted(values)
    return float(ordered[max(0, math.ceil(q * len(ordered)) - 1)])


def http_json(url: str, timeout: float = 5) -> tuple[int, Any]:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            return exc.code, json.loads(body)
        except json.JSONDecodeError:
            return exc.code, {"body": body}


def http_text(url: str, timeout: float = 5) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", errors="replace")


def wait_for(
    label: str,
    predicate: Callable[[], bool],
    timeout: float,
    interval: float = 0.5,
) -> float:
    started = time.monotonic()
    last_error: Exception | None = None
    while time.monotonic() - started < timeout:
        try:
            if predicate():
                return time.monotonic() - started
        except Exception as exc:  # noqa: BLE001
            last_error = exc
        time.sleep(interval)
    suffix = f"; last error: {last_error}" if last_error else ""
    raise GateError(f"timed out waiting for {label}{suffix}")


@dataclass(frozen=True)
class Runtime:
    project: str
    files: tuple[str, ...]
    postgres_user: str
    postgres_db: str

    def command(self, *args: str) -> list[str]:
        command = ["docker", "compose", "--project-name", self.project]
        for file in self.files:
            command.extend(["--file", file])
        return [*command, *args]

    def run(
        self,
        *args: str,
        check: bool = True,
        timeout: float | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            self.command(*args),
            check=check,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

    def sql(self, statement: str) -> str:
        return self.run(
            "exec",
            "-T",
            "postgres",
            "psql",
            "-v",
            "ON_ERROR_STOP=1",
            "-U",
            self.postgres_user,
            "-d",
            self.postgres_db,
            "-Atq",
            "-c",
            statement,
            timeout=30,
        ).stdout.strip()

    def publish(self, topic: str, lines: Iterable[str], flush_every: int = 250) -> None:
        process = subprocess.Popen(
            self.command(
                "exec",
                "-T",
                "mqtt",
                "mosquitto_pub",
                "-h",
                "mqtt",
                "-q",
                "1",
                "-t",
                topic,
                "-l",
            ),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        assert process.stdin is not None
        try:
            for index, line in enumerate(lines, start=1):
                process.stdin.write(line + "\n")
                if index % flush_every == 0:
                    process.stdin.flush()
            process.stdin.flush()
            process.stdin.close()
            process.stdin = None
            stdout, stderr = process.communicate(timeout=180)
        except Exception:
            process.kill()
            process.wait(timeout=10)
            raise
        if process.returncode:
            raise GateError(f"mosquitto_pub failed: {stderr or stdout}")


class MetricSampler:
    def __init__(self, url: str, capacity: int) -> None:
        self.url = url
        self.capacity = capacity
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.samples: list[dict[str, Any]] = []
        self.errors: list[str] = []

    def _run(self) -> None:
        while not self.stop_event.is_set():
            try:
                status, payload = http_json(self.url, 2)
                if status == 200 and isinstance(payload, dict):
                    size = int(payload.get("queue_size") or 0)
                    self.samples.append(
                        {
                            "at": iso(now()),
                            "queue_size": size,
                            "queue_utilization_ratio": size / self.capacity,
                            "database_ready": bool(payload.get("database_ready")),
                            "websocket_clients": int(payload.get("websocket_clients") or 0),
                        }
                    )
            except Exception as exc:  # noqa: BLE001
                self.errors.append(str(exc))
            self.stop_event.wait(0.1)

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> dict[str, Any]:
        self.stop_event.set()
        self.thread.join(timeout=5)
        return {
            "sample_count": len(self.samples),
            "max_queue_size": max((item["queue_size"] for item in self.samples), default=0),
            "max_queue_utilization_ratio": max(
                (item["queue_utilization_ratio"] for item in self.samples), default=0.0
            ),
            "database_not_ready_observed": any(
                not item["database_ready"] for item in self.samples
            ),
            "max_websocket_clients": max(
                (item["websocket_clients"] for item in self.samples), default=0
            ),
            "sampling_errors": self.errors[-10:],
        }


def event(
    policy: dict[str, Any],
    phase: str,
    index: int,
    captured_at: datetime,
    *,
    sequence: int | None = None,
    equipment: str | None = None,
) -> dict[str, Any]:
    topology = policy["topology"]
    node_index = (index // topology["streams_per_node"]) % topology["nodes"]
    stream_index = index % topology["streams_per_node"]
    node_id = f"{topology['node_prefix']}-{node_index + 1:02d}"
    channel_id = f"{topology['channel_prefix']}-{stream_index + 1:02d}"
    resolved_sequence = index if sequence is None else sequence
    event_id = str(
        uuid.uuid5(NAMESPACE, f"{phase}:{node_id}:{channel_id}:{resolved_sequence}")
    )
    raw_value = 35 + ((node_index * 11 + stream_index * 7 + resolved_sequence) % 45)
    return {
        "event_id": event_id,
        "node_id": node_id,
        "captured_at": iso(captured_at),
        "metric": "temperature.probe",
        "value": raw_value / 10.0,
        "unit": "degC",
        "quality": "valid",
        "source": f"capacity-{phase}",
        "equipment_id": equipment
        or f"{topology['equipment_prefix']}-{node_index + 1:02d}",
        "channel_id": channel_id,
        "alarm": None,
        "raw_value": raw_value,
        "raw_status": None,
        "sequence": resolved_sequence,
        "phase": phase,
    }


def lines(payloads: Iterable[dict[str, Any]]) -> list[str]:
    return [json.dumps(item, separators=(",", ":"), sort_keys=True) for item in payloads]


def metrics(api_url: str) -> tuple[dict[str, Any], str]:
    status, payload = http_json(f"{api_url}/metrics/json")
    if status != 200 or not isinstance(payload, dict):
        raise GateError(f"metrics/json unavailable: {status} {payload}")
    prom_status, prom = http_text(f"{api_url}/metrics")
    if prom_status != 200:
        raise GateError(f"Prometheus metrics unavailable: {prom_status}")
    return payload, prom


def wait_source(runtime: Runtime, source: str, expected: int, timeout: float) -> float:
    escaped = source.replace("'", "''")
    return wait_for(
        f"{expected} rows for {source}",
        lambda: int(
            runtime.sql(
                f"SELECT count(*) FROM telemetry_samples WHERE source = '{escaped}';"
            )
        )
        == expected,
        timeout,
    )


def source_summary(runtime: Runtime, source: str) -> dict[str, Any]:
    escaped = source.replace("'", "''")
    value = runtime.sql(
        f"""
SELECT json_build_object(
  'source', '{escaped}',
  'rows', count(*),
  'unique_event_ids', count(DISTINCT event_id),
  'nodes', count(DISTINCT node_id),
  'streams', count(DISTINCT node_id || '|' || equipment_id || '|' || channel_id || '|' || metric),
  'p50_capture_to_persistence_seconds', COALESCE(percentile_cont(0.50) WITHIN GROUP (ORDER BY GREATEST(0, EXTRACT(EPOCH FROM (received_at - captured_at)))), 0),
  'p95_capture_to_persistence_seconds', COALESCE(percentile_cont(0.95) WITHIN GROUP (ORDER BY GREATEST(0, EXTRACT(EPOCH FROM (received_at - captured_at)))), 0),
  'p99_capture_to_persistence_seconds', COALESCE(percentile_cont(0.99) WITHIN GROUP (ORDER BY GREATEST(0, EXTRACT(EPOCH FROM (received_at - captured_at)))), 0)
)
FROM telemetry_samples WHERE source = '{escaped}';
"""
    )
    return json.loads(value)


def validate_steady_sequences(runtime: Runtime, expected_per_stream: int) -> None:
    invalid = int(
        runtime.sql(
            f"""
SELECT count(*) FROM (
  SELECT node_id, equipment_id, channel_id, metric
  FROM telemetry_samples
  WHERE source = 'capacity-steady'
  GROUP BY node_id, equipment_id, channel_id, metric
  HAVING count(*) <> {expected_per_stream}
     OR count(DISTINCT (raw_payload->>'sequence')::bigint) <> {expected_per_stream}
     OR min((raw_payload->>'sequence')::bigint) <> 0
     OR max((raw_payload->>'sequence')::bigint) <> {expected_per_stream - 1}
) invalid_streams;
"""
        )
    )
    if invalid:
        raise GateError(f"steady sequencing invalid for {invalid} streams")


def publish_steady(runtime: Runtime, topic: str, policy: dict[str, Any]) -> tuple[float, datetime, datetime]:
    steady = policy["steady_state"]
    topology = policy["topology"]
    start = now()
    process = subprocess.Popen(
        runtime.command(
            "exec", "-T", "mqtt", "mosquitto_pub", "-h", "mqtt", "-q", "1", "-t", topic, "-l"
        ),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert process.stdin is not None
    started = time.monotonic()
    try:
        for second in range(steady["duration_seconds"]):
            tick = time.monotonic()
            captured_at = start + timedelta(seconds=second)
            for rate_index in range(steady["events_per_stream_per_second"]):
                sequence = second * steady["events_per_stream_per_second"] + rate_index
                for node in range(topology["nodes"]):
                    for stream in range(topology["streams_per_node"]):
                        index = node * topology["streams_per_node"] + stream
                        payload = event(
                            policy,
                            "steady",
                            index,
                            captured_at,
                            sequence=sequence,
                        )
                        process.stdin.write(json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n")
            process.stdin.flush()
            delay = 1.0 - (time.monotonic() - tick)
            if delay > 0 and second + 1 < steady["duration_seconds"]:
                time.sleep(delay)
        process.stdin.close()
        process.stdin = None
        stdout, stderr = process.communicate(timeout=120)
    except Exception:
        process.kill()
        process.wait(timeout=10)
        raise
    if process.returncode:
        raise GateError(f"steady publisher failed: {stderr or stdout}")
    return time.monotonic() - started, start, start + timedelta(seconds=steady["duration_seconds"])


def validate_collection(payload: Any, minimum: int) -> None:
    if not isinstance(payload, dict):
        raise GateError("REST payload must be an object")
    items = payload.get("items")
    if not isinstance(items, list) or len(items) < minimum:
        raise GateError("REST collection is missing telemetry")
    if payload.get("count") != len(items):
        raise GateError("REST count mismatch")
    required = {"event_id", "node_id", "captured_at", "equipment_id", "channel_id"}
    if any(not isinstance(item, dict) or not required <= set(item) for item in items):
        raise GateError("REST item schema mismatch")


def benchmark(url: str, requests: int, concurrency: int, minimum: int) -> dict[str, Any]:
    def call() -> float:
        started = time.perf_counter()
        status, payload = http_json(url, 10)
        elapsed = time.perf_counter() - started
        if status != 200:
            raise GateError(f"REST request failed: {status} {url}")
        validate_collection(payload, minimum)
        return elapsed

    samples: list[float] = []
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        futures = [executor.submit(call) for _ in range(requests)]
        for future in as_completed(futures):
            samples.append(future.result())
    return {
        "url": url,
        "requests": requests,
        "concurrency": concurrency,
        "errors": 0,
        "p50_seconds": percentile(samples, 0.50),
        "p95_seconds": percentile(samples, 0.95),
        "p99_seconds": percentile(samples, 0.99),
        "max_seconds": max(samples),
        "mean_seconds": statistics.fmean(samples),
    }


async def websocket_gate(
    url: str,
    clients: int,
    expected: set[str],
    connect_timeout: int,
    receive_timeout: int,
    publish: Callable[[], None],
) -> dict[str, Any]:
    ready: asyncio.Queue[int] = asyncio.Queue()
    received: list[set[str]] = [set() for _ in range(clients)]

    async def client(index: int) -> None:
        async with websockets.connect(
            url,
            open_timeout=connect_timeout,
            close_timeout=5,
            ping_interval=None,
            max_queue=max(256, len(expected) * 2),
        ) as socket:
            await ready.put(index)
            deadline = time.monotonic() + receive_timeout
            while received[index] != expected:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise GateError(
                        f"WebSocket client {index} missing {len(expected - received[index])} events"
                    )
                payload = json.loads(await asyncio.wait_for(socket.recv(), remaining))
                event_id = payload.get("event_id")
                if event_id in expected:
                    received[index].add(str(event_id))

    tasks = [asyncio.create_task(client(index)) for index in range(clients)]
    try:
        for _ in range(clients):
            await asyncio.wait_for(ready.get(), connect_timeout)
        started = time.monotonic()
        await asyncio.to_thread(publish)
        await asyncio.gather(*tasks)
        elapsed = time.monotonic() - started
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    return {
        "clients": clients,
        "expected_events_per_client": len(expected),
        "received_events_per_client": [len(value) for value in received],
        "missing_events": sum(len(expected - value) for value in received),
        "delivery_seconds": elapsed,
    }


def collect_resources(runtime: Runtime) -> dict[str, Any]:
    ps = runtime.run("ps", "--all", "--format", "json", check=False)
    ids = runtime.run("ps", "-q", check=False).stdout.split()
    stats: list[Any] = []
    if ids:
        output = subprocess.run(
            ["docker", "stats", "--no-stream", "--format", "{{json .}}", *ids],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        ).stdout
        for line in output.splitlines():
            try:
                stats.append(json.loads(line))
            except json.JSONDecodeError:
                stats.append({"raw": line})
    return {
        "compose_ps": [
            json.loads(line) if line.startswith("{") else {"raw": line}
            for line in ps.stdout.splitlines()
        ],
        "docker_stats": stats,
    }


def sanitize(text: str, secrets: Iterable[str]) -> str:
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[REDACTED]")
    return text


def collect_logs(runtime: Runtime, evidence: Path, secrets: Iterable[str]) -> None:
    ps = runtime.run("ps", "--all", check=False)
    (evidence / "compose-ps.txt").write_text(
        sanitize(ps.stdout + ps.stderr, secrets), encoding="utf-8"
    )
    logs = runtime.run(
        "logs", "--no-color", "telemetry-service", "mqtt", "postgres", check=False, timeout=60
    )
    (evidence / "services.log").write_text(
        sanitize(logs.stdout + logs.stderr, secrets), encoding="utf-8"
    )


def manifest(evidence: Path, policy_path: Path, policy: dict[str, Any], results: dict[str, Any]) -> dict[str, Any]:
    artifacts = []
    for path in sorted(evidence.rglob("*")):
        if path.is_file() and path.name != "release-readiness-manifest.json":
            artifacts.append(
                {
                    "path": path.relative_to(evidence).as_posix(),
                    "sha256": sha256(path),
                    "size_bytes": path.stat().st_size,
                }
            )
    total = sum(item["size_bytes"] for item in artifacts)
    if total > policy["limits"]["max_evidence_bytes"]:
        raise GateError("capacity evidence exceeds configured size limit")
    return {
        "schema_version": 1,
        "repository": REPOSITORY,
        "commit": os.getenv("GITHUB_SHA", "local"),
        "generated_at": iso(now()),
        "policy": {
            "path": policy_path.as_posix(),
            "sha256": sha256(policy_path),
            "schema_version": policy["schema_version"],
        },
        "components": {
            "telemetry_service_image": os.getenv(
                "TELEMETRY_SERVICE_IMAGE", "nexolab-telemetry-service:capacity-acceptance"
            ),
            "postgres_image": "postgres:16-alpine",
            "mqtt_image": "eclipse-mosquitto:2.0.22",
        },
        "gate_references": policy["release_references"],
        "max_evidence_bytes": policy["limits"]["max_evidence_bytes"],
        "results": {
            "status": "passed",
            "steady_events": results["steady_state"]["database"]["rows"],
            "replay_events": results["backlog_replay"]["database"]["rows"],
            "websocket_clients": results["websocket"]["clients"],
            "failure_recovered": results["failure_recovery"]["recovered"],
        },
        "artifacts": artifacts,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run NEXOLAB capacity acceptance")
    parser.add_argument("--policy", default="infrastructure/performance/release-workload.v1.yaml")
    parser.add_argument("--evidence-dir", default="test-results-capacity")
    parser.add_argument("--api-url", default="http://127.0.0.1:18083")
    parser.add_argument("--mqtt-topic", default="nexolab/telemetry")
    parser.add_argument("--compose-project", required=True)
    parser.add_argument("--compose-file", action="append", required=True)
    args = parser.parse_args()

    policy_path = Path(args.policy)
    policy = validate_policy(load_policy(policy_path))
    evidence = Path(args.evidence_dir)
    evidence.mkdir(parents=True, exist_ok=True)
    for path in evidence.iterdir():
        if path.is_file() or path.is_symlink():
            path.unlink()
        else:
            import shutil

            shutil.rmtree(path)

    runtime = Runtime(
        args.compose_project,
        tuple(args.compose_file),
        os.getenv("POSTGRES_USER", "nexolab"),
        os.getenv("POSTGRES_DB", "nexolab"),
    )
    api = args.api_url.rstrip("/")
    metrics_url = f"{api}/metrics/json"
    gate_started = time.monotonic()
    results: dict[str, Any] = {
        "schema_version": 1,
        "repository": REPOSITORY,
        "commit": os.getenv("GITHUB_SHA", "local"),
        "started_at": iso(now()),
    }

    initial, initial_prom = metrics(api)
    (evidence / "metrics-before.prom").write_text(initial_prom, encoding="utf-8")
    if int(runtime.sql("SELECT count(*) FROM telemetry_samples;")) != 0:
        raise GateError("capacity Gate requires a fresh PostgreSQL volume")

    steady = policy["steady_state"]
    sampler = MetricSampler(metrics_url, policy["limits"]["ingestion_queue_capacity"])
    sampler.start()
    publish_seconds, steady_start, steady_end = publish_steady(runtime, args.mqtt_topic, policy)
    wait_seconds = wait_source(runtime, "capacity-steady", steady["expected_events"], 120)
    steady_sampling = sampler.stop()
    steady_db = source_summary(runtime, "capacity-steady")
    validate_steady_sequences(
        runtime, steady["duration_seconds"] * steady["events_per_stream_per_second"]
    )
    if steady_db["rows"] != steady["expected_events"] or steady_db["unique_event_ids"] != steady["expected_events"]:
        raise GateError("steady count or uniqueness mismatch")
    if steady_db["nodes"] != policy["topology"]["nodes"] or steady_db["streams"] != policy["topology"]["total_streams"]:
        raise GateError("steady topology mismatch")
    if float(steady_db["p95_capture_to_persistence_seconds"]) > steady["max_p95_capture_to_persistence_seconds"]:
        raise GateError("steady p95 threshold exceeded")
    if steady_sampling["max_queue_utilization_ratio"] >= steady["max_queue_utilization_ratio"]:
        raise GateError("steady queue utilization threshold exceeded")
    after_steady, _ = metrics(api)
    steady_delta = {
        key: int(after_steady.get(key, 0)) - int(initial.get(key, 0))
        for key in (
            "received_total", "accepted_total", "persisted_total", "duplicate_total",
            "rejected_total", "queue_dropped_total", "dead_letter_persisted_total",
            "persistence_failure_total",
        )
    }
    if steady_delta["persisted_total"] != steady["expected_events"]:
        raise GateError("steady persisted metric mismatch")
    for key in ("duplicate_total", "rejected_total", "queue_dropped_total", "dead_letter_persisted_total", "persistence_failure_total"):
        if steady_delta[key]:
            raise GateError(f"steady counter must remain zero: {key}")
    results["steady_state"] = {
        "window": {"from": iso(steady_start), "to": iso(steady_end)},
        "publish_seconds": publish_seconds,
        "persistence_wait_seconds": wait_seconds,
        "database": steady_db,
        "metrics_delta": steady_delta,
        "sampling": steady_sampling,
    }

    replay = policy["backlog_replay"]
    replay_payloads = [
        event(policy, "replay", index, now() + timedelta(milliseconds=index), sequence=100_000 + index)
        for index in range(replay["events"])
    ]
    replay_lines = lines(replay_payloads)
    sampler = MetricSampler(metrics_url, policy["limits"]["ingestion_queue_capacity"])
    sampler.start()
    replay_started = time.monotonic()
    runtime.publish(args.mqtt_topic, replay_lines, replay["publish_batch_size"])
    replay_publish = time.monotonic() - replay_started
    replay_drain = wait_source(runtime, "capacity-replay", replay["events"], replay["max_drain_seconds"])
    replay_sampling = sampler.stop()
    replay_db = source_summary(runtime, "capacity-replay")
    if replay_db["rows"] != replay["events"] or replay_db["unique_event_ids"] != replay["events"]:
        raise GateError("replay count or uniqueness mismatch")
    if replay_db["nodes"] != policy["topology"]["nodes"]:
        raise GateError("replay node topology mismatch")
    if replay_sampling["max_queue_size"] > policy["limits"]["ingestion_queue_capacity"]:
        raise GateError("replay exceeded queue capacity")

    before_duplicate, _ = metrics(api)
    rows_before = int(runtime.sql("SELECT count(*) FROM telemetry_samples;"))
    duplicate_started = time.monotonic()
    runtime.publish(args.mqtt_topic, replay_lines, replay["publish_batch_size"])
    wait_for(
        "duplicate replay accounting",
        lambda: int(http_json(metrics_url, 3)[1].get("duplicate_total", 0))
        - int(before_duplicate.get("duplicate_total", 0))
        >= replay["duplicate_replay_events"],
        replay["max_drain_seconds"],
    )
    after_duplicate, _ = metrics(api)
    rows_after = int(runtime.sql("SELECT count(*) FROM telemetry_samples;"))
    duplicate_delta = int(after_duplicate["duplicate_total"]) - int(before_duplicate["duplicate_total"])
    if rows_after != rows_before or duplicate_delta != replay["duplicate_replay_events"]:
        raise GateError("complete duplicate replay was not idempotent")
    results["backlog_replay"] = {
        "publish_seconds": replay_publish,
        "drain_seconds": replay_drain,
        "database": replay_db,
        "sampling": replay_sampling,
        "duplicate_replay": {
            "events": replay["duplicate_replay_events"],
            "total_seconds": time.monotonic() - duplicate_started,
            "duplicate_metric_delta": duplicate_delta,
            "rows_before": rows_before,
            "rows_after": rows_after,
        },
    }

    rest = policy["rest"]
    latest_url = f"{api}/api/v1/telemetry/latest?{urllib.parse.urlencode({'limit': rest['latest']['limit']})}"
    history_url = f"{api}/api/v1/telemetry/history?{urllib.parse.urlencode({'from': iso(steady_start - timedelta(seconds=1)), 'to': iso(now() + timedelta(seconds=1)), 'limit': rest['history']['limit']})}"
    rest_results = {
        "latest": benchmark(latest_url, rest["latest"]["requests"], rest["latest"]["concurrency"], 48),
        "history": benchmark(history_url, rest["history"]["requests"], rest["history"]["concurrency"], 1),
    }
    if rest_results["latest"]["p95_seconds"] > rest["latest"]["max_p95_seconds"]:
        raise GateError("REST latest p95 threshold exceeded")
    if rest_results["history"]["p95_seconds"] > rest["history"]["max_p95_seconds"]:
        raise GateError("REST history p95 threshold exceeded")
    write_json(evidence / "rest-latencies.json", rest_results)
    results["rest"] = rest_results

    ws = policy["websocket"]
    ws_payloads = [
        event(policy, "websocket", index, now() + timedelta(milliseconds=index), sequence=200_000 + index, equipment="capacity-ws-equipment")
        for index in range(ws["events"])
    ]
    ws_lines = lines(ws_payloads)
    expected_ids = {item["event_id"] for item in ws_payloads}
    ws_before, _ = metrics(api)
    ws_url = api.replace("http://", "ws://").replace("https://", "wss://") + "/api/v1/telemetry/live?equipment_id=capacity-ws-equipment"
    ws_result = asyncio.run(
        websocket_gate(
            ws_url,
            ws["clients"],
            expected_ids,
            ws["connect_timeout_seconds"],
            ws["receive_timeout_seconds"],
            lambda: runtime.publish(args.mqtt_topic, ws_lines),
        )
    )
    wait_source(runtime, "capacity-websocket", ws["events"], 60)
    ws_after, _ = metrics(api)
    ws_result["metric_deltas"] = {
        key: int(ws_after.get(key, 0)) - int(ws_before.get(key, 0))
        for key in (
            "websocket_connect_total", "websocket_disconnect_total",
            "websocket_slow_consumer_total", "websocket_send_timeout_total",
        )
    }
    if ws_result["missing_events"] or ws_result["metric_deltas"]["websocket_slow_consumer_total"] or ws_result["metric_deltas"]["websocket_send_timeout_total"]:
        raise GateError("WebSocket fan-out contract failed")
    write_json(evidence / "websocket-summary.json", ws_result)
    results["websocket"] = ws_result

    recovery = policy["failure_recovery"]
    recovery_before, _ = metrics(api)
    sampler = MetricSampler(metrics_url, policy["limits"]["ingestion_queue_capacity"])
    sampler.start()
    runtime.run("stop", "-t", "5", recovery["dependency"], timeout=30)
    outage_payloads = [
        event(policy, "outage", index, now() + timedelta(milliseconds=index), sequence=300_000 + index)
        for index in range(recovery["events_during_outage"])
    ]
    runtime.publish(args.mqtt_topic, lines(outage_payloads))

    def outage_visible() -> bool:
        status, payload = http_json(metrics_url, 3)
        ready, _ = http_json(f"{api}/health/ready", 3)
        return status == 200 and not payload.get("database_ready") and int(payload.get("queue_size", 0)) > 0 and ready == 503

    detection = wait_for("database outage readiness", outage_visible, 30)
    time.sleep(recovery["outage_seconds"])
    restart_started = time.monotonic()
    runtime.run("start", recovery["dependency"], timeout=30)
    live_payloads = [
        event(policy, "recovery-live", index, now() + timedelta(milliseconds=index), sequence=400_000 + index)
        for index in range(recovery["live_events_after_restart"])
    ]
    runtime.publish(args.mqtt_topic, lines(live_payloads))
    outage_drain = wait_source(runtime, "capacity-outage", recovery["events_during_outage"], recovery["max_recovery_seconds"])
    live_drain = wait_source(runtime, "capacity-recovery-live", recovery["live_events_after_restart"], recovery["max_recovery_seconds"])
    ready_seconds = wait_for(
        "healthy readiness after recovery",
        lambda: http_json(f"{api}/health/ready", 3)[0] == 200,
        recovery["max_recovery_seconds"],
    )
    total_recovery = time.monotonic() - restart_started
    recovery_sampling = sampler.stop()
    recovery_after, _ = metrics(api)
    recovery_delta = {
        key: int(recovery_after.get(key, 0)) - int(recovery_before.get(key, 0))
        for key in (
            "accepted_total", "persisted_total", "duplicate_total", "rejected_total",
            "queue_dropped_total", "dead_letter_persisted_total", "persistence_failure_total",
            "database_retry_total", "database_recovery_total",
        )
    }
    expected_recovery = recovery["events_during_outage"] + recovery["live_events_after_restart"]
    if recovery_delta["persisted_total"] != expected_recovery:
        raise GateError("recovery persisted count mismatch")
    for key in ("duplicate_total", "rejected_total", "queue_dropped_total", "dead_letter_persisted_total"):
        if recovery_delta[key]:
            raise GateError(f"recovery counter must remain zero: {key}")
    if not 0 < recovery_delta["database_retry_total"] <= 50:
        raise GateError("database retry behavior is missing or uncontrolled")
    if total_recovery > recovery["max_recovery_seconds"]:
        raise GateError("database recovery threshold exceeded")
    failure = {
        "dependency": recovery["dependency"],
        "outage_detection_seconds": detection,
        "configured_outage_seconds": recovery["outage_seconds"],
        "outage_drain_seconds": outage_drain,
        "live_drain_seconds": live_drain,
        "readiness_recovery_seconds": ready_seconds,
        "total_recovery_seconds": total_recovery,
        "events_during_outage": recovery["events_during_outage"],
        "live_events_after_restart": recovery["live_events_after_restart"],
        "metrics_delta": recovery_delta,
        "sampling": recovery_sampling,
        "recovered": True,
    }
    write_json(evidence / "failure-recovery.json", failure)
    results["failure_recovery"] = failure

    final, final_prom = metrics(api)
    (evidence / "metrics-after.prom").write_text(final_prom, encoding="utf-8")
    database = json.loads(
        runtime.sql(
            """
SELECT json_build_object(
  'rows', (SELECT count(*) FROM telemetry_samples),
  'unique_event_ids', (SELECT count(DISTINCT event_id) FROM telemetry_samples),
  'dead_letters', (SELECT count(*) FROM telemetry_dead_letters),
  'capacity_rows', (SELECT count(*) FROM telemetry_samples WHERE source LIKE 'capacity-%'),
  'capacity_sources', (SELECT count(DISTINCT source) FROM telemetry_samples WHERE source LIKE 'capacity-%')
);
"""
        )
    )
    expected_unique = steady["expected_events"] + replay["events"] + ws["events"] + expected_recovery
    if database["capacity_rows"] != expected_unique or database["rows"] != database["unique_event_ids"]:
        raise GateError("final PostgreSQL count or uniqueness mismatch")
    if database["dead_letters"] or int(final.get("queue_size", 0)) or int(final.get("queue_dropped_total", 0)) or int(final.get("dead_letter_persisted_total", 0)):
        raise GateError("final no-loss invariants failed")
    write_json(evidence / "database-summary.json", database)
    write_json(evidence / "resource-observations.json", collect_resources(runtime))

    results["database"] = database
    results["final_metrics"] = final
    results["duration_seconds"] = time.monotonic() - gate_started
    results["completed_at"] = iso(now())
    results["status"] = "passed"
    if results["duration_seconds"] > policy["limits"]["max_runtime_seconds"]:
        raise GateError("capacity Gate exceeded maximum runtime")
    write_json(evidence / "results.json", results)

    secrets = (os.getenv("POSTGRES_PASSWORD", ""), os.getenv("MINIO_ROOT_PASSWORD", ""))
    collect_logs(runtime, evidence, secrets)
    write_json(evidence / "release-readiness-manifest.json", manifest(evidence, policy_path, policy, results))
    print(
        f"Capacity acceptance passed: unique_events={expected_unique} "
        f"duration={results['duration_seconds']:.1f}s"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
