# NEXOLAB Blockers

Updated: 2026-08-14

## Issue #453 / PR #456 — completed

Issue #453 is closed and PR #456 was squash-merged into `main` as
`0cfe1321b38fa7c2582503ae98c65d82c76dcbc3` from exact verified head
`ac15c3e61b04a61ff91d2d929218c3431ea7de3c`.

Final exact-head gates were all GREEN:

- CI `31806462184`: PASS;
- Authenticated Dashboard Acceptance `31806462239`: 14/14 PASS;
- Refrigeration Browser Acceptance `31806462166`: PASS;
- Acquisition Scale Acceptance `31806462144`: PASS;
- disconnected Offline Bundle `31806462148`: PASS, including clean transferred
  host startup, blocked egress, `--pull never`, update/rollback and persistent
  volume/marker preservation.

Raspberry Pi operator acceptance remains **pending** and is not claimed.

## Issue #458 — state-only reconciliation

No product/runtime blocker exists. Issue #458 only reconciles the four canonical
`.project` files with the completed #453 merge and Ready #457 state. Its scope is
`.project/**` only.

## Issue #457 — Ready

Issue #457 is open, assigned and `status:ready`. Its former dependency on #453
is resolved. It is the next independent software Work Package after the
state-only #458 reconciliation.

## Independent hardware lane — Issue #289

Issue #289 remains open and `status:in-progress`. Completion still requires the
controlled real Raspberry Pi/RS-485 performance and physical-request matrix.
The software Acquisition Scale workflow for #453 does not replace that real
hardware evidence.

## Other pending hardware evidence

- Issue #445 / PR #446: software/CI/offline verified; Raspberry Pi KK2/Unit 115
  field retest remains pending.
- Issue #447 / PR #448: software/browser/offline verified; Raspberry Pi
  perceived-latency acceptance remains pending.
- Issue #389: physical Raspberry Pi version-management acceptance remains
  pending separately.

## Hard safety blockers

The following actions remain outside current authorization and require explicit
approval where applicable:

- Modbus writes or controller configuration changes;
- hardware writes or actuator control;
- destructive persistent-data or volume deletion;
- production/site cutover;
- secret/billing/DNS changes.

LOCAL_LAN, offline-first runtime and read-only acquisition boundaries remain
unchanged.
