# Issue #866 — XJP60D recovered read-retry investigation

Date: 2026-09-05

Profile: `LOCAL_LAN`

Scope: read-only diagnosis only

## Outcome

The recurring XJP60D FC03 retry pattern is **not a 2026-09-04 restart-specific regression** and is **not attributable to the Mini App/frontend deployment**. The same pattern is present in deployment evidence from 2026-09-03, before that restart, and the Mini App deployment sources have zero Device Agent source delta.

The current evidence best supports a **pre-existing XJP60D-specific device/protocol/timing behavior on `rs485-main`**. It does not support a generic bus-wide retry storm: LE-01MP traffic on the same physical bus has no retries/timeouts during the same observation period, while Embraco on the second bus is also clean.

No production retry count, serial timeout, acquisition cadence, controller setting or topology change is justified by Issue #866. The exact lower-level mechanism remains hardware/protocol-unverified and is split to Issue #916.

## Safety boundary

All evidence in this investigation was collected from existing runtime state and read-only HTTP/file/source inspection. No direct diagnostic Modbus command was issued by the investigation. Normal production acquisition remained FC03/read-only.

The investigation performed none of the following:

- Modbus write function codes;
- controller parameter changes;
- serial topology rewiring;
- adapter reset or device power cycle;
- Device Agent/service restart;
- production polling/retry/timeout changes;
- edge SQLite, outbox, snapshot, production-data or named-volume deletion.

## Historical evidence before the 2026-09-04 restart

Authoritative deployment evidence `runtime/deployments/20260903T191159Z/final-state.txt` already contains the retry pattern at approximately six seconds of Device Agent uptime on 2026-09-03.

At that point:

| Evidence                      |                    Value |
| ----------------------------- | -----------------------: |
| Device Agent status           | healthy / MQTT connected |
| Queue depth                   |                        0 |
| Expected / active bus workers |                    2 / 2 |
| Last error                    |                   `null` |
| Normal physical requests      |                       53 |
| Normal retry attempts         |                       12 |
| Normal successes              |                       41 |
| Normal timeouts               |                       12 |
| XJP60D physical requests      |                       37 |
| XJP60D retry attempts         |                       12 |
| XJP60D successes              |                       25 |
| XJP60D timeouts               |                       12 |
| LE-01MP retry attempts        |                        0 |
| Embraco retry attempts        |                        0 |

Most XJP60D targets that had executed by that snapshot already showed `3 requests / 1 retry / 1 timeout / 2 successes`. This predates the 2026-09-04 controlled restart and excludes that restart as the origin of the behavior.

## Fresh bounded production observation

A 45.007-second read-only observation ran from `2026-09-05T10:19:14Z` through `2026-09-05T10:19:59Z` using the existing local Device Agent diagnostics.

Global delta:

| Metric                   | Delta |
| ------------------------ | ----: |
| `samples_total`          |   +49 |
| normal physical requests |   +65 |
| normal retry attempts    |    +8 |
| normal successes         |   +57 |
| normal timeouts          |    +8 |

Health remained stable for the whole window:

- status `ok`;
- MQTT connected;
- queue depth `0`;
- `last_error=null`;
- two expected and two active bus workers;
- workers healthy;
- zero worker failures/restarts;
- zero degraded/cooldown endpoints.

Exactly eight XJP60D targets were due in the window. Every one produced the same delta: **3 physical requests, 1 retry, 1 timeout and 2 successes**.

Affected due targets in that window were:

- `xjp60d:104-03`;
- `xjp60d:106-01`;
- `xjp60d:106-02`;
- `xjp60d:106-03`;
- `xjp60d:126-04`;
- `xjp60d:127-03`;
- `xjp60d:129-02`;
- `xjp60d:131-06`.

All LE-01MP targets due during the same window on `rs485-main` completed with success only and zero retry/timeout. All Embraco targets due on `rs485-embraco` also completed with success only and zero retry/timeout.

## Current runtime cross-section

A second read-only cross-section at `2026-09-05T10:32:30.318588Z` confirmed the pattern remained bounded and family-specific:

| Family  | Targets | Physical requests | Retries | Timeouts | Successes |
| ------- | ------: | ----------------: | ------: | -------: | --------: |
| XJP60D  |      13 |              3025 |    1009 |     1009 |      2016 |
| LE-01MP |      27 |              4185 |       0 |        0 |      4185 |
| Embraco |      13 |              1001 |       0 |        0 |      1001 |

For XJP60D, retries were `33.355%` of physical attempts. The cumulative relation is almost exactly:

```text
3 physical attempts = 1 timeout/retry + 2 successful register reads
```

That shape matches the XJP60D logical read contract: one channel poll reads one value register and one status register separately. It is strong evidence that a recovered timeout occurs inside most logical channel polls.

It does **not** prove which register address times out. Current acquisition metrics aggregate physical requests under the logical XJP target and do not expose the value/status register address.

