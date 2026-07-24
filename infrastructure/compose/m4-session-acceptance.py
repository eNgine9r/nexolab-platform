#!/usr/bin/env python3
"""M4 real-hardware restart and offline recovery acceptance harness.

The harness temporarily restarts services and stops central MQTT. It never deletes
Docker named volumes and never writes Modbus registers.
"""

from __future__ import annotations

import argparse
import hashlib
import json
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
CENTRAL_FILE = SCRIPT_DIR / "compose.central.yaml"
EDGE_FILES = (
    SCRIPT_DIR / "compose.edge.yaml",
    SCRIPT_DIR / "compose.hardware.yaml",
    SCRIPT_DIR / "compose.edge-central-bridge.yaml",
)
VOLUME_NAMES = (
    "nexolab-central-postgres-data",
    "nexolab-central-mqtt-data",
    "nexolab-edge_edge-data",
    "nexolab-edge_mqtt-data",
)
SCREENSHOTS = (
    "01-sessions-list.png",
    "02-running-session.png",
    "03-completed-session.png",
)


class AcceptanceFailure(RuntimeError):
    pass


def now() -> datetime:
    return datetime.now(UTC)


def now_iso() -> str:
    return now().isoformat()


def load_env(path: Path) -> dict[str, str]:
    if not path.is_file():
        raise AcceptanceFailure(f"missing environment file: {path}")
    result: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key.strip()] = value.strip().strip('"').strip("'")
    return result


def run(command: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        check=False,
        text=True,
        capture_output=True,
    )
    if check and result.returncode != 0:
        raise AcceptanceFailure(
            f"command failed ({result.returncode}): {' '.join(command)}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def digest(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def wait_for(
    label: str,
    predicate: Callable[[], bool],
    *,
    timeout: float = 240,
    interval: float = 2,
) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            if predicate():
                return
        except Exception as error:  # noqa: BLE001 - transient outage evidence
            last_error = error
        time.sleep(interval)
    detail = f": {last_error}" if last_error else ""
    raise AcceptanceFailure(f"timed out waiting for {label}{detail}")


class Api:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def request(
        self,
        method: str,
        path: str,
        *,
        body: object | None = None,
        key: str | None = None,
        query: dict[str, object] | None = None,
        expected: int = 200,
    ) -> object:
        url = f"{self.base_url}{path}"
        if query:
            url = f"{url}?{urlencode(query)}"
        headers = {"Accept": "application/json"}
        encoded = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            encoded = json.dumps(body).encode()
        if key:
            headers["Idempotency-Key"] = key
        request = Request(url, data=encoded, headers=headers, method=method)
        try:
            with urlopen(request, timeout=15) as response:
                status = response.status
                raw = response.read()
        except HTTPError as error:
            status = error.code
            raw = error.read()
        except URLError as error:
            raise AcceptanceFailure(f"request failed: {method} {url}: {error}") from error
        payload: object = json.loads(raw) if raw else None
        if status != expected:
            raise AcceptanceFailure(
                f"unexpected response {status} for {method} {url}; "
                f"expected {expected}: {payload}"
            )
        return payload

    def get(self, path: str, **query: object) -> object:
        return self.request("GET", path, query=query or None)

    def post(
        self,
        path: str,
        body: object,
        key: str,
        *,
        expected: int = 200,
    ) -> object:
        return self.request(
            "POST",
            path,
            body=body,
            key=key,
            expected=expected,
        )


