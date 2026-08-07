# NEXOLAB Current State

Updated: 2026-08-07
Verified product baseline on `main`: `a47f0674c8d6dadae2f6858b093006deb183d19c`
Active completion Work Package: Issue #357 / PR #364 — immediate refrigeration structural snapshot hydration
Verified implementation head: `145bf02210393269622d0422aeba3bcba8b7f361`
Active epic: Issue #326 — Engineering governance, critical operator defects and toolchain hardening
Parallel hardware/runtime track: Issue #282

## Issue #357 software completion

PR #364 implements the completion slice after PR #363:

- one organization/equipment-scoped read-only structural snapshot;
- equipment identity, active image metadata, layout draft/revision, placements, active bindings and canonical channels in one composition path;
- configured channels without current telemetry remain visible with explicit `unknown`/`stale` state;
- bounded organization-scoped stale-while-revalidate cache with concurrent request deduplication and equipment-targeted invalidation;
- retained valid image/layout/markers during background reconciliation and route transitions;
- structural rendering no longer depends on telemetry-history latency;
- refrigeration route and detail reconciliation loops that repeatedly remounted authorization/layout state were removed;
- production browser readiness uses concrete UI assertions rather than global `networkidle`;
- canonical climate-chamber catalog resolution supports restored equipment without a direct `node_id`;
- no database migration, dependency upgrade, acquisition scheduler change, Device Agent configuration change, Modbus write, hardware write or site cutover occurred.

## Exact-head verification

Implementation head `145bf02210393269622d0422aeba3bcba8b7f361` is GREEN for all triggered workflows:

- CI;
- Refrigeration Browser Acceptance;
- Security Browser Acceptance;
- Authenticated Dashboard Acceptance;
- Offline Auth Acceptance;
- Offline Bundle;
- Telemetry service;
- Disaster Recovery Browser;
- Disaster Recovery Domain Completeness;
- Disaster Recovery TLS Fleet;
- Container Supply Chain;
- Device Agent Fleet Acceptance;
- MQTT TLS Fleet Acceptance;
- Broker Control Acceptance;
- Capacity Release Gate;
- Nodes Browser Acceptance;
- Alerts Browser Acceptance;
- Reports Browser Acceptance;
- Rendered Reports Browser Acceptance.

CI includes repository formatting, ESLint, strict TypeScript, Vitest and production build. Review-thread audit reports zero unresolved threads.

## Completion classification

Software acceptance is complete. Real Raspberry Pi perceived-latency acceptance remains a separate physical evidence requirement:

```text
software verified; Raspberry Pi perceived-latency acceptance pending
```

This pending physical acceptance does not authorize a hardware-complete claim and does not permit Modbus writes, hardware writes or production/site cutover.

## Merge state

PR #364 is mergeable and ready for final state-only exact-head verification after this reconciliation commit. Merge is permitted only after the reconciliation head is GREEN and the final diff/review audit remains clean.

## Ordered queue

1. **Issue #357 — software complete, merge pending:** finalize state reconciliation, GREEN exact-head audit, Ready transition and squash merge PR #364.
2. **Issue #245 — Ready parallel runtime track:** standalone offline Raspberry Pi loopback operation; physical acceptance remains required.
3. **Issue #257 — blocked:** ESLint 10 migration.
4. **Issue #256 — deferred:** TypeScript 7 native compiler transition.

The next product-visible Work Package must be selected from current GitHub/Sprint state after #357 merges; do not infer a successor Issue from chat history alone.

## Security and hardware boundaries

The exact `telemetry-service + libcjson1 + CVE-2026-67216` exception expires on **2026-09-05** and remains unbroadened.

Issue #355 remains `software verified; Raspberry Pi runtime latency acceptance pending`. Hardware-dependent Issues #289, #245, #189, #200, #201 and #202 still require controlled Raspberry Pi/RS-485 evidence.

## Next action

Run exact-head verification for the state-reconciliation commit, audit PR #364 diff/mergeability/reviews, mark Ready, squash merge, verify `main`, close Issue #357 as software-complete, and retain Raspberry Pi perceived-latency acceptance as explicitly pending physical evidence.
