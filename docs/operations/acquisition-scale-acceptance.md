# NEXOLAB acquisition scale and truthful-state acceptance

## Purpose

Issue #289 is the final validation Work Package for the acquisition optimization epic. It validates the merged registry, scheduler, persisted delivery, route-persistent telemetry runtime and Live Dashboard workspace as one read-only system.

This document declares targets **before** executing the matrix. Results must not redefine the pass criteria after the fact.

## Evidence classification

Two evidence classes are mandatory and must never be conflated:

```text
Deterministic software evidence
- fake clock and fake serial timing;
- generated acquisition registry inventories;
- local PostgreSQL/MQTT/REST/WebSocket Compose runtime;
- authenticated browser contexts;
- reproducible CI artifacts.

Controlled hardware evidence
- actual Raspberry Pi 5;
- installed isolated USB-RS-485 adapter and wiring;
- real registry-eligible endpoints;
- read-only FC03 request counters and measured serial latency;
- actual CPU, memory, disk, queue and bus-utilization evidence.
```

Issue #289 cannot be classified as fully complete until the controlled hardware matrix passes. When only deterministic evidence is available, report exactly:

```text
software verified; hardware performance acceptance pending
```

## Safety and architecture invariants

Every scenario must preserve:

- read-only FC03 normal acquisition;
- one serialized worker per physical bus;
- only registry-eligible active targets scheduled;
- no page, browser, REST read or WebSocket subscription may create a physical read job;
- no browser action may mutate discovery, configuration, registry lifecycle, scheduler priority or interval;
- no FC05, FC06, FC15 or FC16;
- no production/site cutover;
- no deletion of PostgreSQL, SQLite, MQTT or persistent-volume data;
- no mandatory internet, cloud, CDN, remote font or paid runtime dependency.

## Deterministic inventory profiles

The matrix uses generated read-only registries with valid canonical profiles.

| Profile    | Active XJP60D channels | LE-01MP meters | LE metrics | Total active targets | Purpose                                                |
| ---------- | ---------------------: | -------------: | ---------: | -------------------: | ------------------------------------------------------ |
| `pilot`    |                      2 |              4 |         32 |                   34 | Current laboratory-sized baseline                      |
| `expanded` |                     72 |              8 |         64 |                  136 | Twelve six-channel controllers plus eight meters       |
| `stress`   |                    144 |             12 |         96 |                  240 | Bounded validation above the expected first deployment |

Inactive inventory is tested separately. Disabled, reserve, retired, uninstalled, discovery-only and invalid targets must produce **zero** normal executions.

## Scheduler target thresholds

Default policy under deterministic tests:

```text
high = 5 seconds
medium = 10 seconds
low = 30 seconds
startup spread = 5 seconds
failure threshold = 3
initial cooldown = 30 seconds
maximum cooldown = 300 seconds
high fairness burst = 8
low fairness burst = 12
```

### Fast healthy endpoint scenario

Fake serial duration: 2 ms per physical attempt.

For `pilot`, `expanded` and `stress` profiles:

- exactly one configured worker per bus after `start()`;
- maximum concurrent fake serial reads per bus: `1`;
- callback errors: `0`;
- communication failures: `0`;
- overruns: `0`;
- cooldown entries: `0`;
- disabled/ineligible target executions: `0`;
- every active priority class receives executions when present;
- no catch-up burst after an overrun or clock advance.

The generated workload is considered schedulable only when theoretical utilization is below 70%:

```text
sum(target request duration / target interval) × 100 < 70%
```

The 70% planning guardrail reserves capacity for serial framing variance, retries, service diagnostics and operating-system jitter. It is not a claim about the real bus until hardware measurement exists.

### Slow and unavailable endpoint scenario

One endpoint is configured to take 150 ms and fail with a communication timeout. Healthy endpoints remain 2 ms.

Acceptance:

- the failing endpoint enters cooldown after exactly the configured failure threshold;
- cooldown applies to sibling targets on the same Unit ID only;
- unrelated Unit IDs continue to execute;
- at least one high-priority target on a healthy endpoint executes after cooldown entry;
- retained latest value and original `captured_at` survive communication failure;
- quality changes to `communication_error` and `last_error` is populated;
- no parallel request is introduced while the slow endpoint is executing;
- callback errors remain `0`;
- no UI/browser input changes the cooldown state.

