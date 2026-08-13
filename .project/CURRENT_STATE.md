# NEXOLAB Current State

Updated: 2026-08-13

Canonical product `main` baseline is `06f78b178acfed72033bf607099d827eca1a9f9a`
(Issue #433 / PR #434 sensor enrollment and acquisition recovery).

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

## Selected Next Ready Work Package — Issue #432

Issue #432 is the only open `status:ready` product Work Package in the fresh
audit and is selected next. It will measure and correct warm-navigation
time-to-usable behavior for Overview, Refrigeration, Energy, Live Data, Nodes
and Sessions without changing physical acquisition.

Issue #289 remains `status:needs-validation` until #432 is complete and the
remaining physical Raspberry Pi performance matrix is captured.

## Safety boundary

No Modbus or hardware write, polling amplification, persistent-data deletion,
volume deletion, production/site cutover or mandatory cloud dependency is
included. Core runtime remains LOCAL_LAN and offline-capable.
