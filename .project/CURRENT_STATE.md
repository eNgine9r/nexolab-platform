# NEXOLAB Current State

Updated: 2026-08-15

## Canonical repository baseline

Current `main` is `d32f381d42796e1f44b132cb931729bc6cda76cf`, the state-only reconciliation merged by Issue #462 / PR #463 after the graph-first Live Data Work Package.

## Active software Work Package — Issue #461 / PR #464

Issue #461 — **Add reusable hierarchical TelemetryPointSelector** — is implemented on `feat/461-hierarchical-telemetry-point-selector`.

The product/test/docs implementation is verified on exact product head `7a3dd97a2d406b8cd25680010da55a052edc0f74`:

- CI `31891003782`: PASS;
- Authenticated Dashboard Acceptance `31891003701`: 15/15 PASS, including the production selector scenario;
- Refrigeration Browser Acceptance `31891003707`: PASS;
- disconnected Offline Bundle `31891003946`: PASS;
- Acquisition Scale Acceptance `31891003741`: PASS for both software matrices.

The selector is a reusable, route-independent primitive. It preserves the canonical Live telemetry identity, explicit organization-scoped hierarchy metadata, draft Confirm/Cancel semantics, accessible keyboard tree behavior, bounded inventory rendering, responsive 360/1440/1920 containment and zero selector-owned telemetry/acquisition/configuration side effects.

Classification is **software/browser/offline verified; Raspberry Pi operator acceptance pending**. Acquisition Scale workflow evidence is software-only and does not complete the physical Issue #289 hardware matrix.

This `.project/**` checkpoint is the pre-merge state reconciliation. The resulting PR head still requires a fresh exact-head CI/browser/offline cycle before #464 may be marked Ready or merged.

## Next software Work Package — Issue #465

Issue #465 — **Integrate TelemetryPointSelector into Live Dashboard editor** — exists as the first Epic #450 consumer integration and remains `status:blocked` until #461 is merged.

It must preserve the existing persisted Live Dashboard contract, optimistic concurrency, item ordering, one-WebSocket invariant, selected-series-only history behavior and zero acquisition/discovery/configuration mutation delta.

## Independent hardware lane — Issue #289

Issue #289 remains open and `status:in-progress` for controlled Raspberry Pi/RS-485 acquisition-scale and truthful-state acceptance. No software, browser or offline workflow in Issue #461 substitutes for fresh physical hardware evidence.

Other previously classified physical evidence remains separate, including KK2/Unit 115 field retest, refrigeration perceived-latency acceptance and version-management Raspberry Pi acceptance.

## Safety boundary

LOCAL_LAN and offline-first requirements remain unchanged. No Modbus/hardware write, controller configuration, scheduler/polling change, acquisition-registry mutation, dependency upgrade, persistent-data deletion, production/site cutover, secret/billing/DNS change or mandatory public-cloud runtime change is authorized by Issue #461.
