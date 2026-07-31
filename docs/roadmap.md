# NEXOLAB verified roadmap

**Baseline date:** 2026-08-01  
**Verified `main`:** `01f2a5fcfc929127d4a7b3d9c068944cd65d8636`

This roadmap is derived from current code, merged Pull Requests, open Issues and retained evidence. It separates implementation, software acceptance, actual-host acceptance and real-hardware acceptance.

## 1. Verified platform boundary

### Complete repository foundations

- AI Development Operating Standard and `LOCAL_LAN` profile — PR #184.
- Verified architecture, offline dependency and recovery boundary — PR #190.
- Read-only XJP60D and LE-01MP production drivers for the narrow pilot scope.
- Central MQTT, PostgreSQL, REST, WebSocket, retention, metrics and local MinIO.
- Live dashboard, laboratory sessions, alerts, reports, nodes, refrigeration lifecycle and KK1/KK2 catalog.
- Encrypted fresh-volume central software recovery for PostgreSQL, MinIO and Mosquitto — PR #144.
- Scoped M4 laboratory-session workflow — tracker #74 closed with explicit exclusions.

### Verified real-hardware scope

The retained 2026-07-23 evidence covers only:

- XJP60D `106-03` and `106-04`;
- LE-01MP `200–203`;
- 34 records per complete polling cycle;
- edge MQTT interruption, SQLite queue growth, reconnect and drain;
- Device Agent restart and rollback to simulator;
- no established Modbus write, CRC or serial failure.

### Confirmed gaps

- MQTT broker acknowledgement is not yet end-to-end PostgreSQL durability — #198.
- Live WebSocket lifecycle still needs a clean current-main bugfix — #199.
- Clean disconnected installation/update bundle — #187.
- Fully local production operator identity — #188.
- Actual-host, off-host, edge and power-loss recovery — #189.
- Full physical RS-485 topology and portable polling envelope — #200.
- LE-01MP cumulative energy — #201.
- Extended XJP60D semantics and firmware portability — #202.

## 2. Current Work Package

### Issue #186 — GitHub source-of-truth reconciliation

Outcome completed in the feature branch:

- every open Pull Request classified;
- obsolete/non-mergeable PRs closed with a recorded successor or owning Issue;
- stale M4 and refrigeration trackers corrected;
- mixed historical M1 work split into evidence-backed residual Issues;
- grouped dependency PRs replaced by focused maintenance Work Packages;
- one ordered Ready/queued/blocked Sprint state established.

No runtime code, migration, dependency, production deployment or hardware operation belongs in #186.

## 3. Primary product and platform sequence

### 1. Issue #198 — durable MQTT-to-PostgreSQL handoff

**Priority:** first after #186.

Implement a local durable central staging/replay boundary so a PostgreSQL outage plus Telemetry Service restart cannot silently lose telemetry already acknowledged by MQTT.

### 2. Issue #199 — live WebSocket lifecycle and operator states

**Priority:** critical bug after the data-integrity boundary is scheduled or complete.

Implement from current `main`. PR #175 is closed and may be used only as reference. KK2 catalog availability is already present in `main` and remains out of scope.

### 3. Issue #187 — offline installation and update bundle

Produce checksummed local OCI artifacts and prove install/update/rollback on a clean disconnected supported host.

### 4. Issue #188 — offline operator authentication

Select and prove a fail-closed local identity, token, RBAC, bootstrap and recovery lifecycle. Supabase and external JWKS remain optional.

### 5. Issue #189 — operational and hardware recovery

Extend verified PR #144 software recovery with #198 durability, actual-host scheduling, encrypted off-host copies, edge SQLite, host restart, update rollback, disk-loss and approved power-interruption evidence.

## 4. Residual read-only hardware sequence

These Work Packages remain hardware blocked and do not delay software-only #198/#199/#187/#188:

1. #200 — physical RS-485 topology, stable paths, Unit IDs, termination/biasing, latency and safe polling.
2. #201 — LE-01MP cumulative energy register, scale, unit and rollover.
3. #202 — XJP60D portability, Unit ID `115` reality, extended alarm/setpoint/input/output semantics.
4. #17 — versioned profiles and register-map documentation after #200–#202.

Historical Issues #11–#15 and tracker #18 are closed as superseded. Issue #16 remains completed as the evidence standard.

## 5. Maintenance tracks

Maintenance stays separate from the primary product/data-integrity Work Package.

- #185 / #191 / draft PR #192 — controlled Prettier baseline and grouped formatting Issues #193–#197.
- #203 — focused production dependency updates; grouped PR #159 is closed.
- #204 — separate major TypeScript/ESLint/jsdom/lint-staged/Playwright migrations; grouped PR #160 is closed.
- #205 — combined GitHub Actions checkout/setup-node v7 compatibility and security review; PRs #1/#2 are closed.

## 6. Pull Request source of truth

### Only open PR

- #192 — valid draft formatting inventory. Keep draft until rebased or recreated from the post-#186 `main`, project state is updated, the inventory is refreshed if materially stale and standard CI is green.

### Closed as superseded during #186

- #53 — obsolete fixture-era M3 deployment/client branch.
- #109 — stale optional Tailscale branch; outcome remains open and blocked in #108.
- #111 — obsolete parallel auth/RBAC branch; offline identity remains #188.
- #175 — stale mixed defect branch; focused WebSocket bug is #199.
- #159 — grouped production dependencies; owner #203.
- #160 — grouped major development dependencies; owner #204.
- #1 and #2 — independent action v7 branches; owner #205.

No code from these branches was merged by their closure.

## 7. Tracker reconciliation

- #74 is closed completed for the scoped M4 session workflow; #198 and #189 remain explicit exclusions.
- #94 is closed because current `main` contains and surpasses its photo-backed layout-editor foundation, although historical PR #96 itself was not merged.
- #108 remains open and blocked for optional Tailscale actual-host/operator-workstation acceptance.
- #11–#15/#18 are closed as superseded, not treated as fully accepted hardware.
- #17 is updated and blocked on #200–#202.

## 8. Sequencing rules

- One primary Work Package at a time.
- A task starts only after its dependencies are `done`; `review` is not sufficient.
- Critical data integrity (#198) precedes broad product work.
- Hardware-blocked tasks do not block independent software Work Packages.
- Formatting, dependency and CI-action maintenance never shares a PR with product/runtime work.
- Optional remote access never becomes mandatory for the local LAN runtime.

## 9. Definition of a completed milestone

A milestone is complete only when its required layers have evidence:

- implementation and migrations;
- targeted/module/integration checks;
- production build;
- browser/API acceptance where applicable;
- offline dependency review;
- backup/update/rollback impact;
- actual-host or real-hardware evidence where required;
- updated Issues, state files and checkpoint.

Missing site, hardware, durability, backup, restore or power-loss evidence remains unverified.
