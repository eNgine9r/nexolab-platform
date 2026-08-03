# NEXOLAB Blockers

Updated: 2026-08-03

## Active Work Package — Issue #261

No implementation, runtime or hardware blocker prevents software development of the Energy Monitoring page.

Available confirmed scope:

- KK1 energy meters W1–W4 / Unit IDs 200–203;
- existing read-only LE-01MP measurements for voltage, current, frequency, active/reactive/apparent power, power factor and meter temperature;
- existing local telemetry latest/history and authentication foundations;
- standard NEXOLAB application shell.

The page must not show cumulative active energy until Issue #201 confirms the register layout, scale, unit and rollover behavior with actual hardware evidence.

## Product-page priority correction

Seven primary routes currently render generic placeholder screens. Product delivery now has priority over optional toolchain maintenance.

Issues #252–#257 are deferred. They may resume only for:

- a relevant security fix;
- an end-of-support condition;
- a concrete blocker for an active product Work Package.

A newer dependency version by itself is not a reason to interrupt Product Pages Epic #260.

## Proportional verification rule

For a focused page change:

- run touched-file and focused tests during implementation;
- run lint, typecheck and production build at completion;
- run only the directly affected browser/API workflow;
- do not run Offline Bundle unless package, container, Compose, runtime or offline-delivery contracts changed.

## Smart Lockers blocker

The `/lockers` page remains blocked until a concrete locker inventory, read-only protocol and operator workflow are defined. Do not invent production device behavior or present demo controls as completed functionality.

## Hard blockers

Stop before:

- destructive database or persistent-volume operations;
- restore over production data without isolated proof and explicit approval;
- production/site cutover without explicit approval;
- Modbus or unsafe hardware writes;
- secret exposure or unauthorized key rotation;
- unresolved materially different product or architecture decisions;
- any operation that cannot preserve local laboratory data.

## Actual Raspberry Pi and recovery evidence

Issue #245 software is merged, but actual standalone Raspberry Pi acceptance still requires controlled physical evidence.

Use:

```text
software verified; actual standalone Raspberry Pi acceptance pending
```

Issue #189 software recovery evidence is verified. Actual-host reboot, physical power-loss and physical-media restore remain soft-blocked pending controlled access.

## Open operational and hardware risks

- **N-037 — Sharp compatibility override:** reassess only when a supported patched range is available.
- **N-023 — Node health/status durability:** not claimed equal to telemetry process-restart durability.
- **N-024 — Rollback compatibility:** preserve named volumes and spool compatibility.
- **N-025 — Spool capacity:** actual-host capacity evidence remains required.
- **N-032 — ARM64 offline bundle evidence:** actual Raspberry Pi archive/load/start/update/rollback remains unverified.
- **N-014 / #200 — Physical RS-485 topology:** hardware blocked.
- **N-015 / #201 — LE-01MP cumulative energy:** hardware blocked; do not show guessed kWh.
- **N-016 / #202 — Extended XJP60D semantics:** hardware blocked.

## Next Ready action

Implement Issue #261 on `feat/261-energy-monitoring-page`, replacing the `/energy` placeholder with a real operator workflow using confirmed metrics only.
