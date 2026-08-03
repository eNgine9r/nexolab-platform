# NEXOLAB Blockers

Updated: 2026-08-03

## Active Work Package — Issue #261

The Energy Monitoring implementation is complete in PR #262. No product, runtime or hardware blocker prevents final software validation and merge.

Remaining merge gates:

- final exact-head formatting, ESLint, strict TypeScript, unit/component tests and production build;
- final exact-head Authenticated Dashboard Acceptance including the energy operator flow;
- resolved review threads;
- expected-head merge protection.

The complete energy page uses confirmed read-only LE-01MP metrics for KK1 meters W1-W4. It must not show cumulative active energy until Issue #201 confirms the register layout, scale, unit and rollover behavior with actual hardware evidence.

## Review corrections

PR #262 review identified and corrected:

- first-page-only telemetry history, which could misrepresent 1h, 6h and 24h windows;
- mixed-freshness meter cards, which could remain labelled Live while a secondary value was stale;
- stale project state that did not advance the Product Pages Sprint.

History now follows every `next_offset`, deduplicates samples and downsamples each meter only after the complete selected window is loaded. Meter cards use fresh samples only; the detailed matrix retains per-metric quality labels.

## Product-page priority correction

Six primary routes remain placeholders after `/energy`:

- `/live` — next Ready Work Package #263;
- `/equipment-layouts`;
- `/lockers`;
- `/cameras`;
- `/equipment`;
- `/settings`.

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
- do not require Offline Bundle unless package, container, Compose, runtime or offline-delivery contracts changed.

Existing broad path filters may start unrelated workflows. Those runs are CI-policy debt and do not expand the product Work Package merge gate unless they reveal an actual regression in changed code.

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

Finish the exact-head merge gates for PR #262. After merge, start Issue #263 and replace `/live` with the universal authenticated telemetry explorer.
