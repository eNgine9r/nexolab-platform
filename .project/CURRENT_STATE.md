# NEXOLAB Current State

Updated: 2026-08-07
Repository baseline before active recovery work: `main` at `6c0fe1a65521cfa48ab16fb582ed7df100673b9a`
Active critical Work Package: Issue #374 — Recover RS-485 acquisition after serial EIO without poisoning the bus session
Active Pull Request: PR #375 (`bug/374-rs485-serial-eio-recovery`)
Blocked physical acceptance track: Issue #368 / PR #373 — telemetry latest projection
Active product epic: Issue #356 — eliminate visible loading across monitoring routes
Parallel acquisition/hardware epic: Issue #282

## Why Issue #374 preempts the previous sequence

Controlled Raspberry Pi acceptance for Issue #368 uncovered a new production runtime defect before migration-v2 could be meaningfully measured. Central PostgreSQL, MQTT and Telemetry Service remained healthy, but telemetry history stopped advancing because the Device Agent shared RS-485 client repeatedly reused a serial descriptor that had failed with Linux `EIO`.

Observed controlled-host evidence:

```text
Device Agent process: healthy
Device Agent acquisition state: degraded
MQTT connected: true
last_sample_at / last_publish_at: 2026-08-07T09:53:34Z
PostgreSQL max telemetry id: 2327052
PostgreSQL newest telemetry age: ~14 minutes at diagnosis
serial failure: termios.error: (5, 'Input/output error') at reset_input_buffer()
```

The #368 migration-v2 safety monitor detected stale ingestion (`newest_age ~612 s`) with no advisory lock contention and aborted. Automatic rollback left Alembic at `20260805_0022`; no telemetry history or named volume was deleted or restored.

## Issue #374 implementation

Issue #374 is `priority:critical` and `status:in-progress`. PR #375 is a focused recovery change.

`ModbusRTUClient` now invalidates a cached serial handle after transport `OSError`/EIO:

- clear the cached `self._serial` reference;
- close the failed handle best-effort without masking the original exception;
- do not reopen or retry immediately inside the same failed call;
- allow the next normal scheduler attempt to reopen through the existing configured stable serial path/settings;
- preserve the existing one-worker-per-bus lock, scheduler cooldown policy and FC03 read-only boundary.

Regression coverage proves EIO before transmission does not invent a physical-request metric, the failed handle is closed, a later call opens a fresh handle and succeeds, configured retries do not become an immediate EIO reopen loop, and close failure cannot mask the original transport error.

Initial implementation head before state reconciliation:

```text
2ca37ae0cb987d16322687def1ae5b57c0da8e73
```

Actual CI evidence already GREEN on that head includes Device Agent compile/tests, repository formatting/lint/typecheck/test/build, Device Agent image build and supply-chain checks. The final state head must receive its own exact-head CI before PR readiness or merge.

## Issue #368 status

PR #373 remains Draft. Its latest-projection software implementation is verified on head:

```text
cb082621f8b5e4cedf44534f3b5256fb2817d55a
```

That head previously completed 26 GitHub checks with zero failures and zero in-progress checks. Migration-v2 design and bounded startup deployment-gap reconciliation are software verified.

Physical acceptance is **temporarily blocked by acquisition freshness**, not by a proven migration-v2 failure. The Raspberry Pi database remains at `20260805_0022` with `telemetry_latest` absent after the guard-triggered rollback. A pre-v2 PostgreSQL backup exists in the controlled evidence directory.

Completion classification remains:

```text
#374: software implementation under final verification; Raspberry Pi serial recovery unverified
#368: software verified; Raspberry Pi migration-v2/latest-query acceptance blocked pending #374 recovery
```

## Current execution sequence

```text
#374 serial EIO recovery
  -> exact-head GREEN + merge software fix
  -> controlled Raspberry Pi Device Agent recovery evidence
  -> resume #368 migration-v2/latest-query acceptance
  -> #369 actual Raspberry Pi Live Dashboard browser inventory acceptance
  -> #366 cross-route read-model deduplication
  -> #289 final acquisition/route-latency/hardware matrix
```

Issue #245 remains a separate standalone Raspberry Pi validation track. Issues #257 and #256 remain blocked/deferred by their existing toolchain compatibility boundaries.

## Safety boundary

No Modbus write, controller configuration change, hardware write, data deletion, volume deletion, production/site cutover, polling amplification, mandatory cloud dependency or secret exposure is authorized by #374.

The underlying physical cause of the host `EIO` is not yet claimed solved. If a fresh serial handle still receives EIO after deploying #374, inspect stable `/dev/serial/by-id/...` presence and kernel USB/TTY evidence before any physical intervention.

## Next action

Complete PR #375 exact-head CI and review audit. Merge the focused software recovery only when GREEN. Then rebuild/recreate only the Device Agent on the controlled Raspberry Pi using the existing hardware mapping and configuration, prove `last_sample_at` and PostgreSQL `max(id)` advance again, and only then resume Issue #368 migration-v2 acceptance.
