# NEXOLAB Current State

Updated: 2026-08-06
Verified product baseline: `72aaa668a90cfa1068078167a0cd7023a13e639a`
Active Work Package: Issue #355 / PR #358 — canonical Live Dashboard channel inventory, exact-head GREEN and ready for final merge audit
Branch: `fix/355-live-dashboard-channel-inventory`
Verified implementation head: `6894c1f4c30ac3f1cd5bedf7d138761d0cc112b5`
Next Ready Work Package after merge: Issue #252 — lint-staged 17 migration on the verified Node 22 baseline
Active epic: Issue #326 — Engineering governance, critical operator defects and toolchain hardening
Parallel blocked epic: Issue #282 — acquisition software complete; physical Raspberry Pi/RS-485 acceptance pending

## Reconciled predecessor state

- Issue #254 / PR #352 migrated Playwright to 1.62 and merged as `40aec7d0fa99fe3694e2cb2954d144703eebea5c`.
- Issue #359 / PR #360 stabilized Starlette WebSocket TestClient teardown in test-only code and merged as `72aaa668a90cfa1068078167a0cd7023a13e639a`.
- PR #358 includes current `main`, is zero commits behind and has no unresolved review threads.

## Issue #355 product outcome verified

The Live Dashboard editor now reads one authenticated, organization-scoped canonical measurement catalog endpoint:

```text
GET /api/v1/live-dashboards/channel-inventory?limit=500&offset=0
```

Verified behavior:

- inventory discovery no longer calls paginated `/api/v1/telemetry/latest`;
- active eligible channels remain selectable without telemetry samples;
- no-sample state is explicit: `latest: null`, `quality: unknown`, `alarm: null`;
- inventory and save validation share the same organization, active channel/device/bus/chamber and non-revoked-node eligibility boundary;
- response bounds are deterministic: maximum page size `500`, maximum offset `10,000`, stable identity ordering;
- optional latest metadata uses the complete `node_id + equipment_id + channel_id + metric` identity and PostgreSQL index `ix_telemetry_latest_lookup`;
- saved Dashboard views retain selected-series latest/history and one bounded WebSocket path;
- editor actions do not mutate Device Agent configuration, discovery, acquisition registry, scheduler, Modbus cadence or physical polling eligibility.

## PostgreSQL and browser evidence

PostgreSQL acceptance used 50,003 telemetry rows:

| Evidence                    |                       Result |
| --------------------------- | ---------------------------: |
| Catalog channels            |                            2 |
| `EXPLAIN ANALYZE` execution |                     0.363 ms |
| Complete repository call    |                    13.085 ms |
| Existing client timeout     |                     8,000 ms |
| Latest lookup index         | `ix_telemetry_latest_lookup` |

Authenticated browser acceptance proved:

- one Dashboard library GET and one channel-inventory GET;
- zero `/api/v1/telemetry/*` requests while opening and using editor inventory;
- one active no-sample channel displayed and selected;
- zero acquisition or configuration mutations;
- saved Dashboard selected only `106-03` latest/history;
- maximum active WebSockets per page remained `1`;
- Dashboard persistence survived Telemetry Service restart.

Permanent evidence is recorded in `docs/operations/live-dashboard-channel-inventory.md`.

## Exact-head verification

Exact implementation head `6894c1f4c30ac3f1cd5bedf7d138761d0cc112b5` is GREEN for all 14 workflows:

- CI;
- Telemetry service;
- Authenticated Dashboard Acceptance;
- Refrigeration Browser Acceptance;
- Acquisition Scale Acceptance;
- Offline Auth Acceptance;
- Offline Bundle;
- Container Supply Chain;
- Broker Control Acceptance;
- MQTT TLS Fleet Acceptance;
- Device Agent Fleet Acceptance;
- Capacity Release Gate;
- Disaster Recovery TLS Fleet;
- Disaster Recovery Browser.

Offline Bundle proved disconnected startup and update/rollback persistent-data preservation.

## Focused diff and safety audit

The implementation comparison against current `main` contains 16 permanent files across the permitted Live Dashboard backend, frontend, tests, browser acceptance and operations documentation surfaces. This checkpoint adds only the four authoritative `.project` files.

No temporary workflow remains. Unresolved review threads: zero. There is no database migration, telemetry deletion, production dependency change, cloud runtime dependency, Modbus write, hardware write or site cutover.

## Completion boundary

Software completion classification:

```text
software verified; Raspberry Pi runtime latency acceptance pending
```

The affected Raspberry Pi with its long-running LOCAL_LAN PostgreSQL database still requires physical latency acceptance. That pending hardware evidence does not block the software merge.

## Ordered queue

1. **Issue #252 — next after PR #358 merge:** migrate lint-staged 16.4.0 to 17.x while preserving staged and unstaged work on Node `22.23.1`.
2. **Issue #255 — queued:** TypeScript 6 transition.
3. **Issue #257 — blocked:** ESLint 10 migration.
4. **Issue #256 — deferred:** TypeScript 7 transition.

Open unselected dependency PRs remain #340, #341, #346 and obsolete Playwright PR #347. None is part of Issue #355.

## Security and hardware boundaries

The exact `telemetry-service + libcjson1 + CVE-2026-67216` exception expires on **2026-09-05** and remains unbroadened.

Issue #289 remains `software verified; hardware performance acceptance pending`. Hardware-dependent Issues #289, #245, #189, #200, #201 and #202 remain pending controlled Raspberry Pi/RS-485 evidence.

## Next action

Validate this state-only checkpoint on the exact PR head, mark PR #358 Ready, repeat current-head/check/review/mergeability audit, squash merge PR #358, confirm Issue #355 closure and promote Issue #252 as the sole Next Ready Work Package.
