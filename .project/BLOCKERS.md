# NEXOLAB Blockers

Updated: 2026-08-07

## Issue #374 — resolved

Issue #374 / PR #375 is complete.

Final merge:

```text
verified final head: 956df254a904c49e6a265101ab2fe0f959e3fbf3
squash merge: 442cd6bc37aefc11977f82f31423d052fe70ced1
final CI: 14 completed, 0 failures, 0 in-progress
```

Controlled Raspberry Pi serial-session recovery passed:

```text
PostgreSQL max(id): 2327052 -> 2327095 in first 10 seconds
newest telemetry age: 00:00:19.499133
Device Agent status: ok
mqtt_connected: true
last_error: null
degraded_endpoints: 0
cooldown_endpoints: 0
active_bus_workers: 1
communication_failures_total: 0
cooldown_entered_total: 0
recent EIO/ERROR/WARNING/Traceback matches: 0
```

The poisoned cached serial-session runtime blocker is no longer active. This evidence does not claim that every future physical USB/TTY EIO cause is eliminated; it proves the Device Agent recovered correctly from the observed failure mode.

## Issue #368 — no longer blocked by acquisition freshness

Issue #368 remains open `status:in-progress`. PR #373 latest-projection software was previously verified on `cb082621f8b5e4cedf44534f3b5256fb2817d55a` with 26 completed checks, zero failures and zero in-progress checks.

The previous Raspberry Pi migration-v2 attempt was rejected by its freshness precondition because #374 had already stopped telemetry. Automatic rollback preserved:

```text
Alembic: 20260805_0022
telemetry_latest: absent
history: preserved
named volumes: preserved
```

Acquisition freshness is now hardware verified. No product/runtime blocker prevents resuming #368.

Required sequencing before physical acceptance:

1. reconcile PR #373 branch with current `main` (`442cd6bc37aefc11977f82f31423d052fe70ced1`);
2. obtain fresh exact-head GREEN CI;
3. rerun the controlled Raspberry Pi migration-v2/latest-query acceptance against the long-running database.

Do not accept the old pre-#374 PR head as a post-merge candidate without this reconciliation.

## Sequencing blockers

- #369 waits for #368 physical migration/latest-query acceptance.
- #366 waits for the #368 -> #369 runtime acceptance sequence.
- #289 remains the downstream final acquisition/route-latency/hardware matrix after #366.
- #245 remains a separate Raspberry Pi validation track.
- #257 remains blocked by ESLint 10 compatibility.
- #256 remains deferred pending TypeScript 7 ecosystem compatibility.

## Security boundary

The exact `telemetry-service/libcjson1/CVE-2026-67216` exception expires on **2026-09-05**. Do not broaden it.

## Global hard-stop rules

Stop before destructive data/volume operations, production/site cutover, Modbus or other hardware writes, secret exposure, mandatory online runtime dependencies, grouped migrations, or unsupported physical acceptance claims.
