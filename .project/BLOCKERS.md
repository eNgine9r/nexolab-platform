# NEXOLAB Blockers

Updated: 2026-08-06

## Issue #355 completion boundary

Issue #355 / PR #358 is merged and closed.

Verified software outcome:

- merge SHA: `5ba8af5b7c9a2bec184b7f39bc15f45d5c3a703e`;
- final verified head: `116ffc81844db1506f2f1b622cd2938ea0ae9563`;
- all 14 exact-head workflows were GREEN;
- PostgreSQL large-history evidence was 0.363 ms query execution and 13.085 ms complete repository call on 50,003 telemetry rows;
- browser evidence showed zero telemetry discovery requests, zero acquisition/configuration mutations and successful no-sample selection;
- selected-series latest/history and one bounded WebSocket path were preserved;
- Offline Auth and Offline Bundle were GREEN;
- Offline Bundle proved disconnected startup and update/rollback persistent-data preservation;
- no database migration, telemetry deletion, runtime dependency, cloud service, Modbus write, hardware write or site cutover occurred.

No Issue #355 software blocker remains.

## Raspberry Pi acceptance boundary

The affected Raspberry Pi with its real long-running LOCAL_LAN database has not been retested after the merge.

Required physical evidence:

- update the Raspberry Pi to merged `main`;
- open the Live Dashboard editor against the real database;
- record channel-inventory response timing;
- confirm channels without samples are selectable;
- confirm the editor no longer reports `Telemetry request exceeded 8000 ms`;
- record runtime logs without performing Modbus or hardware writes.

Classification remains:

```text
software verified; Raspberry Pi runtime latency acceptance pending
```

This is a hardware/runtime acceptance item, not a software blocker for Issue #252.

## Active Work Package boundary: Issue #252

Issue #252 is the sole Ready package.

Required outcome:

- upgrade only lint-staged from 16.4.0 to the supported 17.x line;
- retain Node `22.23.1`;
- preserve current command ordering and file globs;
- prove successful staged-file formatting/linting;
- prove failed-task rollback and preservation of unstaged changes;
- cover empty and partially staged cases;
- keep production runtime and Offline Bundle closure unchanged.

Hard boundaries:

- no ESLint, Prettier, Husky or Node migration;
- no mass formatting or source refactor;
- no unrelated dependency update;
- no destructive Git operation;
- no production deployment, secrets, hardware actions or Modbus writes.

## Dependency lanes

Open unselected dependency PRs: #340, #341 and #346.

PR #347 is obsolete because Playwright 1.62 already merged through Issue #254 / PR #352. Do not merge it.

Closed unmerged dependency PRs: #272 and #339.

Ordered sequence:

```text
#252 lint-staged 17
→ #255 TypeScript 6
```

Issue #257 remains blocked. Issue #256 remains deferred.

## Security and hardware blockers

The exact `telemetry-service/libcjson1/CVE-2026-67216` exception expires on **2026-09-05**. Do not broaden it.

Issue #289 remains `software verified; hardware performance acceptance pending`. Hardware-dependent Issues #289, #245, #189, #200, #201 and #202 remain pending controlled Raspberry Pi/RS-485 evidence.

`/lockers`, physical cameras, ONVIF/RTSP and NVR remain blocked or unverified by their existing evidence requirements.

## Global hard-stop rules

Stop before destructive data/volume operations, production cutover, hardware writes, secret exposure, mandatory online runtime dependencies, grouped migrations or unsupported physical acceptance claims.
