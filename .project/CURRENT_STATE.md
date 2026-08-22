# NEXOLAB Current State

Updated: 2026-08-22

## State Model v2 boundary

NEXOLAB continuity uses durable repository state plus current GitHub observations. GitHub remains authoritative for current `main` HEAD, Issue/PR lifecycle, merge SHA and repository settings; those volatile facts do not require a dedicated reconciliation PR.

## Durable baselines

Accepted product source: `61aeaa430075d4caa5d7164cae2866fcabc57108`.

Deployed product source: `6e387485b68fb862d9f82ae7f6000b1f5b672764`.

The accepted source includes Issue #618, security prerequisite #654 and completed Issue #607 dual-RS485 software architecture. The deployed Raspberry Pi baseline is intentionally older and must not be represented as containing these changes until a controlled deployment is actually performed.

## Completed process hardening — Issues #646 / #648 / #650

Impact-aware CI, deterministic `npm ci`, exact-head external workflow aggregation, the state-only fast lane and State Model v2 are repository-side verified.

Issue #646 remains soft-blocked only on technical `main` branch protection. The retained GitHub observation reports branch protection disabled; normal development continues to enforce the stable `NEXOLAB Merge Gate` operationally.

## Completed product Work Package — Issue #618

Issue #618 — **Restore Saved Dashboard CSV export browser acceptance on LOCAL_LAN** — completed through PR #652.

Accepted evidence:

- verified PR head `3982e901f6732713fa23ea1650299eb6738a9f79`;
- Core CI `32572681394`: PASS;
- Authenticated Dashboard Acceptance `32572681396`: PASS;
- Offline Bundle `32572681390`: PASS;
- `NEXOLAB Merge Gate`: PASS;
- production Chromium observed a real CSV download with no public requests or acquisition mutations.

Raspberry Pi repetition remains unverified because the remote Pi is offline.

## Completed product Work Package — Issue #607

Issue #607 — **Add dual RS-485 bus isolation for KK1 and KK2** — completed through PR #653.

Accepted software evidence is anchored to exact PR head `4889bae7d942be407d5df1412daae2cbf7c9a2ae`:

- Core CI `32576635748`: PASS;
- Device Agent Fleet `32576635775`: PASS;
- Edge image `32576635778`: PASS;
- Offline Bundle `32576635742`: PASS;
- Authenticated Dashboard `32576635799`: PASS;
- MQTT TLS Fleet `32576635745`: PASS;
- Disaster Recovery TLS Fleet `32576635744`: PASS;
- Container Supply Chain `32576635747`: PASS;
- `NEXOLAB Merge Gate`: PASS;
- unresolved review threads: zero.

GitHub recorded the accepted merged product source as `61aeaa430075d4caa5d7164cae2866fcabc57108`.

Architecture outcome:

- explicit stable logical bus identities;
- independent Modbus clients/readers/physical locks per bus;
- serialization within one bus and concurrency between different buses;
- bus-aware discovery and `discovery_only` enrollment;
- per-bus request/retry/timeout/latency diagnostics;
- fail-closed missing-active-bus health state;
- legacy single-bus fallback preserved;
- no Modbus write, hardware write or site cutover path added.

Physical two-adapter acceptance remains **hardware unverified**. The Raspberry Pi connector is offline and no wiring or adapter cutover was authorized.

## Active Work Package — Issue #589

Issue #589 — **Add persistent device-scoped acquisition cadence with RS-485 capacity validation** — is active in branch `feat/589-persisted-acquisition-cadence`.

Current implementation candidate:

- upgrades Acquisition Registry persistence to schema v2 with cadence in the same SQLite document, revision and audit stream;
- supports 10/30/60-second presets and custom `10..3600 s` cadence;
- resolves effective cadence as device override, then bus/device-family default;
- migrates v1 registries without accelerating historical polling and records one migration audit;
- makes persisted cadence the scheduler interval authority while priority remains ordering/fairness only;
- validates cadence and newly poll-eligible activation against a conservative per-bus RS-485 capacity model before commit;
- leaves rejected mutation revision/audit/scheduler state unchanged;
- always allows deactivation that reduces bus load;
- accounts for XJP60D value+status as two FC03 requests and LE-01MP metric pass as one FC03 request;
- includes retry reserve, inter-frame timing, scheduler overhead and a 25% utilization safety margin;
- uses measured per-bus p95 only after at least 20 physical samples, otherwise serial timeout remains the conservative authority;
- preserves #607 explicit multi-bus topology and bus-aware discovery cadence policy;
- adds local `GET/PUT /api/v1/acquisition-cadence` without causing Modbus activity from reads or configuration inspection.

Architecture contract: `docs/architecture/persisted-acquisition-cadence.md`.

The candidate is not yet accepted. Exact-head CI and review evidence must be collected after the final implementation/state candidate is published as one focused PR.

## Runtime and hardware boundary

Issue #589 is currently **software candidate / hardware unverified**.

No hardware write, Modbus write, wiring change, second-adapter installation or production/site cutover is authorized. The real safe site cadence remains unverified until read-only measurements are collected from the intended Raspberry Pi and physical buses.

## Current blocker boundary

- #589: no software hard blocker; Raspberry Pi hardware acceptance is unavailable while the connector is offline but does not block deterministic software verification.
- #646: technical branch-protection setting remains a soft access blocker.
- Security maintenance: four temporary `CVE-2026-14456` exceptions from Issue #598 remain due for review/removal by **2026-08-26** or earlier when a fixed Debian package becomes available or reachability assumptions change.
- Security prerequisite #654 for `CVE-2026-67215` was isolated and merged before #607; it is not part of the #589 feature diff.

Known dependencies:

- #590 remains blocked on completion of #589;
- #585 remains blocked pending explicit physical W2 / Unit 201 handback approval;
- #444 and #245 remain validation lanes;
- #200 / #201 / #202 remain hardware/validation evidence lanes;
- #189 remains blocked on controlled actual-host recovery evidence.

## Safety boundaries

`LOCAL_LAN`, offline-first runtime and read-only industrial boundaries remain unchanged. No Modbus/controller write, hardware write, production/site cutover, persistent-data deletion, Docker named-volume deletion, secret/billing/DNS mutation or mandatory cloud runtime dependency is authorized by Issue #589.
