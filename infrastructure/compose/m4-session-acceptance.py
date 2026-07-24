#!/usr/bin/env python3
"""Two-phase M4 real-hardware session recovery acceptance harness.

This harness is intentionally destructive only to service availability: it restarts
containers and temporarily stops the central MQTT broker. It never runs Docker
Compose with ``down --volumes`` and never writes Modbus registers.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent
CENTRAL_COMPOSE_FILE = SCRIPT_DIR / "compose.central.yaml"
EDGE_COMPOSE_FILES = (
    SCRIPT_DIR / "compose.edge.yaml",
    SCRIPT_DIR / "compose.hardware.yaml",
    SCRIPT_DIR / "compose.edge-central-bridge.yaml",
)
EXPECTED_VOLUME_NAMES = (
    "nexolab-central-postgres-data",
    "nexolab-central-mqtt-data",
    "nexolab-edge_edge-data",
    "nexolab-edge_mqtt-data",
)
SCREENSHOT_NAMES = (
    "01-sessions-list.png",
    "02-running-session.png",
    "03-completed-session.png",
)


class AcceptanceFailure(RuntimeError):
    pass


def utc_now() -> datetime:
    return datetime.now(UTC)


def iso_now() -> str:
    return utc_now().isoformat()


def load_env(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise AcceptanceFailure(f"missing environment file: {path}")
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def run(
    command: list[str],
    *,
    check: bool = True,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        check=False,
        text=True,
        capture_output=True,
        cwd=cwd,
        env=env,
    )
    if check and result.returncode != 0:
        raise AcceptanceFailure(
            f"command failed ({result.returncode}): {' '.join(command)}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def stable_hash(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def wait_for(
    description: str,
    predicate: Callable[[], bool],
    *,
    timeout: float = 180.0,
    interval: float = 2.0,
) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            if predicate():
                return
        except Exception as error:  # noqa: BLE001 - evidence loop records transient failures
            last_error = error
        time.sleep(interval)
    suffix = f": {last_error}" if last_error else ""
    raise AcceptanceFailure(f"timed out waiting for {description}{suffix}")


class ApiClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def request(
        self,
        method: str,
        path: str,
        *,
        body: object | None = None,
        idempotency_key: str | None = None,
        query: dict[str, object] | None = None,
        expected_status: int = 200,
    ) -> object:
        url = f"{self.base_url}{path}"
        if query:
            url = f"{url}?{urlencode({key: value for key, value in query.items() if value is not None})}"
        payload = None if body is None else json.dumps(body).encode()
        headers = {"Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        request = Request(url, data=payload, headers=headers, method=method)
        try:
            with urlopen(request, timeout=15) as response:
                status = response.status
                raw = response.read()
        except HTTPError as error:
            status = error.code
            raw = error.read()
        except URLError as error:
            raise AcceptanceFailure(f"request failed: {method} {url}: {error}") from error
        parsed: object = json.loads(raw) if raw else None
        if status != expected_status:
            raise AcceptanceFailure(
                f"unexpected response {status} for {method} {url}; expected {expected_status}: {parsed}"
            )
        return parsed

    def get(self, path: str, **query: object) -> object:
        return self.request("GET", path, query=query)

    def post(self, path: str, body: object, key: str, expected_status: int = 200) -> object:
        return self.request(
            "POST",
            path,
            body=body,
            idempotency_key=key,
            expected_status=expected_status,
        )


class Harness:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.central_env = Path(args.central_env).resolve()
        self.edge_env = Path(args.edge_env).resolve()
        self.central_values = load_env(self.central_env)
        self.edge_values = load_env(self.edge_env)
        bind_address = self.central_values.get("CENTRAL_BIND_ADDRESS", "127.0.0.1")
        if bind_address in {"0.0.0.0", "::"}:
            bind_address = "127.0.0.1"
        api_port = self.central_values.get("CENTRAL_API_PORT", "8082")
        self.api = ApiClient(args.api_base_url or f"http://{bind_address}:{api_port}")
        self.edge_health_url = args.edge_health_url
        self.central = [
            "docker",
            "compose",
            "--env-file",
            str(self.central_env),
            "-f",
            str(CENTRAL_COMPOSE_FILE),
        ]
        self.edge = ["docker", "compose", "--env-file", str(self.edge_env)]
        for compose_file in EDGE_COMPOSE_FILES:
            self.edge.extend(["-f", str(compose_file)])

    def validate_contract(self) -> None:
        if not self.args.confirm_real_hardware:
            raise AcceptanceFailure("pass --confirm-real-hardware to run outage drills")
        if self.edge_values.get("RS485_HOST_DEVICE", "").startswith("/dev/ttyUSB"):
            raise AcceptanceFailure("RS485_HOST_DEVICE must use a stable /dev/serial/by-id path")
        hardware_mode = self.edge_values.get("HARDWARE_DEVICE_MODE", "xjp60d")
        if hardware_mode in {"simulator", "demo"}:
            raise AcceptanceFailure(f"real-hardware acceptance refuses mode {hardware_mode!r}")
        run([*self.central, "config", "--quiet"])
        run([*self.edge, "config", "--quiet"])

    def start_stacks(self) -> None:
        run([*self.central, "up", "-d"])
        run([*self.edge, "up", "-d"])
        self.wait_ready()

    def wait_ready(self) -> None:
        wait_for(
            "central readiness",
            lambda: self.api.get("/health/ready") is not None,
            timeout=240,
        )
        wait_for(
            "edge health",
            lambda: self.http_json(self.edge_health_url) is not None,
            timeout=180,
        )

    @staticmethod
    def http_json(url: str) -> object:
        with urlopen(url, timeout=10) as response:
            return json.load(response)

    def capture_command(self, path: Path, command: list[str]) -> None:
        result = run(command, check=False)
        path.write_text(
            f"$ {' '.join(command)}\nexit={result.returncode}\n\nSTDOUT\n{result.stdout}\nSTDERR\n{result.stderr}",
            encoding="utf-8",
        )

    def volume_snapshot(self) -> dict[str, object]:
        result = run(["docker", "volume", "inspect", *EXPECTED_VOLUME_NAMES])
        volumes = json.loads(result.stdout)
        return {
            item["Name"]: {
                "name": item["Name"],
                "mountpoint": item["Mountpoint"],
                "created_at": item.get("CreatedAt"),
            }
            for item in volumes
        }

    def websocket_probe(self, evidence_path: Path) -> None:
        script = (
            "import asyncio, websockets; "
            "asyncio.run(websockets.connect("
            "'ws://127.0.0.1:8082/api/v1/telemetry/live?node_id=edge-01', "
            "open_timeout=8, close_timeout=3).__aenter__())"
        )
        self.capture_command(
            evidence_path,
            [*self.central, "exec", "-T", "telemetry-service", "python", "-c", script],
        )
        if "exit=0" not in evidence_path.read_text(encoding="utf-8"):
            raise AcceptanceFailure("WebSocket probe failed")

    def wait_for_34_series(self, session_id: str) -> dict[str, Any]:
        result: dict[str, Any] = {}

        def ready() -> bool:
            nonlocal result
            result = self.api.get(
                f"/api/v1/sessions/{session_id}/telemetry/latest",
                limit=100,
            )
            return result.get("count") == 34

        wait_for("34 attributed production series", ready, timeout=300, interval=5)
        return result

    def session_evidence(self, session_id: str) -> dict[str, object]:
        now = utc_now()
        start = now - timedelta(hours=24)
        return {
            "session": self.api.get(f"/api/v1/sessions/{session_id}"),
            "configuration": self.api.get(f"/api/v1/sessions/{session_id}/configuration"),
            "events": self.api.get(f"/api/v1/sessions/{session_id}/events", limit=500),
            "audit": self.api.get(f"/api/v1/sessions/{session_id}/audit", limit=500),
            "stages": self.api.get(f"/api/v1/sessions/{session_id}/stages"),
            "notes": self.api.get(f"/api/v1/sessions/{session_id}/notes", limit=500),
            "latest": self.api.get(
                f"/api/v1/sessions/{session_id}/telemetry/latest",
                limit=100,
            ),
            "history": self.api.get(
                f"/api/v1/sessions/{session_id}/telemetry/history",
                **{"from": start.isoformat(), "to": now.isoformat(), "limit": 1000},
            ),
        }

    def capture_runtime(self, root: Path, label: str, session_id: str | None = None) -> None:
        root.mkdir(parents=True, exist_ok=True)
        write_json(root / f"{label}-central-ready.json", self.api.get("/health/ready"))
        write_json(root / f"{label}-edge-health.json", self.http_json(self.edge_health_url))
        write_json(root / f"{label}-volumes.json", self.volume_snapshot())
        self.capture_command(root / f"{label}-central-ps.txt", [*self.central, "ps"])
        self.capture_command(root / f"{label}-edge-ps.txt", [*self.edge, "ps"])
        self.capture_command(
            root / f"{label}-central-logs.txt",
            [*self.central, "logs", "--since=15m", "--no-color"],
        )
        self.capture_command(
            root / f"{label}-edge-logs.txt",
            [*self.edge, "logs", "--since=15m", "--no-color"],
        )
        if session_id:
            evidence = self.session_evidence(session_id)
            write_json(root / f"{label}-session-evidence.json", evidence)
            write_json(
                root / f"{label}-session-hashes.json",
                {key: stable_hash(value) for key, value in evidence.items()},
            )

    def pre_reboot(self) -> None:
        self.validate_contract()
        self.start_stacks()
        stamp = utc_now().strftime("%Y%m%dT%H%M%SZ")
        root = Path(self.args.evidence_dir or REPO_ROOT / "runtime" / "evidence" / f"m4-{stamp}").resolve()
        root.mkdir(parents=True, exist_ok=False)
        state_path = root / "state.json"
        boot_id = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        self.capture_runtime(root, "00-baseline")
        self.websocket_probe(root / "00-websocket-before.txt")

        number = f"NXL-M4-HW-{stamp}"
        create_payload = {
            "session_number": number,
            "title": "M4 real-hardware restart acceptance",
            "test_object": "K106 refrigerated display cabinet",
            "node_id": "edge-01",
            "customer": "NEXOLAB",
            "standard": "ISO 23953",
            "method": "Restart, outage and recovery acceptance",
            "operator_id": "m4-acceptance",
            "responsible_engineer_id": "m4-acceptance",
            "metadata_payload": {"acceptance_gate": 82, "run_id": stamp},
            "actor_id": "m4-acceptance",
            "actor_source": "raspberry-pi-harness",
            "occurred_at": iso_now(),
            "reason": "Create Gate 82 real-hardware acceptance session",
        }
        created = self.api.post("/api/v1/sessions", create_payload, f"{stamp}-create", 201)
        session_id = created["session"]["id"]

        self.api.post(
            f"/api/v1/sessions/{session_id}/bindings/production",
            {
                "actor_id": "m4-acceptance",
                "actor_source": "raspberry-pi-harness",
                "occurred_at": iso_now(),
                "reason": "Assign all validated production series",
                "binding_metadata": {"acceptance_run": stamp},
            },
            f"{stamp}-bindings",
            201,
        )
        self.api.post(
            f"/api/v1/sessions/{session_id}/limits",
            {
                "actor_id": "m4-acceptance",
                "actor_source": "raspberry-pi-harness",
                "occurred_at": iso_now(),
                "reason": "Create acceptance limits version 1",
                "limits": [
                    {
                        "metric": "temperature.probe",
                        "unit": "degC",
                        "lower_limit": -5.0,
                        "upper_limit": 8.0,
                        "hysteresis": 0.5,
                        "duration_seconds": 60,
                    },
                    {
                        "metric": "electrical.power.active",
                        "unit": "W",
                        "upper_limit": 5000.0,
                    },
                ],
            },
            f"{stamp}-limits",
            201,
        )
        prepare_payload = {
            "actor_id": "m4-acceptance",
            "actor_source": "raspberry-pi-harness",
            "occurred_at": iso_now(),
            "reason": "Prepare real-hardware acceptance session",
        }
        self.api.post(
            f"/api/v1/sessions/{session_id}/prepare",
            prepare_payload,
            f"{stamp}-prepare",
        )
        start_payload = {
            "actor_id": "m4-acceptance",
            "actor_source": "raspberry-pi-harness",
            "occurred_at": iso_now(),
            "reason": "Start real-hardware acceptance session",
        }
        started = self.api.post(
            f"/api/v1/sessions/{session_id}/start",
            start_payload,
            f"{stamp}-start",
        )
        snapshot_id = started["session"]["active_config_snapshot_id"]
        stage_payload = {
            "actor_id": "m4-acceptance",
            "actor_source": "raspberry-pi-harness",
            "occurred_at": iso_now(),
            "reason": "Begin stabilization before recovery drills",
            "sequence_index": 0,
            "stage_type": "stabilization",
            "name": "Stabilization",
        }
        stage = self.api.post(
            f"/api/v1/sessions/{session_id}/stages/advance",
            stage_payload,
            f"{stamp}-stage-0",
            201,
        )
        first_stage_id = stage["stage"]["id"]
        first_latest = self.wait_for_34_series(session_id)
        write_json(root / "01-first-34-series.json", first_latest)

        events_before_replay = self.api.get(f"/api/v1/sessions/{session_id}/events", limit=500)
        replayed_start = self.api.post(
            f"/api/v1/sessions/{session_id}/start",
            start_payload,
            f"{stamp}-start",
        )
        if not replayed_start["replayed"]:
            raise AcceptanceFailure("repeated start was not reported as replayed")
        events_after_replay = self.api.get(f"/api/v1/sessions/{session_id}/events", limit=500)
        if events_before_replay["count"] != events_after_replay["count"]:
            raise AcceptanceFailure("repeated start created a duplicate event")

        run([*self.central, "restart", "telemetry-service"])
        self.wait_ready()
        self.websocket_probe(root / "02-websocket-after-service-restart.txt")
        after_service_restart = self.api.get(f"/api/v1/sessions/{session_id}")
        if after_service_restart["state"] != "running":
            raise AcceptanceFailure("active session did not survive Telemetry Service restart")
        if after_service_restart["active_config_snapshot_id"] != snapshot_id:
            raise AcceptanceFailure("configuration snapshot changed after service restart")

        run([*self.central, "restart", "postgres"])
        self.wait_ready()
        after_postgres_restart = self.api.get(f"/api/v1/sessions/{session_id}")
        if after_postgres_restart["state"] != "running":
            raise AcceptanceFailure("active session did not survive PostgreSQL restart")

        pause_payload = {
            "actor_id": "m4-acceptance",
            "actor_source": "raspberry-pi-harness",
            "occurred_at": iso_now(),
            "reason": "Pause workflow while Device Agent continues polling",
        }
        pause_started_at = utc_now()
        self.api.post(
            f"/api/v1/sessions/{session_id}/pause",
            pause_payload,
            f"{stamp}-pause",
        )
        time.sleep(self.args.pause_seconds)
        pause_history = self.api.get(
            f"/api/v1/sessions/{session_id}/telemetry/history",
            **{
                "from": pause_started_at.isoformat(),
                "to": iso_now(),
                "limit": 1000,
            },
        )
        if pause_history["count"] < 34:
            raise AcceptanceFailure("telemetry did not continue through pause")
        write_json(root / "03-pause-telemetry.json", pause_history)

        mqtt_outage_started_at = utc_now()
        run([*self.central, "stop", "mqtt"])
        time.sleep(self.args.mqtt_outage_seconds)
        write_json(root / "04-edge-health-during-mqtt-outage.json", self.http_json(self.edge_health_url))
        run([*self.central, "start", "mqtt"])
        self.wait_ready()
        self.wait_for_34_series(session_id)
        mqtt_history = self.api.get(
            f"/api/v1/sessions/{session_id}/telemetry/history",
            **{
                "from": mqtt_outage_started_at.isoformat(),
                "to": iso_now(),
                "limit": 1000,
            },
        )
        if mqtt_history["count"] < 34:
            raise AcceptanceFailure("MQTT outage backlog was not restored")
        write_json(root / "04-mqtt-outage-recovery.json", mqtt_history)

        resume_payload = {
            "actor_id": "m4-acceptance",
            "actor_source": "raspberry-pi-harness",
            "occurred_at": iso_now(),
            "reason": "Resume after central MQTT recovery",
        }
        self.api.post(
            f"/api/v1/sessions/{session_id}/resume",
            resume_payload,
            f"{stamp}-resume",
        )
        second_stage_payload = {
            "actor_id": "m4-acceptance",
            "actor_source": "raspberry-pi-harness",
            "occurred_at": iso_now(),
            "reason": "Enter main test at a real polling boundary",
            "sequence_index": 1,
            "stage_type": "main_test",
            "name": "Main test",
        }
        second_stage = self.api.post(
            f"/api/v1/sessions/{session_id}/stages/advance",
            second_stage_payload,
            f"{stamp}-stage-1",
            201,
        )
        second_stage_id = second_stage["stage"]["id"]

        def second_stage_visible() -> bool:
            latest = self.api.get(
                f"/api/v1/sessions/{session_id}/telemetry/latest",
                stage_id=second_stage_id,
                limit=100,
            )
            return latest["count"] == 34

        wait_for("34-series cycle in the new stage", second_stage_visible, timeout=300, interval=5)

        self.capture_runtime(root, "05-pre-reboot", session_id)
        state = {
            "version": 1,
            "phase": "pre-reboot-passed",
            "run_id": stamp,
            "evidence_dir": str(root),
            "created_at": iso_now(),
            "pre_reboot_boot_id": boot_id,
            "session_id": session_id,
            "session_number": number,
            "snapshot_id": snapshot_id,
            "first_stage_id": first_stage_id,
            "second_stage_id": second_stage_id,
            "volumes_before_reboot": self.volume_snapshot(),
            "complete_key": f"{stamp}-complete",
            "complete_payload": {
                "actor_id": "m4-acceptance",
                "actor_source": "raspberry-pi-harness",
                "occurred_at": iso_now(),
                "reason": "Complete Gate 82 after Raspberry Pi reboot",
            },
        }
        write_json(state_path, state)
        print(json.dumps({"status": "pre-reboot-passed", "state_file": str(state_path)}, indent=2))
        print(f"Next: sudo reboot\nThen run: {sys.argv[0]} post-reboot --state-file {state_path} --confirm-real-hardware")

    def post_reboot(self) -> None:
        self.validate_contract()
        state_path = Path(self.args.state_file).resolve()
        state = read_json(state_path)
        root = Path(state["evidence_dir"])
        current_boot_id = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        if current_boot_id == state["pre_reboot_boot_id"]:
            raise AcceptanceFailure("boot ID did not change; perform the Raspberry Pi reboot drill first")

        self.start_stacks()
        volumes_after_reboot = self.volume_snapshot()
        if volumes_after_reboot != state["volumes_before_reboot"]:
            raise AcceptanceFailure("named volume identity changed across Raspberry Pi reboot")

        session_id = state["session_id"]
        session = self.api.get(f"/api/v1/sessions/{session_id}")
        if session["state"] != "running":
            raise AcceptanceFailure(f"expected running session after reboot, got {session['state']!r}")
        if session["active_config_snapshot_id"] != state["snapshot_id"]:
            raise AcceptanceFailure("active configuration snapshot changed across reboot")
        if session["current_stage_id"] != state["second_stage_id"]:
            raise AcceptanceFailure("current stage changed across reboot")
        self.wait_for_34_series(session_id)
        self.websocket_probe(root / "06-websocket-after-pi-reboot.txt")
        self.capture_runtime(root, "06-post-reboot-running", session_id)

        completed = self.api.post(
            f"/api/v1/sessions/{session_id}/complete",
            state["complete_payload"],
            state["complete_key"],
        )
        if completed["session"]["state"] != "completed":
            raise AcceptanceFailure("session did not complete after reboot")
        immutable_before = self.session_evidence(session_id)
        immutable_hashes = {key: stable_hash(value) for key, value in immutable_before.items()}
        write_json(root / "07-completed-evidence.json", immutable_before)
        write_json(root / "07-completed-hashes.json", immutable_hashes)

        run([*self.central, "restart", "telemetry-service"])
        self.wait_ready()
        run([*self.central, "restart", "postgres"])
        self.wait_ready()

        replayed_complete = self.api.post(
            f"/api/v1/sessions/{session_id}/complete",
            state["complete_payload"],
            state["complete_key"],
        )
        if not replayed_complete["replayed"]:
            raise AcceptanceFailure("repeated complete was not idempotent after restart")
        immutable_after = self.session_evidence(session_id)
        hashes_after = {key: stable_hash(value) for key, value in immutable_after.items()}
        if hashes_after != immutable_hashes:
            raise AcceptanceFailure("completed session evidence changed after restart")

        rejected = self.api.request(
            "PATCH",
            f"/api/v1/sessions/{session_id}",
            body={"title": "Forbidden post-completion rewrite"},
            expected_status=409,
        )
        if rejected["detail"]["code"] != "session_immutable":
            raise AcceptanceFailure("completed-session immutability returned the wrong domain error")

        self.capture_runtime(root, "08-post-completion-restart", session_id)
        state.update(
            {
                "phase": "post-reboot-passed",
                "post_reboot_boot_id": current_boot_id,
                "completed_at": iso_now(),
                "immutable_hashes": immutable_hashes,
            }
        )
        write_json(state_path, state)
        print(json.dumps({"status": "post-reboot-passed", "state_file": str(state_path)}, indent=2))
        print(
            "Capture screenshots in the evidence directory with names:\n  "
            + "\n  ".join(SCREENSHOT_NAMES)
            + f"\nThen run: {sys.argv[0]} finalize --state-file {state_path} --confirm-real-hardware"
        )

    def finalize(self) -> None:
        self.validate_contract()
        state_path = Path(self.args.state_file).resolve()
        state = read_json(state_path)
        root = Path(state["evidence_dir"])
        if state.get("phase") != "post-reboot-passed":
            raise AcceptanceFailure("post-reboot phase has not passed")
        missing = [name for name in SCREENSHOT_NAMES if not (root / name).is_file()]
        if missing:
            raise AcceptanceFailure(f"missing required screenshots: {', '.join(missing)}")

        rollback_evidence = sorted((REPO_ROOT / "runtime" / "evidence").glob("m3-rollback-*/manifest.json"))
        rollback_manifest: object | None = None
        if rollback_evidence:
            rollback_manifest = read_json(rollback_evidence[-1])
            if not rollback_manifest.get("device_agent_container_preserved"):
                raise AcceptanceFailure("latest rollback evidence did not preserve Device Agent")
            if not rollback_manifest.get("modbus_mode_preserved"):
                raise AcceptanceFailure("latest rollback evidence did not preserve Modbus mode")
            if rollback_manifest.get("volumes_deleted"):
                raise AcceptanceFailure("latest rollback evidence reports deleted volumes")

        manifest = {
            "validation": "m4-session-restart-offline-real-hardware",
            "status": "passed",
            "completed_at": iso_now(),
            "run_id": state["run_id"],
            "session_id": state["session_id"],
            "session_number": state["session_number"],
            "pre_reboot_boot_id": state["pre_reboot_boot_id"],
            "post_reboot_boot_id": state["post_reboot_boot_id"],
            "active_session_survived_restarts": True,
            "pause_telemetry_continuous": True,
            "mqtt_backlog_recovered": True,
            "idempotent_commands_verified": True,
            "stage_context_restored": True,
            "production_series_count": 34,
            "demo_fallback_allowed": False,
            "completed_evidence_immutable": True,
            "named_volumes_preserved": True,
            "rollback_manifest": rollback_manifest,
            "screenshots": list(SCREENSHOT_NAMES),
        }
        write_json(root / "manifest.json", manifest)
        state["phase"] = "finalized"
        state["finalized_at"] = manifest["completed_at"]
        write_json(state_path, state)
        print(json.dumps(manifest, indent=2))
        print(f"M4 Gate 82 evidence finalized: {root}")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("phase", choices=("pre-reboot", "post-reboot", "finalize"))
    result.add_argument(
        "--central-env",
        default=str(SCRIPT_DIR / ".env.central"),
    )
    result.add_argument(
        "--edge-env",
        default=str(SCRIPT_DIR / ".env.edge-central"),
    )
    result.add_argument("--api-base-url")
    result.add_argument("--edge-health-url", default="http://127.0.0.1:8081/health")
    result.add_argument("--evidence-dir")
    result.add_argument("--state-file")
    result.add_argument("--pause-seconds", type=int, default=20)
    result.add_argument("--mqtt-outage-seconds", type=int, default=20)
    result.add_argument("--confirm-real-hardware", action="store_true")
    return result


def main() -> int:
    args = parser().parse_args()
    if args.phase in {"post-reboot", "finalize"} and not args.state_file:
        raise AcceptanceFailure(f"{args.phase} requires --state-file")
    harness = Harness(args)
    if args.phase == "pre-reboot":
        harness.pre_reboot()
    elif args.phase == "post-reboot":
        harness.post_reboot()
    else:
        harness.finalize()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AcceptanceFailure as error:
        print(f"M4 acceptance failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
