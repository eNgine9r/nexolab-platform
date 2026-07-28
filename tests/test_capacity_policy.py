from __future__ import annotations

import copy
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from run_capacity_acceptance import event  # noqa: E402
from validate_capacity_policy import PolicyError, validate_policy  # noqa: E402


@pytest.fixture()
def policy() -> dict[str, object]:
    return yaml.safe_load(
        (ROOT / "infrastructure/performance/release-workload.v1.yaml").read_text(
            encoding="utf-8"
        )
    )


def test_release_policy_is_valid(policy: dict[str, object]) -> None:
    assert validate_policy(policy) is policy


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (("topology", "total_streams"), 49, r"nodes \* streams_per_node"),
        (("steady_state", "expected_events"), 2879, "expected_events"),
        (("backlog_replay", "duplicate_replay_events"), 4999, "complete replay"),
        (("rest", "latest", "max_p95_seconds"), 1.1, "must be <= 1.0"),
        (("limits", "max_runtime_seconds"), 3601, "must be <= 3600"),
    ],
)
def test_rejects_weakened_or_inconsistent_policy(
    policy: dict[str, object],
    path: tuple[str, ...],
    value: object,
    message: str,
) -> None:
    candidate = copy.deepcopy(policy)
    current: dict[str, object] = candidate
    for part in path[:-1]:
        current = current[part]  # type: ignore[assignment]
    current[path[-1]] = value
    with pytest.raises(PolicyError, match=message):
        validate_policy(candidate)


def test_rejects_actual_host_capacity_claim(policy: dict[str, object]) -> None:
    candidate = copy.deepcopy(policy)
    candidate["purpose"] = "production host capacity certification"
    with pytest.raises(PolicyError, match="actual-host capacity"):
        validate_policy(candidate)


def test_rejects_unknown_policy_keys(policy: dict[str, object]) -> None:
    candidate = copy.deepcopy(policy)
    candidate["silent_override"] = True
    with pytest.raises(PolicyError, match="unknown top-level"):
        validate_policy(candidate)


def test_generator_covers_all_48_streams(policy: dict[str, object]) -> None:
    generated = [event(policy, "test", index, datetime.now(UTC)) for index in range(48)]
    streams = {(item["node_id"], item["channel_id"]) for item in generated}
    event_ids = {item["event_id"] for item in generated}
    assert len(streams) == 48
    assert len(event_ids) == 48
