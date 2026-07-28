#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import yaml


class PolicyError(ValueError):
    pass


def _mapping(value: object, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PolicyError(f"{path} must be a mapping")
    return value


def _integer(
    mapping: dict[str, Any],
    key: str,
    path: str,
    *,
    minimum: int = 1,
    maximum: int | None = None,
) -> int:
    value = mapping.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise PolicyError(f"{path}.{key} must be an integer")
    if value < minimum:
        raise PolicyError(f"{path}.{key} must be >= {minimum}")
    if maximum is not None and value > maximum:
        raise PolicyError(f"{path}.{key} must be <= {maximum}")
    return value


def _number(
    mapping: dict[str, Any],
    key: str,
    path: str,
    *,
    minimum: float,
    maximum: float | None = None,
) -> float:
    value = mapping.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PolicyError(f"{path}.{key} must be numeric")
    parsed = float(value)
    if parsed < minimum:
        raise PolicyError(f"{path}.{key} must be >= {minimum}")
    if maximum is not None and parsed > maximum:
        raise PolicyError(f"{path}.{key} must be <= {maximum}")
    return parsed


def _text(mapping: dict[str, Any], key: str, path: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise PolicyError(f"{path}.{key} must be a non-empty string")
    return value.strip()


def load_policy(path: Path) -> dict[str, Any]:
    try:
        parsed = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise PolicyError(f"unable to load policy {path}: {exc}") from exc
    return _mapping(parsed, "policy")


def validate_policy(policy: dict[str, Any]) -> dict[str, Any]:
    allowed_top_level = {
        "schema_version",
        "name",
        "purpose",
        "topology",
        "steady_state",
        "backlog_replay",
        "rest",
        "websocket",
        "failure_recovery",
        "limits",
        "release_references",
    }
    unknown = sorted(set(policy) - allowed_top_level)
    if unknown:
        raise PolicyError(f"unknown top-level policy keys: {unknown}")

    if policy.get("schema_version") != 1:
        raise PolicyError("schema_version must equal 1")
    _text(policy, "name", "policy")
    purpose = _text(policy, "purpose", "policy")
    if "not an actual-host capacity claim" not in purpose:
        raise PolicyError("purpose must explicitly reject actual-host capacity claims")

    topology = _mapping(policy.get("topology"), "topology")
    nodes = _integer(topology, "nodes", "topology", minimum=6, maximum=32)
    streams_per_node = _integer(
        topology, "streams_per_node", "topology", minimum=1, maximum=64
    )
    total_streams = _integer(
        topology, "total_streams", "topology", minimum=48, maximum=2048
    )
    if nodes * streams_per_node != total_streams:
        raise PolicyError("topology.total_streams must equal nodes * streams_per_node")
    for key in ("node_prefix", "equipment_prefix", "channel_prefix"):
        _text(topology, key, "topology")

    steady = _mapping(policy.get("steady_state"), "steady_state")
    duration = _integer(
        steady, "duration_seconds", "steady_state", minimum=10, maximum=300
    )
    rate = _integer(
        steady,
        "events_per_stream_per_second",
        "steady_state",
        minimum=1,
        maximum=20,
    )
    expected = _integer(
        steady, "expected_events", "steady_state", minimum=1, maximum=100_000
    )
    computed_expected = total_streams * duration * rate
    if expected != computed_expected:
        raise PolicyError(
            "steady_state.expected_events must equal "
            "total_streams * duration_seconds * events_per_stream_per_second"
        )
    _number(
        steady,
        "max_p95_capture_to_persistence_seconds",
        "steady_state",
        minimum=0.1,
        maximum=10.0,
    )
    queue_ratio = _number(
        steady,
        "max_queue_utilization_ratio",
        "steady_state",
        minimum=0.01,
        maximum=0.95,
    )
    if queue_ratio >= 0.95:
        raise PolicyError("steady_state queue utilization must preserve headroom")

    replay = _mapping(policy.get("backlog_replay"), "backlog_replay")
    replay_events = _integer(
        replay, "events", "backlog_replay", minimum=5000, maximum=50_000
    )
    batch_size = _integer(
        replay,
        "publish_batch_size",
        "backlog_replay",
        minimum=1,
        maximum=2000,
    )
    if batch_size > replay_events:
        raise PolicyError("backlog_replay.publish_batch_size exceeds replay events")
    _integer(
        replay,
        "max_drain_seconds",
        "backlog_replay",
        minimum=10,
        maximum=300,
    )
    duplicate_replay = _integer(
        replay,
        "duplicate_replay_events",
        "backlog_replay",
        minimum=1,
        maximum=replay_events,
    )
    if duplicate_replay != replay_events:
        raise PolicyError("duplicate replay must cover the complete replay event set")

    rest = _mapping(policy.get("rest"), "rest")
    for endpoint, minimum_requests, max_threshold in (
        ("latest", 20, 1.0),
        ("history", 20, 2.0),
    ):
        section = _mapping(rest.get(endpoint), f"rest.{endpoint}")
        concurrency = _integer(
            section,
            "concurrency",
            f"rest.{endpoint}",
            minimum=2,
            maximum=64,
        )
        requests = _integer(
            section,
            "requests",
            f"rest.{endpoint}",
            minimum=minimum_requests,
            maximum=5000,
        )
        if requests < concurrency:
            raise PolicyError(f"rest.{endpoint}.requests must cover every worker")
        _integer(section, "limit", f"rest.{endpoint}", minimum=1, maximum=1000)
        threshold = _number(
            section,
            "max_p95_seconds",
            f"rest.{endpoint}",
            minimum=0.05,
            maximum=max_threshold,
        )
        if threshold > max_threshold:
            raise PolicyError(f"rest.{endpoint} p95 threshold is too weak")

    websocket = _mapping(policy.get("websocket"), "websocket")
    clients = _integer(websocket, "clients", "websocket", minimum=20, maximum=100)
    ws_events = _integer(websocket, "events", "websocket", minimum=48, maximum=1000)
    if ws_events < clients:
        raise PolicyError("websocket.events must be at least websocket.clients")
    _integer(
        websocket,
        "connect_timeout_seconds",
        "websocket",
        minimum=5,
        maximum=60,
    )
    _integer(
        websocket,
        "receive_timeout_seconds",
        "websocket",
        minimum=5,
        maximum=120,
    )

    recovery = _mapping(policy.get("failure_recovery"), "failure_recovery")
    if _text(recovery, "dependency", "failure_recovery") != "postgres":
        raise PolicyError("failure_recovery.dependency must be postgres")
    _integer(
        recovery,
        "outage_seconds",
        "failure_recovery",
        minimum=3,
        maximum=30,
    )
    outage_events = _integer(
        recovery,
        "events_during_outage",
        "failure_recovery",
        minimum=48,
        maximum=5000,
    )
    live_recovery_events = _integer(
        recovery,
        "live_events_after_restart",
        "failure_recovery",
        minimum=1,
        maximum=1000,
    )
    _integer(
        recovery,
        "max_recovery_seconds",
        "failure_recovery",
        minimum=10,
        maximum=300,
    )

    limits = _mapping(policy.get("limits"), "limits")
    max_events = _integer(
        limits,
        "max_total_generated_events",
        "limits",
        minimum=(
            expected
            + replay_events
            + duplicate_replay
            + ws_events
            + outage_events
            + live_recovery_events
        ),
        maximum=100_000,
    )
    generated = (
        expected
        + replay_events
        + duplicate_replay
        + ws_events
        + outage_events
        + live_recovery_events
    )
    if generated > max_events:
        raise PolicyError("configured phases exceed max_total_generated_events")
    _integer(
        limits,
        "max_runtime_seconds",
        "limits",
        minimum=duration + 60,
        maximum=3600,
    )
    _integer(
        limits,
        "max_evidence_bytes",
        "limits",
        minimum=1_048_576,
        maximum=104_857_600,
    )
    queue_capacity = _integer(
        limits,
        "ingestion_queue_capacity",
        "limits",
        minimum=max(outage_events, batch_size),
        maximum=100_000,
    )
    if replay_events > queue_capacity * 5:
        raise PolicyError("replay workload is disproportionate to queue capacity")
    _integer(
        limits,
        "websocket_client_queue_capacity",
        "limits",
        minimum=ws_events,
        maximum=10_000,
    )

    references = _mapping(policy.get("release_references"), "release_references")
    for key in (
        "supply_chain_workflow",
        "disaster_recovery_workflow",
        "observability_workflow",
    ):
        _text(references, key, "release_references")

    return policy


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate NEXOLAB capacity policy")
    parser.add_argument(
        "policy",
        nargs="?",
        default="infrastructure/performance/release-workload.v1.yaml",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    try:
        policy = validate_policy(load_policy(Path(args.policy)))
    except PolicyError as exc:
        print(f"capacity policy invalid: {exc}")
        return 1

    if args.json:
        print(json.dumps(policy, indent=2, sort_keys=True))
    else:
        steady = policy["steady_state"]
        replay = policy["backlog_replay"]
        print(
            "capacity policy valid: "
            f"streams={policy['topology']['total_streams']} "
            f"steady_events={steady['expected_events']} "
            f"replay_events={replay['events']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
