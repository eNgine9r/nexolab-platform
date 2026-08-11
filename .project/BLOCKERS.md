# NEXOLAB Blockers

Updated: 2026-08-11

## Issue #385 — physical acceptance pending

Issue #385 / PR #390 is the selected Work Package after explicit Product Owner reprioritization.

Pre-reconciliation software evidence was verified on product head `b7951011ebc337c23808b1f89deab5a7d99f7208`:

```text
19 completed workflows
19 success
0 failures
0 in-progress
```

Offline Auth Acceptance is GREEN and proves local administrator login, creation of an engineer with explicit `dashboard.read` + `telemetry.read`, engineer login with exactly those effective permissions, and server-side `403` for the engineer against the user-administration API.

Offline Bundle is GREEN and proves disconnected startup plus update/rollback persistent-data preservation.

PR #373 merged as `ba2441a3a5a2dcdfb748b53c2513cb3cbbb6fec4`. The #385 branch is reconciled on that base and its local-membership migration is now `20260807_0024` after canonical telemetry `20260807_0023`. Fresh exact-head CI is required before physical Raspberry Pi acceptance.

The remaining blocker is **physical Raspberry Pi acceptance**, after fresh CI. No hardware/runtime acceptance claim may be made until the controlled Raspberry Pi actually exercises the local Users & Access flow.

This is a hard blocker only if the required Raspberry Pi access/evidence path is unavailable. It is not a software defect.

## Issue #389 — blocked by Issue #385

Issue #389 (administrator-only local NEXOLAB Version Management) depends on the final administrator authorization boundary from #385.

It remains blocked until:

1. #385 controlled Raspberry Pi acceptance is complete;
2. PR #390 remains GREEN and is merged;
3. the merged administrator-only `project_versions.manage` capability is available on `main`.

After those conditions, #389 is the next selected Work Package for this product lane.

## Issue #368 — completed and merged

Issue #368 / PR #373 merged as `ba2441a3a5a2dcdfb748b53c2513cb3cbbb6fec4`. The canonical telemetry latest projection is revision `20260807_0023`; no second `0023` may be introduced.

When the selected lane completes, continue the runtime sequence:

```text
#368 -> #369 -> #366 -> #289
```

## Other known boundaries

- Issue #245 remains a separate Raspberry Pi validation track.
- Issue #386 remains Ready but not selected.
- Issue #257 remains blocked by ESLint 10 ecosystem compatibility.
- Issue #256 remains deferred pending TypeScript 7 ecosystem compatibility.

## Security boundary

The exact `telemetry-service/libcjson1/CVE-2026-67216` exception expires on **2026-09-05**. Issue #385 does not broaden it.

## Global hard-stop rules

Stop before destructive data/volume operations, production/site cutover, Modbus or other hardware writes, secret exposure, mandatory online runtime dependencies, privileged hardware containers or unsupported physical-acceptance claims.
