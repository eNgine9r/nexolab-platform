# NEXOLAB Blockers

Updated: 2026-08-12

## Issue #385 — completed

Issue #385 / PR #390 is merged as `e0b124e9a0152be50966daa131974b3543651e87`. Software and Raspberry Pi acceptance are complete. There is no remaining #385 blocker.

## Issue #386 — completed

Issue #386 / PR #399 is merged as `3b34ec321c2453778b20b6bf8e4cc232970e5e1e`. Chart System software, offline runtime and Raspberry Pi renderer performance acceptance are complete. The production physical acquisition-invariant that was intentionally deferred from #386 is now verified by Issue #400.

## Issue #400 — hardware acceptance PASS; final merge audit pending

Issue #400 / PR #402 has no remaining product, software, offline-runtime or Raspberry Pi hardware blocker.

Exact pre-hardware candidate `2da08a028f54884acb74ea71cf1fac741426687b` passed format, lint, typecheck, 77 files / 344 tests, production build, Authenticated Dashboard, Acquisition Scale, Refrigeration Browser and Offline Bundle.

Controlled Raspberry Pi acceptance on 2026-08-12 is PASS:

```text
60s browser-closed baseline: 180 physical requests / 3.000 req/s
60s active 8-channel chart: 181 physical requests / 3.017 req/s
rate delta: +0.56%
retries: 12 -> 12
timeouts: 12 -> 12
bus executions: 156 -> 157
bus busy seconds: 11.928 -> 11.772
scheduler policy: unchanged
configured targets: 38 -> 38
poll-eligible targets: 38 -> 38
telemetry: continued advancing
```

Evidence directory:

`/home/nexolab/nexolab-400-hardware.5B0rFp/evidence`

The Device Agent remained in the same pre-existing degraded condition with three failing/cooldown endpoints; the Chart System did not increase failures, retries, timeouts, registry eligibility or request cadence. No Modbus write, hardware write, scheduler change, polling change, persistent-data deletion or site cutover occurred. Production dashboard service was restored after acceptance.

The remaining control step is not a blocker: run final exact-head checks after the hardware-evidence/state commits, review the focused diff and review threads, then merge only while GREEN and current with `main`.

## Issue #389 — unblocked, Ready and not selected

Issue #389 (administrator-only local NEXOLAB Version Management) remains `status:ready`, but is `ready_not_selected` while the Chart System lane completes.

Its #385 dependency is satisfied because `project_versions.manage` and the administrator-only authorization boundary are canonical on `main`.

Hard stops specific to #389 remain:

- target package/version identity cannot be verified;
- required PostgreSQL backup fails;
- migration or rollback compatibility is unknown;
- rollback would require destructive schema/data downgrade;
- named volumes or edge SQLite cannot be preserved;
- secrets would be exposed;
- action would cross into unapproved production/site cutover.

## Remaining prepared sequence

The existing runtime sequence remains preserved:

```text
#369 -> #366 -> #289
```

Other known boundaries:

- Issue #245 remains a separate Raspberry Pi validation track.
- no parallel implementation lane is allowed while #400 is completing its final merge audit;
- Issue #257 remains blocked by ESLint 10 ecosystem compatibility;
- Issue #256 remains deferred pending TypeScript 7 ecosystem compatibility.

## Security boundary

The exact `telemetry-service/libcjson1/CVE-2026-67216` exception expires on **2026-09-05**. Issue #400 did not broaden it.

## Global hard-stop rules

Stop before destructive data/volume operations, production/site cutover, Modbus or other hardware writes, secret exposure, mandatory online runtime dependencies, privileged hardware containers or unsupported physical-acceptance claims.
