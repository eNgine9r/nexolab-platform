# NEXOLAB Current State

Updated: 2026-08-15

## Canonical repository baseline

Current `main` is `30659fb22e6420863383071079a5a40a6b6cd0d8`, the squash merge of Issue #461 / PR #464 — **Add reusable hierarchical TelemetryPointSelector**.

PR #464 merged from final exact verified head `a49ee1a92546a04d8ae5c2b47d4a3d01b882ee56`.

Final exact-head evidence on that PR head:

- CI `31891562678`: PASS;
- Authenticated Dashboard Acceptance `31891562657`: PASS, including the production selector scenario;
- Refrigeration Browser Acceptance `31891562662`: PASS;
- disconnected Offline Bundle `31891562661`: PASS;
- Acquisition Scale Acceptance `31891562659`: PASS for both software matrices.

Issue #461 is closed. Classification remains **software/browser/offline verified; Raspberry Pi operator acceptance pending**. Software Acquisition Scale evidence does not complete the physical Issue #289 matrix.

## Active software Work Package — Issue #466

Issue #466 — **Reconcile Issue #461 merge state and activate Issue #465** — is the active state-only Work Package on `chore/466-reconcile-issue-461-merge-state`.

Scope is restricted to the four canonical `.project/**` files. No product/runtime, dependency, acquisition, scheduler, database or hardware behavior is changed.

This reconciliation records the final #461 merge/evidence and removes the now-resolved dependency blocker from the software queue. It still holds Issue #465 from implementation until this state-only PR itself is merged and exact-head CI is GREEN.

## Next software Work Package — Issue #465

Issue #465 — **Integrate TelemetryPointSelector into Live Dashboard editor** — is the next independent software Work Package.

Its product dependency on #461 is resolved by merge `30659fb22e6420863383071079a5a40a6b6cd0d8`. It remains temporarily blocked only on completion of Issue #466 state reconciliation. After #466 merges, #465 should move from `status:blocked` to `status:ready`, then to `status:in-progress` when its own feature branch is created from reconciled `main`.

The #465 implementation must preserve the existing persisted Live Dashboard contract, optimistic concurrency, item ordering, one-WebSocket invariant, selected-series-only history behavior and zero acquisition/discovery/configuration mutation delta.

## Independent hardware lane — Issue #289

Issue #289 remains open and `status:in-progress` for controlled Raspberry Pi/RS-485 acquisition-scale and truthful-state acceptance. No software, browser or offline workflow from #461 or #466 substitutes for fresh physical hardware evidence.

Other previously classified physical evidence remains separate, including KK2/Unit 115 field retest, refrigeration perceived-latency acceptance and version-management Raspberry Pi acceptance.

## Safety boundary

LOCAL_LAN and offline-first requirements remain unchanged. No Modbus/hardware write, controller configuration, scheduler/polling change, acquisition-registry mutation, dependency upgrade, persistent-data deletion, production/site cutover, secret/billing/DNS change or mandatory public-cloud runtime change is authorized by Issue #466.
