# NEXOLAB Current State

Updated: 2026-08-08

Verified repository baseline on `main`: `810f6a6b48fc3ce04eeb1174236df3bd5ed53380`

Active Work Package: Issue #385 / PR #390 — local Raspberry Pi users, administrator-managed permissions and access lifecycle.

Product Owner priority decision: the local Users & Access / Version Management lane is selected ahead of the previously active telemetry-latest physical acceptance lane. Issue #368 remains open and blocked/paused; it is not completed or cancelled.

## Issue #385 / PR #390

Software implementation is verified on product head:

```text
b7951011ebc337c23808b1f89deab5a7d99f7208
19 completed workflows
19 success
0 failures
0 in-progress
```

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
- migration `20260807_0023` for explicit membership permissions and the laboratory-technician role;
- controlled legacy-role compatibility/backfill without runtime fallback to static legacy permissions.

### Exact software evidence

Offline Auth Acceptance run `31254031318` is GREEN on `b7951011ebc337c23808b1f89deab5a7d99f7208`.

Artifact:

```text
offline-auth-acceptance-b7951011ebc337c23808b1f89deab5a7d99f7208
sha256:f85b69451e7d5648e9ce9b6cc5112a53564657ed7b0a0fee9e955edf363507e5
```

It proves the disconnected local flow:

```text
administrator login
-> open Users & Access
-> create issue385.engineer
-> role engineer
-> explicit permissions dashboard.read + telemetry.read
-> engineer login
-> session exposes exactly those permissions
-> GET /api/v1/admin/users returns server-side 403 for engineer
```

PostgreSQL migration upgrade and downgrade passed in the same acceptance line.

Offline Bundle run `31254031285` is GREEN on the same product head. It built the linux/amd64 bundle, removed local runtime images, blocked container egress, loaded and started the transferred stack with pulling disabled, and completed update/rollback data-preservation verification.

Artifact:

```text
nexolab-offline-amd64-b7951011ebc337c23808b1f89deab5a7d99f7208
sha256:4a7b0c7eb4ce97fac407848a69c1d4d7e1b704d9666939fa9cedbb8a37281a36
```

The exact-head workflow set also includes GREEN CI, Telemetry Service, Security Browser, Authenticated Dashboard, Reports, Rendered Reports, Alerts, Test Sessions, Refrigeration, Nodes, Broker Control, Device Agent Fleet, MQTT TLS Fleet, Disaster Recovery Browser/TLS, Container Supply Chain and Capacity Release gates.

Completion classification remains:

```text
software verified; Raspberry Pi local user-management acceptance pending
```

No Raspberry Pi acceptance is claimed until the controlled physical runtime is actually exercised.

## Current sequencing

```text
#385 controlled Raspberry Pi local user-management acceptance
  -> final PR #390 audit / merge when hardware evidence is sufficient and checks remain GREEN
  -> #389 administrator-only local NEXOLAB Version Management
```

Issue #389 remains blocked by #385 until the administrator-only authorization capability is physically accepted and merged.

Issue #368 remains blocked/paused by the explicit Product Owner priority decision. After the selected local administration/version lane, reassess and resume the critical runtime sequence:

```text
#368 -> #369 -> #366 -> #289
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
- no secret material is part of the PR evidence.

The existing `telemetry-service/libcjson1/CVE-2026-67216` exception still expires on 2026-09-05 and is not broadened by Issue #385.

## Next action

Run controlled Raspberry Pi acceptance for Issue #385 using the exact software candidate, proving local administrator/user management, explicit grants, session revocation, audit, persistence and offline behavior on the real Raspberry Pi. If physical access is unavailable, record that as the only hard blocker rather than claiming hardware verification.
