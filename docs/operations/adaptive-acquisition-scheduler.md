# Adaptive Acquisition Scheduler

## Purpose

Issue #285 replaces the hardware Device Agent's monolithic full-cycle loop with deterministic, read-only jobs derived exclusively from the active acquisition registry.

The scheduler protects the physical RS-485 bus while keeping critical temperature channels responsive:

- one worker per physical registry bus;
- one request sequence at a time on that bus;
- monotonic, jitter-free target deadlines;
- bounded `high`, `medium` and `low` normal-acquisition classes;
- explicit service operations such as discovery remain on demand;
- bounded fairness prevents permanent starvation;
- repeatedly unavailable endpoints enter cooldown;
- successful latest values remain readable while the next poll is pending or communication is degraded.

This implementation does not perform Modbus writes, commissioning, browser-driven polling or cloud synchronization.

## Eligibility boundary

Only targets for which both the registry device and registry target have lifecycle `active` enter normal scheduling. The target must also use read-only FC03.

Inventory targets in these states remain visible but create no normal scheduler job:

- `disabled`;
- `reserve`;
- `retired`;
- `uninstalled`;
- `discovery_only`;
- `invalid`.

A registry mutation reconciles the scheduler in memory after the atomic SQLite registry transaction. A newly ineligible target is removed from future scheduling. A request already holding the bus lock may finish before the mutation completes; no second or parallel request is started.

## Default policy

Defaults deliberately do not promise a faster high-priority interval than the previously configured `SAMPLE_INTERVAL_SECONDS` baseline.

| Class | Default | Current target mapping |
|---|---:|---|
| `high` | `max(5 s, SAMPLE_INTERVAL_SECONDS)` | XJP60D temperature and status target |
| `medium` | `max(10 s, high)` | LE-01MP voltage, current, frequency, active power and power factor |
| `low` | `max(30 s, medium)` | LE-01MP reactive/apparent power and internal diagnostics |
| `on_demand` | no recurring job | explicit discovery/configuration service operations |

All normal intervals are bounded to `1..3600` seconds and must satisfy `high <= medium <= low`.

Final site intervals remain hardware-unverified until measured on the real Raspberry Pi, adapter and RS-485 topology. A local override is configuration, not evidence that the bus can sustain the selected rate.

## Local configuration

```dotenv
ACQUISITION_HIGH_INTERVAL_SECONDS=5
ACQUISITION_MEDIUM_INTERVAL_SECONDS=10
ACQUISITION_LOW_INTERVAL_SECONDS=30
ACQUISITION_STARTUP_SPREAD_SECONDS=5
ACQUISITION_FAILURE_THRESHOLD=3
ACQUISITION_COOLDOWN_INITIAL_SECONDS=30
ACQUISITION_COOLDOWN_MAX_SECONDS=300
ACQUISITION_FAIRNESS_HIGH_BURST=8
ACQUISITION_FAIRNESS_LOW_BURST=12
```

Validation is fail closed:

- interval and cooldown values must be `1..3600` seconds;
- failure threshold must be `1..20`;
- high fairness burst must be `1..100`;
- low fairness burst must be `1..200` and cannot be smaller than the high burst;
- initial cooldown cannot exceed maximum cooldown.

No remote configuration service is required. These values are local runtime configuration and remain usable without internet access.

## Deadline and fairness model

Each registry-eligible target receives an explicit priority, interval and monotonic next deadline.

Selection rules on each bus are:

1. choose the highest-priority due target;
2. within a class, choose the oldest effective deadline;
3. after the configured consecutive high-priority burst, force a due non-high target;
4. after the configured consecutive non-low burst, force the oldest due low target.

A deadline advances from its previous monotonic value rather than from completion time. If a slow read finishes after one or more future intervals, expired occurrences are counted as skipped and the target advances to the next future deadline. The scheduler never launches a catch-up burst.

## Bus serialization and service operations

Every normal worker and explicit service operation uses the same bus-operation lock. This preserves:

- one active Modbus master request sequence per physical bus;
- existing timeout and retry behavior;
- existing serial inter-frame behavior;
- separation between normal acquisition and discovery accounting.

Opening Overview, Live Data, REST routes or WebSocket connections does not create jobs, change priorities or change intervals. Subscription isolation is a separate Work Package, Issue #286; Issue #285 introduces no browser-controlled physical polling path.

## Cooldown and circuit breaker

Failure state is tracked by `(bus_id, unit_id)`, not by browser session or telemetry subscriber.

When consecutive communication failures reach the configured threshold:

- the endpoint enters cooldown;
- all normal jobs for that Unit ID are deferred to the cooldown deadline;
- another Unit ID on the same bus remains eligible;
- cooldown grows exponentially from the initial duration to the configured maximum;
- a successful post-cooldown read resets the failure streak and trip count.

A sensor-quality state such as `sensor_error` is a successful communication attempt. It remains truthful telemetry but does not trip the communication circuit breaker.

## Latest-value cache

The existing edge SQLite database gains `acquisition_latest_values`.

Each attempt stores:

- target and source identity;
- value and measurement capture time from the last successful communication;
- current quality;
- last attempt time;
- last success time;
- alarm/raw fields where available;
- the most recent communication error.

On communication failure, the prior successful value and its `captured_at` timestamp are preserved while `quality`, `last_attempt_at` and `last_error` are updated. Consumers can therefore distinguish an older retained value from a live successful sample.

The read-only local endpoint is:

```text
GET /api/v1/acquisition-latest
```

It returns at most 500 items by default and never causes a Modbus request.

## Restart behavior

At startup, jobs are deterministically spread across the bounded startup window. When the latest-value table contains a recent attempt, the first deadline uses the remaining target interval.

Restart therefore does not trigger:

- a full discovery scan;
- one immediate request per inventory target;
- a catch-up burst for missed downtime intervals.

The cache is rebuilt from the durable local SQLite read model, not from an uncontrolled full-bus scan.

## Metrics and health evidence

`/metrics`, `/health` and `/ready` include `acquisition.scheduler` evidence:

- configured target count and explicit target priority/interval;
- one worker count per bus;
- current and maximum due queue depth;
- executions and successes;
- communication failures and internal callback errors;
- missed deadlines;
- skipped expired deadlines;
- overruns;
- deferred work;
- cooldown entries and active cooldown endpoint count;
- fairness-forced selections;
- scheduler lag;
- bounded rolling bus-load percentage;
- executions by priority.

The JSON evidence uses bounded categories. It adds no secret labels and no remote telemetry dependency.

## Verification

Targeted software verification:

```bash
PYTHONPATH=services/device-agent \
  python -m unittest discover -s services/device-agent/tests -v

python -m py_compile \
  services/device-agent/adaptive_scheduler.py \
  services/device-agent/latest_values.py \
  services/device-agent/registry_main.py
```

Required completion gates also include the Edge image, Device Agent fleet, MQTT TLS, telemetry, authenticated browser acquisition invariant and disconnected Offline Bundle workflows.

## Hardware acceptance boundary

Software acceptance can prove deterministic ordering, no parallel bus worker, cooldown, fairness, cache persistence and restart behavior with fake clock/serial tests.

Physical acceptance remains pending until the Product Owner can provide the real Raspberry Pi and RS-485 environment. The hardware procedure must remain read-only and collect:

- per-target and total physical request counters;
- measured request latency and retries;
- bus utilization;
- scheduler lag and missed deadlines;
- high-priority deadline behavior under absent/slow endpoints;
- confirmation that UI activity does not change request rate.

No Modbus write, controller configuration or production cutover is part of this Work Package.