### Fairness and deadline behavior

Acceptance:

- high-priority targets win before medium/low targets while fairness budgets are not exhausted;
- a due non-high target is forced after at most `fairness_high_burst` consecutive high selections;
- a due low target is forced after at most `fairness_low_burst` consecutive non-low selections;
- a request duration longer than its interval increments overrun and skipped-deadline counters;
- expired occurrences advance to the next future monotonic deadline and do not create a catch-up burst;
- maximum due queue depth remains bounded by configured active targets.

## Browser and delivery thresholds

The authenticated Compose/browser matrix uses equal bounded acquisition windows.

### Physical request-rate invariant fixture

For the deterministic 20 requests/second fixture:

- every phase remains inside `17..23 requests/second`;
- spread between maximum and minimum phase rate is at most `3.5 requests/second`;
- discovery delta: `0`;
- configuration mutation delta: `0`;
- Device Agent control-proxy requests produced by normal pages are GET-only.

Required phases:

1. no browser;
2. Overview open;
3. Overview refresh;
4. persisted Live Dashboard open;
5. Overview + Live Dashboard + Refrigeration + Energy in authenticated contexts;
6. three additional authenticated browser contexts;
7. WebSocket offline/online reconnect;
8. Telemetry Service restart and recovery.

### Selected-series delivery

For a saved Live Dashboard containing one canonical series:

- exactly one selected `latest` request;
- exactly one selected `history` request;
- both requests include the saved `channel_id` and `metric`;
- no broad telemetry inventory bootstrap after opening the saved definition;
- maximum concurrent physical WebSockets per authenticated scope: `1`;
- acquisition mutations: `0`;
- persisted definition remains available after Telemetry Service restart.

### Operator time-to-usable targets

Measured in the local authenticated CI runtime:

- first persisted Live Dashboard open: less than 5 seconds;
- return to Overview with retained telemetry: less than 2 seconds;
- route transitions to Refrigeration and Energy: less than 5 seconds;
- recovery after WebSocket reconnect: less than 10 seconds;
- no full-page blank state when retained values exist.

These are local software targets. Real operator latency on the Raspberry Pi must be recorded separately.

## Truthful-state matrix

The following states must be distinguishable in UI and evidence:

| Condition                                          | Required state         | Retained value behavior                                 |
| -------------------------------------------------- | ---------------------- | ------------------------------------------------------- |
| Initial selected snapshot and socket pending       | `connecting` / loading | No fabricated value                                     |
| Fresh persisted/latest sample and connected socket | `live`                 | Current value visible                                   |
| Socket reconnecting, retained sample available     | `reconnecting`         | Value remains visible, not labelled live                |
| Sample older than stale threshold                  | `stale`                | Original value and timestamp preserved                  |
| Delivery transport unavailable                     | `offline`              | Retained value visible when available                   |
| Sample reports sensor fault                        | `sensor_error`         | Fault remains distinct from transport outage            |
| Sample reports communication error                 | `communication_error`  | Prior successful value may remain with truthful quality |
| Missing authorization                              | `unauthenticated`      | No telemetry/dashboard requests after gate              |
| Missing permission                                 | `forbidden`            | No protected data or mutation controls                  |
| Invalid runtime configuration                      | `configuration_error`  | No demo fallback presented as production data           |
| Empty saved dashboard                              | empty state            | No universal scan or fabricated series                  |

## Backend and data-consistency targets

- committed telemetry event IDs remain unique across MQTT interruption and outbox replay;
- latest REST and selected WebSocket payloads agree by event identity when they represent the same sample;
- backend restart does not convert old retained telemetry into fresh data;
- outbox drain produces no duplicate committed event;
- bounded history and latest queries remain authorized and organization-scoped;
- no secret, token, raw production payload or private network credential enters evidence artifacts.

## Hardware evidence schema

The controlled Raspberry Pi run must emit a machine-readable JSON record containing:

