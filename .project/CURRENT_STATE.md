# NEXOLAB Current State

Updated: 2026-08-11

Canonical product baseline on `main`: `e0b124e9a0152be50966daa131974b3543651e87` — PR #390 squash merge, closing Issue #385.

## Completed Work Package — Issue #385

Issue #385 / PR #390 is completed and merged.

Delivered:

- four product roles: `administrator`, `laboratory_manager`, `engineer`, `laboratory_technician`;
- local-only Users & Access workspace at `/settings/users`;
- bounded server-authoritative permission catalog;
- administrator full access including `memberships.manage` and `project_versions.manage`;
- explicit persisted permissions for non-administrator product roles;
- role/permission/account/password lifecycle with affected-session revocation;
- transactional last-active-administrator protection;
- immutable redacted security audit events;
- offline-local authentication and user management without mandatory cloud identity;
- canonical migration `20260807_0024` after telemetry latest projection `20260807_0023`.

Verification:

```text
final PR head: 5d4aacc8d6d2c7157ef42bf0356d102700f78960
PR #390 merge: e0b124e9a0152be50966daa131974b3543651e87
final exact-head CI: 19/19 GREEN
hardware-tested product candidate: d37cf08af9560ffa0d18c102656301e667299836
Raspberry Pi: PASS, aarch64 / Debian 13.6 / Docker 29.7.1
production browser acceptance: 4 passed
persistence/recreation acceptance: 1 passed
acceptance exit_code: 0
```

Hardware evidence directory:

```text
/home/nexolab/nexolab-385-hardware.VGhXYn/evidence-retry-20260811T094325Z
```

No Modbus write, hardware write, production/site cutover, named-volume deletion or mandatory online runtime dependency was introduced.

Canonical Alembic chain:

```text
20260805_0022
  -> 20260807_0023 telemetry latest projection
  -> 20260807_0024 local membership permissions (head)
```

## Selected Next Work Package — Issue #389

Issue #389 — administrator-only local NEXOLAB version management and safe update/rollback — is now `status:ready` because its #385 authorization dependency is canonical on `main`.

The next step is discovery and implementation-readiness review before code changes:

- inventory existing deploy/update/rollback scripts;
- inventory offline bundle/release evidence contracts;
- identify the trustworthy local version/SHA source;
- map backup, migration-before-readiness and rollback compatibility gates;
- preserve named volumes and edge SQLite;
- define the smallest administrator-only API/UI wrapper around existing deployment contracts;
- keep GitHub/internet optional rather than mandatory at runtime.

Do not create a second deployment engine and do not expose arbitrary shell, arbitrary Git branch switching, destructive database downgrade, Modbus writes or unattended site cutover.

After the selected local version-management lane, continue the prepared runtime sequence:

```text
#369 -> #366 -> #289
```

Issue #386 remains Ready but not selected. Issue #245 remains a separate Raspberry Pi validation track.

## Security boundary

The existing `telemetry-service/libcjson1/CVE-2026-67216` exception still expires on 2026-09-05 and was not broadened by Issue #385.

## Next action

Complete this post-merge state-only reconciliation, then begin Issue #389 repository inventory and implementation-readiness work from the reconciled `main` baseline.
