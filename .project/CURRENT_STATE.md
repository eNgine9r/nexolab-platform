# NEXOLAB Current State

Updated: 2026-08-15

## Canonical repository baseline

Current `main` is `d06b7958eab08d8ce319b3f3397ac541079e7f68`, the squash merge of Issue #468 / PR #473.

Issue #468 is closed/completed at the software level. Its stale `status:in-progress` label has been removed. Post-merge repository-state reconciliation is tracked by state-only Issue #474.

## Completed software Work Package — Issue #468 / PR #473

Issue #468 — **Keep Device Agent acquisition alive across SQLite queue lock contention** — is software-complete and merged.

PR #473 delivered:

- explicit SQLite `busy_timeout` plus bounded retry for queue operations;
- complete-operation retry/rollback without resetting or deleting edge SQLite;
- contention coverage for enqueue, backlog reads, delete, queue depth and monotonic stream-sequence allocation;
- process-level supervision tying HTTP availability to the top-level Device Agent runtime, so an unexpectedly dead acquisition runtime cannot remain hidden behind a live health server;
- deterministic real-SQLite contention and runtime-supervision regressions;
- preserved polling cadence, target eligibility, one serialized worker per physical bus and read-only Modbus boundary.

Merge-authoritative source head was `4dd2cdeb9aa2827e55217a1ba57bf6c6a150bf04`. Final exact-head workflows were GREEN:

- CI `31907158772`;
- Device Agent Fleet Acceptance `31907158788`;
- Acquisition Scale Acceptance `31907158853` — software-only;
- Offline Bundle `31907158836` — disconnected startup, pull disabled, persistent-data-preserving update/rollback;
- Authenticated Dashboard Acceptance `31907158743`;
- MQTT TLS Fleet Acceptance `31907158756`;
- Disaster Recovery TLS Fleet `31907158716`;
- Container Supply Chain `31907158779`;
- Edge image `31907158763`.

This does **not** constitute physical Raspberry Pi acceptance. Fresh controlled Raspberry Pi/RS-485 evidence must still prove active worker recovery or fail-closed restart and advancing telemetry freshness.

## Active state-only Work Package — Issue #474

Issue #474 — **Reconcile Issue #468 merge state and activate next Ready Work Package** — is `status:in-progress`.

Its scope is `.project/**` only. No product/runtime code, dependency, schema, hardware or deployment mutation is permitted.

## Next Ready software Work Package — Issue #469

Issue #469 — **Prevent Raspberry Pi deployment evidence capture from exhausting disk** — remains open, `priority:high`, `status:ready`.

It is the next software Work Package after Issue #474 merges. The deployment path must gain capacity preflight and bounded deployment-evidence retention without deleting PostgreSQL, edge SQLite, MQTT, MinIO or named-volume product data.

## Independent hardware lane — Issue #289

Issue #289 remains open and `status:in-progress`. Fresh physical Raspberry Pi/RS-485 performance and recovery evidence is required after the #468 software fix and after #469 makes controlled deployment/evidence capture capacity-safe.

Other pending physical evidence includes KK2/Unit 115 field retest, refrigeration perceived-latency acceptance and Raspberry Pi version-management acceptance.

## Safety boundary

LOCAL_LAN and offline-first requirements remain unchanged. Read-only Modbus remains mandatory. No controller configuration, hardware write, destructive persistent-data/volume action, site cutover, secret/billing/DNS change or mandatory cloud runtime dependency is authorized.
