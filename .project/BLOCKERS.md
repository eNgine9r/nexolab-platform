# NEXOLAB Blockers

Updated: 2026-08-06

## Acquisition software acceptance completed

Issue #289 software acceptance is merged through PR #323 at `959bd8f54cf044280d385917578f836a5c8ec7c8` from verified head `a15f4b084137bb53a11eff7c7ba5f2f3d78436f5`.

The merged evidence proves in deterministic and local Compose environments:

- 34, 136 and 240 active-target profiles;
- one serialized physical read at a time;
- priority coverage and bounded fairness;
- no normal executions for disabled/ineligible targets;
- endpoint-scoped cooldown and continuation of unrelated healthy endpoints;
- retained latest values with truthful `communication_error` state;
- UI-independent request rate across Overview, persisted Live Dashboard, Refrigeration, Energy, Sessions, additional browsers, WebSocket reconnect and Telemetry Service restart;
- selected-only Live Dashboard latest/history requests;
- one maximum physical WebSocket per page/scope;
- zero discovery/configuration mutations;
- MQTT outbox replay ordering;
- connecting, live, reconnecting, stale, offline, authorization and configuration state distinctions;
- disconnected Offline Bundle startup, update/rollback and persistent-volume preservation.

Issue #289 remains open and must retain this classification:

```text
software verified; hardware performance acceptance pending
```

## Hard blocker: controlled hardware access

No independent Ready software Work Package remains in the active acquisition sprint after Issue #324 state reconciliation.

The next required action is the controlled Raspberry Pi/RS-485 phase of Issue #289. It cannot be executed from the current environment because no usable host address, SSH session, controlled maintenance window or physical RS-485 access is available.

The required physical phases are:

1. no browser;
2. Overview;
3. one persisted Live Dashboard;
4. repeated route transitions;
5. multiple browser workstations;
6. WebSocket reconnect;
7. one known unavailable endpoint;
8. MQTT interruption and outbox drain.

Physical evidence must include:

- normal FC03 physical requests per bus and bounded window;
- real response latency and retries;
- bus busy time and utilization;
- scheduler lag, missed deadlines, fairness and cooldown behavior;
- CPU, RAM, disk and outbox depth;
- ingestion-to-WebSocket latency;
- proof that page/browser count does not change the physical polling envelope;
- proof that unrelated channels remain available when one endpoint is absent;
- exact source commit and sanitized aggregate evidence.

The procedure must remain read-only. Do not run Modbus writes, controller configuration, production cutover, persistent-volume deletion or unapproved disruptive hardware actions.

## Other hardware-dependent blockers

- **#245:** standalone loopback runtime software is merged; actual Raspberry Pi acceptance remains pending.
- **#189:** physical reboot, hard power-loss and media restore remain pending.
- **#200:** physical RS-485 topology, termination, single-master status and polling envelope remain pending.
- **#201:** LE-01MP cumulative energy remains excluded pending read-only hardware validation.
- **#202:** extended XJP60D semantics and portability require read-only physical evidence.
- Issue #284 still requires real request-counter proof for disabled physical targets.
- Issue #285 still requires real interval, utilization and deadline proof.
- Physical cameras, ONVIF/RTSP media and NVR remain unverified.

## Smart Lockers blocker

`/lockers` remains blocked pending:

- concrete locker inventory;
- a read-only protocol or API contract;
- a defined operator workflow;
- verified physical locker evidence.

Do not create demo controls, guessed states, door/lock writes or fabricated production behavior.

## Supply-chain security risk

One exact exception remains for `telemetry-service/libcjson1/CVE-2026-67216` because Debian Trixie currently reports no fixed package. It:

- is owned by `platform-security`;
- expires on 2026-08-15;
- is limited to the authenticated local `mosquitto_ctrl` dynamic-security adapter path;
- does not weaken global HIGH/CRITICAL enforcement.

Remove the exception immediately when a fixed Debian package becomes available.

## Hard-stop rules

Stop before:

- destructive database or persistent-volume operations;
- production/site cutover without explicit approval;
- Modbus, camera, locker or other hardware writes;
- credential exposure or unauthorized secret rotation;
- materially different product or architecture choices;
- any operation that cannot preserve local laboratory data;
- claiming physical performance acceptance without controlled Raspberry Pi/RS-485 evidence.

## Next action

Complete Issue #324 as a four-file state-only PR. After it merges, wait for controlled Raspberry Pi/RS-485 access or a newly created independent Ready software Work Package. Do not treat the hardware-blocked Issue #245 label as evidence that actual Raspberry Pi acceptance can be performed without the device.
