# NEXOLAB Current State

Updated: 2026-08-05
Verified main baseline: `5aa2252a6c20874dcc3d975c19fee441d20600a8`
Active Work Package: Issue #273 — operator-safe local Cameras workspace
Branch: `feat/273-local-cameras-workspace`
Pull Request: #274 — readiness checkpoint
Verified source head: `3b39d9e9f1a8e15c0cb66d0fd8924c25ffba390b`
Parent Product Epic: Issue #260 — complete all NEXOLAB operator pages
Status confidence: high for software, authenticated browser and disconnected-runtime evidence; physical Raspberry Pi, RS-485 and camera hardware remain explicitly unverified.

## Product route status

Implemented on merged `main`: Overview, Nodes, Sessions, Refrigeration, Alerts, Reports, Energy, Live Data, Equipment Layouts, Equipment registry and Settings.

Verified in PR #274 and pending merge:

- `/cameras` — authenticated truthful local camera readiness workspace;
- Overview camera panel — fabricated six-scene `LIVE` presentation removed and replaced with canonical unconfigured/configured summaries.

Remaining placeholder route on merged `main`:

- `/lockers` — blocked pending concrete inventory and read-only protocol scope.

## Issue #273 verified outcome

The source implementation on `3b39d9e9f1a8e15c0cb66d0fd8924c25ffba390b` provides:

- typed validated camera records and bounded source/state/capability values;
- local endpoint sanitization that removes query strings/fragments and rejects credentials or public hosts;
- explicit configured, online, offline, unavailable and invalid states;
- no production inventory fallback: the runtime honestly renders `unconfigured` until a real safe contract exists;
- authenticated `/cameras` shell with deterministic search and state filtering;
- removal of fabricated Overview camera scenes and animated `LIVE` badges;
- focused unit tests for sanitization, invalid entries and raw RTSP browser boundaries;
- focused production browser acceptance for `/cameras`, Overview navigation, zero non-GET requests and no secret/fake-LIVE evidence;
- no camera API, database migration, dependency change, credential path, device write or production cutover.

Exact-source verification:

- CI `30973348158` GREEN;
- Authenticated Dashboard Acceptance `30973348163` GREEN;
- Refrigeration Browser Acceptance `30973348162` GREEN;
- Offline Bundle `30973348151` GREEN;
- focused source files: 8 plus four `.project/**` state files;
- temporary formatting workflow removed from final diff.

## Runtime, offline and hardware evidence

```text
software verified; authenticated seven-flow browser stack verified; disconnected bundle startup/update/rollback verified; physical Raspberry Pi, RS-485, cameras, ONVIF, RTSP media and NVR unverified
```

The Offline Bundle proved connected linux/amd64 build, clean-host simulation, runtime-image removal, blocked container egress, disconnected load/start with pulls disabled and persistent-data preservation through update/rollback.

## Next action

Validate the state-only head, repeat review and focused-diff audit, update PR #274 summary and mark Ready without merging.
