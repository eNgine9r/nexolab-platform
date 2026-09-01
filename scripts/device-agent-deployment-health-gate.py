#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from typing import Any, Callable, Protocol
from urllib.request import urlopen


class HealthGateError(RuntimeError):
    """Raised when final Device Agent deployment health is not trustworthy."""


class ContainerRuntime(Protocol):
    def list_container_ids(self) -> list[str]: ...

    def inspect_state(self, container_id: str) -> dict[str, Any]: ...


class DockerRuntime:
    def __init__(self, project: str, service: str) -> None:
        self.project = project
        self.service = service

    def _run(self, *args: str) -> str:
        try:
            result = subprocess.run(
                args,
                check=True,
                capture_output=True,
                text=True,
            )
        except (OSError, subprocess.CalledProcessError) as exc:
            raise HealthGateError(f"Docker command failed: {' '.join(args)}") from exc
        return result.stdout

    def list_container_ids(self) -> list[str]:
        output = self._run(
            "docker",
            "ps",
            "-q",
            "--filter",
            f"label=com.docker.compose.project={self.project}",
            "--filter",
            f"label=com.docker.compose.service={self.service}",
        )
        return [line.strip() for line in output.splitlines() if line.strip()]

    def inspect_state(self, container_id: str) -> dict[str, Any]:
        raw = self._run("docker", "inspect", container_id)
        try:
            document = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise HealthGateError("Docker inspect returned invalid JSON") from exc
        if not isinstance(document, list) or len(document) != 1:
            raise HealthGateError("Docker inspect did not return exactly one container")
        state = document[0].get("State")
        if not isinstance(state, dict):
            raise HealthGateError("Docker inspect response is missing State")
        return state


def fetch_health_payload(url: str) -> dict[str, Any]:
    try:
        with urlopen(url, timeout=3) as response:
            payload = json.load(response)
    except Exception as exc:  # urllib exposes several concrete transport errors.
        raise HealthGateError(f"Device Agent health request failed: {url}") from exc
    if not isinstance(payload, dict):
        raise HealthGateError("Device Agent health payload must be a JSON object")
    return payload


def validate_operational_health(payload: dict[str, Any]) -> None:
    status = payload.get("status")
    if status != "ok":
        raise HealthGateError(f"Device Agent operational status is {status!r}, expected 'ok'")
    if payload.get("mqtt_connected") is not True:
        raise HealthGateError("Device Agent MQTT is not connected")

    acquisition = payload.get("acquisition")
    if not isinstance(acquisition, dict):
        raise HealthGateError("Device Agent health payload is missing acquisition state")
    scheduler = acquisition.get("scheduler")
    if scheduler is not None:
        if not isinstance(scheduler, dict):
            raise HealthGateError("Device Agent scheduler health must be an object")
        if scheduler.get("workers_healthy") is not True:
            raise HealthGateError("Device Agent scheduler workers are not healthy")
        expected = scheduler.get("expected_bus_workers")
        active = scheduler.get("active_bus_workers")
        if isinstance(expected, int) and isinstance(active, int) and expected != active:
            raise HealthGateError(
                f"Device Agent active bus workers {active} do not match expected {expected}"
            )


def wait_for_deployment_health(
    runtime: ContainerRuntime,
    *,
    expected_container_id: str,
    health_url: str,
    timeout_seconds: float,
    poll_seconds: float,
    clock: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
    health_fetcher: Callable[[str], dict[str, Any]] = fetch_health_payload,
) -> None:
    if timeout_seconds <= 0 or poll_seconds <= 0:
        raise ValueError("timeout_seconds and poll_seconds must be positive")
    deadline = clock() + timeout_seconds
    last_operational_error: HealthGateError | None = None

    while True:
        container_ids = runtime.list_container_ids()
        if len(container_ids) != 1:
            raise HealthGateError(
                f"expected exactly one running Device Agent container, found {len(container_ids)}"
            )
        if container_ids[0] != expected_container_id:
            raise HealthGateError("Device Agent container changed during health convergence")

        state = runtime.inspect_state(expected_container_id)
        if state.get("Running") is not True:
            raise HealthGateError("Device Agent container is not running")
        health = state.get("Health")
        if not isinstance(health, dict):
            raise HealthGateError("Device Agent container is missing Docker health state")
        health_status = health.get("Status")

        if health_status == "healthy":
            try:
                validate_operational_health(health_fetcher(health_url))
            except HealthGateError as exc:
                last_operational_error = exc
            else:
                return
        elif health_status == "unhealthy":
            raise HealthGateError("Device Agent Docker health is unhealthy")
        elif health_status != "starting":
            raise HealthGateError(f"unsupported Device Agent Docker health {health_status!r}")

        remaining = deadline - clock()
        if remaining <= 0:
            if last_operational_error is not None:
                raise HealthGateError(
                    "Device Agent operational health did not converge before deadline: "
                    f"{last_operational_error}"
                ) from last_operational_error
            raise HealthGateError("Device Agent Docker health did not converge before deadline")
        sleeper(min(poll_seconds, remaining))


def positive_float(value: str) -> float:
    parsed = float(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return parsed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Wait for trustworthy final Device Agent deployment health."
    )
    parser.add_argument("--expected-container-id", required=True)
    parser.add_argument("--project", default="nexolab-edge")
    parser.add_argument("--service", default="device-agent")
    parser.add_argument("--health-url", default="http://127.0.0.1:8081/health")
    parser.add_argument("--timeout-seconds", type=positive_float, default=90.0)
    parser.add_argument("--poll-seconds", type=positive_float, default=2.0)
    args = parser.parse_args(argv)

    runtime = DockerRuntime(args.project, args.service)
    try:
        wait_for_deployment_health(
            runtime,
            expected_container_id=args.expected_container_id,
            health_url=args.health_url,
            timeout_seconds=args.timeout_seconds,
            poll_seconds=args.poll_seconds,
        )
    except (HealthGateError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"device_agent_container={args.expected_container_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
