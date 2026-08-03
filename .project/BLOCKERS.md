# NEXOLAB Blockers

Updated: 2026-08-03

## Issue #242 — optional Supabase compatibility

No product, implementation, offline-runtime or hardware blocker is open for this Work Package.

The required exact-head workflows for candidate `73cf19b2e7191a38290b3dc99fa211bdaf038878` completed GREEN, including CI, Security Browser, Offline Auth, Authenticated Dashboard and disconnected Offline Bundle with update/rollback volume preservation.

A state-only follow-up commit records the completed checks. Merge remains gated only by:

- exact-head GREEN workflows for the state-only commit;
- resolution of the review thread;
- expected-head merge protection.

## Hard blockers

No hard blocker prevents completing PR #248 or beginning the next independent software Work Package after merge.

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

Complete the state-only exact-head checks, resolve the PR #248 review thread and merge with expected-head protection. Then record the actual merge SHA and begin Issue #243.
