# Issue #440 — Acquisition bus-worker recovery acceptance

## Outcome

Issue #440 fixes a production runtime failure discovered during Issue #289
hardware acceptance: the Device Agent process and Docker healthcheck could remain
alive while the adaptive acquisition worker for the physical RS-485 bus was dead,
leaving eligible polling jobs queued indefinitely.

Issue #440 is software verified and hardware verified on the controlled
Raspberry Pi installation. Final project-state exact-head CI and merge remain
pending at this checkpoint.

## Repository scope

- Issue: #440
- Pull Request: #441
- Branch: `fix/440-acquisition-worker-self-recovery`
- Base main: `f523f14dc17b28de3683e1773a2ef5a7143a194f`
- Verified implementation head:
  `97fab27dd99a8685edc6c96c8e99bc0db88e1bd7`

Implementation scope is limited to:

- `services/device-agent/adaptive_main.py`
- `services/device-agent/adaptive_scheduler.py`
- `services/device-agent/tests/test_adaptive_main.py`
- `services/device-agent/tests/test_adaptive_scheduler.py`

No dependency, registry-schema, polling-interval, priority, fairness, controller
configuration or Modbus write change is included.

## Original physical defect

The first controlled Issue #289 no-browser hardware phase established:

- 33 poll-eligible targets;
- 33 due scheduler jobs;
- historical normal physical requests: 13,531;
- 60-second normal physical request delta: 0;
- `rs485-main.worker_count = 0`;
- maximum scheduler lag approximately 53.93 seconds;
- Docker container health remained healthy;
- the stable USB-RS485 device path remained present.

The zero-request phase is defect evidence only. It must not be reused as a
passing Issue #289 request-rate baseline.

## Root cause

The adaptive scheduler could retain a dead bus thread in its internal thread
mapping. Worker startup treated mapping membership as sufficient even when the
thread was no longer alive. The bus loop had no top-level unexpected-failure
boundary, and the Device Agent runtime loop did not supervise worker liveness.

This allowed the HTTP/container process to remain alive while normal acquisition
silently stopped.

## Correction

The focused correction:

- detects missing or dead workers for buses with configured eligible jobs;
- preserves exactly one serialized worker per physical bus;
- replaces only a dead worker;
- supervises worker liveness from the Device Agent runtime loop;
- advances expired deadlines to a future cadence before recovery so recovery
  cannot generate a catch-up burst;
- records bounded worker failure/restart diagnostics;
- exposes expected and active worker counts and worker state;
- fails health closed while an eligible configured bus has no live worker;
- leaves UI, browser, REST and WebSocket activity unable to create physical
  polling jobs or workers directly.

Normal physical acquisition remains FC03 read-only.

## Software verification

Raspberry Pi execution-host verification:

- changed-file Python compile: PASS;
- `git diff --check`: PASS;
- Modbus write-token safety audit: PASS;
- focused adaptive tests: 16/16 PASS;
- full Device Agent suite: 122/122 PASS.

Deterministic fault injection proves:

- worker failure becomes observable;
- `active_bus_workers` becomes zero while the worker is dead;
- exactly one replacement worker is created;
- a second supervisor pass cannot create a duplicate worker;
- expired deadlines are skipped forward rather than executed as a burst;
- acquisition resumes on the future cadence;
- health fails closed when eligible polling has no worker.

Exact implementation-head GitHub workflows were all GREEN:

- CI — run `31773335041`;
- Acquisition Scale Acceptance — run `31773335047`;
- Edge image — run `31773335084`;
- Container Supply Chain — run `31773335022`;
- Disaster Recovery TLS Fleet — run `31773335034`;
- MQTT TLS Fleet Acceptance — run `31773335136`;
- Device Agent Fleet Acceptance — run `31773335114`;
- Authenticated Dashboard Acceptance — run `31773335223`;
- Offline Bundle — run `31773335094`.

Offline Bundle proved disconnected startup and update/rollback persistent-data
preservation.

## Controlled Raspberry Pi hardware acceptance

Candidate source:

`97fab27dd99a8685edc6c96c8e99bc0db88e1bd7`

Candidate image:

`nexolab-device-agent:issue-440-97fab27dd99a`

The acceptance recreated only the Device Agent container. The existing named
edge SQLite volume remained `nexolab-edge_edge-data`.

After candidate startup:

- expected bus workers: 1;
- active bus workers: 1;
- `workers_healthy = true`;
- `rs485-main.worker_count = 1`;
- worker state: `running`;
- worker failures: 0;
- worker restarts: 0;
- Docker health remained healthy.

Read-only 60-second no-browser physical window:

- normal physical requests: 155;
- successful outcomes: 132;
- timeout outcomes: 23;
- retry attempts: 18;
- bus busy time: 13.41896 seconds;
- bus utilization: 22.365%;
- maximum scheduler lag: 2.183755 seconds;
- missed deadlines: 41;
- deferred executions: 24;
- overruns: 0;
- CPU: 8.162%;
- RSS: 33,996,800 bytes;
- outbox depth: 0.

The evidence demonstrates that normal physical acquisition resumed with exactly
one serialized worker and remained live for the acceptance window.

## Truthful residual evidence

The hardware collector reported `health` and `ready` as degraded during the
window because real endpoints produced timeout and retry activity.

This is intentionally **not** classified as an Issue #440 failure. Worker
liveness was restored and remained healthy. The timeout/retry, missed-deadline
and defer evidence is transferred unchanged into Issue #289 for the remaining
scale, performance and truthful-state analysis.

## Safety evidence

No acceptance step performed:

- Modbus write;
- hardware/controller write;
- registry mutation;
- polling-policy mutation;
- dependency change;
- named-volume deletion;
- persistent-data deletion;
- production/site cutover.

## Continuation

Issue #289 remains blocked until Issue #440 / PR #441 is merged into `main`.

After merge, Issue #289 must resume from a **fresh** equal-window
`no-browser` hardware baseline. The original zero-request defect window is not
valid passing performance evidence.
