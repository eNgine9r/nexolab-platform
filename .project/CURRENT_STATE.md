# NEXOLAB Current State

Updated: 2026-08-14

## Canonical product/runtime baseline

Current product/runtime `main` after Issue #453 / PR #456 is
`0cfe1321b38fa7c2582503ae98c65d82c76dcbc3`.

PR #456 was squash-merged from exact verified head
`ac15c3e61b04a61ff91d2d929218c3431ea7de3c` and closed Issue #453.
The merge extends the canonical Chart System without changing backend ingestion,
acquisition scheduling, Modbus behavior, persistence schemas or runtime
dependencies.

## Completed Chart System Work Package — Issue #453 / PR #456

The merged Chart System now provides:

- equipment-first Live Data and Saved Live Dashboard chart grouping;
- one synchronized equipment canvas for mixed native units such as `V`, `A`
  and `W`, with one shared time X domain;
- deterministic series-to-Y-axis binding and stable axis IDs/order;
- dynamic axis omission/restoration across hide/show/solo without renderer or
  ChartShell remounting;
- a bounded five-axis readability budget with deterministic additional
  equipment-scene partitioning beyond the budget;
- no implicit telemetry-unit conversion and no mutation of raw telemetry;
- visible-series-only ChartShell accessibility summaries for series count,
  axes, units, freshness and continuity breaks;
- preserved #451 continuity, Exact Inspector, live-tail, pause-view and
  event-provenance behavior;
- production mixed-unit V/A/W acceptance plus the updated canonical #451
  production regression on the same equipment-centric contract.

## Final exact-head verification — GREEN

Exact final PR head `ac15c3e6...` passed every required gate before merge:

- CI run `31806462184`: PASS — formatting, lint, typecheck, full tests and
  production build;
- Authenticated Dashboard Acceptance run `31806462239`: 14/14 PASS, including
  the seeded V/A/W single-equipment canvas, the canonical #451 regression,
  max one WebSocket and zero acquisition/configuration mutations;
- Refrigeration Browser Acceptance run `31806462166`: PASS;
- Acquisition Scale Acceptance run `31806462144`: PASS;
- disconnected Offline Bundle run `31806462148`: PASS — exact source checkout,
  clean transferred-host simulation, blocked container egress, `--pull never`
  startup, update/rollback and persistent volume/marker preservation.

Final merge audit confirmed that the branch was behind-by 0, its merge-base was
current `main`, the PR was mergeable, reviews/threads were empty, and the diff
was limited to the approved Chart System/frontend, tests/E2E, architecture and
project-state files.

Classification: **software/browser/offline verified; Raspberry Pi operator
acceptance pending**. No physical Raspberry Pi completion is claimed for #453.

## State-only reconciliation — Issue #458

Issue #458 exists only to reconcile `.project/**` after the #453 merge. It does
not change product/runtime code. Its reconciliation basis is product/runtime
`main` `0cfe1321b38fa7c2582503ae98c65d82c76dcbc3`.

## Independent active hardware lane — Issue #289

Issue #289 remains open and `status:in-progress`. Its real Raspberry Pi/RS-485
matrix is not satisfied by software, browser or offline CI evidence from #453.
The physical polling envelope, multiple-browser matrix and truthful hardware
state still require controlled real-device evidence.

Independent prior hardware classifications remain unchanged:

- Issue #445 / PR #446: software/CI/offline verified; Raspberry Pi KK2/Unit 115
  field retest pending;
- Issue #447 / PR #448: software/browser/offline verified; Raspberry Pi
  perceived-latency acceptance pending;
- Issue #389: Raspberry Pi version-management hardware acceptance remains
  pending separately.

## Next Ready Work Package

Issue #457 — **Recompose Live Data around a graph-first operator workspace** —
is open, assigned and `status:ready` after the #453 merge. It is the next
independent software Work Package from Epic #450.

Its scope is composition/read-model/browser verification only: primary graph
first, selected context/legend/Exact Inspector adjacent to it, responsive
360/1440/1920 behavior, one existing WebSocket, selected-series-only history and
zero acquisition/configuration mutations.

## Safety boundary

LOCAL_LAN and offline-first requirements remain unchanged. No work completed in
#453/#456 or this state-only reconciliation authorizes Modbus/hardware writes,
controller configuration changes, destructive persistent-data operations,
production/site cutover, secret/billing/DNS changes or mandatory public-cloud
runtime dependencies.
