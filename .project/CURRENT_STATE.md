# NEXOLAB Current State

Updated: 2026-08-19

## Repository and runtime baseline

Accepted product-code baseline on `main` is `b46e518f8769f83ba22c608bacd5a368776e1701`, the squash merge of PR #593 — **feat: add read-only NEXOLAB MCP gateway**. State-only reconciliation commits may advance repository HEAD without changing this accepted product baseline; use GitHub `main` for the exact repository HEAD.

The Raspberry Pi source runtime remains deployed at `7a19f53950492a40255c53b1d2018bbdff9466e2`. The persisted local AcquisitionRegistry remains revision 8 with `le01mp-201` intentionally `disabled` while W2 is externally owned. No source deployment was performed by Issues #584 or #586.

## Issue #584 — complete

Temporary Unit 201 exclusion is complete and verified on the real Raspberry Pi. Evidence remains `runtime/deployments/issue-584-20260818T185455Z`.

## Issue #585 — blocked restoration lane

Do not restore Unit 201 until the Product Owner confirms that the external controller no longer owns W2 and explicitly approves any required physical handback. The 2026-08-21 through 2026-08-23 review window is not authorization by itself.

## Issue #586 — complete

Issue #586 is closed `status:done`. PR #592 merged GREEN as `75c6f5471d77d781b124fbd40c33ba924aec26f8`.

Real Raspberry Pi browser-closed evidence proved the acquisition and persistence planes are independent of browser lifetime:

- 60 sampled checks observed zero established browser/API connections on ports 3000/8081/8082;
- AcquisitionRegistry remained `8 -> 8`;
- Device Agent `normal.physical_requests_total` advanced `5049 -> 5392` (`+343`);
- PostgreSQL `telemetry_samples` advanced `4,665,493 -> 4,665,722` (`+229`);
- newest persisted `captured_at` advanced from `2026-08-18 19:18:52.033946+00` to `2026-08-18 19:20:28.276628+00`.

Evidence: `runtime/deployments/issue-586-browser-closed-20260818T191852Z`.

The merged repair now provides:

- one canonical complete-history loader with stable `snapshot_at`, captured-time pagination and event deduplication;
- Live Data reuse of that canonical loader;
- complete persisted Overview bootstrap instead of a single `limit=1000` page;
- deterministic buffered history-to-live reconciliation;
- duplicate and out-of-order tail rejection;
- preservation of newer non-valid samples for truthful Chart System gaps;
- no duplicate route-local latest buffer appended after reconciliation.

Final PR #592 gates on head `6ef7c65b1e0838e75ebaff60d85881f4718cd7c7`:

- Core CI `32179697028`: PASS;
- Authenticated Dashboard Acceptance `32179696964`: PASS;
- Offline Bundle `32179696933`: PASS.

No backend schema, acquisition scheduler, physical polling cadence, dependency graph, Modbus behavior or hardware configuration changed in #586.

## Issue #594 — complete

The Product Owner explicitly authorized provisioning a dedicated read-only LOCAL_LAN identity for the MCP gateway. The account `nexolab-mcp` is active under the supported `laboratory_technician` product role with exactly two explicit grants: `telemetry.read` and `nodes.read`. The password was generated outside Git, was never printed or committed, and remains in a mode-600 local secret file pending any separately approved persistent deployment.

Real Raspberry Pi acceptance on `nexolab-edge-01` proved:

- MCP modern protocol negotiation `2026-07-28`;
- exactly six approved tools, all read-only/non-destructive;
- real `system_health`, node list, node status, latest telemetry, bounded history and active-alarm calls PASS;
- local-session access-token refresh PASS and rotated the access token;
- Device Agent remained healthy and Telemetry API/database/MQTT remained ready with queue depth 0;
- the ephemeral acceptance container was removed and port 8787 returned free;
- no Modbus write, hardware write, site exposure or persistent MCP service enablement occurred.

PR #593 merged GREEN as `b46e518f8769f83ba22c608bacd5a368776e1701` and Issue #594 is closed `status:done`. Persistent systemd enablement, external tunnel/reverse-proxy exposure and production credential relocation remain a separate cutover decision.

## Issue #598 — container supply-chain baseline restored

Issue #598 is closed `status:done`. PR #599 merged GREEN as `b25ae18e196eb84fc56ae951003d0820a22dc579`.

A fresh Container Supply Chain scan surfaced HIGH `CVE-2026-14456` in Debian 13 OpenSSL packages used by Device Agent and telemetry-service. Debian describes the affected path as an OpenSSL QUIC server listener pending-connection exhaustion path. Repository/runtime audit proved neither NEXOLAB image creates a QUIC/HTTP3 listener or accepts QUIC Initial packets.

The repository's existing HIGH/no-fix policy was used without weakening global gates: four exact image/package/CVE decisions were added, owned by `platform-security`, expiring **2026-08-26**. Wildcards, Critical exceptions, `ignore-unfixed`, dependency changes and runtime changes remain forbidden.

Exact PR #599 gates:

- Core CI `32219771902`: PASS;
- Telemetry Service `32219771893`: PASS;
- Container Supply Chain `32219772068`: PASS.

No application runtime, dependency version, database, deployment, Modbus or hardware behavior changed.

## Current execution boundary

**Issue #587 — Add complete persisted ranges and CSV export to Saved Live Dashboards** is again `status:in-progress`. PR #597 is open and must now be rebased onto repository `main` `b25ae18e196eb84fc56ae951003d0820a22dc579` so the repaired supply-chain policy is part of its exact head.

Before the security prerequisite appeared, PR #597 had already passed Core CI, Telemetry Service, Authenticated Dashboard Acceptance, Offline Bundle, Acquisition Scale, Device Agent Fleet and the other completed runtime gates; the only failed release gate was the newly surfaced CVE baseline. No merge is authorized until the rebased PR head reruns and all required checks are GREEN.

Issue #588 remains next in sequence only after #587 is GREEN merged and reconciled. Issue #585 remains independently blocked on physical handback.

## Safety boundaries

`LOCAL_LAN`, offline-first runtime and read-only industrial boundaries remain unchanged. No Modbus/controller write, hardware write, production/site cutover, persistent-data deletion, named-volume deletion, secret/billing/DNS mutation or mandatory cloud runtime dependency is authorized.
