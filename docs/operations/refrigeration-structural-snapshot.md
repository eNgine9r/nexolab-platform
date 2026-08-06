# Refrigeration structural snapshot

Issue #357 introduces a read-only equipment-scoped structural snapshot at:

```text
GET /api/v1/equipment/{equipment_id}/structural-snapshot
```

The response composes equipment identity, active image metadata, the current layout draft and revision, normalized placements, active sensor bindings, canonical node channels and their optional latest sample.

A channel without a persisted latest sample remains present with `latest_value: null` and `sample_state: unknown`. A non-good persisted sample is classified as `stale`. Structural rendering must not wait for telemetry history or trigger Device Agent configuration, scheduler changes, discovery, Modbus writes or physical polling.

The endpoint is organization-scoped through the existing `READ_DASHBOARD` authorization dependency. It performs no mutation and requires no database migration.

Software verification must include formatting, Python tests, frontend tests, TypeScript checks, production build, Refrigeration Browser Acceptance, Offline Auth and Offline Bundle. Raspberry Pi perceived-latency acceptance remains a separate physical check.
