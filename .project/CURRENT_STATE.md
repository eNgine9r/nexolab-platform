# NEXOLAB Current State

Updated: 2026-08-15

## Canonical product/runtime baseline

Current product/runtime `main` is
`41439a5bf692d40555799df80a912ab4bc98735c`.

That baseline includes Issue #453 / PR #456 equipment-centric multi-axis Chart
System work and Issue #458 / PR #459 post-merge state reconciliation. Issue #289
remains an independent Raspberry Pi/RS-485 hardware-performance validation lane.

## Active Work Package — Issue #457 / PR #460

Issue #457 — **Recompose Live Data around a graph-first operator workspace** —
is `status:in-progress` on branch `feat/457-live-data-graph-first-workspace` with
PR #460.

Verified product head before this state-only checkpoint:
`acbbeadabe0162286060e3d97353cb51752f7706`.

The Live Data explorer now preserves one canonical `useLiveTelemetry` model while
using the operator reading/focus order:

1. Live Data identity and truthful connection status;
2. primary canonical chart workspace;
3. search and filters;
4. latest-values inventory / comparison selection.

The primary chart owns the selected-context summary, range controls, Pause/Return
to Live behavior, canonical legend and Exact Inspector. Empty comparison
selection is explicit and performs no history request. Inventory table overflow
remains locally contained.

## Product-head verification — GREEN

Exact product head `acbbeada...` passed the required product gates:

- CI `31883123214`: PASS — runtime-contract/ADR/dependency-policy validation,
  formatting, lint, typecheck, full tests and production build;
- Authenticated Dashboard Acceptance `31883123221`: **14/14 PASS**, including
  `live-chart-system.production.e2e.ts` with graph-first DOM/layout/focus order,
  selected-context adjacency, selected-series-only history, canonical chart
  interactions, max one WebSocket and zero acquisition/configuration mutations;
- Refrigeration Browser Acceptance `31883123215`: PASS;
- disconnected Offline Bundle `31883123222`: PASS — exact source checkout,
  clean transferred-host simulation, container egress blocked, `--pull never`
  disconnected startup, update/rollback and persistent-data preservation.

No Acquisition Scale workflow was required or claimed for this layout/read-model
Work Package.

Classification: **software/browser/offline verified; Raspberry Pi operator
acceptance pending**.

## State-only final-head reconciliation

This checkpoint updates only `.project/**` after product-head verification.
Because it creates a new PR head, CI, Authenticated Dashboard, Refrigeration
Browser and disconnected Offline Bundle must pass again on that exact state-
reconciled head before PR #460 may be marked Ready or merged.

## Next software Work Package

Issue #461 — **Add reusable hierarchical TelemetryPointSelector** — has been
created from Epic #450 WP4 and is currently `status:blocked` only on merge of
#457. Its reusable selector scope is intentionally not implemented in PR #460.
After #457 merges and project state is reconciled, #461 becomes the next
independent software Work Package.

## Independent hardware lane — Issue #289

Issue #289 remains open and `status:in-progress`. The physical Raspberry Pi/
RS-485 polling envelope, multi-browser matrix and truthful hardware-state
acceptance still require controlled real-device evidence. Software/browser/
offline verification for #457 does not satisfy that hardware acceptance.

Other pending physical evidence remains separate, including the KK2/Unit 115
field retest (#445), refrigeration perceived-latency acceptance (#447) and
version-management Raspberry Pi acceptance (#389).

## Safety boundary

LOCAL_LAN and offline-first requirements remain unchanged. Issue #457 / PR #460
contains no backend/API/schema, dependency/lockfile, telemetry acquisition,
scheduler/registry, Modbus/hardware write, destructive persistent-data,
production/site cutover, secret/billing/DNS or mandatory public-cloud runtime
change.
