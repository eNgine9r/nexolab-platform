# NEXOLAB Blockers

Updated: 2026-08-03

## Issue #243 — Lucide operator-semantics compatibility

No product, implementation, security, accessibility, offline-runtime or hardware blocker is open.

Decision: retain `lucide-react ^1.25.0` with lockfile resolution `1.26.0`.

The published npm candidate `1.27.0` changes the SVG geometry of `Zap`, which NEXOLAB uses for the persistent **Енергомоніторинг** navigation item and its page icon. No security advisory, runtime compatibility fix or product requirement justifies that operator-facing visual change.

A focused regression test now locks:

- `Zap → Енергомоніторинг → /energy`;
- explicit accessible naming for icon-only refrigeration controls;
- default `40 px` icon-button sizing;
- keyboard focus outline behavior.

Merge remains gated only by normal software controls:

- exact-head repository formatting, ESLint, strict TypeScript, Vitest and production build;
- relevant browser acceptance for refrigeration, security, dashboard, nodes, sessions, alerts and reports;
- Offline Bundle disconnected startup and update/rollback volume preservation;
- clean review audit and expected-head merge protection.

## Hard blockers

No hard blocker prevents completing Issue #243.

Stop before:

- destructive database or persistent-volume operations;
- restore over production data without isolated proof and explicit approval;
- production/site cutover without explicit approval;
- Modbus or unsafe hardware writes;
- secret exposure or unauthorized key rotation;
- unresolved materially different product or architecture decisions;
- any operation that cannot preserve local laboratory data.

## Issue #245 — standalone offline Raspberry Pi runtime

### N-039 — Actual Raspberry Pi loopback-only acceptance

**Status:** Soft blocker after software merge.

Software contracts are verified and merged in PR #246, but actual-host acceptance still requires controlled physical evidence from the intended Raspberry Pi 5:

- deploy `main` with `--runtime-mode standalone`;
- disconnect Ethernet and Wi-Fi;
- confirm no default route and no IPv4 on physical uplinks;
- reboot without reconnecting networking;
- open `http://127.0.0.1:3000` in the locally attached browser;
- verify Security Gate, REST, WebSocket, Device Agent, MQTT, PostgreSQL and MinIO;
- prove real telemetry advances for at least 15 minutes;
- restart Telemetry Service and verify no silent loss;
- reboot again and verify runtime and persistent data recover.

Until that evidence exists, use:

```text
software verified; actual standalone Raspberry Pi acceptance pending
```

## Active production dependency risks

### N-037 — Temporary `sharp 0.35.3` compatibility control

**Status:** Merged in PR #244.

The production advisory path is removed, but the override exceeds the Next.js 16.2.12 declared optional range. Reassess or remove it when Next.js publishes a supported patched range.

### N-038 — Playwright `1.55.0` dev-tool advisory

**Status:** Open and isolated under Issue #204. It is not a mandatory runtime dependency.

## Issue #189 recovery status

Software recovery evidence is verified. Actual-host reboot, physical power-loss and physical-media restore remain soft-blocked pending controlled access.

## Open operational and hardware risks

- **N-023 — Node health/status durability:** not claimed equal to telemetry process-restart durability.
- **N-024 — Rollback compatibility:** preserve named volumes and spool compatibility.
- **N-025 — Spool capacity:** actual-host capacity evidence remains required.
- **N-032 — ARM64 offline bundle evidence:** actual Raspberry Pi 5 archive/load/start/update/rollback remains unverified and is outside Issue #245.
- **N-014 / #200 — Physical RS-485 topology:** hardware blocked.
- **N-015 / #201 — LE-01MP cumulative energy:** hardware blocked.
- **N-016 / #202 — Extended XJP60D semantics:** hardware blocked.
- **N-017 / #17 — Versioned profiles:** blocked until #200–#202 evidence exists.

## Next Ready action

Run the exact-head PR #249 CI/browser/offline cascade, perform review audit and merge only on GREEN. Then reconcile parent Issue #203 and select the next independent Ready software Work Package.
