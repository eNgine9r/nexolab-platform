# NEXOLAB Blockers

Updated: 2026-08-06

## cJSON exception: reviewed, narrow and time-bounded

Issue #327 / PR #331 is completed. The exact `telemetry-service/libcjson1/CVE-2026-67216` exception remains necessary because the rebuilt exact image contains:

```text
libcjson1 1.7.18-3.1+deb13u1
CVE-2026-67216
HIGH
status: affected
fixed version: none
```

The exception is owned by `platform-security` and expires on **2026-09-05**. It is not a blocker for current software work, but it is an active security risk requiring another exact-image review by that date.

Remove it immediately when:

- a supported fixed Debian package is available;
- the exact image no longer reports the finding;
- `mosquitto_ctrl` can be isolated without weakening local TLS-authenticated dynamic-security administration;
- the broker control boundary is replaced by a supported local implementation without the affected package.

Do not broaden the exception. Global CRITICAL and unapproved HIGH blocking remains mandatory.

## Active Work Package boundary: ADR registry

Issue #300 is Ready and is not blocked by hardware or dependency compatibility.

It must remain documentation and validation work only:

- establish one authoritative ADR registry;
- preserve the legacy `docs/architecture/decisions/0001-*` path;
- classify non-contiguous numbering and historical locations without rewriting accepted decisions;
- reject duplicate active identifiers;
- reject broken canonical and legacy links;
- add deterministic integrity validation;
- avoid runtime, dependency, migration and product changes.

Stop and open a focused discrepancy Issue if two ADR files claim the same active identifier with materially different decisions and no authoritative source can be established from repository history.

## Queued software constraints

Issue #328 is queued after #300 and may change dependency automation policy only. It must not update dependency versions.

Toolchain sequence:

```text
#253 jsdom 30
→ #254 Playwright 1.62.x
→ #252 lint-staged 17
→ #255 TypeScript 6
```

Blocked or deferred:

- **#257 ESLint 10:** blocked until a compatible Next.js and plugin graph is demonstrated.
- **#256 TypeScript 7:** deferred until TypeScript 6 is complete and ecosystem support exists.

PR #271 remains closed unmerged as superseded. PR #272 remains independently open and unselected.

## Parallel hardware blocker

Issue #289 remains:

```text
software verified; hardware performance acceptance pending
```

Hardware-dependent Issues:

- **#245:** actual standalone Raspberry Pi acceptance pending;
- **#189:** physical reboot, power-loss and media restore pending;
- **#200:** physical RS-485 topology and single-master proof pending;
- **#201:** LE-01MP cumulative energy validation pending;
- **#202:** extended XJP60D semantics validation pending.

These blockers do not prevent Issue #300 or the queued engineering-hardening Work Packages.

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

Merge the exact four-file Issue #332 checkpoint, then execute Issue #300. The ADR Work Package must preserve accepted decision content and existing external links while creating one canonical registry and deterministic validation.
