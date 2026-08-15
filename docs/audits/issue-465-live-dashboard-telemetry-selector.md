# Issue #465 — Live Dashboard TelemetryPointSelector integration

## Decision

The Live Dashboard editor consumes the reusable `TelemetryPointSelector` through a focused adapter. The existing `/api/v1/live-dashboards/channel-inventory` remains the only selection inventory request and is enriched read-only with climate-chamber/device taxonomy already present in PostgreSQL. No database migration or new endpoint is introduced.

Laboratory and zone metadata is exposed only when existing non-retired refrigeration equipment assigned to a climate chamber agrees on the known value. Missing or conflicting values remain `null`; the UI renders an explicit unclassified branch and never infers taxonomy from identifiers or channel names.

## Persistence boundary

The selector leaf identity remains `node_id | equipment_id | channel_id | metric | unit`. The persisted Live Dashboard contract remains `channel_id + metric` plus visualization metadata and ordering. The adapter maps between these identities only at the editor boundary.

Saved dashboard items absent from the current canonical inventory remain visible as unresolved items and are preserved during selector Confirm/Cancel. Existing selected items retain visualization/color/display-unit metadata and relative order. New selected items are appended in canonical selector order.

## Runtime invariants

The integration does not create a WebSocket, telemetry-history request, discovery/configuration request, acquisition-registry mutation, scheduler change, Modbus write or hardware write. Live view remains the only owner of its existing WebSocket/history behavior.

## Verification

Targeted adapter, component, API and PostgreSQL query-plan regressions plus production browser acceptance are required before merge. Final classification remains `software/browser/offline verified; Raspberry Pi operator acceptance pending` until physical evidence exists.
