# NEXOLAB Blockers

Updated: 2026-08-07

## Issue #374 — resolved

Issue #374 / PR #375 is completed, software verified and Raspberry Pi serial recovery hardware verified. Post-merge state reconciliation is also merged into `main`.

The observed poisoned cached serial-session failure is no longer an active blocker for Issue #368.

## Issue #368 — reconciled, exact-head CI pending

Issue #368 remains open `status:in-progress` and PR #373 remains Draft until physical acceptance completes.

The previous software head `cb082621f8b5e4cedf44534f3b5256fb2817d55a` passed 26 checks, but it predated Issue #374 and its post-merge state reconciliation.

PR #373 is now reconciled with current main through non-force two-parent merge commit:

```text
ad3923ace7aa8ae6bfe29548916d594171a5e50b
reconciled main: 1c10f86a57dbeea9b2d410888d57d8b19a2288ab
```

No conflict was resolved by dropping production work: the merge retains #368 telemetry code and inherits current-main Device Agent recovery/canonical state.

Fresh exact-head CI is required before the reconciled branch becomes a valid Raspberry Pi candidate.

The previous Raspberry Pi migration-v2 attempt was rejected by its freshness precondition because #374 had already stopped telemetry. Automatic rollback preserved:

```text
Alembic: 20260805_0022
telemetry_latest: absent
history: preserved
named volumes: preserved
```

No product/runtime blocker currently prevents #368 physical acceptance after fresh CI passes.

## #368 physical acceptance requirements

- verify acquisition freshness before migration;
- fresh PostgreSQL backup/evidence before candidate migration;
- prove long initial backfill does not hold a long-lived exclusive ingestion lock;
- measure total migration duration and bounded final lock/catch-up phase;
- preserve all history and named volumes;
- verify projection cardinality against canonical history series;
- verify startup deployment-gap reconciliation;
- measure `/api/v1/telemetry/latest?limit=1&offset=0` and normal latest reads: all HTTP 200, normal-load p95 `<500 ms`;
- capture query-plan evidence that normal latest reads use `telemetry_latest` rather than full history;
- central smoke must pass without timeout/retry-budget increases.

## Sequencing blockers

- #369 waits for #368 physical migration/latest-query acceptance.
- #366 waits for the #368 -> #369 runtime acceptance sequence.
- #289 remains the downstream final acquisition/route-latency/hardware matrix after #366.
- #245 remains a separate Raspberry Pi validation track.
- #257 remains blocked by ESLint 10 compatibility.
- #256 remains deferred pending TypeScript 7 ecosystem compatibility.

## Security boundary

The exact `telemetry-service/libcjson1/CVE-2026-67216` exception expires on **2026-09-05**. Do not broaden it.

## Global hard-stop rules

Stop before destructive data/volume operations, production/site cutover, Modbus or other hardware writes, secret exposure, mandatory online runtime dependencies, grouped migrations, or unsupported physical acceptance claims.
