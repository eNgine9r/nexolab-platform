# NEXOLAB Current State

Updated: 2026-08-15

## Canonical repository baseline

Current `main` is `8b7bb76115d11de0cc92cfaab2c131f27a891aa6`, the squash merge of Issue #465 / PR #470 — **Integrate TelemetryPointSelector into Live Dashboard editor**.

Issue #465 is closed/completed and its stale `status:in-progress` label has been removed.

The merged product now provides the reusable hierarchical `TelemetryPointSelector` in the Live Dashboard editor, truthful read-only inventory taxonomy enrichment, preservation of the existing persisted dashboard contract, unresolved-selection preservation, bounded latest-value lookup and deterministic PostgreSQL index-path evidence.

## Issue #465 completion evidence

Final merge-authoritative PR head: `31d71914e7ddd86e8d52936c0849b9722bc53eae`.

All exact-head merge gates were GREEN:

- CI `31903598683` — PASS;
- Telemetry service `31903598706` — PASS;
- Authenticated Dashboard Acceptance `31903598797` — PASS;
- Refrigeration Browser Acceptance `31903598778` — PASS;
- Offline Bundle `31903598715` — PASS;
- Offline Auth Acceptance `31903598743` — PASS;
- Acquisition Scale Acceptance `31903598902` — PASS software-only;
- Device Agent Fleet Acceptance `31903598652` — PASS;
- Container Supply Chain `31903598871` — PASS;
- Broker Control Acceptance `31903598751` — PASS;
- Disaster Recovery Browser `31903598737` — PASS after same-head browser rerun;
- Disaster Recovery TLS Fleet `31903598777` — PASS;
- MQTT TLS Fleet Acceptance `31903598659` — PASS;
- Capacity Release Gate `31903598661` — PASS.

Offline Bundle proved clean transferred-host startup with container egress blocked, pull disabled and persistent data preserved across update/rollback.

Issue #465 did not perform or require Modbus writes, hardware writes, polling/scheduler changes, acquisition-registry changes, dependency upgrades, database migrations, persistent-data deletion or production/site cutover.

## Repository-backed Ready audit after #465

Open `status:ready` software Issues are:

1. **Issue #468 — Keep Device Agent acquisition alive across SQLite queue lock contention** — `priority:critical`, `area:edge`.
2. **Issue #469 — Prevent Raspberry Pi deployment evidence capture from exhausting disk** — `priority:high`, `area:edge`.

### Selected next software Work Package: Issue #468

Issue #468 is selected first because the documented production defect can leave the Device Agent HTTP server reachable while the real acquisition worker is dead and all telemetry becomes stale. It directly blocks truthful acquisition behavior and completion of the independent hardware acceptance lane #289.

Issue #469 remains Ready immediately after #468. It is required to make controlled Raspberry Pi deployment/evidence capture capacity-safe before final hardware retest, but it does not supersede the critical live-acquisition defect.

## Independent hardware lane — Issue #289

Issue #289 remains open and `status:in-progress`. Fresh physical Raspberry Pi/RS-485 evidence is still required. Software workflow evidence from #465 does **not** count as hardware acceptance.

Known physical/operational work includes:

- controlled acquisition recovery validation after #468;
- capacity-safe deployment/retest after #469;
- KK2/Unit 115 field retest;
- refrigeration perceived-latency acceptance;
- Raspberry Pi version-management acceptance.

## Active state-only Work Package

Issue #471 reconciles this post-merge state. Its branch is `chore/471-reconcile-issue-465-merge-state`; net product/runtime change must remain zero and the PR must contain only `.project/**`.

## Safety boundary

LOCAL_LAN and offline-first requirements remain unchanged. Read-only Modbus remains mandatory. No controller configuration, hardware write, destructive persistent-data action, site cutover, secret/billing/DNS change or mandatory cloud runtime dependency is authorized.
