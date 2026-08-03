# NEXOLAB Blockers

Updated: 2026-08-03

## Issue #204 — frontend toolchain migration planning

No hard blocker prevents completing the planning Pull Request.

The grouped Dependabot PR #160 is superseded by focused child Issues #251–#257.

## Ready and queued toolchain work

- **#251 — Ready:** align Node 22 developer/CI baseline and Node 22 type definitions.
- **#254 — Queued after #251:** Playwright browser/evidence migration.
- **#253 — Queued after #251:** jsdom unit-test DOM migration.
- **#255 — Queued after independent tool migrations:** TypeScript 6 transition.

## Toolchain blockers

### #252 — lint-staged 17

Blocked by #251.

Reason: lint-staged 17 requires Node 22.22.1 or newer, while the repository currently declares `node >=22.0.0` and uses a broad `.nvmrc` selector.

### #256 — TypeScript 7

Blocked by #255 and confirmed ecosystem support.

Reason: direct `5.9.3 → 7.0.2` migration is not accepted. TypeScript 6 must provide a verified transition baseline, and Next.js, Vitest/Vite and ESLint integrations must support the chosen TypeScript 7 line.

### #257 — ESLint 10

Blocked by the current resolved Next plugin graph.

Reason: `eslint-plugin-import 2.32.0` declares peer compatibility only through ESLint 9. Do not install ESLint 10 until every resolved plugin declares support.

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

Merge the Issue #204 planning PR after exact-head CI and review, keep #204 open as the tracking parent, then start Issue #251 on its own feature branch.
