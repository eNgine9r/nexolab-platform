# NEXOLAB verified roadmap

**Baseline date:** 2026-07-31  
**Verified `main`:** `8371ee59e76e64963405706be79fc4a909f9fac9`

This roadmap is derived from current code, configuration, GitHub Issues, Pull Requests and available evidence. It replaces page-by-page planning with vertical operator/system outcomes.

## 1. Verified milestone boundary

| Boundary | Repository implementation | Operational/hardware acceptance |
| --- | --- | --- |
| Development operating standard | Complete in PR #184 | Process is active; compliance is evaluated per Work Package |
| Read-only RS-485 acquisition | Production drivers exist for the narrow 34-series scope | Smoke and soak evidence exists for XJP60D `106-03`, `106-04` and LE-01MP `200–203`; broader register/hardware scope remains open |
| Single edge continuity | SQLite outbox, local MQTT, QoS 1, health and restart logic exist | MQTT outage/reconnect/drain and Device Agent restart are evidenced for the narrow scope; power-loss/site-duration evidence is not complete |
| Central telemetry platform | MQTT ingestion, PostgreSQL, REST, WebSocket, retention, metrics and local MinIO exist | Actual-host backup/restore/rollback and full outage evidence are incomplete |
| Live dashboard | Typed live clients and explicit states exist; no silent demo fallback is allowed | Current site/browser state depends on environment; PR #175 identifies an active defect |
| Laboratory sessions | Domain, persistence, API, UI, attribution, audit and recovery harness exist | Issue #82 is closed, but parent tracker #74 is stale and must be reconciled |
| Refrigeration and climate catalog | Equipment lifecycle, KK1/KK2 catalog, layouts, sensor binding and image workflows exist | PR #175 remains a draft, non-mergeable correction for live connection and KK2 availability |
| Alerts, reports and nodes | Substantial code and browser acceptance tooling exist | Not equivalent to full offline/site recovery acceptance |
| Production security | JWT/RBAC/audit foundations exist; Supabase is optional | Secure offline operator authentication is not yet accepted |
| Offline installation/update | Local runtime topology exists | Clean disconnected installation/update bundle is missing |
| Backup/restore/rollback | Runbooks and focused scripts exist | One consolidated current-host acceptance package is missing |

## 2. Current Work Package

### Issue #183 — architecture, roadmap and offline reconciliation

Outcome:

- replace stale architecture text with a code-backed baseline;
- classify local, optional online, development-only and prohibited dependencies;
- separate implementation from actual acceptance;
- create an ordered Work Package queue;
- update project state and blockers.

No runtime code, migration, Modbus operation or production cutover belongs in this Work Package.

## 3. Ordered next Work Packages

### 1. Issue #186 — reconcile stale trackers and superseded PRs

**Status:** Ready after #183.

This is the next source-of-truth task. It must:

- reconcile open milestone trackers with closed children;
- classify every open PR;
- close superseded branches rather than merge them blindly;
- preserve residual hardware gaps;
- decide whether PR #175 is rebased or recreated as a clean defect Work Package.

### 2. Critical live/KK2 defect currently represented by PR #175

**Status:** Blocked on #186 classification.

PR #175 is draft and non-mergeable against current `main`. Its intended operator outcome remains important:

- configured KK2 channels remain selectable without latest telemetry;
- stale values are not presented as live;
- transient WebSocket failures recover correctly;
- authorization/configuration errors are distinct from generic offline state.

The work must continue only after #186 creates or confirms one clean Issue/branch boundary.

### 3. Issue #187 — verified offline installation and update bundle

**Status:** Ready after #183; schedule after source-of-truth cleanup and any critical defect interruption.

Outcome: install, start, update and roll back the LOCAL_LAN core from a checksummed local artifact bundle without registry or package-manager access.

### 4. Issue #188 — offline operator authentication

**Status:** Ready for architecture/discovery after #183.

Outcome: select and prove a fail-closed local login, token, RBAC and recovery lifecycle. Supabase and external JWKS remain optional.

### 5. Issue #189 — backup, restore, rollback and power-loss recovery

**Status:** Software preparation Ready; final acceptance blocked on controlled central/Raspberry Pi access.

Outcome: one evidence package covering PostgreSQL, MinIO, MQTT, edge SQLite, host restart, update rollback and approved power interruption.

### 6. Issue #185 — controlled formatting baseline

**Status:** Separate maintenance track.

It must not be mixed with product, architecture, offline or recovery Work Packages.

## 4. Open Pull Request classification at baseline

| PR | Baseline classification | Required next action |
| --- | --- | --- |
| #175 | Current defect intent, draft, non-mergeable | #186 must rebase/recreate or close with a replacement Issue |
| #53 | Very old M3 branch, non-mergeable, scope largely present in later `main` | Candidate for superseded closure after unique-diff review |
| #109 | Old Tailscale acceptance branch, draft, non-mergeable, requires actual-host evidence | Extract still-needed evidence scope into current Work Package or close as superseded |
| #111 | Old auth/RBAC branch, draft, non-mergeable, overlaps later security code | Compare unique work with `main`; use #188 for remaining offline-auth outcome |
| #159 | Dependabot production dependency group | Handle independently after compatibility/security review |
| #160 | Dependabot development dependency group with major upgrades | Do not merge as one blind group; split/review compatibility |
| #1 | GitHub Action dependency update | Maintenance-only review |
| #2 | GitHub Action dependency update | Maintenance-only review |
| #184 | Merged | Squash commit `8371ee59e76e64963405706be79fc4a909f9fac9` |

## 5. Stale or ambiguous Issue boundaries

### M1 register mapping

Issues #11–#18 remain open, but later code and evidence prove part of their intended outcome. They must not all be marked complete wholesale.

Verified:

- narrow XJP60D channels `106-03`, `106-04`;
- LE-01MP operational metrics used in the 34-series cycle;
- read-only FC03 production drivers;
- combined smoke and soak.

Still residual or explicitly excluded:

- LE-01MP cumulative-energy register `7`;
- full portability across all historical XJP60D Unit IDs/channels;
- all setpoint/alarm/input/output semantics originally requested;
- additional buses/firmware variants;
- broader power-cycle and site evidence.

Issue #186 must split or update this tracker honestly.

### M4 session tracker

Issue #74 marks #82 as active, but #82 is closed as completed. The parent tracker must be updated after verifying the evidence boundary; closure metadata alone must not be used to invent missing artifacts.

### Refrigeration foundation

Issue #94 remains open although later merged work appears to include image-backed layouts and broader lifecycle features. It requires supersession review under #186.

## 6. Product sequencing rule

No new broad product feature starts until:

1. Issue #183 is merged;
2. Issue #186 restores GitHub as a reliable source of truth;
3. any critical live defect is represented by one clean Issue/branch;
4. offline installation and authentication dependencies are scheduled explicitly.

After these foundations, product work continues as complete vertical outcomes across UI, API, data, edge, deployment and recovery—not as disconnected page changes.

## 7. Definition of a completed milestone

A milestone is complete only when all required layers have evidence:

- implementation and migrations;
- module and integration checks;
- production build;
- browser/API acceptance;
- offline dependency review;
- backup/update/rollback impact;
- real hardware or controlled-host evidence where applicable;
- updated Issues, state files and checkpoint.

Missing hardware, site, backup, restore or power-loss evidence remains unverified.
