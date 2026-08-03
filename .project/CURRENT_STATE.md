# NEXOLAB Current State

Updated: 2026-08-03
Verified main baseline: `2c00812aed7bc107f191a50e2e0745cb9c091bbd`
Active Work Package: Issue #245 / PR #246 — standalone offline Raspberry Pi 5 runtime
Status confidence: high for repository state, runtime contracts, GitHub-hosted quality checks, Telemetry Service regression and linux/amd64 disconnected delivery; partial for actual Raspberry Pi 5 reboot, loopback-only browser use and physical telemetry acceptance.

## Profile

- Project type: `LOCAL_LAN` with an explicit same-host `standalone` runtime mode.
- Development and connected deployment may use the internet; core runtime must not require it.
- Local PostgreSQL, MQTT, MinIO, edge SQLite, logs, backup and restore remain first-class.
- No Modbus write, hardware write or production/site cutover is authorized.

## Completed maintenance baseline

- PR #184 — AI Development Operating Standard.
- PR #190 — verified architecture and offline boundary.
- PR #206 — tracker and Pull Request reconciliation.
- PR #207 — durable MQTT-to-PostgreSQL ingestion.
- PR #209 — Device Agent supply-chain hardening.
- PR #213 — dashboard security diagnostics.
- PR #214 — WebSocket lifecycle stabilization.
- PR #215 — offline installation/update bundle.
- PR #216 — offline operator authentication.
- PR #224 — encrypted local-auth disaster recovery.
- PR #225–#229 and #233 — controlled Prettier baseline.
- PR #234 — GitHub Actions runtime compatibility.
- PR #238 — argument-safe disaster-recovery credentials.
- PR #240 — Next.js and React security patch line.
- PR #244 / Issue #241 — `sharp 0.35.3` compatibility control, merged as `2c00812aed7bc107f191a50e2e0745cb9c091bbd`.

## Issue #245 / PR #246 software outcome

The implementation adds two explicit deployment modes:

```text
lan
standalone
```

`lan` remains the default and preserves trusted-LAN behavior. `standalone` compiles and exposes the same-host operator path through:

```text
Dashboard: http://127.0.0.1:3000
API:       http://127.0.0.1:8082
WebSocket: ws://127.0.0.1:8082/api/v1/telemetry/live
```

The standalone contract:

- uses exact loopback CORS origins;
- preserves the configured authentication mode and Security Gate;
- rejects remote-JWKS-only authentication in standalone mode;
- removes the dashboard dependency on `network-online.target`;
- connects the edge broker to the central broker through an isolated Docker bridge and the unambiguous alias `central-mqtt:1883`;
- keeps Telemetry Service on the private central network so the edge broker cannot shadow the central `mqtt` DNS name;
- preserves PostgreSQL, central MQTT, MinIO, telemetry-ingestion and edge SQLite volume identities;
- adds `scripts/verify-standalone-offline-raspberry-pi.sh` and a dedicated operator runbook;
- does not add demo fallback, wildcard CORS, dependency upgrades, Modbus writes or hardware writes.

## Candidate verification

Candidate head `d4ff514e1448454d90fb53ac4e4e049cc81f225e` completed all triggered workflows GREEN:

- CI `30791309275` — standalone/LAN contract test, repository formatting, ESLint, strict typecheck, Vitest and production build;
- Telemetry Service `30791309295` — migrations, MQTT/REST/WebSocket/object-storage tests, PostgreSQL outage recovery, offline migration SQL and container build;
- Offline Bundle `30791309244` — disconnected image load/start, blocked container egress, smoke verification and update/rollback volume preservation.

The contract test proves that:

- invalid runtime modes fail before mutation;
- standalone frontend/API/WebSocket/CORS values are loopback-only;
- LAN mode remains backward compatible;
- central MQTT and the edge bridge use a dedicated shared runtime network;
- Telemetry Service cannot resolve the edge broker as its `mqtt` dependency.

## Open Pull Requests

- #246 — standalone offline Raspberry Pi runtime; state update and final exact-head sweep pending.

## Runtime and hardware evidence

Software status:

```text
software verified; actual standalone Raspberry Pi acceptance pending
```

Not yet verified on the physical Raspberry Pi 5:

- reboot with Ethernet and Wi-Fi unavailable;
- no default route and no IPv4 on physical uplinks;
- local browser opening `http://127.0.0.1:3000`;
- Security Gate, REST and WebSocket behavior on the actual host;
- continued real RS-485 telemetry for at least 15 minutes;
- telemetry preservation across Telemetry Service restart and a second reboot.

## Open risks and blockers

- No hard blocker prevents the final software sweep and merge of PR #246.
- Actual Raspberry Pi acceptance remains a soft blocker before Issue #245 can be closed.
- Issue #189 actual-host recovery and power-loss evidence remains incomplete.
- Issues #200–#202 remain blocked pending controlled read-only hardware evidence.
- Actual ARM64 offline bundle installation/update/rollback remains separate from this runtime Work Package.
- The temporary `sharp` override must be reassessed when Next.js publishes a supported patched range.

## Next Ready action

Complete the state-only exact-head checks, review PR #246 and merge it. Then deploy `main` on the Raspberry Pi with `--runtime-mode standalone` and collect the required loopback-only actual-host evidence before closing Issue #245.
