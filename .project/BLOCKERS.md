# NEXOLAB Blockers

Updated: 2026-08-06

## Issue #254 / PR #352 merge boundary

No implementation or verification blocker remains on exact implementation head `0092a1035af913cbe5be22d2e57db2a3fc257e98`.

Verified:

- current `main` base `67b471e44201f7c96ef4e51e7c3904e8c78df323` is included; branch is zero commits behind;
- implementation diff is limited to five permitted permanent files;
- 13 Playwright config hashes and 24 discovered tests are unchanged;
- removed Playwright APIs are absent;
- CI and every required browser acceptance workflow are GREEN;
- Offline Auth Acceptance is GREEN;
- Offline Bundle disconnected startup and update/rollback preservation are GREEN;
- unresolved review threads are zero;
- production dependencies, runtime containers, database/schema, acquisition, hardware and Modbus behavior are unchanged.

Remaining control sequence:

1. validate the four-file state checkpoint;
2. mark PR #352 Ready;
3. repeat current-head, mergeability, review and required-check audit;
4. squash merge PR #352 and confirm Issue #254 closure.

## Next Ready Work Package boundary: Issue #355

After PR #352 merges, Issue #355 is the sole Ready package.

Required outcome:

- load the Live Dashboard editor inventory from the organization-scoped canonical measurement catalog rather than paginated telemetry latest/history;
- include eligible active channels even when no current sample exists;
- keep the response bounded, deterministic and permission-aware;
- optionally attach latest state only through a bounded indexed lookup;
- preserve selected-series latest/history/WebSocket behavior after a dashboard opens;
- prove a large telemetry history cannot cause the editor inventory request to exceed the existing 8-second client timeout;
- record PostgreSQL timing/query-plan evidence and separate Raspberry Pi runtime evidence.

Hard boundaries:

- do not treat a larger global timeout as the primary fix;
- do not change acquisition registry, scheduler, Modbus cadence or physical polling eligibility;
- do not delete/truncate telemetry history;
- do not add cloud or paid runtime dependencies;
- no Modbus write, hardware action, secret exposure or production/site cutover;
- Raspberry Pi latency remains `software verified; Raspberry Pi runtime latency acceptance pending` until physical evidence exists.

## Dependency lanes

Open and unselected dependency PRs: #340, #341, #346 and #347. PR #347 is superseded by the focused Playwright 1.62 migration after PR #352 merges. Do not combine any of them with Issue #355.

Closed unmerged dependency PRs: #272 and #339.

Queued sequence after Issue #355:

```text
#355 Live Dashboard canonical inventory defect
→ #252 lint-staged 17
→ #255 TypeScript 6
```

Issue #257 remains blocked. Issue #256 remains deferred.

## Security and hardware blockers

The exact `telemetry-service/libcjson1/CVE-2026-67216` exception expires on **2026-09-05**. Do not broaden it.

Issue #289 remains `software verified; hardware performance acceptance pending`. Hardware-dependent Issues #289, #245, #189, #200, #201 and #202 remain pending controlled Raspberry Pi/RS-485 evidence.

`/lockers`, physical cameras, ONVIF/RTSP and NVR remain blocked or unverified by their existing evidence requirements.

## Global hard-stop rules

Stop before destructive data/volume operations, production cutover, hardware writes, secret exposure, mandatory online runtime dependencies, grouped migrations or unsupported physical acceptance claims.
