# NEXOLAB Blockers

Updated: 2026-08-03

## Issue #251 — Node 22 baseline and type definitions

No product, implementation, runtime or hardware blocker is open.

The focused candidate uses:

```text
Node exact: 22.23.1
Node engine: >=22.22.1 <23
@types/node: 22.20.1
undici-types: 6.21.0
```

Merge remains gated by:

- exact Node version evidence;
- deterministic dependency installation;
- formatting, lint, strict typecheck, full tests and production build;
- all triggered browser acceptance workflows;
- Offline Bundle disconnected startup and update/rollback volume preservation;
- clean review audit and expected-head merge protection.

## Toolchain dependency changes after #251

- #254 Playwright becomes the next ordered Ready Work Package after #251 merges.
- #252 lint-staged becomes technically unblocked because the Node floor satisfies v17, but remains ordered after #254.
- #253 jsdom remains queued after the Node baseline.
- #256 TypeScript 7 and #257 ESLint 10 remain blocked by their separate compatibility gates.

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

## Next Ready action

Open the Issue #251 PR, run exact-head CI/browser/offline acceptance, perform review audit and merge only on GREEN. Then start Issue #254.