class Harness:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.central_env = Path(args.central_env).resolve()
        self.edge_env = Path(args.edge_env).resolve()
        self.central_values = load_env(self.central_env)
        self.edge_values = load_env(self.edge_env)
        bind = self.central_values.get("CENTRAL_BIND_ADDRESS", "127.0.0.1")
        if bind in {"0.0.0.0", "::"}:
            bind = "127.0.0.1"
        port = self.central_values.get("CENTRAL_API_PORT", "8082")
        self.api = Api(args.api_base_url or f"http://{bind}:{port}")
        self.central = [
            "docker",
            "compose",
            "--env-file",
            str(self.central_env),
            "-f",
            str(CENTRAL_FILE),
        ]
        self.edge = ["docker", "compose", "--env-file", str(self.edge_env)]
        for compose_file in EDGE_FILES:
            self.edge.extend(["-f", str(compose_file)])

    def validate(self) -> None:
        if not self.args.confirm_real_hardware:
            raise AcceptanceFailure("pass --confirm-real-hardware to run outage drills")
        serial_device = self.edge_values.get("RS485_HOST_DEVICE", "")
        if not serial_device.startswith("/dev/serial/by-id/"):
            raise AcceptanceFailure(
                "RS485_HOST_DEVICE must use a stable /dev/serial/by-id path"
            )
        mode = self.edge_values.get("HARDWARE_DEVICE_MODE", "xjp60d")
        if mode in {"simulator", "demo"}:
            raise AcceptanceFailure(f"real-hardware acceptance refuses mode {mode!r}")
        run([*self.central, "config", "--quiet"])
        run([*self.edge, "config", "--quiet"])

    def start(self) -> None:
        run([*self.central, "up", "-d"])
        run([*self.edge, "up", "-d"])
        self.wait_ready()

    def wait_ready(self) -> None:
        wait_for("central readiness", lambda: bool(self.api.get("/health/ready")))
        wait_for(
            "edge health",
            lambda: bool(self.http_json(self.args.edge_health_url)),
            timeout=180,
        )

    @staticmethod
    def http_json(url: str) -> object:
        with urlopen(url, timeout=10) as response:
            return json.load(response)

    def volumes(self) -> dict[str, object]:
        inspected = json.loads(
            run(["docker", "volume", "inspect", *VOLUME_NAMES]).stdout
        )
        return {
            item["Name"]: {
                "name": item["Name"],
                "mountpoint": item["Mountpoint"],
                "created_at": item.get("CreatedAt"),
            }
            for item in inspected
        }

    @staticmethod
    def capture(path: Path, command: list[str]) -> None:
        result = run(command, check=False)
        path.write_text(
            f"$ {' '.join(command)}\nexit={result.returncode}\n\n"
            f"STDOUT\n{result.stdout}\nSTDERR\n{result.stderr}",
            encoding="utf-8",
        )

    def websocket_probe(self, path: Path) -> None:
        script = """
import asyncio
import websockets


async def main() -> None:
    uri = "ws://127.0.0.1:8082/api/v1/telemetry/live?node_id=edge-01"
    async with websockets.connect(uri, open_timeout=8, close_timeout=3):
        return


asyncio.run(main())
"""
        self.capture(
            path,
            [
                *self.central,
                "exec",
                "-T",
                "telemetry-service",
                "python",
                "-c",
                script,
            ],
        )
        if "exit=0" not in path.read_text(encoding="utf-8"):
            raise AcceptanceFailure("WebSocket probe failed")

    def wait_for_cycle(
        self,
        session_id: str,
        *,
        stage_id: str | None = None,
    ) -> dict[str, Any]:
        result: dict[str, Any] = {}

        def ready() -> bool:
            nonlocal result
            query: dict[str, object] = {"limit": 100}
            if stage_id:
                query["stage_id"] = stage_id
            result = self.api.get(
                f"/api/v1/sessions/{session_id}/telemetry/latest",
                **query,
            )
            return result.get("count") == 34

        wait_for("34 attributed production series", ready, timeout=300, interval=5)
        return result

    def evidence(self, session_id: str) -> dict[str, object]:
        end = now()
        start = end - timedelta(hours=24)
        return {
            "session": self.api.get(f"/api/v1/sessions/{session_id}"),
            "configuration": self.api.get(
                f"/api/v1/sessions/{session_id}/configuration"
            ),
            "events": self.api.get(
                f"/api/v1/sessions/{session_id}/events",
                limit=500,
            ),
            "audit": self.api.get(
                f"/api/v1/sessions/{session_id}/audit",
                limit=500,
            ),
            "stages": self.api.get(f"/api/v1/sessions/{session_id}/stages"),
            "notes": self.api.get(
                f"/api/v1/sessions/{session_id}/notes",
                limit=500,
            ),
            "latest": self.api.get(
                f"/api/v1/sessions/{session_id}/telemetry/latest",
                limit=100,
            ),
            "history": self.api.get(
                f"/api/v1/sessions/{session_id}/telemetry/history",
                **{"from": start.isoformat(), "to": end.isoformat(), "limit": 1000},
            ),
        }

    def capture_runtime(
        self,
        root: Path,
        label: str,
        session_id: str | None = None,
    ) -> None:
        write_json(root / f"{label}-central-ready.json", self.api.get("/health/ready"))
        write_json(
            root / f"{label}-edge-health.json",
            self.http_json(self.args.edge_health_url),
        )
        write_json(root / f"{label}-volumes.json", self.volumes())
        self.capture(root / f"{label}-central-ps.txt", [*self.central, "ps"])
        self.capture(root / f"{label}-edge-ps.txt", [*self.edge, "ps"])
        self.capture(
            root / f"{label}-central-logs.txt",
            [*self.central, "logs", "--since=15m", "--no-color"],
        )
        self.capture(
            root / f"{label}-edge-logs.txt",
            [*self.edge, "logs", "--since=15m", "--no-color"],
        )
        if session_id:
            value = self.evidence(session_id)
            write_json(root / f"{label}-session-evidence.json", value)
            write_json(
                root / f"{label}-session-hashes.json",
                {key: digest(item) for key, item in value.items()},
            )

    @staticmethod
    def actor(reason: str) -> dict[str, object]:
        return {
            "actor_id": "m4-acceptance",
            "actor_source": "raspberry-pi-harness",
            "occurred_at": now_iso(),
            "reason": reason,
        }

    def pre_reboot(self) -> None:
        self.validate()
        self.start()
        stamp = now().strftime("%Y%m%dT%H%M%SZ")
        root = Path(
            self.args.evidence_dir
            or REPO_ROOT / "runtime" / "evidence" / f"m4-{stamp}"
        ).resolve()
        root.mkdir(parents=True, exist_ok=False)
        boot_id = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        self.capture_runtime(root, "00-baseline")
        self.websocket_probe(root / "00-websocket-before.txt")

        created = self.api.post(
            "/api/v1/sessions",
            {
                "session_number": f"NXL-M4-HW-{stamp}",
                "title": "M4 real-hardware restart acceptance",
                "test_object": "K106 refrigerated display cabinet",
                "node_id": "edge-01",
                "customer": "NEXOLAB",
                "standard": "ISO 23953",
                "method": "Restart, outage and recovery acceptance",
                "operator_id": "m4-acceptance",
                "responsible_engineer_id": "m4-acceptance",
                "metadata_payload": {"acceptance_gate": 82, "run_id": stamp},
                **self.actor("Create Gate 82 real-hardware acceptance session"),
            },
            f"{stamp}-create",
            expected=201,
        )
        session_id = created["session"]["id"]
        session_number = created["session"]["session_number"]

        bindings = self.api.post(
            f"/api/v1/sessions/{session_id}/bindings/production",
            {
                **self.actor("Assign all validated production series"),
                "binding_metadata": {"acceptance_run": stamp},
            },
            f"{stamp}-bindings",
            expected=201,
        )
        if bindings["expected_series_count"] != 34:
            raise AcceptanceFailure("production binding count is not 34")

        self.api.post(
            f"/api/v1/sessions/{session_id}/limits",
            {
                **self.actor("Create acceptance limits version 1"),
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
            expected=201,
        )
        self.api.post(
            f"/api/v1/sessions/{session_id}/prepare",
            self.actor("Prepare real-hardware acceptance session"),
            f"{stamp}-prepare",
        )
        start_payload = self.actor("Start real-hardware acceptance session")
        started = self.api.post(
            f"/api/v1/sessions/{session_id}/start",
            start_payload,
            f"{stamp}-start",
        )
        snapshot_id = started["session"]["active_config_snapshot_id"]
        stage_zero = self.api.post(
            f"/api/v1/sessions/{session_id}/stages/advance",
            {
                **self.actor("Begin stabilization before recovery drills"),
                "sequence_index": 0,
                "stage_type": "stabilization",
                "name": "Stabilization",
            },
            f"{stamp}-stage-0",
            expected=201,
        )
        first_stage_id = stage_zero["stage"]["id"]
        write_json(root / "01-first-34-series.json", self.wait_for_cycle(session_id))

        count_before = self.api.get(
            f"/api/v1/sessions/{session_id}/events",
            limit=500,
        )["count"]
        replayed = self.api.post(
            f"/api/v1/sessions/{session_id}/start",
            start_payload,
            f"{stamp}-start",
        )
        count_after = self.api.get(
            f"/api/v1/sessions/{session_id}/events",
            limit=500,
        )["count"]
        if not replayed["replayed"] or count_before != count_after:
            raise AcceptanceFailure("repeated start created a duplicate event")

        run([*self.central, "restart", "telemetry-service"])
        self.wait_ready()
        self.websocket_probe(root / "02-websocket-after-service-restart.txt")
        restored = self.api.get(f"/api/v1/sessions/{session_id}")
        if restored["state"] != "running":
            raise AcceptanceFailure("active session did not survive service restart")
        if restored["active_config_snapshot_id"] != snapshot_id:
            raise AcceptanceFailure("snapshot changed after service restart")

        run([*self.central, "restart", "postgres"])
        self.wait_ready()
        if self.api.get(f"/api/v1/sessions/{session_id}")["state"] != "running":
            raise AcceptanceFailure("active session did not survive PostgreSQL restart")

        pause_started = now()
        self.api.post(
            f"/api/v1/sessions/{session_id}/pause",
            self.actor("Pause workflow while Device Agent continues polling"),
            f"{stamp}-pause",
        )
        time.sleep(self.args.pause_seconds)
        pause_history = self.api.get(
            f"/api/v1/sessions/{session_id}/telemetry/history",
            **{"from": pause_started.isoformat(), "to": now_iso(), "limit": 1000},
        )
        if pause_history["count"] < 34:
            raise AcceptanceFailure("telemetry did not continue through pause")
        write_json(root / "03-pause-telemetry.json", pause_history)

        outage_started = now()
        run([*self.central, "stop", "mqtt"])
        time.sleep(self.args.mqtt_outage_seconds)
        write_json(
            root / "04-edge-health-during-mqtt-outage.json",
            self.http_json(self.args.edge_health_url),
        )
        run([*self.central, "start", "mqtt"])
        self.wait_ready()
        self.wait_for_cycle(session_id)
        outage_history = self.api.get(
            f"/api/v1/sessions/{session_id}/telemetry/history",
            **{"from": outage_started.isoformat(), "to": now_iso(), "limit": 1000},
        )
        if outage_history["count"] < 34:
            raise AcceptanceFailure("MQTT outage backlog was not restored")
        write_json(root / "04-mqtt-outage-recovery.json", outage_history)

        self.api.post(
            f"/api/v1/sessions/{session_id}/resume",
            self.actor("Resume after central MQTT recovery"),
            f"{stamp}-resume",
        )
        stage_one = self.api.post(
            f"/api/v1/sessions/{session_id}/stages/advance",
            {
                **self.actor("Enter main test at a real polling boundary"),
                "sequence_index": 1,
                "stage_type": "main_test",
                "name": "Main test",
            },
            f"{stamp}-stage-1",
            expected=201,
        )
        second_stage_id = stage_one["stage"]["id"]
        self.wait_for_cycle(session_id, stage_id=second_stage_id)
        self.capture_runtime(root, "05-pre-reboot", session_id)

        complete_payload = self.actor("Complete Gate 82 after Raspberry Pi reboot")
        state = {
            "version": 1,
            "phase": "pre-reboot-passed",
            "run_id": stamp,
            "evidence_dir": str(root),
            "created_at": now_iso(),
            "pre_reboot_boot_id": boot_id,
            "session_id": session_id,
            "session_number": session_number,
            "snapshot_id": snapshot_id,
            "first_stage_id": first_stage_id,
            "second_stage_id": second_stage_id,
            "volumes_before_reboot": self.volumes(),
            "complete_key": f"{stamp}-complete",
            "complete_payload": complete_payload,
        }
        state_path = root / "state.json"
        write_json(state_path, state)
        print(
            json.dumps(
                {"status": "pre-reboot-passed", "state_file": str(state_path)},
                indent=2,
            )
        )
        print("Next: capture running screenshots, run sudo reboot, then post-reboot phase.")

    def post_reboot(self) -> None:
        self.validate()
        state_path = Path(self.args.state_file).resolve()
        state = read_json(state_path)
        root = Path(state["evidence_dir"])
        current_boot_id = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        if current_boot_id == state["pre_reboot_boot_id"]:
            raise AcceptanceFailure("boot ID did not change; perform the reboot drill")

        self.start()
        if self.volumes() != state["volumes_before_reboot"]:
            raise AcceptanceFailure("named volume identity changed across reboot")
        session_id = state["session_id"]
        session = self.api.get(f"/api/v1/sessions/{session_id}")
        if session["state"] != "running":
            raise AcceptanceFailure(f"expected running session, got {session['state']!r}")
        if session["active_config_snapshot_id"] != state["snapshot_id"]:
            raise AcceptanceFailure("snapshot changed across reboot")
        if session["current_stage_id"] != state["second_stage_id"]:
            raise AcceptanceFailure("stage changed across reboot")
        self.wait_for_cycle(session_id)
        self.websocket_probe(root / "06-websocket-after-pi-reboot.txt")
        self.capture_runtime(root, "06-post-reboot-running", session_id)

        completed = self.api.post(
            f"/api/v1/sessions/{session_id}/complete",
            state["complete_payload"],
            state["complete_key"],
        )
        if completed["session"]["state"] != "completed":
            raise AcceptanceFailure("session did not complete after reboot")
        immutable_before = self.evidence(session_id)
        hashes_before = {key: digest(value) for key, value in immutable_before.items()}
        write_json(root / "07-completed-evidence.json", immutable_before)
        write_json(root / "07-completed-hashes.json", hashes_before)

        run([*self.central, "restart", "telemetry-service"])
        self.wait_ready()
        run([*self.central, "restart", "postgres"])
        self.wait_ready()
        replayed = self.api.post(
            f"/api/v1/sessions/{session_id}/complete",
            state["complete_payload"],
            state["complete_key"],
        )
        if not replayed["replayed"]:
            raise AcceptanceFailure("repeated complete was not idempotent")
        hashes_after = {
            key: digest(value) for key, value in self.evidence(session_id).items()
        }
        if hashes_after != hashes_before:
            raise AcceptanceFailure("completed evidence changed after restart")

        rejected = self.api.request(
            "PATCH",
            f"/api/v1/sessions/{session_id}",
            body={"title": "Forbidden post-completion rewrite"},
            expected=409,
        )
        if rejected["detail"]["code"] != "session_immutable":
            raise AcceptanceFailure("completed-session immutability returned wrong error")
        self.capture_runtime(root, "08-post-completion-restart", session_id)

        state.update(
            {
                "phase": "post-reboot-passed",
                "post_reboot_boot_id": current_boot_id,
                "completed_at": now_iso(),
                "immutable_hashes": hashes_before,
            }
        )
        write_json(state_path, state)
        print(json.dumps({"status": "post-reboot-passed"}, indent=2))
        print("Capture 03-completed-session.png, then run finalize phase.")

    def finalize(self) -> None:
        self.validate()
        state_path = Path(self.args.state_file).resolve()
        state = read_json(state_path)
        root = Path(state["evidence_dir"])
        if state.get("phase") != "post-reboot-passed":
            raise AcceptanceFailure("post-reboot phase has not passed")
        missing = [name for name in SCREENSHOTS if not (root / name).is_file()]
        if missing:
            raise AcceptanceFailure(f"missing screenshots: {', '.join(missing)}")

        rollback_paths = sorted(
            (REPO_ROOT / "runtime" / "evidence").glob(
                "m3-rollback-*/manifest.json"
            )
        )
        if not rollback_paths:
            raise AcceptanceFailure(
                "missing required M3 rollback evidence under runtime/evidence"
            )
        rollback = read_json(rollback_paths[-1])
        if not rollback.get("device_agent_container_preserved"):
            raise AcceptanceFailure("rollback did not preserve Device Agent")
        if not rollback.get("modbus_mode_preserved"):
            raise AcceptanceFailure("rollback did not preserve Modbus mode")
        if rollback.get("volumes_deleted"):
            raise AcceptanceFailure("rollback reports deleted volumes")

        manifest = {
            "validation": "m4-session-restart-offline-real-hardware",
            "status": "passed",
            "completed_at": now_iso(),
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
            "rollback_manifest": rollback,
            "screenshots": list(SCREENSHOTS),
        }
        write_json(root / "manifest.json", manifest)
        state["phase"] = "finalized"
        state["finalized_at"] = manifest["completed_at"]
        write_json(state_path, state)
        print(json.dumps(manifest, indent=2))
        print(f"M4 Gate 82 evidence finalized: {root}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("pre-reboot", "post-reboot", "finalize"))
    parser.add_argument(
        "--central-env",
        default=str(SCRIPT_DIR / ".env.central"),
    )
    parser.add_argument(
        "--edge-env",
        default=str(SCRIPT_DIR / ".env.edge-central"),
    )
    parser.add_argument("--api-base-url")
    parser.add_argument("--edge-health-url", default="http://127.0.0.1:8081/health")
    parser.add_argument("--evidence-dir")
    parser.add_argument("--state-file")
    parser.add_argument("--pause-seconds", type=int, default=20)
    parser.add_argument("--mqtt-outage-seconds", type=int, default=20)
    parser.add_argument("--confirm-real-hardware", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
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
