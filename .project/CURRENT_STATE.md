# NEXOLAB Current State

Updated: 2026-08-14

## Canonical repository baseline

Current product/runtime `main` is
`058ddf8131d43e0b8ea56553bff83fbe0b90efa0`.

That baseline includes the completed Issue #454 / PR #455 state-only
reconciliation after Issue #451. PR #455 was squash-merged into `main` as
`058ddf8131d43e0b8ea56553bff83fbe0b90efa0` from final PR head
`af92129a03591e10dab594f9cfe1dfcfe16256c0`.

Independent prior hardware classifications remain unchanged:

- Issue #445 / PR #446: software/CI/offline verified; Raspberry Pi KK2/Unit 115
  field retest pending;
- Issue #447 / PR #448: software/browser/offline verified; Raspberry Pi
  perceived-latency acceptance pending;
- Issue #289 remains the independent controlled Raspberry Pi/RS-485
  acquisition-scale and truthful-state acceptance lane.

## Active critical Chart System Work Package — Issue #453 / PR #456

Issue #453 is `status:in-progress` on branch
`feat/453-equipment-centric-multi-axis-charts` with PR #456.

Verified product head before this state-only reconciliation commit:
`3e7f9d8cac8da1b8a34fdf62053b6fe3a7bf3e79`.

The canonical Chart System extension now provides:

- equipment-first Live Data and Saved Live Dashboard chart grouping;
- one synchronized equipment canvas for mixed native units such as `V`, `A`
  and `W`, with a shared X domain;
- deterministic series-to-Y-axis binding and stable axis IDs/order;
- dynamic axis omission/restoration across hide/show/solo without renderer or
  ChartShell remounting;
- a bounded five-axis readability budget with deterministic additional
  equipment-scene partitioning beyond the budget;
- no implicit telemetry-unit conversion and no mutation of raw telemetry;
- visible-series-only ChartShell accessibility summaries for series count,
  axes, units, freshness and continuity breaks;
- preserved #451 continuity, exact-inspector, live-tail, pause-view and
  event-provenance behavior;
- production mixed-unit V/A/W acceptance plus the updated canonical #451
  production regression on the same equipment-centric contract.

## Product-head verification — GREEN

Exact product head `3e7f9d8c...` is GREEN:

- CI run `31805527701`: PASS — formatting, lint, typecheck, full tests and
  production build;
- Authenticated Dashboard Acceptance run `31805527693`: 14/14 PASS, including
  the seeded V/A/W single-equipment canvas, canonical Chart System regression,
  max one WebSocket and zero acquisition/configuration mutations;
- Refrigeration Browser Acceptance run `31805527758`: PASS;
- Acquisition Scale Acceptance run `31805527743`: PASS;
- disconnected Offline Bundle run `31805527696`: PASS — exact source checkout,
  clean transferred-host simulation, runtime image removal/reload, blocked
  container egress, `--pull never` startup, update/rollback and persistent
  volume/marker preservation.

Classification: **software/browser/offline verified; Raspberry Pi operator
acceptance pending**. No physical Raspberry Pi completion is claimed for #453.

## State-only final-head reconciliation

This checkpoint updates only `.project/**` after product-head verification.
Because the state reconciliation itself creates a new PR head, all required
exact-head gates must run again before PR #456 may be marked Ready or merged.
The final merge audit must confirm unchanged `main`, no unresolved reviews,
focused diff and GREEN checks on that state-reconciled exact head.

## Independent active hardware lane — Issue #289

Issue #289 remains open and `status:in-progress`. Its real Raspberry Pi/RS-485
matrix is not satisfied by software, browser or offline CI evidence from #453.
The physical polling envelope, multiple-browser matrix and truthful hardware
state still require controlled real-device evidence.

## Next Chart System Work Package

Issue #457 — graph-first Live Data operator workspace — is created and currently
`status:blocked` only on the merge of #453. It is intentionally not implemented
inside PR #456. After #453 merges, #457 becomes the next independent software
Work Package and may move to `status:ready` on its own feature branch/PR.

## Safety boundary

LOCAL_LAN and offline-first requirements remain unchanged. Issue #453 / PR #456
contains no backend ingestion, persistence-schema, scheduler, acquisition-registry,
Modbus/hardware write, dependency-upgrade, destructive persistent-data, volume
removal, production/site cutover, secret/billing/DNS or mandatory public-cloud
runtime change.
