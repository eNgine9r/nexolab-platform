# NEXOLAB Current State

Updated: 2026-08-23

## State Model v2 boundary

NEXOLAB continuity uses durable repository state plus current GitHub observations. GitHub remains authoritative for current `main` HEAD, Issue/PR lifecycle, merge SHA and repository settings; those volatile facts do not require a dedicated post-merge reconciliation PR.

## Durable baselines

Accepted product source: `24d6d039fb11366ab589ec3cb039e76bb7e565d7`.

Deployed product source: `6e387485b68fb862d9f82ae7f6000b1f5b672764`.

The accepted source includes completed Issue #589 persisted device-scoped acquisition cadence and RS-485 capacity validation. The Raspberry Pi deployment baseline is intentionally older and must not be represented as containing #607/#589/#590 or later work until a controlled deployment is actually performed.

## Completed Work Package — Issue #589

Issue #589 — **Add persistent device-scoped acquisition cadence with RS-485 capacity validation** — completed through PR #656.

Accepted evidence is anchored to exact PR head `69a6eff795bd275372dd2588ef56bd2bd1e12704`:

- Core CI `32585746454`: PASS;
- Acquisition Scale Acceptance `32585746507`: PASS;
- Edge image `32585746469`: PASS;
- Device Agent Fleet `32585746497`: PASS;
- MQTT TLS Fleet `32585746510`: PASS;
- Disaster Recovery TLS Fleet `32585746501`: PASS;
- Telemetry service `32585746522`: PASS;
- Authenticated Dashboard Acceptance `32585746451`: PASS;
- Container Supply Chain `32585746595`: PASS;
- Offline Bundle `32585746509`: PASS;
- `NEXOLAB Merge Gate`: PASS;
- unresolved review threads: zero.

Physical cadence acceptance remains **hardware unverified** while `nexolab-edge-01` is offline.

## Completed Work Package candidate — Issue #590

Issue #590 — **Add operator acquisition cadence controls to NEXOLAB Settings** — is software-complete in PR #657 and is awaiting final state-only verification/merge.

Exact product evidence is anchored to PR head `b4b8608d82e90844ae9905c60b083232e68ef689`:

- Core CI `32606407885`: PASS — repository policy, format, lint, typecheck, full tests and production build;
- Acquisition Scale Acceptance `32606407863`: PASS;
- Refrigeration Browser Acceptance `32606407879`: PASS;
- Authenticated Dashboard Acceptance `32606407875`: PASS — authenticated cadence read/write control plane, persistence after reload, capacity rejection and stale-revision recovery;
- Offline Bundle `32606407871`: PASS — disconnected pull-disabled startup plus update/rollback with persistent-data preservation;
- `NEXOLAB Merge Gate`: PASS;
- unresolved review threads: zero.

Architecture outcome:

- Settings exposes physical polling cadence separately from chart/history presentation refresh;
- browser traffic uses only the authenticated Next.js loopback proxy;
- GET requires `dashboard.read`; mutation requires `equipment.manage`;
- successful mutation is followed by a canonical Device Agent reread;
- `409` revision conflict refreshes canonical state;
- `422 acquisition_capacity_exceeded` preserves server-authoritative capacity evidence and recommendation;
- 10/30/60-second presets and Custom are supported without a force/bypass path;
- family/bus defaults and physical-device override/inheritance are supported;
- read-only users can inspect persisted cadence but cannot mutate it;
- no per-logical-channel physical cadence controls were added;
- no browser-to-Modbus path, Modbus write, hardware write or cloud runtime dependency was introduced.

Hardware cadence acceptance remains **unverified** because the Remote Desktop/Raspberry Pi connector is offline. Software capacity evidence is not represented as physical KK1/KK2 acceptance.

## Runtime and offline evidence

The exact product head passed the repository offline bundle with blocked container egress, transferred-image loading, `pull` disabled, disconnected stack startup and persistence-preserving update/rollback. NEXOLAB therefore retains its `LOCAL_LAN` offline-first runtime boundary for this Work Package.

No controlled deployment of #590 to the Raspberry Pi has been performed; deployed product source remains `6e387485b68fb862d9f82ae7f6000b1f5b672764`.

## Current blocker boundary

- #590: no software blocker; only Raspberry Pi hardware/deployment evidence is unavailable.
- #607: software accepted; physical two-adapter KK1/KK2 verification remains unavailable while the Pi connector is offline.
- #646: technical `main` branch protection remains a soft access blocker; retained observation still reports branch protection disabled.
- Security maintenance: temporary `CVE-2026-14456` exceptions remain due for review/removal by **2026-08-26** or earlier when fixed packages/reachability assumptions change.
- #585 remains blocked pending explicit physical W2 / Unit 201 handback approval.
- #444 and #245 remain validation lanes.
- #200 / #201 / #202 remain hardware/validation evidence lanes.
- #189 remains blocked on controlled actual-host recovery evidence.

## Safety boundaries

`LOCAL_LAN`, offline-first runtime and read-only industrial boundaries remain unchanged. No Modbus/controller write, hardware write, production/site cutover, persistent-data deletion, Docker named-volume deletion, secret/billing/DNS mutation or mandatory cloud runtime dependency is authorized by Issue #590.
