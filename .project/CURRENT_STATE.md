# NEXOLAB Current State

Updated: 2026-08-06
Verified product baseline: `5ba8af5b7c9a2bec184b7f39bc15f45d5c3a703e`
Completed Work Package: Issue #355 / PR #358 — canonical Live Dashboard channel inventory
Verified implementation head: `116ffc81844db1506f2f1b622cd2938ea0ae9563`
Active Work Package: Issue #252 — lint-staged 17 migration on the verified Node 22 baseline
Active epic: Issue #326 — Engineering governance, critical operator defects and toolchain hardening
Parallel blocked epic: Issue #282 — acquisition software complete; physical Raspberry Pi/RS-485 acceptance pending

## Issue #355 completed

Issue #355 / PR #358 merged into `main` as `5ba8af5b7c9a2bec184b7f39bc15f45d5c3a703e`.

The Live Dashboard editor now reads the authenticated organization-scoped canonical measurement catalog through:

```text
GET /api/v1/live-dashboards/channel-inventory?limit=500&offset=0
```

Completed behavior:

- inventory discovery is independent of paginated `/api/v1/telemetry/latest` and telemetry-history volume;
- active eligible channels remain selectable without telemetry samples;
- no-sample state is explicit: `latest: null`, `quality: unknown`, `alarm: null`;
- inventory and save validation share the same organization, active channel/device/bus/chamber and non-revoked-node eligibility boundary;
- response bounds are deterministic: maximum page size `500`, maximum offset `10,000`, stable identity ordering;
- optional latest metadata uses `node_id + equipment_id + channel_id + metric` and PostgreSQL index `ix_telemetry_latest_lookup`;
- saved Dashboard views retain selected-series latest/history and one bounded WebSocket path;
- editor actions do not mutate Device Agent configuration, discovery, acquisition registry, scheduler, Modbus cadence or physical polling eligibility.

## Verification evidence

Final exact head `116ffc81844db1506f2f1b622cd2938ea0ae9563` was GREEN across all 14 workflows:

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

PostgreSQL acceptance used 50,003 telemetry rows:

| Evidence                    |                       Result |
| --------------------------- | ---------------------------: |
| Catalog channels            |                            2 |
| `EXPLAIN ANALYZE` execution |                     0.363 ms |
| Complete repository call    |                    13.085 ms |
| Existing client timeout     |                     8,000 ms |
| Latest lookup index         | `ix_telemetry_latest_lookup` |

Authenticated browser evidence recorded zero telemetry discovery requests, zero acquisition/configuration mutations, successful no-sample selection, selected-only latest/history requests and maximum one WebSocket. Offline Bundle proved disconnected startup and update/rollback persistent-data preservation.

Permanent evidence is recorded in `docs/operations/live-dashboard-channel-inventory.md`.

## Completion boundary

Issue #355 classification remains:

```text
software verified; Raspberry Pi runtime latency acceptance pending
```

The affected Raspberry Pi with its long-running LOCAL_LAN PostgreSQL database still requires physical latency acceptance. No hardware or Modbus write was performed.

## Active Work Package: Issue #252

Issue #252 is open, assigned to `eNgine9r` and labeled:

- `area:devops`;
- `dependencies`;
- `priority:high`;
- `status:ready`.

Required outcome:

- upgrade only lint-staged from 16.4.0 to the supported 17.x line;
- retain Node `22.23.1`;
- preserve current command ordering and file globs;
- prove successful staged-file formatting/linting;
- prove failure rollback and preservation of unstaged changes;
- cover empty and partially staged cases;
- keep production runtime and Offline Bundle closure unchanged.

## Ordered queue

1. **Issue #252 — Ready:** lint-staged 17 migration.
2. **Issue #255 — queued:** TypeScript 6 transition.
3. **Issue #257 — blocked:** ESLint 10 migration.
4. **Issue #256 — deferred:** TypeScript 7 transition.

Open unselected dependency PRs remain #340, #341 and #346. PR #347 is obsolete because Playwright 1.62 already merged through Issue #254 / PR #352.

## Security and hardware boundaries

The exact `telemetry-service + libcjson1 + CVE-2026-67216` exception expires on **2026-09-05** and remains unbroadened.

Issue #289 remains `software verified; hardware performance acceptance pending`. Hardware-dependent Issues #289, #245, #189, #200, #201 and #202 remain pending controlled Raspberry Pi/RS-485 evidence.

## Next action

Begin Issue #252 from current `main` in one focused feature branch and Pull Request. Do not combine ESLint, Prettier, Husky, Node, source refactors or unrelated dependency updates with the lint-staged migration.
