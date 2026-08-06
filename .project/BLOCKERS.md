# NEXOLAB Blockers

Updated: 2026-08-06

## Active software risk: cJSON exception review

Issue #327 is Ready and is not blocked by hardware access.

The repository currently records a narrow `telemetry-service/libcjson1/CVE-2026-67216` exception introduced through Issue #295 / PR #296. Its review date is 2026-08-15.

Current package and fix status must not be inferred from the previous review. The exact current telemetry-service image must be rebuilt and rescanned before any decision.

The decision order is:

1. remove the package from the runtime image when the affected tooling can be isolated or removed;
2. use a fixed supported package or base image;
3. replace the affected tooling with an already supported local path;
4. renew only the exact image/package/CVE exception with current evidence, owner and a short new expiry.

Hard stop conditions for Issue #327:

- broad suppression of HIGH/CRITICAL findings;
- exception matching beyond `telemetry-service + libcjson1 + CVE-2026-67216`;
- unsupported package replacement;
- secret exposure;
- authentication or MQTT security weakening;
- unrelated dependency upgrades.

## Queued software constraints

Issue #300 is queued after #327. It is documentation and validation work only; it must preserve legacy ADR links and avoid dependency/runtime changes.

Issue #328 is queued after #300. It must change dependency automation policy without changing dependency versions. PR #271 is already closed unmerged as superseded. PR #272 remains independently open and unselected.

Toolchain sequencing:

```text
#253 jsdom 30
→ #254 Playwright 1.62.x
→ #252 lint-staged 17
→ #255 TypeScript 6
```

Blocked or deferred:

- **#257 ESLint 10:** blocked until a compatible Next.js and plugin graph is demonstrated.
- **#256 TypeScript 7:** deferred until TypeScript 6 is complete and ecosystem support exists.

Do not group these major migrations or silently advance Node types beyond the Node 22 runtime baseline.

## Parallel hardware blocker

The acquisition optimization software is complete, but controlled Raspberry Pi/RS-485 access is unavailable.

Issue #289 remains open with:

```text
software verified; hardware performance acceptance pending
```

Hardware-dependent Issues:

- **#245:** actual standalone Raspberry Pi acceptance pending;
- **#189:** physical reboot, power-loss and media restore pending;
- **#200:** physical RS-485 topology and single-master proof pending;
- **#201:** LE-01MP cumulative energy validation pending;
- **#202:** extended XJP60D semantics validation pending.

These blockers do not prevent Issue #327 or the queued engineering-hardening Work Packages.

## Other product blockers

`/lockers` remains blocked pending:

- concrete locker inventory;
- a read-only protocol or API contract;
- a defined operator workflow;
- verified physical locker evidence.

Physical cameras, ONVIF/RTSP media and NVR remain unverified.

## Global hard-stop rules

Stop before:

- destructive database or persistent-volume operations;
- production/site cutover without explicit approval;
- Modbus, camera, locker or other hardware writes;
- credential exposure or unauthorized secret rotation;
- mandatory internet, cloud, CDN, external API or paid runtime dependencies;
- claiming physical performance acceptance without controlled evidence;
- merging a grouped major dependency migration.

## Next action

Merge the exact four-file Issue #329 checkpoint, then execute Issue #327. If the exact image scan proves the exception obsolete, remove it. If no supported fix exists, renew only with current evidence, explicit ownership and a new short review date.
