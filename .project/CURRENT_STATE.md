# NEXOLAB Current State

Updated: 2026-08-18

## Accepted product baseline

The current accepted product baseline remains:

`9732b68b0d14e4056e5773e0a9bec3f3741e267f`

Repository state reconciliation after the approved Raspberry Pi deployment is merged through:

`11432d5f0f41164db9621b7567b95466136b574d`

The controlled Raspberry Pi runtime remains deployed at:

`7a19f53950492a40255c53b1d2018bbdff9466e2`

with evidence:

`runtime/deployments/20260818T131726Z`

## Issue #566 / #560 runtime acceptance

Issue #566 is completed. The LOCAL_LAN deployment passed capacity, PostgreSQL backup, Dashboard/API readiness, JWT/local-auth preservation, Device Agent worker health and telemetry advancement gates.

Issue #560 post-fix runtime acceptance is PASS: Energy Monitoring remained correct beyond the full 300-second access-token rotation window and `/api/v1/auth/local/refresh` returned HTTP 200 without recurrence of the prior `invalid_bearer_token` defect.

## Issue #576 — software verified, Raspberry Pi acceptance pending

PR #579 implements trusted lineage evidence for controlled source deployments without claiming validated package authority.

Implementation head before project-state checkpoint:

`994c2e66cd05e161172fc76654173805cea72c75`

Exact-head verification on that implementation state:

- CI #3560 — GREEN: repository contracts, formatting, lint, typecheck, tests and production build;
- Telemetry service #1740 — GREEN: the new source-adoption tests, existing update-orchestrator/version-manager contracts, full Telemetry tests, PostgreSQL outage recovery, migration validation and container build.

The implementation adds `scripts/nexolab-adopt-source-deployment.py` and an operator runbook. The adopter requires canonical repository/main lineage, a clean tracked tree, deployment evidence whose commit equals deployed HEAD, fast-forward ancestry to the current `origin/main`, matching runtime/auth mode, live Alembic revision, API/database/MQTT readiness, healthy Device Agent bus-worker invariant and host platform.

A successful source record is explicitly marked `deployment_authority=controlled_source_deployment` and `known_packaged_release=false`. It creates no catalog entry, stages no bundle, queues no update/rollback and does not enable automatic updates. Manual discovery can therefore know the deployed source commit while activation remains fail-closed as `current_release_unverified` until genuine validated package authority exists.

The Raspberry Pi has **not** run this adopter yet. Its version-management state therefore still returns `current_revision_unknown`. Writing the bounded host metadata and collecting real Pi acceptance requires a new separate explicit Product Owner approval after PR #579 is GREEN/merged.

## Independent runtime defect: Issue #575

LE-01MP Unit 201 remains an independent Ready read-only diagnostic lane. Device Agent bus workers are healthy and telemetry advances, but Unit 201 has timeout-only/cooldown behavior. No Modbus or hardware write is authorized.

## Current execution boundary

Issue #576 software is verified and PR #579 is being finalized for merge. After merge, stop at the physical/runtime boundary and request separate approval before any Raspberry Pi source-adoption metadata write or acceptance action.

## Safety boundaries

`LOCAL_LAN`, offline-first runtime and read-only industrial boundaries remain unchanged. No Modbus/controller write, actuator/hardware write, persistent-data deletion, named-volume deletion, secret/billing/DNS mutation or mandatory cloud runtime dependency is authorized.
