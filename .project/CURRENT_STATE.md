# NEXOLAB Current State

Updated: 2026-08-07
Repository baseline before active recovery merge: `main` at `6c0fe1a65521cfa48ab16fb582ed7df100673b9a`
Active critical Work Package: Issue #374 — Recover RS-485 acquisition after serial EIO without poisoning the bus session
Active Pull Request: PR #375 (`bug/374-rs485-serial-eio-recovery`)
Next validation track after #374 merge: Issue #368 / PR #373 — telemetry latest projection migration-v2/latest-query acceptance
Active product epic: Issue #356 — eliminate visible loading across monitoring routes
Parallel acquisition/hardware epic: Issue #282

## Issue #374 — software and Raspberry Pi acceptance verified

Issue #374 was created from a production runtime defect discovered during controlled Raspberry Pi acceptance for Issue #368. Central PostgreSQL, MQTT and Telemetry Service remained healthy while Device Agent acquisition stopped because a shared cached RS-485 serial descriptor continued to be reused after Linux `EIO`.

Original controlled-host defect evidence:

```text
Device Agent process: healthy
Device Agent acquisition state: degraded
MQTT connected: true
last_sample_at / last_publish_at: 2026-08-07T09:53:34Z
PostgreSQL max telemetry id: 2327052
PostgreSQL newest telemetry age: ~14 minutes at diagnosis
serial failure: termios.error: (5, 'Input/output error') at reset_input_buffer()
```

The #368 migration-v2 safety monitor correctly rejected that stale-ingestion state and rolled back before meaningful migration acceptance. Alembic remained at `20260805_0022`; `telemetry_latest` remained absent; telemetry history and named volumes were preserved.

PR #375 changes only the shared serial-client recovery boundary. `ModbusRTUClient` now invalidates and best-effort closes a cached serial handle after transport `OSError`/EIO, preserves the original exception, performs no immediate EIO reopen loop, and lets the next normal scheduler attempt reopen the existing configured stable serial path/settings. One-worker-per-bus locking, scheduler cadence/cooldown policy and read-only FC03 behavior remain unchanged.

Software exact-head evidence on candidate:

```text
8543bebad6149ac9c23be75b60d85830e980509e
14 completed GitHub checks
0 failures
0 in-progress
```

GREEN coverage includes Device Agent compile/full tests, repository formatting/lint/typecheck/tests/production build, secure edge Compose validation, multi-platform Device Agent image build, telemetry/MQTT supply-chain gates, JWT REST/history/WebSocket/acquisition invariant, secure/TLS fleet outage acceptance, release manifest validation and Offline Bundle disconnected startup plus update/rollback persistent-data preservation.

### Controlled Raspberry Pi hardware evidence

The exact candidate `8543bebad6149ac9c23be75b60d85830e980509e` was built on the controlled Raspberry Pi and only the Device Agent was recreated. Existing hardware mapping remained:

```text
/dev/serial/by-id/usb-Silicon_Labs_CP2104_USB_to_UART_Bridge_Controller_0133F090-if00-port0 -> ../../ttyUSB1
```

Observed after candidate recreate:

```text
PostgreSQL max(id) before: 2327052
PostgreSQL max(id) after first 10 s: 2327095
PostgreSQL newest telemetry age: 00:00:19.499133
Device Agent status: ok
mqtt_connected: true
queue_depth: 0
samples_total: 43
last_sample_at:  2026-08-07T10:40:08.526303+00:00
last_publish_at: 2026-08-07T10:40:08.940904+00:00
last_error: null
degraded_endpoints: 0
cooldown_endpoints: 0
active_bus_workers: 1
communication_failures_total: 0
cooldown_entered_total: 0
```

Successful FC03 acquisition was observed from configured XJP60D targets and LE01MP units 200-203. Normal timeout/retry outcomes still occurred on some XJP60D reads, but acquisition remained healthy and no endpoint entered degraded/cooldown state. The recent Device Agent log filter contained no `Input/output error`, `ERROR`, `WARNING` or `Traceback` entries.

Completion classification:

```text
#374: software verified; Raspberry Pi serial recovery hardware verified; final evidence-head CI/merge pending
```

This proves recovery from the observed poisoned serial-session failure mode. It does not claim that every future USB/TTY EIO physical cause has been eliminated.

## Issue #368 status

PR #373 remains Draft. Its latest-projection software implementation is verified on:

```text
cb082621f8b5e4cedf44534f3b5256fb2817d55a
```

That head completed 26 GitHub checks with zero failures and zero in-progress checks. Migration-v2 design and bounded startup deployment-gap reconciliation remain software verified.

The acquisition freshness blocker has now been resolved by #374 physical acceptance. #368 may resume immediately after PR #375 is merged and #374 is closed. Its remaining boundary is the controlled Raspberry Pi migration-v2/latest-query acceptance on the existing long-running PostgreSQL database.

## Current execution sequence

```text
#374 evidence checkpoint -> exact-head GREEN -> PR #375 merge -> close #374
  -> resume #368 migration-v2/latest-query acceptance
  -> #369 actual Raspberry Pi Live Dashboard browser inventory acceptance
  -> #366 cross-route read-model deduplication
  -> #289 final acquisition/route-latency/hardware matrix
```

Issue #245 remains a separate standalone Raspberry Pi validation track. Issues #257 and #256 remain blocked/deferred by their existing toolchain compatibility boundaries.

## Safety boundary

No Modbus write, controller configuration change, hardware write, data deletion, volume deletion, production/site cutover, polling amplification, mandatory cloud dependency or secret exposure occurred during #374 implementation or Raspberry Pi acceptance.

## Next action

Run exact-head CI on the final evidence/state checkpoint for PR #375. If GREEN and the final review/base audit remains clean, mark PR #375 Ready, merge it, close Issue #374 as completed, reconcile `main`, and resume Issue #368 migration-v2/latest-query acceptance. Do not start #369 or #366 before #368 physical acceptance is complete.
