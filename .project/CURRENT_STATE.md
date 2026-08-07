# NEXOLAB Current State

Updated: 2026-08-07
Verified repository baseline on `main`: `442cd6bc37aefc11977f82f31423d052fe70ced1`
Last completed critical Work Package: Issue #374 / PR #375 — RS-485 serial EIO recovery
Active Work Package: Issue #368 / PR #373 — telemetry latest projection migration-v2/latest-query Raspberry Pi acceptance
Active product epic: Issue #356 — eliminate visible loading across monitoring routes
Parallel acquisition/hardware epic: Issue #282

## Issue #374 completed

Issue #374 is closed as completed. PR #375 was squash-merged into `main` as:

```text
442cd6bc37aefc11977f82f31423d052fe70ced1
```

Final software head before merge:

```text
956df254a904c49e6a265101ab2fe0f959e3fbf3
14 completed GitHub checks
0 failures
0 in-progress
```

The focused fix invalidates and best-effort closes a cached Modbus RTU serial handle after transport `OSError`/EIO, preserves the original exception, performs no immediate EIO reopen loop, and lets the next normal scheduler attempt reopen the existing stable serial path/settings. Scheduler production code, polling cadence, one-worker-per-bus behavior and FC03 read-only boundaries were unchanged.

Controlled Raspberry Pi acceptance passed on exact candidate `8543bebad6149ac9c23be75b60d85830e980509e`:

```text
stable path: /dev/serial/by-id/usb-Silicon_Labs_CP2104_USB_to_UART_Bridge_Controller_0133F090-if00-port0 -> ttyUSB1
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

Completion classification:

```text
software verified; Raspberry Pi serial recovery hardware verified; merged
```

This proves recovery from the observed poisoned serial-session failure mode. It does not claim that every possible future physical USB/TTY EIO cause has been eliminated.

## Active Issue #368

Issue #368 remains open and `status:in-progress`. PR #373 remains Draft while physical acceptance is pending.

Its latest-projection software implementation was previously verified on:

```text
cb082621f8b5e4cedf44534f3b5256fb2817d55a
26 completed checks
0 failures
0 in-progress
```

The previous Raspberry Pi migration-v2 retry did **not** establish a migration-v2 failure. Its freshness precondition rejected the run because Issue #374 had already stopped telemetry acquisition. Automatic rollback preserved:

```text
Alembic: 20260805_0022
telemetry_latest: absent
history: preserved
named volumes: preserved
```

That acquisition blocker is now resolved and hardware verified. The next product/runtime result is therefore the controlled Raspberry Pi migration-v2/latest-query acceptance on the existing long-running PostgreSQL history.

Because PR #373 was created before #374 merged, its branch must first be reconciled with current `main` and receive fresh exact-head CI before a new physical candidate is accepted.

## Execution sequence

```text
#368 branch/current-main reconciliation
  -> exact-head GREEN
  -> controlled Raspberry Pi migration-v2/latest-query acceptance
  -> #369 actual Raspberry Pi Live Dashboard browser inventory acceptance
  -> #366 cross-route read-model deduplication
  -> #289 final acquisition/route-latency/hardware matrix
```

Issue #245 remains a separate standalone Raspberry Pi validation track. Issues #257 and #256 remain blocked/deferred by their existing toolchain compatibility boundaries.

## Safety boundary

No Modbus write, controller configuration change, hardware write, data deletion, volume deletion, production/site cutover, polling amplification, mandatory cloud dependency or secret exposure occurred in Issue #374 or this state reconciliation.

## Next action

Complete state-only Issue #376, then reconcile PR #373 with merged `main` and resume Issue #368 physical acceptance. Do not start #369 or #366 before #368 acceptance is complete.
