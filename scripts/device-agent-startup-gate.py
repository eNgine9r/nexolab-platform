#!/usr/bin/env python3
"""Validate the effective hardware startup without opening site devices or data."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any
from uuid import uuid4

IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}\Z")
INTERPRETER = "/usr/bin/python3"
SCRIPT = "/app/dual_bus_main.py"


class StartupGateError(RuntimeError):
    pass


def require_image_id(value: str) -> None:
    if not IMAGE_ID.fullmatch(value):
        raise StartupGateError("an immutable Docker image ID is required")


def write_overlay(path: Path, image_id: str | None = None) -> None:
    service: dict[str, Any] = {"entrypoint": [INTERPRETER], "command": [SCRIPT]}
    if image_id is not None:
        require_image_id(image_id)
        service["image"] = image_id
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump({"services": {"device-agent": service}}, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        temporary.unlink(missing_ok=True)


def validate_contract(
    model: dict[str, Any], image: dict[str, Any], image_id: str, platform: str
) -> dict[str, Any]:
    require_image_id(image_id)
    if platform not in {"linux/arm64", "linux/amd64"}:
        raise StartupGateError("unsupported expected image platform")
    services = model.get("services")
    service = services.get("device-agent") if isinstance(services, dict) else None
    if not isinstance(service, dict) or service.get("image") != image_id:
        raise StartupGateError("effective Device Agent image differs from the pinned candidate")
    if service.get("entrypoint") != [INTERPRETER] or service.get("command") != [SCRIPT]:
        raise StartupGateError("hardware startup requires the explicit interpreter and absolute script")
    if image.get("Id") != image_id:
        raise StartupGateError("Docker image inspection differs from the pinned candidate")
    if f"{image.get('Os')}/{image.get('Architecture')}" != platform:
        raise StartupGateError("Device Agent image platform differs from the selected runtime")
    config = image.get("Config")
    if not isinstance(config, dict):
        raise StartupGateError("Device Agent image configuration is missing")
    user = service.get("user", config.get("User"))
    if not isinstance(user, str) or not user or user.split(":", 1)[0] in {"0", "root"}:
        raise StartupGateError("Device Agent must retain its nonroot runtime user")
    if user != config.get("User"):
        raise StartupGateError("Device Agent user override differs from the probed image")
    if service.get("working_dir", config.get("WorkingDir")) != "/app":
        raise StartupGateError("Device Agent working directory must remain /app")
    return {"image_id": image_id, "platform": platform, "entrypoint": [INTERPRETER],
            "command": [SCRIPT], "user": user, "working_dir": "/app"}


def probe_image(image_id: str) -> None:
    require_image_id(image_id)
    name = f"nexolab-agent-startup-{uuid4().hex}"
    # Compile, never import/execute acquisition entrypoints. Import only runtime
    # dependencies: this detects a missing interpreter, loader, SQLite or module.
    code = (
        "import pathlib,sys; "
        "p=pathlib.Path(sys.argv[1]); compile(p.read_bytes(),str(p),'exec'); "
        "import sqlite3,ssl,serial,paho.mqtt.client"
    )
    command = [
        "docker", "run", "--rm", "--name", name, "--pull=never", "--network=none",
        "--read-only", "--cap-drop=ALL", "--security-opt=no-new-privileges",
        "--memory=128m", "--memory-swap=128m", "--pids-limit=32", "--cpus=0.5",
        "--no-healthcheck", "--workdir=/app", "--entrypoint", INTERPRETER,
        image_id, "-B", "-c", code, SCRIPT,
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            raise StartupGateError("isolated Device Agent interpreter/script/dependency probe failed")
    except (OSError, subprocess.TimeoutExpired) as error:
        raise StartupGateError("isolated Device Agent startup probe could not finish") from error
    finally:
        # Killing a timed-out Docker CLI does not stop its container. Never use
        # a project/service-wide cleanup; only this unique probe may be removed.
        try:
            cleanup = subprocess.run(["docker", "rm", "--force", name], capture_output=True,
                                     text=True, timeout=10, check=False)
            if cleanup.returncode != 0:
                remaining = subprocess.run(
                    ["docker", "ps", "-aq", "--filter", f"name=^{name}$"],
                    capture_output=True, text=True, timeout=10, check=False,
                )
                if remaining.returncode != 0 or remaining.stdout.strip():
                    raise StartupGateError("isolated startup probe cleanup could not be confirmed")
        except (OSError, subprocess.TimeoutExpired):
            raise StartupGateError("isolated startup probe cleanup could not be confirmed")


def run_json(command: list[str]) -> Any:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=30, check=True)
        return json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, ValueError) as error:
        # Compose output may contain site secrets. Do not include raw stdout/stderr.
        raise StartupGateError("Device Agent startup metadata could not be resolved") from error


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    overlay = commands.add_parser("write-overlay")
    overlay.add_argument("--output", type=Path, required=True)
    overlay.add_argument("--image-id")
    check = commands.add_parser("check")
    check.add_argument("--expected-image-id", required=True)
    check.add_argument("--platform", choices=["linux/arm64", "linux/amd64"], required=True)
    check.add_argument("--env-file", required=True)
    check.add_argument("--compose-file", action="append", required=True)
    probe = commands.add_parser("probe")
    probe.add_argument("--image-id", required=True)
    args = parser.parse_args(argv)
    try:
        if args.action == "write-overlay":
            write_overlay(args.output, args.image_id)
        elif args.action == "probe":
            probe_image(args.image_id)
            print(json.dumps({"kind": "nexolab-device-agent-startup-probe",
                              "status": "passed", "image_id": args.image_id}))
        else:
            require_image_id(args.expected_image_id)
            command = ["docker", "compose", "--env-file", args.env_file]
            for path in args.compose_file:
                command.extend(["-f", path])
            model = run_json(command + ["config", "--format", "json"])
            images = run_json(["docker", "image", "inspect", args.expected_image_id])
            if not isinstance(model, dict) or not isinstance(images, list) or len(images) != 1 or not isinstance(images[0], dict):
                raise StartupGateError("invalid Device Agent startup metadata")
            evidence = validate_contract(model, images[0], args.expected_image_id, args.platform)
            probe_image(args.expected_image_id)
            print(json.dumps({"kind": "nexolab-device-agent-startup-gate", "status": "passed",
                              "probe": "isolated_compile_and_dependency_import", **evidence}))
    except (StartupGateError, OSError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
