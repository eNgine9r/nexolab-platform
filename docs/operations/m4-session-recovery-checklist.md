# M4 Gate 82 — operator checklist

Use this checklist together with `m4-session-recovery-acceptance.md`.

## Before the drill

- [ ] `main` is current and the working tree is clean.
- [ ] Central and edge Compose contracts validate.
- [ ] `RS485_HOST_DEVICE` uses `/dev/serial/by-id/`.
- [ ] Device Agent reports production hardware mode.
- [ ] Central REST and WebSocket endpoints are reachable.
- [ ] Dashboard uses live mode with no demo fallback.
- [ ] Latest M3 rollback evidence exists.
- [ ] No unrelated laboratory test is active.

## Automated pre-reboot phase

- [ ] Session created with a unique acceptance number.
- [ ] 34 production bindings assigned.
- [ ] Limits version 1 created.
- [ ] Session prepared and started.
- [ ] Configuration snapshot frozen.
- [ ] First 34-series cycle attributed.
- [ ] Repeated start command is replayed without a duplicate event.
- [ ] Telemetry Service restart passed.
- [ ] PostgreSQL restart passed.
- [ ] Pause retained telemetry collection.
- [ ] MQTT outage backlog recovered.
- [ ] Stage boundary produced a fresh 34-series cycle.
- [ ] Pre-reboot evidence captured.

## Manual reboot phase

- [ ] Sessions-list screenshot captured.
- [ ] Running-session screenshot captured.
- [ ] Raspberry Pi rebooted.
- [ ] Linux boot ID changed.
- [ ] Named volumes retained identity.
- [ ] Session restored as running.
- [ ] Active stage and configuration snapshot restored.
- [ ] Fresh 34-series cycle attributed after reboot.
- [ ] WebSocket reconnect passed.

## Completion and immutability

- [ ] Session completed after reboot.
- [ ] Completed-session screenshot captured.
- [ ] Telemetry Service restarted again.
- [ ] PostgreSQL restarted again.
- [ ] Repeated complete command was replayed.
- [ ] Completed evidence hashes stayed unchanged.
- [ ] Completed-session mutation returned `session_immutable`.
- [ ] Rollback manifest proves Device Agent and volumes were preserved.
- [ ] Final `manifest.json` reports `passed`.

## Evidence review

Record the final evidence directory in GitHub issue #82. Do not commit runtime evidence or environment files to the repository.
