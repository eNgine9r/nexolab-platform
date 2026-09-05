# Issue #916 — XJP60D status-read timeout validation

Date: 2026-09-05

Profile: `LOCAL_LAN`

Scope: bounded read-only hardware/protocol validation on the production Raspberry Pi.

## Outcome

The recurring recovered XJP60D timeout is localized to the **first FC03 attempt for the status register**, not to the first request after controller idle.

For every representative XJP poll captured at physical-attempt resolution, the observed order was:

1. value register, attempt 1 — `success`;
2. status register, attempt 1 — `timeout`;
3. status register, attempt 2 — `success`.

The pattern was reproduced on Units `102`, `104`, and `106`, across channels `1`, `2`, and `3`. The evidence supports an XJP controller/status-phase protocol or turnaround timing characteristic. It does not support a generic `rs485-main` electrical/bus failure or a restart-specific software regression.

No production timing, retry, cadence, topology, controller, or hardware setting was changed.

## Evidence authority

The production Device Agent relevant source files are byte-identical between deployed product source `9a3556b25b257396d15db80af591d1cc3684b8f7` and the current repository main used for inspection:

- `services/device-agent/xjp60d.py`;
- `services/device-agent/modbus_rtu.py`;
- `services/device-agent/managed_main.py`;
- `services/device-agent/dual_bus_main.py`;
- `services/device-agent/adaptive_main.py`.

The official Copeland/Dixell profile authority is `config/edge/dixell-xjp60d-v1.6-register-map.yaml`, package SHA-256 `e1a4e160ba9ac0ea0e2a610f2e5fc3aa581b1f6d2c69c61f0853852cdfd0ffa3`.

`XJP60DReader.read_channel()` always reads the value register first and the status register second. `ModbusRTUClient` records each physical FC03 attempt independently. The acquisition retry counter increments only when `measurement.attempt > 1`, so the observed outcome sequence also identifies the attempt ordinal without issuing any extra Modbus request.

## Register map

| Channel | Value register | Status register |
| ------: | -------------: | --------------: |
|       1 | 256 (`0x0100`) |  257 (`0x0101`) |
|       2 | 258 (`0x0102`) |  259 (`0x0103`) |
|       3 | 260 (`0x0104`) |  261 (`0x0105`) |
|       4 | 262 (`0x0106`) |  263 (`0x0107`) |
|       5 | 264 (`0x0108`) |  265 (`0x0109`) |
|       6 | 266 (`0x010A`) |  267 (`0x010B`) |

## Passive physical-attempt captures

The validation repeatedly polled the existing local `/health` snapshot while normal production acquisition continued. The observer did not initiate a Modbus transaction; it only read counters already emitted by Device Agent after each physical attempt.

| Target          | Value attempt 1    | Status attempt 1    | Status attempt 2   |
| --------------- | ------------------ | ------------------- | ------------------ |
| `xjp60d:102-01` | success, 37.122 ms | timeout, 312.791 ms | success, 42.401 ms |
| `xjp60d:102-02` | success, 36.809 ms | timeout, 314.427 ms | success, 42.386 ms |
| `xjp60d:106-02` | success, 36.802 ms | timeout, 318.138 ms | success, 43.555 ms |
| `xjp60d:104-03` | success, 35.269 ms | timeout, 312.436 ms | success, 50.369 ms |

Across these four polls:

- value attempt-1 success latency mean: `36.501 ms`;
- status attempt-1 timeout latency mean: `314.448 ms`;
- status attempt-2 success latency mean: `44.678 ms`.

The timeout duration tracks the configured `0.3 s` serial timeout plus bounded overhead. The retry succeeds immediately on the same status register without adapter reset, topology change, controller action, or another logical poll.

The capture windows were `2026-09-05T11:43:54Z` through `11:45:16Z`, with normal acquisition remaining active.

## First-after-idle hypothesis

The XJP targets run on a `60 s` cadence. For representative Unit `104`, channel `3` is the active XJP target on that controller. Its first value-register request after the long idle interval succeeded in `35.269 ms`; the immediately subsequent status-register request timed out, then the retry succeeded.

Unit `102` reproduced the same ordering on two adjacent channels. Therefore the failing request is not the first request after controller idle. It is the first attempt of the second/status read in the normal XJP two-register sequence.

## Same-bus LE-01MP comparison

A bounded adjacent observation on `rs485-main` from `2026-09-05T11:46:34Z` to `11:46:38Z` captured seven Unit `203` LE-01MP reads:

- 7 physical requests;
- 7 successes;
- 0 retries;
- 0 timeouts;
- 0 protocol errors;
- 0 I/O errors;
- 0 Modbus exception responses.

Representative LE-01MP request latencies were approximately `47.2–48.7 ms`. This confirms the shared bus can complete normal FC03 traffic during the same production session while XJP status-attempt-1 timeouts continue.

## Error-class separation

Current `rs485-main` runtime counters after the bounded captures remained:

- request rate: `93/min`;
- bus load: approximately `13.98%`;
- scheduler queue depth: `0`;
- timeouts: present and attributable to the recovered XJP status-read pattern;
- protocol errors: `0`;
- I/O errors: `0`;
- Modbus exception responses: `0`.

CRC mismatches are classified by `ModbusRTUClient` as `protocol_error`, so the zero protocol-error counter also means no CRC mismatch was observed in the current Device Agent process. The failure class is timeout, not CRC/protocol corruption or host serial I/O failure.

Post-capture Device Agent health remained `ok`, MQTT connected, queue depth `0`, two of two bus workers healthy, worker failures/restarts `0`, and `last_error=null`.

## Logical telemetry impact

A post-capture XJP configuration snapshot contained 13 active targets with `1,011,420` logical attempts, `1,011,222` successes, and `198` terminal communication failures: `0.019576%` terminal logical failure rate. All 13 targets were `valid`, `steady`, and had `consecutive_failures=0`.

Recovered status-register retries therefore remain predominantly an efficiency/latency issue rather than a telemetry-integrity failure. Issue #866 already proved that recovered physical retries produce one logical telemetry record and terminal failures remain fail-visible as `communication_error`.

## Classification and decision

**Classification:** systematic XJP60D status-register first-attempt timeout, recovered by attempt 2; controller/status-phase protocol or turnaround timing behavior is supported. A generic bus-wide physical RS-485 fault, first-request-after-idle behavior, CRC corruption, host I/O fault, restart regression, or Mini App regression is not supported by the evidence.

The current evidence does not distinguish whether the status register itself has a controller-specific first-access response characteristic or whether a deliberate inter-register pause would avoid the timeout. Answering that narrower optimization question would require a separately scoped controlled experiment that changes request ordering/pacing or adds diagnostic FC03 traffic.

No such experiment is justified as part of #916 because current acquisition is stable: bus load is low, queue depth is zero, retries recover, and terminal logical failure rate is about `0.02%`. Production timeout/retry/cadence behavior remains unchanged.

If optimization is later prioritized, create a focused Work Package with an explicit bounded test matrix for inter-register delay/status-only ordering and require before/after hardware evidence before any production timing change.

## Safety evidence

No Modbus write function code was issued. The validation performed no direct diagnostic Modbus request, service restart, adapter reset, topology rewire, cable move, termination/bias change, controller action, power cycle, production cutover, polling/retry/timeout/cadence mutation, persistent-data deletion, evidence deletion, or named-volume deletion.

The only live observation activity was local HTTP GET polling of existing Device Agent diagnostics while normal FC03 production acquisition continued.
