# NEXOLAB Current State

Updated: 2026-08-07
Verified repository baseline on `main`: `6c0fe1a65521cfa48ab16fb582ed7df100673b9a`
Active critical Work Package: Issue #368 — Make telemetry latest reads independent of history volume
Active implementation PR: #373
Verified implementation head before state reconciliation: `8b44241df429cedb6c28a8382bbd43ae4c285fd7`
Blocked downstream Work Package: Issue #366 — Audit and deduplicate monitoring-route read models
Active product epic: Issue #356 — Eliminate visible loading across monitoring routes
Parallel acquisition/performance epic: Issue #282

## Why Issue #368 preempted Issue #366

Controlled Raspberry Pi 5 acceptance against the existing long-running PostgreSQL database exposed a backend latest-read bottleneck that is independent of route-local cache duplication:

```text
GET /health/ready
HTTP 200 in 0.002680 s

GET /api/v1/live-dashboards/channel-inventory
HTTP 200 in 0.050279 s
162 canonical channels

GET /api/v1/telemetry/latest?limit=1&offset=0
client timeout after 20.002650 s
HTTP 000 / zero response bytes
```

Repository inspection confirmed that `Database.latest_samples` derived current state by ranking retained `telemetry_samples` history with a per-series window function before applying latest pagination. Even `limit=1` therefore depended on total history volume.

Issue #366 is intentionally blocked until #368 is resolved. The frontend must not cache around a backend defect or hide it with larger TTLs/timeouts.

## Issue #368 implementation

Branch: `perf/368-telemetry-latest-projection`  
PR: #373  
Implementation head: `8b44241df429cedb6c28a8382bbd43ae4c285fd7`

Implemented product behavior:

- added durable `telemetry_latest` projection keyed by `node_id + equipment_id + channel_id + metric`;
- latest reads now query the bounded projection instead of ranking retained history on every request;
- history insert and latest upsert are transactionally coupled;
- duplicate `event_id` delivery does not mutate history/latest twice;
- delayed older samples remain valid immutable history but cannot regress current latest state;
- equal timestamps preserve deterministic history `sample_id` tie-break semantics;
- only the minimum delivery/staleness metadata is duplicated; large raw payloads remain history-only;
- history retention can remove old `telemetry_samples` while the last-known latest snapshot remains available and truthfully stale;
- test-session attribution uses the same canonical history/latest persistence semantics without redesigning the session domain;
- Alembic revision `20260807_0023` creates/backfills the projection non-destructively;
- PostgreSQL migration backfill serializes against ingestion with the existing telemetry-history advisory lock;
- offline Alembic SQL renders the literal advisory-lock ID correctly;
- `/api/v1/telemetry/latest` public response/filter contract remains unchanged;
- no Device Agent, scheduler, registry, physical polling or timeout-budget change was introduced.

## Verification actually completed on implementation head

Focused sandbox verification:

- new latest-projection SQLite regressions: GREEN;
- existing delivery/staleness regressions: GREEN;
- duplicate/out-of-order/equal-timestamp invariants: GREEN;
- retention independence: GREEN;
- hot-path SQL uses `telemetry_latest` and does not use `row_number()` or `telemetry_samples`: GREEN;
- SQLite old-schema migration upgrade/backfill/downgrade: GREEN;
- PostgreSQL offline migration SQL rendering: GREEN.

GitHub exact-head verification on `8b44241df429cedb6c28a8382bbd43ae4c285fd7`:

- 26 current checks completed with zero failures;
- Telemetry Service PostgreSQL migration and full MQTT/REST/WebSocket/object-storage/dead-letter/retention test stage: GREEN;
- PostgreSQL outage recovery: GREEN;
- offline Alembic migration SQL: GREEN;
- telemetry-service container build: GREEN;
- authenticated/browser/operator-route regressions: GREEN;
- container/release/fleet/security gates: GREEN;
- Offline Bundle disconnected startup: GREEN;
- Offline Bundle update/rollback persistent-volume preservation: GREEN;
- Disaster Recovery TLS fleet first runtime attempt failed before service startup with empty service diagnostics and successful certificate preflight; the isolated failed job was rerun without code changes and passed on attempt 2. Current exact-head check set contains no failure.

The PostgreSQL regression suite now includes a deterministic large-history fixture with 200 canonical latest series plus 8,000 older retained history rows and asserts both `<500 ms` local query execution target and an `EXPLAIN (ANALYZE, BUFFERS)` plan that reads `telemetry_latest` without touching `telemetry_samples`.

## Acceptance boundary

Current classification:

```text
software verified; Raspberry Pi latest-query acceptance pending
```

Issue #368 cannot be declared fully complete until the controlled Raspberry Pi 5 reruns the original direct latest request and central smoke against the existing long-running database after deploying the candidate. The database must not be truncated, reset or replaced for that acceptance.

No Modbus write, hardware write, destructive telemetry operation or production/site cutover is authorized by this Work Package.

## Parallel validation tracks

- **#245:** software merged; `status:needs-validation`; standalone Raspberry Pi acceptance remains a separate hardware/runtime track.
- **#289:** `status:needs-validation`; final acquisition/route-latency matrix remains downstream of the remaining navigation optimization sequence.
- **#355:** software verified; Raspberry Pi runtime latency acceptance pending.
- **#357:** software completed; Raspberry Pi perceived-latency acceptance pending.

## Security boundary

The exact `telemetry-service/libcjson1/CVE-2026-67216` exception expires on **2026-09-05** and must not be broadened.

## Next action

Complete state-only reconciliation on PR #373, require the final state head to pass exact-head CI, perform focused diff/review audit, then execute the controlled Raspberry Pi #368 latest-query acceptance on the existing long-running PostgreSQL database. If physical acceptance passes, complete/merge #368 and unblock #366 as the next product Work Package. If physical acceptance fails, keep #368 active and diagnose the measured remaining bottleneck without increasing frontend/global timeout budgets.