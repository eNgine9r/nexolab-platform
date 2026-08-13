# NEXOLAB Current State

Updated: 2026-08-13

Canonical `main` is `aa8c8fc2a4a3d496c4e9d6bfaa49ac284f4f2b2c`
(Issue #430 / PR #431 post-#389 state reconciliation).

## Active critical Work Package — Issue #433

Issue #433 is implemented on branch `fix/433-sensor-enrollment-recovery` and
published as draft PR #434. Product head
`1c138d0c87ea09847ea5d3311a11b405470a3682` passed all 15 triggered checks;
one image-attestation publish matrix entry was intentionally skipped.

The recovered implementation provides:

- atomic audited enrollment of newly discovered configured XJP60D Unit IDs into
  the existing #284 registry as `discovery_only` FC03 inventory;
- zero new scheduler jobs until explicit operator activation;
- live #285 scheduler reconciliation after enrollment/activation with existing
  cadence, fairness, retry and cooldown policy unchanged;
- bounded per-target attempt/success/failure/cooldown/recovery diagnostics;
- truthful initializing UI before the first sample, plus visible sensor and
  communication error states without demo fallback;
- unchanged #378 stable `/dev/serial/by-id/...` handle recovery.

Local verification is GREEN: 30 focused Device Agent tests, all 120 Device
Agent tests, 4 focused UI tests, all 384 frontend tests, formatting, lint,
typecheck and production build. The before-change Raspberry Pi read-only
baseline is preserved in `docs/audits/issue-433-sensor-enrollment-recovery.md`.
The exact-head gates include CI quality/build, Device Agent and service images,
the acquisition invariant, deterministic scheduler scale, secure fleet outage
and TLS recovery, and disconnected Offline Bundle startup/data preservation.
Post-change physical acceptance has not been performed and is not claimed.

## Next Ready Work Package — Issue #432

Issue #432 remains prepared and `status:ready`, but sequencing explicitly keeps
it unchanged until #433 is GREEN, reconciled and merged. It is the next focused
route-prefetch/time-to-usable package before final #289 physical validation.

## Safety boundary

No Modbus or hardware write, polling amplification, persistent-data deletion,
volume deletion, production/site cutover or mandatory cloud dependency is
included. Core runtime remains LOCAL_LAN and offline-capable.
