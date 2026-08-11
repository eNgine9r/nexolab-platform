# NEXOLAB Blockers

Updated: 2026-08-11

## Issue #385 — physical blocker cleared

Issue #385 / PR #390 is the selected Work Package.

Exact candidate `d37cf08af9560ffa0d18c102656301e667299836` has:

```text
GitHub CI: 19/19 successful
Raspberry Pi acceptance: PASS
architecture: aarch64 / linux/arm64
Next.js production build: PASS
local-auth production browser tests: 4 passed
persistence/recreation test: 1 passed
acceptance exit_code: 0
```

Evidence directory:

```text
/home/nexolab/nexolab-385-hardware.VGhXYn/evidence-retry-20260811T094325Z
```

The earlier loopback collision on port `18093` was an isolated environment conflict. The successful retry used alternate loopback-only ports and did not require stopping production services.

There is **no remaining #385 hardware or product blocker**.

Remaining gates are procedural and repository-controlled:

1. commit the state-only reconciliation;
2. require fresh exact-head CI on that new state commit;
3. perform final review/base/diff/migration audit;
4. mark PR #390 Ready;
5. squash merge with an expected-head lock.

No merge may occur until the final state head is GREEN.

## Issue #389 — blocked only by Issue #385 merge

Issue #389 (administrator-only local NEXOLAB Version Management) depends on the administrator authorization boundary from #385.

The physical acceptance dependency is now satisfied. It remains blocked only until:

1. PR #390 is merged;
2. the administrator-only `project_versions.manage` capability is canonical on `main`;
3. project state is updated to select #389.

After those conditions, #389 is the next selected Work Package for this product lane.

## Issue #368 — completed and merged

Issue #368 / PR #373 merged as `ba2441a3a5a2dcdfb748b53c2513cb3cbbb6fec4`. The canonical telemetry latest projection is revision `20260807_0023`; Issue #385 follows it with `20260807_0024`.

When the selected local administration/version lane completes, continue:

```text
#369 -> #366 -> #289
```

## Other known boundaries

- Issue #245 remains a separate Raspberry Pi validation track.
- Issue #386 remains Ready but not selected.
- Issue #257 remains blocked by ESLint 10 ecosystem compatibility.
- Issue #256 remains deferred pending TypeScript 7 ecosystem compatibility.

## Security boundary

The exact `telemetry-service/libcjson1/CVE-2026-67216` exception expires on **2026-09-05**. Issue #385 does not broaden it.

## Global hard-stop rules

Stop before destructive data/volume operations, production/site cutover, Modbus or other hardware writes, secret exposure, mandatory online runtime dependencies, privileged hardware containers or unsupported physical-acceptance claims.
