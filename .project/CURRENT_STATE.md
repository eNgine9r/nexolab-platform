# NEXOLAB Current State

Updated: 2026-08-12

Canonical repository baseline on `main`:
`ecd61dfc8682f5aa0c7231b8a73341d1d292f03a` — Issue #413 / PR #414
Overview Chart System merge.

## Completed Chart System migrations

- Issue #386 / PR #399 established the canonical Chart System and merged as
  `3b34ec321c2453778b20b6bf8e4cc232970e5e1e`.
- Issue #400 / PR #402 migrated Live Data and merged as
  `afdfa387a7aa988a49e010d75c27d59a7cdf74d2` with Raspberry Pi acquisition
  acceptance PASS.
- Issue #404 / PR #410 migrated Saved Live Dashboards and merged as
  `d4068e28402aa113f4485dc3afecb1f8eb44bd7b` with controlled Raspberry Pi
  continuity and cursor-layout acceptance PASS.
- Issue #411 / PR #412 reconciled post-#404 project state and merged as
  `e89560cd2f52b59ed1c9fda4adca38e4c634a3b7`.
- Issue #413 / PR #414 migrated Overview XJP60D temperature history and merged as
  `ecd61dfc8682f5aa0c7231b8a73341d1d292f03a`.

## Issue #413 completion evidence

Hardware-tested corrective product head:
`0b0b239911c729e31c791c8fa2eb2c6f433bfcce`.

Corrective product gates were GREEN:

- CI #2944;
- Authenticated Dashboard Acceptance #1632, including acquisition invariant;
- Refrigeration Browser Acceptance #1606;
- Offline Bundle #1015.

Controlled Raspberry Pi cursor retest passed:

- chart visual continuity — PASS;
- post-event Overview render — PASS;
- cursor vertical jump — NO;
- graph/card stays fixed — YES;
- Hide/Show/Solo — PASS;
- zoom/pan/reset — PASS;
- 1h -> 6h -> 24h — PASS;
- route reopen — PASS;
- dashboard remains usable — YES.

Final PR head was `a845e39b0daa628e20e551289a378dcc33ffef2b`.
Changes after the hardware-tested corrective product head were state/audit-only.
Final exact-head gates were GREEN:

- CI #2950;
- Authenticated Dashboard Acceptance #1638;
- Refrigeration Browser Acceptance #1612;
- Offline Bundle #1021.

The earlier physical acquisition/control-plane evidence remains applicable because
no telemetry, Device Agent, scheduler, registry, polling or hardware behavior was
changed by the cursor correction.

## Active Work Package — Issue #417

Issue #417 reconciles the #413 merge into the durable repository state. It is
state/audit-only and changes exactly four `.project` files plus the #413 audit.
No product/runtime code is in scope.

After #417 merges, a fresh repository-backed Ready audit is required before the
next implementation package is selected.

## Prepared lanes for the fresh Ready audit

- Issue #369 remains the critical preserved runtime lane with sequence
  `#369 -> #366 -> #289`.
- Issue #389 remains Ready/not selected for administrator-only Version
  Management.
- Issue #415 is the new canonical Chart System UX follow-up for left-button
  drag-to-pan. It is open and must not be auto-selected before the fresh audit.
- Issue #245 remains a separate Raspberry Pi validation track.
- Issue #257 remains blocked.
- Issue #256 remains deferred.

## Safety boundary

No Modbus write or hardware write is permitted. Issue #417 changes no product
runtime, backend schema, PostgreSQL migration, Device Agent, acquisition
scheduler/registry, discovery path, dependency version or network boundary.

The `telemetry-service/libcjson1/CVE-2026-67216` exception still expires on
2026-09-05.

## Next action

Complete Issue #417 with a five-file focused diff and GREEN state-only CI, merge
it, then run the mandatory fresh Ready audit against the resulting `main`.
