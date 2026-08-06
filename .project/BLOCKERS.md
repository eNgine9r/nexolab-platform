# NEXOLAB Blockers

Updated: 2026-08-06

## Active Work Package boundary: dependency automation policy

Issue #328 is the sole Next Ready Work Package after Issue #335 merges.

Allowed scope:

- audit and revise `.github/dependabot.yml`;
- separate production runtime, development patch/minor and major migration lanes;
- add deterministic dependency-policy validation and fixtures;
- document cadence, ownership, triage, rollback and offline-runtime verification;
- preserve PR #272 as an independent unselected review.

Hard scope boundaries:

- no dependency version changes;
- no `package-lock.json` changes;
- no grouped unrelated major migrations;
- no automatic merge route for major updates;
- no Node or `@types/node` major beyond the supported Node 22 runtime boundary without a dedicated migration Issue;
- no product, runtime, database, acquisition, hardware, Modbus, secret or deployment changes.

The required focused migration order remains:

```text
#253 jsdom 30
→ #254 Playwright 1.62.x
→ #252 lint-staged 17
→ #255 TypeScript 6
```

Blocked or deferred:

- **#257 ESLint 10:** blocked until a compatible Next.js and plugin graph is demonstrated.
- **#256 TypeScript 7:** deferred until TypeScript 6 is complete and ecosystem support exists.

PR #271 is closed unmerged and superseded by focused migration Issues. PR #272 remains open and must not be merged, closed or implicitly approved by Issue #328.

## cJSON exception: reviewed, narrow and time-bounded

Issue #327 / PR #331 is completed. The exact `telemetry-service/libcjson1/CVE-2026-67216` exception remains necessary because the verified exact image contains `libcjson1 1.7.18-3.1+deb13u1`, severity HIGH, status affected and no fixed version.

The exception is owned by `platform-security` and expires on **2026-09-05**. It is not a blocker for current software work, but it must be reviewed again by that date. Do not broaden it.

## Parallel hardware blocker

Issue #289 remains:

```text
software verified; hardware performance acceptance pending
```

Hardware-dependent Issues:

- **#245:** standalone Raspberry Pi acceptance pending;
- **#189:** physical reboot, power-loss and media restore pending;
- **#200:** physical RS-485 topology and single-master proof pending;
- **#201:** LE-01MP cumulative energy validation pending;
- **#202:** extended XJP60D semantics validation pending.

These blockers do not prevent dependency-policy or focused toolchain work.

## Other product blockers

`/lockers` remains blocked pending concrete inventory, a read-only protocol/API contract, a defined operator workflow and physical evidence.

Physical cameras, ONVIF/RTSP media and NVR remain unverified.

## Global hard-stop rules

Stop before:

- destructive database or persistent-volume operations;
- production/site cutover without explicit approval;
- Modbus, camera, locker or other hardware writes;
- credential exposure or unauthorized secret rotation;
- mandatory internet, cloud, CDN, external API or paid runtime dependencies;
- claiming physical performance acceptance without controlled evidence;
- merging a grouped major dependency migration;
- broadening the cJSON exception beyond the exact image/package/CVE tuple.

## Next action

Merge Issue #335 as an exact four-file state-only checkpoint. Then implement Issue #328 with a focused policy/configuration PR and full repository verification while keeping dependency closure unchanged.
