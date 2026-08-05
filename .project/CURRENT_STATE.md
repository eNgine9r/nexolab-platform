# NEXOLAB Current State

Updated: 2026-08-05
Verified main baseline: `4af4c04167d82bdbf2d0cec71b1d10e843c30fb2`
Active control Work Package: Issue #292 — post-Overview project-state reconciliation
Branch: `chore/292-post-overview-state`
Next Ready Work Package: Issue #283 — acquisition instrumentation and UI-independent Modbus request invariant
Active epic: Issue #282 — Performance and data acquisition optimization
Status confidence: high for merged software, authenticated browser and disconnected-runtime evidence; physical Raspberry Pi, RS-485, cameras and Smart Lockers remain explicitly unverified.

## Truthful Overview completed

Issue #280 / PR #290 was squash-merged as `4af4c04167d82bdbf2d0cec71b1d10e843c30fb2`.

The live Overview now:

- uses the canonical authenticated equipment-layout catalog instead of a fabricated laboratory map;
- exposes published, draft, unconfigured and failed layout states;
- exposes explicit loading, no-organization, empty and unavailable states;
- preserves canonical navigation to `/equipment-layouts`;
- removes the misleading live camera demo label;
- retains illustrative layout values only inside explicitly labelled demo mode;
- performs no Device Agent discovery/configuration request and no Modbus operation.

Final PR #290 verification on head `66e6133ab1129c5397f32d3e3e62946cff4a92f7`:

- CI `30980784355` GREEN;
- Authenticated Dashboard Acceptance `30980784398` GREEN;
- Offline Bundle `30980784393` GREEN, including disconnected startup, update/rollback and persistent-data preservation;
- focused diff: three files under `src/components/dashboard/**`;
- inline review threads: zero;
- submitted reviews: zero.

## Active architecture sequence

Epic #282 defines the ordered acquisition-optimization sequence:

1. #283 — instrument physical acquisition and prove UI-independent Modbus request rates;
2. #284 — universal active acquisition registry;
3. #285 — priority-aware adaptive scheduler and edge latest-value cache;
4. #286 — isolate REST/WebSocket subscriptions from physical acquisition;
5. #287 — persisted Live Dashboard domain and local API;
6. #288 — Live Dashboard editor and channel-scoped operator workspace;
7. #289 — scale, stability and truthful live-state acceptance.

Issue #283 is selected first because scheduler changes must be preceded by objective physical-request, latency, retry, cycle-duration and bus-utilization evidence.

## Approved blocked route

`/lockers` remains blocked pending concrete locker inventory, a read-only protocol/API contract and a defined operator workflow. No demo controls, guessed device states or door/lock writes may be introduced.

## Runtime and hardware evidence

```text
software verified; authenticated browser verified; disconnected update/rollback verified; physical Raspberry Pi, RS-485, camera and locker hardware unverified
```

## Next action

Validate and squash-merge the control-only Issue #292 PR after confirming exactly four `.project/**` files and GREEN CI. Then start Issue #283 on `feat/283-acquisition-instrumentation` without changing polling policy or performing hardware writes.
