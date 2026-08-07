# Refrigeration structural snapshot

Issue #357 introduces a read-only equipment-scoped structural snapshot at:

```text
GET /api/v1/equipment/{equipment_id}/structural-snapshot
```

The response composes equipment identity, active image metadata, the current layout draft and revision, normalized placements, active sensor bindings, canonical measurement channels and their optional latest sample.

For equipment assigned to a climate chamber, channels are sourced from the canonical chamber catalog and resolved through its measurement bus. This keeps configured channels visible even when no telemetry sample exists and avoids requiring a direct equipment `node_id`. Legacy equipment without a chamber can still use its node-scoped channel source.

A channel without a persisted latest sample remains present with `latest_value: null` and `sample_state: unknown`. A non-good persisted sample is classified as `stale`. Structural rendering must not wait for telemetry history or trigger Device Agent configuration, scheduler changes, discovery, Modbus writes or physical polling.

The endpoint is organization-scoped through the existing `READ_DASHBOARD` authorization dependency. It performs no mutation and requires no database migration.

Cold and warm navigation acceptance must record endpoint request counts. Concurrent consumers for the same organization and equipment are expected to resolve through the bounded frontend structural cache rather than issuing duplicate physical reads. A valid cached snapshot remains visible while background reconciliation is in progress, so route transitions do not replace the canvas with a full-screen loading state.

Production browser readiness is proven with concrete equipment-heading and layout-revision assertions after DOM content is loaded. The acceptance flow does not wait for global network idleness because bounded background reconciliation may keep legitimate requests active.

The structural client and its focused tests are formatted with the repository-pinned Prettier version before the final software gate is evaluated. Background reconciliation avoids capturing the complete mutable equipment record, preventing unnecessary effect restarts while retaining the current valid snapshot. Runtime fixtures explicitly model the optional structural repository, and route hydration uses a typed nullable snapshot promise rather than property-shape detection.

Software verification must include formatting, Python tests, frontend tests, TypeScript checks, production build, Refrigeration Browser Acceptance, Offline Auth and Offline Bundle. Raspberry Pi perceived-latency acceptance remains a separate physical check.
