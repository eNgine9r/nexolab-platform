# NEXOLAB Blockers

Updated: 2026-08-11

## Issue #368 — runtime and physical blockers resolved

Issue #368 / PR #373 passed controlled Raspberry Pi physical acceptance and the full software content head `6c4955f73dde147f5f6797dbb04b99b1b67239ba` completed 17/17 workflows GREEN.

The original `>20 s` latest request is eliminated. Projection cardinality is `194/194`, latest p95 is 13–23 ms for normal unfiltered shapes, the query plan uses `telemetry_latest`, central smoke is GREEN, ingestion remains live and the PostgreSQL named volume is preserved.

Post-hardware regression findings are resolved:

- delayed older gap rows no longer make startup reconciliation report repeated projection mutations; Telemetry Service PostgreSQL integration is GREEN;
- authenticated-dashboard deterministic history fixtures now also seed the bounded latest projection; authenticated REST/history/WebSocket browser acceptance is GREEN;
- the telemetry image HIGH-vulnerability blocker is resolved by merged Issue #396 / PR #397 without new exceptions.

The only remaining #368 gate is exact-head CI on the final four-file state checkpoint, followed by final focused-diff/review/base audit and merge.

## Alembic sequencing hazard — #368 and #385

Issue #385 / PR #390 remains paused until #368 merges because both feature histories currently define revision `20260807_0023` from `20260805_0022`.

The controlled production database already records `20260807_0023` as the physically verified #368 telemetry projection. Therefore #385 must not merge or be deployed with its current revision id.

Required safe sequence:

1. merge #368 only after final state exact-head GREEN;
2. reconcile #385 with post-#368 `main`;
3. rename the #385 migration to `20260807_0024` and set `down_revision = 20260807_0023`;
4. rerun #385 exact-head migration/integration/offline/browser CI;
5. run #385 physical acceptance in an isolated Raspberry Pi local-auth stack without touching production PostgreSQL volumes;
6. merge #385 only after GREEN and physical evidence.

No database downgrade, restore, history deletion or volume deletion is required or authorized to resolve this sequencing hazard.

## Runtime sequencing

- #368: software and physical acceptance GREEN; final state CI pending.
- #385: software verified on its old head, paused only for migration ordering; resumes immediately after #368 merge.
- #389: waits for #385 completion.
- #369 waits until the selected Users & Access / Version Management lane permits the runtime sequence to resume.
- #366 waits for #369.
- #289 remains downstream after #366.
- #245 remains a separate Raspberry Pi validation track.
- #257 remains blocked by ESLint 10 compatibility.
- #256 remains deferred pending TypeScript 7 ecosystem compatibility.

## Security boundary

The exact `telemetry-service/libcjson1/CVE-2026-67216` exception expires on **2026-09-05**. Do not broaden it.

## Global hard-stop rules

Stop before destructive data or volume operations, production/site cutover, Modbus or other hardware writes, secret exposure, mandatory online runtime dependencies, grouped migrations, privileged hardware containers or unsupported physical acceptance claims.