```json
{
  "schema_version": 1,
  "classification": "hardware",
  "source_commit": "<exact main SHA>",
  "node_id": "<sanitized node id>",
  "window_seconds": 60,
  "phases": [
    {
      "name": "no-browser",
      "normal_physical_requests_delta": 0,
      "retry_attempts_delta": 0,
      "outcomes_delta": {},
      "bus_busy_seconds_delta": 0,
      "bus_utilization_percent": 0,
      "scheduler_lag_max_seconds": 0,
      "missed_deadlines_delta": 0,
      "cpu_percent": 0,
      "memory_rss_bytes": 0,
      "disk_free_bytes": 0,
      "outbox_depth": 0,
      "ingestion_to_websocket_p95_ms": 0
    }
  ],
  "discovery_delta": 0,
  "configuration_mutation_delta": 0,
  "modbus_write_attempts": 0
}
```

Required physical phases:

1. no browser;
2. Overview;
3. one persisted Live Dashboard;
4. repeated route transitions;
5. multiple authenticated browser workstations;
6. WebSocket reconnect;
7. one known unavailable endpoint;
8. MQTT interruption and local outbox drain.

## Controlled Raspberry Pi capture procedure

The repository collector reads only local `GET /metrics`, `GET /health` and `GET /ready`. It does not open the serial adapter, execute discovery, mutate the registry or issue a Modbus write.

First identify the running Device Agent container without assuming a Compose project name:

```bash
cd ~/nexolab-platform

git switch main
git pull --ff-only

SOURCE_COMMIT="$(git rev-parse HEAD)"

docker ps \
  --filter label=com.docker.compose.service=device-agent \
  --format 'table {{.ID}}\t{{.Names}}\t{{.Status}}'
```

Select the controlled installation container explicitly, then resolve its host PID:

```bash
export DEVICE_AGENT_CONTAINER='<container id from the previous command>'
export DEVICE_AGENT_PID="$(
  docker inspect --format '{{.State.Pid}}' "$DEVICE_AGENT_CONTAINER"
)"

printf 'Source commit: %s\nDevice Agent PID: %s\n' \
  "$SOURCE_COMMIT" "$DEVICE_AGENT_PID"
```

Capture one equal bounded window while the named operator condition is held:

```bash
python3 scripts/acquisition_hardware_acceptance.py capture \
  --phase no-browser \
  --source-commit "$SOURCE_COMMIT" \
  --node-id edge-01 \
  --pid "$DEVICE_AGENT_PID" \
  --window-seconds 60 \
  --output runtime/evidence/acquisition-hardware-matrix.json
```

Repeat the same command with exactly these phase names:

```text
no-browser
overview
live-dashboard
route-transitions
multiple-browsers
websocket-reconnect
unavailable-endpoint
mqtt-outbox-drain
```

The collector does not create the test condition. A Product Owner or controlled-site operator must separately perform the approved read-only UI activity. Physical endpoint isolation and MQTT interruption are disruptive acceptance actions and require an explicitly controlled maintenance window. They must not include controller configuration, Modbus write functions, production cutover or persistent-data deletion.

Validate the final evidence after all eight unique phases:

```bash
python3 scripts/acquisition_hardware_acceptance.py validate \
  --input runtime/evidence/acquisition-hardware-matrix.json \
  --require-complete
```

Do not attach raw telemetry values, credentials, bearer tokens, private network addresses or unsanitized production logs to GitHub. Attach only the validated aggregate JSON and separately approved sanitized snapshots.

## Required artifacts

Deterministic software:

- `acquisition-scale-matrix.json`;
- `acquisition-ui-invariant.json`;
- `live-dashboard-summary.json`;
- truthful-state test output;
- CI, authenticated browser, refrigeration browser and Offline Bundle results.

Controlled hardware:

- `acquisition-hardware-matrix.json` matching the schema above;
- sanitized `/metrics`, `/health` and `/ready` snapshots;
- exact source commit and local runtime versions;
- no raw production telemetry values beyond approved aggregate evidence.

## Completion rule

Issue #289 is complete only when both deterministic and controlled hardware evidence pass. If the software matrix passes but hardware access is unavailable, the PR or checkpoint must remain truthful and state:

```text
software verified; hardware performance acceptance pending
```
