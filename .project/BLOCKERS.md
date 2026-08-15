# NEXOLAB Blockers

Updated: 2026-08-15

## Issue #457 / PR #460 — no known software/runtime blocker

Issue #457 is active and product-verified on exact head
`acbbeadabe0162286060e3d97353cb51752f7706`:

- CI `31883123214`: PASS;
- Authenticated Dashboard Acceptance `31883123221`: 14/14 PASS, including the
  graph-first Live Chart System production regression, max one WebSocket and
  zero acquisition/configuration mutations;
- Refrigeration Browser Acceptance `31883123215`: PASS;
- disconnected Offline Bundle `31883123222`: PASS, including exact source
  checkout, clean transferred-host simulation, blocked egress, `--pull never`
  disconnected startup, update/rollback and persistent-data preservation.

The remaining boundary is procedural and exact-head based: this state-only
checkpoint creates a new PR head, so the required gates must run again on that
exact head before Ready/merge. Final audit must also confirm current `main`,
focused diff and unresolved-review state.

Raspberry Pi operator acceptance remains **pending** and is not claimed.

## Issue #461 — intentionally blocked on #457 merge

Issue #461 is the next Epic #450 Work Package: reusable hierarchical
`TelemetryPointSelector`. It is created with `status:blocked` and must remain
blocked until #457 / PR #460 is merged and state is reconciled. No #461
implementation belongs in PR #460.

## Independent hardware lane — Issue #289

Issue #289 remains open and `status:in-progress`. Completion still requires the
controlled real Raspberry Pi/RS-485 performance and physical-request matrix.
Software/browser/offline verification for #457 does not replace that evidence.

## Other pending hardware evidence

- Issue #445 / PR #446: Raspberry Pi KK2/Unit 115 field retest remains pending;
- Issue #447 / PR #448: Raspberry Pi perceived-latency acceptance remains pending;
- Issue #389: physical Raspberry Pi version-management acceptance remains pending.

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
