# NEXOLAB Current State

Updated: 2026-08-13

Canonical product `main` baseline is `9ddef4445b2894f25a6e93267f497d0e5b09b970`
(Issue #433 merge reconciled by Issue #435 / PR #436).

## Completed critical Work Package — Issue #433 / PR #434

Issue #433 is closed and PR #434 is squash-merged. Final PR head
`236019f9929aa230ff1f2f6ff0954ecee3bde6f1` passed the required exact-head
verification: 15 checks passed, the disconnected Offline Bundle runtime passed,
and one image-attestation publish matrix entry was intentionally skipped.

The merged LOCAL_LAN implementation provides:

- atomic audited enrollment of newly discovered configured XJP60D Unit IDs into
  the existing #284 registry as `discovery_only` FC03 inventory;
- zero new scheduler jobs until explicit operator activation;
- live #285 scheduler reconciliation after enrollment/activation with cadence,
  fairness, retry and cooldown policy unchanged;
- bounded per-target attempt/success/failure/cooldown/recovery diagnostics;
- truthful initializing UI before the first sample and explicit sensor /
  communication error states without demo fallback;
- unchanged #378 stable `/dev/serial/by-id/...` transport recovery.

Local verification was GREEN: 30 focused Device Agent tests, all 120 Device
Agent tests, 4 focused UI tests, all 384 frontend tests, formatting, lint,
typecheck and production build. Evidence is recorded in
`docs/audits/issue-433-sensor-enrollment-recovery.md`.

Classification: software verified; post-change Raspberry Pi sensor enrollment
and recovery acceptance remains pending and is not claimed.

## Completed software/browser Work Package — Issue #432 / PR #437

Issue #432 is implemented on `perf/432-route-prefetch-time-to-usable`; focused
PR #437 is open. Deterministic production-browser evidence proved that the
installed Next.js 16.2.12 automatic `<Link>` prefetch already warms all six
canonical static monitoring routes, so no product navigation correction was
required.

Warm median time-to-usable was `263 ms` Overview, `275 ms` Refrigeration,
`282 ms` Energy, `198 ms` Live Data, `265 ms` Nodes and `208 ms` Sessions. The
complete repeated route cycle kept one document load, no visible loading
transition, no eager channel or Node inventory fetch from visible links,
`websocket_max_concurrent = 1` and zero acquisition mutations.

Local verification passed format, lint, typecheck, all 89 frontend test files /
384 tests, lint-staged behavior, production build, the focused production route
matrix, the 13-scenario Authenticated Dashboard/acquisition-invariant gate, and
Offline Auth migration/browser/persistence gates. Exact evidence head
`cbcf3a53c3cf73dc279d9f48d55669cf7e3dd8c2` passed CI, Acquisition Scale,
Authenticated Dashboard, Refrigeration Browser, Offline Auth and the complete
disconnected Offline Bundle with update/rollback volume preservation.

Evidence is recorded in
`docs/audits/issue-432-route-prefetch-time-to-usable.md`.

Classification: software/browser route-prefetch verified; Raspberry Pi
performance acceptance remains pending under Issue #289 and is not claimed.

## Next continuation

Merge PR #437, reconcile the Issue #432 merge, then reassess Issue #289 for the
remaining controlled Raspberry Pi physical/performance matrix.

## Safety boundary

No Modbus or hardware write, polling amplification, persistent-data deletion,
volume deletion, production/site cutover or mandatory cloud dependency is
included. Core runtime remains LOCAL_LAN and offline-capable.