At the same cross-section, `rs485-main` was not saturated:

- bus load `13.82%`;
- request rate `93/min`;
- scheduler queue depth `0`;
- worker state `running`;
- zero scheduler communication failures;
- zero protocol errors;
- zero I/O errors.

`rs485-embraco` was also healthy with zero retries/timeouts.

## Persistent logical-attempt evidence

`GET /api/v1/xjp60d/configuration` exposes persisted target diagnostics from the existing edge latest-value store. At the same 2026-09-05 cross-section, all 13 XJP60D targets together reported:

- logical attempts: `1,010,394`;
- logical successes: `1,010,196`;
- terminal communication failures: `198`;
- terminal logical failure rate: `0.019596%`.

All 13 targets were simultaneously:

- `state=valid`;
- `recovery_state=steady`;
- `consecutive_failures=0`;
- `last_attempt_at == last_success_at`;
- no cooldown.

This separates the frequent recovered **physical** timeout from an actual logical acquisition failure. The overwhelming majority recover inside the Modbus call before one logical sample is completed.

## Source-path analysis

### XJP60D logical read

`services/device-agent/xjp60d.py` deliberately performs two single-register FC03 reads for one channel:

1. value register;
2. status register.

The controller-compatible implementation does not use the rejected 12-register block request, and it does not cache XJP reads.

### Physical retry accounting

`services/device-agent/modbus_rtu.py` performs `retries + 1` attempts. A timed-out physical attempt is recorded as `timeout` and retried. A successful retry is recorded as `success` and returned to the reader. Protocol, exception-response and I/O failures are tracked separately.

Production `rs485-main` currently uses one retry and a 0.3-second serial timeout; Issue #866 did not change either value.

### No duplicate telemetry from recovered retry

`services/device-agent/adaptive_main.py` creates a single `TelemetryRecord` only after the complete logical XJP channel read succeeds. The scheduler calls `LatestValueStore.record_attempt()` once per logical target execution and publishes one result once per execution.

Therefore an internal physical timeout followed by a successful retry does **not** create duplicate logical samples or duplicate telemetry records.

### Terminal failure is fail-visible

If the logical read ultimately fails after its allowed retries, the scheduled result is emitted as `quality="communication_error"` with no measured value. `LatestValueStore` records the failed attempt and increments failure counters without rewriting the previously successful value as a new valid sample.

Consequently the retry implementation does not silently convert a terminal communication failure into a fresh valid reading.

## Regression attribution

The corrected Mini App deployment did not change Device Agent source:

```text
git diff 13ab26392fcb1c1385dca3c1f619da4512fe568c \
         9a3556b25b257396d15db80af591d1cc3684b8f7 \
         -- services/device-agent
→ zero diff
```

Together with the 2026-09-03 pre-restart evidence, this rules out the 2026-09-04 Mini App deployment as the source of the XJP retry behavior.

## Classification

**Classification:** pre-existing XJP60D-specific device/protocol/timing behavior; restart-specific software regression not supported.

Evidence confidence is high for that classification because:

1. the same pattern exists before the questioned restart;
2. it appears across the XJP target set;
3. LE-01MP on the same `rs485-main` bus does not reproduce it;
4. Device Agent source did not change in the frontend/Mini App cutover;
5. bus load, worker health and queue depth remain bounded;
6. the physical request ratio matches the two-register XJP logical-read shape;
7. terminal logical communication failures are rare and explicitly represented.

## Remaining uncertainty / follow-up

Issue #866 cannot determine the exact low-level cause because current metrics do not retain register address per physical attempt. It is not yet proven whether the timeout is:

- specifically the value register;
- specifically the status register;
- the first XJP request after controller idle;
- a controller firmware turnaround/wakeup characteristic;
- or XJP-specific physical/electrical sensitivity on the current RS-485 topology.

That residual question is tracked in **Issue #916**. #916 is hardware/protocol validation and is not authorization for a service restart, adapter reset, wiring change, topology isolation, termination/bias action, power cycle or any controller write. Those actions require a separate explicit Product Owner gate.

## Verification actually run

On the production Raspberry Pi repository checkout:

- `python3 -m unittest tests.test_xjp60d` — **6/6 PASS**;
- `python3 -m unittest tests.test_modbus_rtu tests.test_modbus_rtu_recovery` — **18/18 PASS**;
- an attempted host-system import of `tests.test_adaptive_scheduler` could not run because the production Pi system Python intentionally does not contain the development `paho` dependency. No dependency was installed onto production to force that test. Exact-head GitHub CI remains the heavy verification authority for the final documentation/state candidate.

State Model v2 and diff-integrity checks are required again after the final candidate is committed.

## Decision

No product/runtime code change is made under #866. Existing read-only FC03 acquisition remains operational. Any future change to timeout, retry strategy, pacing or physical topology requires evidence from #916 and a separate focused implementation/physical-action Work Package.
