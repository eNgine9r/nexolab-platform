# NEXOLAB Current State

Updated: 2026-08-22

## State Model v2 boundary

NEXOLAB continuity uses durable repository state plus current GitHub observations. GitHub remains authoritative for current `main` HEAD, Issue/PR lifecycle, merge SHA and repository settings; those volatile facts do not require a dedicated post-merge reconciliation PR.

## Durable baselines

Accepted product source: `24d6d039fb11366ab589ec3cb039e76bb7e565d7`.

Deployed product source: `6e387485b68fb862d9f82ae7f6000b1f5b672764`.

The accepted source includes completed Issue #589 persisted device-scoped acquisition cadence and RS-485 capacity validation. The Raspberry Pi deployment baseline is intentionally older and must not be represented as containing #607/#589 or later work until a controlled deployment is actually performed.

## Completed Work Package — Issue #589

Issue #589 — **Add persistent device-scoped acquisition cadence with RS-485 capacity validation** — completed through PR #656.

Accepted evidence is anchored to exact PR head `69a6eff795bd275372dd2588ef56bd2bd1e12704`:

- Core CI `32585746454`: PASS — format, lint, typecheck, tests and production build;
- Acquisition Scale Acceptance `32585746507`: PASS;
- Edge image `32585746469`: PASS, including Device Agent compile/full unit suite;
- Device Agent Fleet `32585746497`: PASS;
- MQTT TLS Fleet `32585746510`: PASS;
- Disaster Recovery TLS Fleet `32585746501`: PASS;
- Telemetry service `32585746522`: PASS;
- Authenticated Dashboard Acceptance `32585746451`: PASS;
- Container Supply Chain `32585746595`: PASS;
- Offline Bundle `32585746509`: PASS, including blocked-egress pull-disabled startup and persistence-preserving update/rollback;
- `NEXOLAB Merge Gate`: PASS;
- unresolved review threads: zero.

Architecture outcome:

- Acquisition Registry v2 is the authoritative local cadence source;
- 10/30/60-second presets and custom `10..3600 s` are supported;
- effective cadence resolves device override before bus/device-family default;
- scheduler priority remains ordering/fairness only and cannot silently accelerate persisted cadence;
- capacity validation is per physical bus and occurs before cadence or newly-active topology commit;
- unsafe mutations fail atomically and preserve the prior revision/policy;
- Device Agent GET/PUT cadence control remains local/offline and does not introduce Modbus writes.

Physical cadence acceptance remains **hardware unverified** while `nexolab-edge-01` is offline.

## Active Work Package — Issue #590

Issue #590 — **Add operator acquisition cadence controls to NEXOLAB Settings** — is active in branch `feat/590-settings-acquisition-cadence`.

Current implementation candidate:

- adds authenticated Next.js proxy `GET/PUT /api/device-agent/acquisition-cadence` using the existing security-session pattern;
- browser-to-Device-Agent control remains loopback-only and never exposes the Device Agent URL to React;
- GET requires `dashboard.read`; mutation requires `equipment.manage`;
- actor metadata is propagated as `organization:<id>:equipment.manage`;
- adds typed sanitized cadence client and canonical-state controller;
- successful PUT is followed by a canonical GET rather than trusting browser-local state;
- `409` optimistic concurrency conflict is explicit and triggers a canonical refresh;
- `422 acquisition_capacity_exceeded` preserves server capacity evidence and recommendation;
- Settings shows a dedicated **Physical polling interval** section separate from presentation refresh/history ranges;
- family/bus defaults support 10/30/60/Custom with client-side minimum mirror while server validation remains authoritative;
- optional override is physical-device scoped and can return to inherited family default;
- no per-logical-channel polling controls or force/bypass control exist;
- read-only operators see the persisted policy with mutation controls disabled;
- production Settings browser acceptance is wired to the existing authenticated acquisition-invariant workflow;
- deterministic acceptance fixture exposes sanitized cadence GET and safe/unsafe revisioned control semantics without changing production runtime behavior.

The #590 candidate is **not accepted yet**. No exact-head PR CI has run for this candidate. Required evidence remains route/client/component tests, production Settings browser acceptance, acquisition invariant, Core quality/build, Offline Bundle and every other path-triggered exact-head workflow plus `NEXOLAB Merge Gate`.

## Runtime and hardware boundary

Issue #590 changes operator control-plane/UI only. It does not redesign #589 scheduler/capacity logic and introduces no direct browser → Modbus path.

Hardware cadence acceptance remains whatever the real #589/#607 installation can prove. The UI cannot convert software capacity validation into physical hardware evidence.

No Modbus write, controller configuration write, wiring change, adapter installation or production/site cutover is authorized.

## Current blocker boundary

- #590: no software hard blocker; Raspberry Pi access is a soft hardware-evidence blocker only.
- #607: software accepted; physical two-adapter KK1/KK2 verification remains unavailable while the Pi connector is offline.
- #646: technical `main` branch protection remains a soft access blocker; retained observation still reports branch protection disabled.
- Security maintenance: temporary `CVE-2026-14456` exceptions remain due for review/removal by **2026-08-26** or earlier when fixed packages/reachability assumptions change.
- #585 remains blocked pending explicit physical W2 / Unit 201 handback approval.
- #444 and #245 remain validation lanes.
- #200 / #201 / #202 remain hardware/validation evidence lanes.
- #189 remains blocked on controlled actual-host recovery evidence.

## Safety boundaries

`LOCAL_LAN`, offline-first runtime and read-only industrial boundaries remain unchanged. No Modbus/controller write, hardware write, production/site cutover, persistent-data deletion, Docker named-volume deletion, secret/billing/DNS mutation or mandatory cloud runtime dependency is authorized by Issue #590.
