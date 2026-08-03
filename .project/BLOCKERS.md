# NEXOLAB Blockers

Updated: 2026-08-03

## Issue #203 — production dependency maintenance

No dependency-maintenance blocker remains.

Completed focused groups:

- #239 / PR #240 — Next.js and React security line;
- #241 / PR #244 — transitive Sharp risk;
- #242 / PR #248 — optional Supabase compatibility with offline-local auth preserved;
- #243 / PR #249 — Lucide operator-semantics review and no-update decision.

Only the state-only reconciliation PR and parent Issue closure remain.

## Issue #204 — major frontend toolchain migrations

No hard blocker prevents planning. Package changes must not begin until a compatibility matrix and migration order exist.

Open dev-tool risk:

- Playwright `1.55.0` advisory remains isolated here and is not a mandatory runtime dependency.

Do not bundle TypeScript, ESLint, Next.js ESLint config, jsdom, lint-staged, Playwright or Node types blindly. Each migration group requires its own Issue, branch, PR and rollback.

## Hard blockers

Stop before:

- destructive database or persistent-volume operations;
- restore over production data without isolated proof and explicit approval;
- production/site cutover without explicit approval;
- Modbus or unsafe hardware writes;
- secret exposure or unauthorized key rotation;
- unresolved materially different product or architecture decisions;
- any operation that cannot preserve local laboratory data.

## Issue #245 — actual Raspberry Pi standalone acceptance

**Status:** Soft blocker after software merge.

Software contracts are merged, but actual-host acceptance still requires controlled physical evidence from the Raspberry Pi 5 with no physical uplink IPv4 or default route, local browser verification, advancing telemetry, service restart and repeated reboot recovery.

Until that evidence exists, use:

```text
software verified; actual standalone Raspberry Pi acceptance pending
```

## Issue #189 recovery status

Software recovery evidence is verified. Actual-host reboot, physical power-loss and physical-media restore remain soft-blocked pending controlled access.

## Open operational and hardware risks

- **N-037 — Sharp compatibility override:** reassess when Next.js supports a patched range.
- **N-023 — Node health/status durability:** not claimed equal to telemetry process-restart durability.
- **N-024 — Rollback compatibility:** preserve named volumes and spool compatibility.
- **N-025 — Spool capacity:** actual-host capacity evidence remains required.
- **N-032 — ARM64 offline bundle evidence:** actual Raspberry Pi 5 archive/load/start/update/rollback remains unverified.
- **N-014 / #200 — Physical RS-485 topology:** hardware blocked.
- **N-015 / #201 — LE-01MP cumulative energy:** hardware blocked.
- **N-016 / #202 — Extended XJP60D semantics:** hardware blocked.
- **N-017 / #17 — Versioned profiles:** blocked until #200–#202 evidence exists.

## Next Ready action

Merge the Issue #203 state reconciliation, close the parent Issue, then begin Issue #204 with planning only: current package inventory, compatibility matrix, migration order and focused child Issues.
