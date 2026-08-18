# NEXOLAB Current State

Updated: 2026-08-18

## Accepted product baseline

The current accepted NEXOLAB product baseline is:

`dc4e3186d115d7e2877c0a02c5f315df5946da7e`

This is the squash merge of PR #579 — **fix: add trusted source deployment lineage evidence**.

Final PR #579 head:

`cbb0dfba44d8d6cce256ffbf45b8577a9d114629`

Exact-head verification on that final state-inclusive head:

- CI #3564 — GREEN: repository contracts, formatting, lint, typecheck, tests and production build;
- Telemetry service #1744 — GREEN: targeted source-adoption/update-orchestrator/version-manager contracts, full Telemetry integration tests, PostgreSQL outage recovery, migration validation and container build.

## Current Raspberry Pi runtime

The Raspberry Pi remains deployed at:

`7a19f53950492a40255c53b1d2018bbdff9466e2`

Evidence:

`runtime/deployments/20260818T131726Z`

Issue #566 deployment and Issue #560 token-rotation runtime acceptance remain PASS. Energy Monitoring survived the full 300-second access-token rotation window without recurrence of `invalid_bearer_token`.

## Issue #576 — software merged, real Pi adoption pending

The merged implementation introduces an explicit source-lineage adoption gate for source-deployed Raspberry Pi runtimes. It does **not** retroactively call the running source deployment a validated package.

A successful adoption record is marked:

- `deployment_authority=controlled_source_deployment`;
- `known_packaged_release=false`.

The adopter requires canonical repo/main lineage, clean tracked state, exact deployment-evidence commit, fast-forward ancestry to `origin/main`, runtime/auth consistency, live Alembic revision, API/database/MQTT readiness, healthy Device Agent bus-worker invariant and supported host platform.

It creates no catalog entry, stages no package, queues no update/rollback, restarts no service and does not enable automatic updates. Manual discovery can learn the deployed commit, while activation remains fail-closed as `current_release_unverified` until genuine validated package authority exists.

The adopter has **not** been run on the Raspberry Pi. The host therefore still reports `current_revision_unknown` for manual discovery. Issue #576 is open with `status:blocked` at a new explicit approval boundary: writing `/var/lib/nexolab/version-management/current.json` source-lineage metadata and collecting post-adoption runtime evidence require separate Product Owner approval.

Automatic updates remain OFF and the host-local timer remains fixed at 02:00.

## Independent runtime defect: Issue #575

LE-01MP Unit 201 remains an independent Ready read-only diagnostic lane. Device Agent bus workers are healthy and telemetry advances, but Unit 201 has timeout-only/cooldown behavior. No Modbus or hardware write is authorized.

## Current execution boundary

Stop before any Issue #576 Raspberry Pi metadata mutation. Request separate explicit Product Owner approval for the bounded source-adoption acceptance action. Issue #575 remains independently Ready but does not remove the #576 physical/runtime approval boundary.

## Safety boundaries

`LOCAL_LAN`, offline-first runtime and read-only industrial boundaries remain unchanged. No Modbus/controller write, actuator/hardware write, persistent-data deletion, named-volume deletion, secret/billing/DNS mutation or mandatory cloud runtime dependency is authorized.
