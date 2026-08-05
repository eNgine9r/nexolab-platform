# NEXOLAB acquisition performance metrics

## Purpose

Issue #283 establishes the measurable baseline for read-only Modbus acquisition. It does not change the configured target set, retry policy, fixed sample interval or physical device configuration.

The required invariant is:

```text
normal UI navigation, refresh, REST reads and WebSocket reconnects
must not increase or trigger physical Modbus requests
```

Only explicit permission-gated service operations, currently XJP60D discovery, may use the bus outside normal acquisition. Those requests are recorded separately.

## Runtime endpoints

The managed Device Agent exposes local JSON metrics at:

```text
GET http://127.0.0.1:8081/metrics
```

The existing endpoints remain available:

```text
GET /health
GET /ready
```

`/health` and `/ready` include the same `acquisition` object. The endpoint is local read-only diagnostics and must not be published to an untrusted network.

## Metric model

The response uses `schema_version: 1` and includes:

- `polling_policy`: confirms that this Work Package retains the existing fixed interval;
- `configured_logical_targets`: active XJP60D channels plus LE-01MP metric reads;
- `normal.physical_requests_total`: every serial FC03 attempt, including retries;
- `normal.retry_attempts_total`: attempts whose ordinal is greater than one;
- `normal.outcomes`: `success`, `timeout`, `protocol_error`, `exception_response` or `io_error`;
- `normal.bus_busy_seconds_total`: measured duration spent in physical request attempts;
- `service_operations`: discovery and future explicitly named non-normal operations;
- `request_series`: bounded aggregation by operation, bus, device family, Unit ID, function and outcome;
- `targets`: bounded per-target outcome and latency summaries;
- `cycle`: starts, completions, failures, overruns, skipped cycles, request delta and bus utilization for the last cycle.

Latency buckets are cumulative upper bounds in milliseconds:

```text
10, 25, 50, 100, 250, 500, 1000
```

Target IDs are derived from the configured inventory:

- XJP60D: `UNIT-CHANNEL`, for example `106-03`;
- LE-01MP: `UNIT-METRIC`, for example `200-active-power`.

No raw register values, telemetry values, MQTT payloads, event IDs, credentials, bearer tokens or production data are stored as metric labels.

## Request accounting contract

One physical serial request attempt produces exactly one measurement.

Examples:

```text
first attempt succeeds
→ one physical request, outcome success, retry count 0

first attempt times out and retry succeeds
→ two physical requests, outcomes timeout + success, retry count 1

CRC/protocol failure
→ one physical request, outcome protocol_error
```

Instrumentation failures are isolated and cannot stop read-only acquisition.

## Discovery separation

The normal polling loop uses `operation=normal`.

Explicit XJP60D discovery uses:

```text
operation=discovery
device_family=xjp60d
target_id=catalog-discovery
```

Discovery counters must never be included when comparing normal page/browser acquisition rates.

## CI acceptance

The authenticated dashboard workflow runs:

```bash
bash scripts/run-acquisition-invariant-browser-acceptance.sh
```

The wrapper starts a deterministic local fixed-rate acquisition fixture, then runs the established authenticated dashboard stack and Playwright suite.

The focused test records rates for:

1. no browser;
2. Overview open;
3. Overview refresh;
4. Live Data;
5. three authenticated browser contexts on different routes;
6. browser offline/online and WebSocket reconnect.

Acceptance requires:

- each measured request rate remains inside the same fixed envelope;
- rate spread across phases remains bounded;
- normal page activity emits only GET requests to the Device Agent control proxy;
- discovery delta remains zero;
- configuration-mutation delta remains zero.

Evidence is written to:

```text
dashboard-acceptance-evidence/acquisition-ui-invariant.json
```

The fixture proves browser/control-plane isolation deterministically. Production request accounting is independently verified with fake serial frames through Device Agent unit tests.

## Local software checks

From the repository root:

```bash
python3 -m unittest discover -s services/device-agent/tests -p 'test_*.py'
npm run format:check
npm run lint
npm run typecheck
npm test
npm run build
```

Full authenticated browser acceptance requires Docker and Playwright:

```bash
bash scripts/run-acquisition-invariant-browser-acceptance.sh
```

## Hardware acceptance

Software evidence does not establish the final Raspberry Pi/RS-485 request envelope.

On the controlled installation, record `/metrics` across equal bounded windows with:

1. no browser;
2. Overview open;
3. one Live Dashboard;
4. multiple pages and browser workstations;
5. WebSocket reconnect.

Compare only `acquisition.normal.physical_requests_total`. Record explicit discovery separately. The normal request rate must remain within scheduler variance in every phase.

Until this physical matrix is executed, report:

```text
software verified; hardware request-rate acceptance pending
```

## Safety

- read-only FC03 only;
- no FC05, FC06, FC15 or FC16;
- no automatic discovery from normal pages;
- no polling-policy or interval change in Issue #283;
- no raw production values or secrets in evidence;
- no persistent-volume deletion;
- no production/site cutover.
