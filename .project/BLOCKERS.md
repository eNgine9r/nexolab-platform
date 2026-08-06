# NEXOLAB Blockers

Updated: 2026-08-06

## Issue #355 / PR #358 merge boundary

No software implementation or verification blocker remains on exact implementation head `6894c1f4c30ac3f1cd5bedf7d138761d0cc112b5`.

Verified:

- current `main` base `72aaa668a90cfa1068078167a0cd7023a13e639a` is included and the branch is zero commits behind;
- implementation diff is limited to 16 permitted permanent files plus this four-file state checkpoint;
- all 14 exact-head workflows are GREEN;
- PostgreSQL large-history evidence is 0.363 ms query execution and 13.085 ms complete repository call on 50,003 telemetry rows;
- browser evidence shows zero telemetry discovery requests, zero acquisition/configuration mutations and successful no-sample selection;
- selected-series latest/history and one bounded WebSocket path are preserved;
- Offline Auth and Offline Bundle are GREEN;
- unresolved review threads are zero;
- no database migration, telemetry deletion, runtime dependency, cloud service, Modbus write, hardware write or site cutover exists.

Remaining control sequence:

1. validate this four-file state checkpoint;
2. mark PR #358 Ready;
3. repeat current-head, mergeability, review and required-check audit;
4. squash merge PR #358 and confirm Issue #355 closure;
5. promote Issue #252 as the sole Next Ready Work Package.

## Raspberry Pi acceptance boundary

Issue #355 software is verified, but the affected Raspberry Pi with its real long-running LOCAL_LAN database has not been retested.

Required physical evidence:

- update the Raspberry Pi to the merged `main`;
- open the Live Dashboard editor against the real database;
- record channel-inventory response timing;
- confirm channels without samples are selectable;
- confirm the editor no longer reports `Telemetry request exceeded 8000 ms`;
- record runtime logs without performing Modbus or hardware writes.

Classification remains:

```text
software verified; Raspberry Pi runtime latency acceptance pending
```

This is a hardware/runtime acceptance item, not a software merge blocker.

## Next Ready Work Package boundary: Issue #252

After PR #358 merges, Issue #252 becomes the sole Ready package.

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
- no destructive Git operation;
- no production deployment, secrets, hardware actions or Modbus writes.

## Dependency lanes

Open unselected dependency PRs: #340, #341 and #346.

PR #347 is obsolete because Playwright 1.62 already merged through Issue #254 / PR #352. Do not merge it.

Closed unmerged dependency PRs: #272 and #339.

Ordered sequence:

```text
#355 Live Dashboard canonical inventory
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
