# NEXOLAB Current State

Updated: 2026-08-03
Verified main baseline: `47d5124fd96f54800cf7347ff672297a1d421526`
Active Work Package: Issue #261 — Energy Monitoring implementation complete, exact-head validation pending
Parent Product Epic: Issue #260 — complete all NEXOLAB operator pages
Next Ready Work Package: Issue #263 — Live Data telemetry explorer
Status confidence: high for repository route inventory, implemented energy scope, focused CI/browser evidence and review findings.

## Completed baseline

Issue #251 merged through PR #259 as `47d5124fd96f54800cf7347ff672297a1d421526` with all exact-head quality, browser and offline gates GREEN.

This baseline is sufficient for product delivery. Optional toolchain migrations #252–#257 remain deferred unless they become a security, support or concrete product-delivery blocker.

## Product route status

Implemented workflow routes:

- `/` — Overview dashboard;
- `/nodes` — Nodes;
- `/sessions` — Test sessions;
- `/refrigeration` — Refrigeration equipment;
- `/alerts` — Alerts;
- `/reports` — Reports;
- `/energy` — LE-01MP Energy Monitoring candidate in PR #262.

Remaining placeholder routes:

- `/live` — Live data, tracked by Issue #263;
- `/equipment-layouts` — Equipment layouts;
- `/lockers` — Smart lockers, blocked pending inventory/protocol scope;
- `/cameras` — Cameras;
- `/equipment` — Equipment registry;
- `/settings` — Settings.

Epic #260 owns focused replacement of the remaining six placeholder routes.

## Issue #261 implementation outcome

PR #262 replaces the `/energy` placeholder with an authenticated operator workspace for KK1 LE-01MP meters W1–W4.

Delivered behavior:

- deterministic W1–W4 cards for Unit IDs 200–203;
- confirmed latest values for voltage, current, frequency, active/reactive/apparent power, power factor and meter temperature;
- authenticated local REST snapshot and WebSocket live updates;
- complete paginated PostgreSQL history for the selected 1h/6h/24h window;
- bounded per-meter downsampling that preserves the first and last points of the complete window;
- meter and metric comparison controls;
- explicit loading, empty, stale, offline, communication-error, permission-denied and configuration states;
- stale card readings are suppressed while the detailed table retains per-metric quality labels;
- no silent demo fallback in live mode;
- explicit evidence boundary: cumulative energy/kWh remains unavailable pending hardware Issue #201.

No package, Compose, container, database migration, Modbus, production deployment or hardware action is part of the Work Package.

## Verification evidence

Confirmed on pre-review-fix head `cb4aa8af499d64859df46d8895bd3f07a3b400ac`:

- formatting GREEN;
- ESLint GREEN;
- strict TypeScript GREEN;
- 190 unit/component tests GREEN;
- production build GREEN;
- Authenticated Dashboard Acceptance GREEN with energy latest, history, meter selection, live WebSocket update and screenshot evidence.

Review then identified two product defects:

- incomplete first-page-only history;
- mixed-freshness meter cards labelled Live.

Both defects are corrected in the current branch. Final exact-head quality and authenticated browser validation remain required before merge.

## Verification policy

Tests support product delivery; they are not an independent roadmap.

For page Work Packages:

1. touched-file checks and focused tests during implementation;
2. lint, typecheck and production build at completion;
3. only the directly affected browser/API acceptance;
4. Offline Bundle only when package, container, Compose, runtime or offline-delivery contracts change.

Broad existing path filters may start unrelated workflows, but they do not expand the Work Package merge gate.

## Runtime and hardware status

```text
energy page software implemented; exact-head validation pending; hardware unchanged and unverified for cumulative energy
```

Actual Raspberry Pi standalone acceptance for #245, physical recovery evidence for #189 and hardware investigations #200–#202 remain soft-blocked by controlled hardware access. No Modbus or hardware write is authorized.

## Next Ready Work Package

After PR #262 merges, start Issue #263 — replace `/live` with the universal authenticated telemetry explorer. Do not resume deferred toolchain maintenance between product pages.
