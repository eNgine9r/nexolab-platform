# Device Agent hardware startup preflight

The hardware overlay explicitly starts `/usr/bin/python3 /app/dual_bus_main.py`.
It supports both the historical Python ENTRYPOINT image and the patched
base-debian13 image with no ENTRYPOINT. Replacing an image CMD with a bare script
name is unsafe: Docker otherwise tries to execute that name directly.

## Before controlled deployment

`deploy-current-head-raspberry-pi.sh` checksum-stages
`device-agent-startup-gate.py` and a startup-only Compose override in the deployment
audit directory before selecting historical source. The selected source still
supplies its hardware environment, networks, groups and volumes. The staged
override supplies only the interpreter, absolute script and, after build, the
exact candidate image ID. It remains part of the installed container's Compose
provenance after the control checkout is restored.

Before stopping the current agent, capturing its final SQLite snapshot or writing
the runtime mutation marker, the gate checks the resolved Compose command,
immutable image identity, platform, nonroot user and `/app` working directory.
It then compiles the entry script and imports Python runtime dependencies in an
isolated container. The probe has no network, site environment, device bindings or
data mounts, and uses a read-only filesystem, bounded memory/CPU/process count and
a 30-second deadline. Cleanup targets only the unique probe container. Missing
Python, script or dependencies and an unexpected effective model fail closed.
The activated agent must match the startup-verified image before deployment can
publish its final state.

This proves the interpreter/script startup contract. It does not execute the
acquisition application or replace final Docker health, MQTT, healthy bus workers,
advancing telemetry or real-hardware acceptance.

## Offline packages, update and rollback

New package builds probe the actual hardware entry script even when disconnected
CI starts the simulator. The bundle digest-binds the helper and probe evidence and
advertises `hardware-startup-gate` in tooling provenance. A historical runtime can
be rebuilt with corrected current tooling through `--runtime-source-ref`; runtime
source and tooling identity remain separate.

For hardware installation, `install-offline-bundle.sh` validates both Compose
models and probes the pinned image before any central or edge `up`. It preserves
the startup override and sanitized result outside the immutable bundle under
`runtime/device-agent-startup/hardware-startup.*`. Do not delete that directory
while its container is installed: Compose labels refer to its override.

The version manager first invokes the installer with `--preflight-only`, before
backup, source Dashboard shutdown or transaction mutation. That invocation loads
and verifies candidate images and validates startup without activating services.
The actual installer checks again at its activation boundary. Package tooling
without the gate capability/helper is rejected. Rebuild both the current and
rollback packages with corrected tooling; the earlier C296/T artifacts do not
satisfy this new contract.

## Recovery boundary for Issue #1321

The 2026-10-09 V2 owner recovery restored only the exact old Device Agent image,
without SQLite/PostgreSQL restore or changing package authority. Its report is
agent continuity evidence. Central services had already entered the failed C296
activation while frontend activation was never reached. The recovery therefore
does not establish a whole-stack rollback or a successful C296 deployment.

Keep the interrupted deployment evidence and recovery override. A subsequent full
installer must explicitly reconcile the mixed runtime and source authority; this
startup fix does not bypass the existing unresolved-mutation gate or manufacture
`current.json`. See [edge SQLite recovery](edge-sqlite-cutover-recovery.md) for the
separate restore boundary. No database restore is implied by this runbook.
