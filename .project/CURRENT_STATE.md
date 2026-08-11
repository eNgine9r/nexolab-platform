# NEXOLAB Current State

Updated: 2026-08-11

Verified repository baseline on `main`: `ba2441a3a5a2dcdfb748b53c2513cb3cbbb6fec4` (PR #373 squash merge).

Active Work Package: Issue #385 / PR #390 — local Raspberry Pi users, administrator-managed permissions and access lifecycle.

Issue #368 / PR #373 is merged. Its telemetry-latest projection is the canonical `20260807_0023` migration. Issue #385 is rebased onto that main and remains the active Work Package until the final state-only checkpoint, exact-head CI and merge complete.

## Issue #385 / PR #390

Implemented product boundary:

- four product roles: `administrator`, `laboratory_manager`, `engineer`, `laboratory_technician`;
- bounded typed permission catalog;
- administrator receives the full canonical permission set implicitly;
- laboratory manager, engineer and laboratory technician use explicit PostgreSQL permission grants;
- local-only authenticated user administration API;
- `/settings/users` Users & Access workspace;
- create, role change, permission change, activate/deactivate, password reset and session revocation flows;
- role, permission, password and account-state changes revoke affected sessions;
- transactional last-active-administrator protection;
- safe immutable audit events without passwords, hashes, tokens or signing material;
- migration `20260807_0024` for explicit membership permissions and the laboratory-technician role, ordered after canonical telemetry `20260807_0023`;
- controlled legacy-role compatibility/backfill without runtime fallback to static legacy permissions.

### Exact software evidence

Frozen software/hardware candidate:

```text
d37cf08af9560ffa0d18c102656301e667299836
base main ba2441a3a5a2dcdfb748b53c2513cb3cbbb6fec4
```

GitHub exact-head verification on this candidate:

```text
19 completed workflows
19 success
0 failures
0 queued
0 in-progress
```

Notable GREEN gates include CI, Telemetry Service, Offline Auth Acceptance, Security Browser Acceptance, Offline Bundle, Disaster Recovery TLS Fleet, Container Supply Chain and all remaining browser/fleet/capacity workflows.

Offline Auth Acceptance on the exact candidate proved:

- all four product roles;
- non-admin server-side denial of administration;
- administrator `memberships.manage` and `project_versions.manage`;
- access-token and refresh-token revocation after permission changes;
- role-change session revocation;
- deactivate/reactivate lifecycle;
- password-reset session revocation, old-password rejection and new-password acceptance;
- last-active-administrator protection;
- audit redaction;
- explicit permission persistence;
- two controlled full-stack recreations;
- internal acceptance networking and blocked container egress;
- production Next.js build.

### Raspberry Pi hardware acceptance

Hardware acceptance is **PASS** on the exact candidate `d37cf08af9560ffa0d18c102656301e667299836`.

Controlled host evidence:

```text
host: nexolab-edge-01
architecture: aarch64 / linux/arm64
OS: Debian GNU/Linux 13.6 (trixie)
kernel: 6.18.39+rpt-rpi-2712
Docker Engine: 29.7.1
candidate SHA: d37cf08af9560ffa0d18c102656301e667299836
```

Runtime acceptance:

```text
Next.js 16.2.12 production build: PASS
local-auth production browser tests: 4 passed
local-auth persistence/recreation test: 1 passed
acceptance subprocess exit_code: 0
```

Evidence directory:

```text
/home/nexolab/nexolab-385-hardware.VGhXYn/evidence-retry-20260811T094325Z
```

The first physical attempt was blocked only by a pre-existing loopback-port collision on `127.0.0.1:18093`. The successful retry used isolated alternative loopback ports; no production service was stopped and no product defect was indicated.

Completion classification:

```text
software verified; Raspberry Pi local user-management acceptance verified
```

### Migration state

Verified linear chain and single head:

```text
20260805_0022
  -> 20260807_0023 telemetry latest projection
  -> 20260807_0024 local membership permissions (head)
```

## Current sequencing

```text
#385 hardware PASS
  -> state-only reconciliation on PR #390
  -> fresh exact-head CI on the state checkpoint
  -> final PR review/base/diff audit
  -> mark PR #390 Ready
  -> squash merge with expected-head lock
  -> verify canonical main
  -> unblock/select #389 administrator-only local NEXOLAB Version Management
```

Issue #389 remains blocked only until PR #390 is merged and `project_versions.manage` is canonical on `main`.

After the selected local administration/version lane, continue the remaining runtime sequence:

```text
#369 -> #366 -> #289
```

Issue #386 remains a prepared Ready chart-domain implementation package and is not selected while the current lane is active.

Issue #245 remains a separate Raspberry Pi validation track.

## Safety and runtime boundary

- profile: `LOCAL_LAN`;
- mandatory cloud identity/services: none;
- runtime internet requirement: none;
- PostgreSQL persistence remains local;
- no Modbus write performed;
- no hardware write performed;
- no polling cadence change performed;
- no telemetry-history deletion performed;
- no named-volume deletion performed;
- no production/site cutover performed;
- no secret material is part of the recorded evidence.

The existing `telemetry-service/libcjson1/CVE-2026-67216` exception still expires on 2026-09-05 and is not broadened by Issue #385.

## Next action

Commit this state-only hardware-acceptance reconciliation to PR #390, require a fresh complete exact-head CI cycle, then perform the final PR audit and squash merge only if every required check remains GREEN.
