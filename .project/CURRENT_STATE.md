# NEXOLAB Current State

Updated: 2026-08-03
Verified main baseline: `47d5124fd96f54800cf7347ff672297a1d421526`
Active Work Package: Issue #261 — complete the Energy Monitoring operator page
Parent Product Epic: Issue #260 — complete all NEXOLAB operator pages
Status confidence: high for the main route audit, merged Node/offline baseline and current GitHub Issue/branch state.

## Completed baseline

Issue #251 merged through PR #259 as `47d5124fd96f54800cf7347ff672297a1d421526`.

Verified outcomes:

- developer and GitHub Actions Node baseline: `22.23.1`;
- supported package engine: `>=22.22.1 <23 || >=24 <25`;
- Node source declarations: `@types/node 22.20.1`;
- all 11 exact-head workflows GREEN;
- disconnected startup GREEN;
- offline update/rollback persistent-volume preservation GREEN;
- review threads resolved;
- Issue #251 closed as completed.

This baseline is sufficient for continued product development. Further toolchain upgrades #252–#257 are deferred unless they become a security, support or concrete product-delivery blocker.

## Product route audit

The main navigation contains 13 routes.

Implemented workflow routes:

- `/` — Overview dashboard;
- `/nodes` — Nodes;
- `/sessions` — Test sessions;
- `/refrigeration` — Refrigeration equipment;
- `/alerts` — Alerts;
- `/reports` — Reports.

Placeholder routes:

- `/live` — Live data;
- `/equipment-layouts` — Equipment layouts;
- `/lockers` — Smart lockers;
- `/cameras` — Cameras;
- `/energy` — Energy monitoring;
- `/equipment` — Equipment registry;
- `/settings` — Settings.

Epic #260 owns replacement of all seven placeholder routes with focused product Work Packages.

## Active outcome — Issue #261

Replace the `/energy` placeholder with a real operator workspace for KK1 LE-01MP meters W1–W4.

Confirmed existing data scope:

- voltage;
- current;
- frequency;
- active power;
- reactive power;
- apparent power;
- power factor;
- meter temperature;
- telemetry quality and capture time;
- latest and history contracts.

Cumulative active energy remains explicitly unavailable until Issue #201 provides physical register, scale and rollover evidence. No guessed `kWh` value is permitted.

## Verification policy

Tests support product delivery; they are not an independent roadmap.

For page Work Packages:

1. run touched-file checks and focused tests during implementation;
2. run lint, typecheck and production build at completion;
3. run only the directly affected browser/API acceptance;
4. run Offline Bundle only when package, container, Compose, runtime or offline-delivery contracts change.

Do not trigger every browser workflow for a presentation-only page change.

## Runtime and hardware status

```text
core software and offline baseline verified; active work is product UI; no hardware operation performed
```

Actual Raspberry Pi standalone acceptance for #245, physical recovery evidence for #189 and hardware investigations #200–#202 remain soft-blocked by controlled hardware access. No Modbus or hardware write is authorized.

## Next Ready Work Packages

Ordered under Epic #260:

1. #261 — Energy Monitoring operator page;
2. Live Data telemetry explorer;
3. Equipment Layouts catalog;
4. Equipment and metrology registry;
5. Settings;
6. Cameras;
7. Smart lockers after concrete hardware/protocol scope exists.
