# NEXOLAB Current State

Updated: 2026-08-15

## Canonical repository baseline

Current `main` is `bc0f0612cdb8ba882a6ed66a49249ded68589507`, the squash merge of Issue #466 / PR #467 — **Reconcile Issue #461 merge state and activate Issue #465**.

Issue #461 / PR #464 remains completed and merged as `30659fb22e6420863383071079a5a40a6b6cd0d8`. Its reusable hierarchical `TelemetryPointSelector` is the canonical selector component used by the active Live Dashboard integration.

## Active software Work Package — Issue #465 / PR #470

Issue #465 — **Integrate TelemetryPointSelector into Live Dashboard editor** — is implemented on `feat/465-live-dashboard-telemetry-selector` with Draft PR #470.

The verified product head is `34dbc2fb2936940e5193aabc2898fefe5bf3c984`.

Scope completed at that product head:

- the Live Dashboard editor now uses the reusable hierarchical `TelemetryPointSelector` instead of the former flat picker;
- the existing read-only `/api/v1/live-dashboards/channel-inventory` contract is enriched with explicit climate-chamber, equipment-type, laboratory and zone taxonomy without a new endpoint or database migration;
- laboratory/zone metadata is exposed only when existing repository data is unambiguous; missing or conflicting metadata remains truthful/unclassified;
- the canonical selector identity `nodeId|equipmentId|channelId|metric|unit` maps back to the existing persisted Live Dashboard channel/metric contract without changing dashboard save semantics;
- unresolved persisted selections remain preserved rather than silently dropped;
- the latest-value inventory page remains bounded before taxonomy enrichment, preserving the PostgreSQL latest-value lookup plan;
- browser acceptance covers selecting a catalog channel that has no telemetry-history sample through the hierarchical selector.

No acquisition scheduler, polling policy, acquisition registry, WebSocket ownership, telemetry-history fetch policy, Modbus behavior, dependency version or database schema was changed.

## Verified product-head evidence

Exact product head `34dbc2fb2936940e5193aabc2898fefe5bf3c984` is GREEN:

- CI `31902408125`: PASS — repository contracts, formatting, lint, typecheck, full frontend tests and production build;
- Telemetry service `31902408104`: PASS — PostgreSQL migrations/integration suite, inventory API and query-plan coverage;
- Authenticated Dashboard Acceptance `31902408118`: PASS on same-tree rerun, **15/15** production scenarios, including Live Dashboard hierarchical selection, acquisition invariant and navigation checks;
- Refrigeration Browser Acceptance `31902408095`: PASS;
- Offline Bundle `31902408111`: PASS — clean transferred host, blocked container egress, pull-disabled disconnected startup, update/rollback persistent-data preservation;
- Offline Auth Acceptance `31902408077`: PASS;
- Acquisition Scale Acceptance `31902408205`: PASS for software matrices only;
- Device Agent Fleet `31902408179`: PASS;
- Container Supply Chain `31902408121`: PASS;
- Broker Control `31902408101`: PASS;
- Disaster Recovery Browser `31902408056`: PASS;
- Disaster Recovery TLS Fleet `31902408079`: PASS;
- MQTT TLS Fleet `31902408091`: PASS;
- Capacity Release Gate `31902408060`: PASS.

Authenticated Dashboard attempt 1 on the same product tree observed a transient pre-existing multi-axis WebSocket peak of 2 and failed that unrelated assertion. No #465 product code was changed for it. Re-running the failed job on the exact same commit/tree passed all 15 scenarios, confirming it was not a reproducible #465 regression.

## Merge gate

This checkpoint updates only the canonical `.project/**` continuity files after the verified product tree. PR #470 must now pass exact-head verification again on the final state-checkpoint head before it can be marked Ready and squash-merged.

Before merge, re-check:

- final head and current `main`;
- intended focused diff only;
- no temporary helper workflows in net diff;
- PR mergeability / behind count;
- reviews and unresolved review threads;
- exact-head required workflows GREEN.

## Independent hardware lane — Issue #289

Issue #289 remains open and `status:in-progress` for controlled Raspberry Pi/RS-485 acquisition-scale and truthful-state acceptance. Software Acquisition Scale, browser, backend and Offline Bundle evidence from #465 does **not** satisfy physical hardware acceptance.

Other pending physical evidence remains separate, including KK2/Unit 115 field retest, refrigeration perceived-latency acceptance and Raspberry Pi version-management acceptance.

## Safety boundary

LOCAL_LAN and offline-first requirements remain unchanged. Issue #465 performs no Modbus/hardware write, controller configuration, scheduler/polling change, acquisition-registry mutation, dependency upgrade, persistent-data deletion, production/site cutover, secret/billing/DNS change or mandatory public-cloud runtime change.
