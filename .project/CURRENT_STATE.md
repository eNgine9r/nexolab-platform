# NEXOLAB Current State

Updated: 2026-08-05
Verified main baseline: `6aaa3e700365aa7edcf8ce7de1818e5e2d1b67c8`
Active control Work Package: Issue #301 — post-registry project-state reconciliation
Branch: `chore/301-post-registry-state`
Next Ready Work Package: Issue #285 — priority-aware adaptive acquisition scheduler
Active epic: Issue #282 — Performance and data acquisition optimization
Status confidence: high for merged software, deterministic registry/polling tests, authenticated browser acceptance, secure fleet operation and disconnected-runtime evidence; physical Raspberry Pi, RS-485, cameras and Smart Lockers remain explicitly unverified.

## Universal active acquisition registry completed

Issue #284 / PR #299 was squash-merged as `6aaa3e700365aa7edcf8ce7de1818e5e2d1b67c8` from verified head `c83f42aee7fc1251a683fb5c55cbe2779217673f`.

The merged edge runtime now:

- stores one versioned SQLite registry for buses, devices and channel/metric targets;
- separates inventory visibility from normal physical polling eligibility;
- supports `active`, `disabled`, `reserve`, `retired`, `uninstalled`, `discovery_only` and `invalid` lifecycle states;
- requires both device and target lifecycle `active` before a target enters normal polling;
- migrates legacy XJP60D active points and configured LE-01MP units without deleting existing SQLite data;
- supports individual LE-01MP metric eligibility;
- persists registry revision and audit changes atomically with optimistic concurrency;
- exposes a sanitized local registry and permission-gated loopback mutation API;
- preserves existing XJP60D active-point, telemetry ID and MQTT compatibility;
- accepts only read-only Modbus RTU FC03 targets and adds no hardware-write path.

Final exact-head verification:

- CI `30990278424` GREEN — formatting, lint, strict typecheck, 267 frontend tests and production build;
- Edge image `30990278312` GREEN — Python compile, full Device Agent unittest suite, secure Compose validation and amd64/arm64 image build;
- Container Supply Chain `30990278313` GREEN;
- Telemetry service `30990278544` GREEN;
- Device Agent Fleet Acceptance `30990278529` GREEN;
- MQTT TLS Fleet Acceptance `30990278311` GREEN;
- Disaster Recovery TLS Fleet `30990278521` GREEN;
- Authenticated Dashboard Acceptance `30990278466` GREEN on attempt 2;
- Offline Bundle `30990278317` GREEN;
- focused diff: 8 product/test/docs files;
- inline review threads: zero;
- submitted reviews: zero.

The first Authenticated Dashboard attempt encountered a non-reproducible equipment URL-filter timeout outside the registry diff. The same job passed on rerun against the identical exact head, so no unrelated equipment change was mixed into PR #299.

## Acquisition instrumentation baseline

Issue #283 / PR #294 remains the measurement baseline. It records every physical read-only FC03 attempt, retry, latency, outcome, cycle duration, overrun and bus utilization while separating normal acquisition from explicit service operations.

Authenticated browser evidence held the request envelope at 19.57–20.32 requests/second across no browser, Overview open/refresh, Live Data, concurrent contexts and WebSocket reconnect, with zero discovery/mutation deltas.

## Supply-chain security state

Issue #295 / PR #296 was squash-merged as `3b26fb444cdfc3f11659bce149037a87c6e3fc36`.

- `cryptography` uses the fixed 50.x line;
- one exact `telemetry-service/libcjson1/CVE-2026-67216` exception remains because the current Debian Trixie package has no fix;
- the exception is owned by `platform-security`, expires on 2026-08-15 and does not weaken global HIGH/CRITICAL enforcement.

## Active architecture sequence

Epic #282 continues in dependency order:

1. #285 — priority-aware adaptive scheduler and edge latest-value cache;
2. #286 — isolate REST/WebSocket subscriptions from physical acquisition;
3. #287 — persisted Live Dashboard domain and local API;
4. #288 — Live Dashboard editor and channel-scoped operator workspace;
5. #289 — scale, stability and truthful live-state acceptance.

Issue #285 is Ready because #283 established objective acquisition metrics and #284 established the canonical eligible target set. The scheduler may now prioritize and adapt polling without letting UI subscriptions define physical work.

## Approved blocked route

`/lockers` remains blocked pending concrete locker inventory, a read-only protocol/API contract and a defined operator workflow. No demo controls, guessed device states or door/lock writes may be introduced.

## Runtime and hardware evidence

```text
software verified; deterministic serial and registry tests verified; authenticated browser acceptance verified; secure fleet verified; disconnected update/rollback verified; physical Raspberry Pi, RS-485, camera and locker hardware unverified
```

## Next action

Validate and squash-merge control Issue #301 after confirming exactly four `.project/**` files and GREEN CI. Then start Issue #285 on a dedicated feature branch. Preserve FC03 read-only behavior, one-worker-per-bus serialization and the rule that UI display refresh never changes physical polling eligibility or cadence.
