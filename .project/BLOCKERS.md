# NEXOLAB Blockers

Updated: 2026-08-11

## Issue #396 — resolved

The telemetry-service image security blocker discovered during #368 final CI is resolved and merged.

Issue #396 / PR #397 removed runtime `pip` after dependency validation, retained fixed standalone `msgpack==1.2.1`, added regression coverage, and passed telemetry Container Supply Chain with no new vulnerability exception. PR #397 merged as `d75b353435e8c613203017cb68ee68c1f63d3268`.

## Issue #368 — physical blocker resolved; final exact-head CI pending

Issue #368 / PR #373 passed controlled Raspberry Pi physical acceptance on candidate `105ae34425a8937a6f61c172b52ce2c6fa09f3b3`.

The original `>20 s` latest request is eliminated. Projection cardinality is `194/194`, latest p95 is 13–23 ms for normal unfiltered shapes, the query plan uses `telemetry_latest`, central smoke is GREEN, ingestion remains live and the PostgreSQL named volume is preserved.

PR #373 is reconciled with current `main=d75b353435e8c613203017cb68ee68c1f63d3268` through two-parent commit `97917fe627c704f7aa7fd6d32c7cfb0c459d1256` and inherits merged #396 security hardening. The only remaining #368 gate is fresh exact-head CI plus final focused-diff/review/base audit.

## Alembic sequencing hazard — #368 and #385

Issue #385 / PR #390 is software verified but paused until #368 merges because both feature histories currently define revision `20260807_0023` from `20260805_0022`.

The controlled production database already records `20260807_0023` as the physically verified #368 telemetry projection. Therefore #385 must not merge or be deployed with its current revision id.

Required safe sequence:

1. merge #368 only after fresh exact-head GREEN;
2. reconcile #385 with post-#368 `main`;
3. rename the #385 migration to `20260807_0024` and set `down_revision = 20260807_0023`;
4. rerun #385 exact-head migration/integration/offline/browser CI;
5. run #385 physical acceptance in an isolated Raspberry Pi local-auth stack without touching production PostgreSQL volumes;
6. merge #385 only after GREEN and physical evidence.

No database downgrade, restore, history deletion or volume deletion is required or authorized to resolve this sequencing hazard.

## Runtime sequencing

- #368: active critical bug interrupt; physical PASS, final CI pending.
- #385: software verified, paused only for migration ordering; resumes immediately after #368 merge.
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
