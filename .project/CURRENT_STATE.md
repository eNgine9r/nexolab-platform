# NEXOLAB Current State

Updated: 2026-08-04
Verified main baseline: `56b4c2ab307a621ac3e77adb2f4c2eec70ae842f`
Verified executable source head: `de80cf689fc8829fdf325f8991de9e7d3533ee3e`
Active Work Package: Issue #263 — Live Data telemetry explorer
Pull Request: #264 — verified and ready to leave draft after the state-only gate
Parent Product Epic: Issue #260 — complete all NEXOLAB operator pages
Status confidence: high for repository state, real PostgreSQL REST/history, authenticated WebSocket live updates, browser acceptance and disconnected offline evidence.

## Product route status

Implemented operator routes:

- `/` — Overview dashboard;
- `/nodes` — Nodes;
- `/sessions` — Test sessions;
- `/refrigeration` — Refrigeration equipment;
- `/alerts` — Alerts;
- `/reports` — Reports;
- `/energy` — verified LE-01MP Energy Monitoring;
- `/live` — verified universal telemetry explorer in PR #264.

Remaining placeholder routes:

- `/equipment-layouts` — next queued product page;
- `/equipment` — equipment and metrology registry;
- `/settings` — operator-safe Settings;
- `/cameras` — local Cameras monitoring;
- `/lockers` — blocked pending concrete inventory and read-only protocol scope.

Optional toolchain migrations #252–#257 remain deferred unless they become a security, support or concrete product-delivery blocker.

## Issue #263 outcome

PR #264 replaces the `/live` placeholder with the authenticated operator telemetry explorer.

Delivered behavior:

- real latest-state inventory using stable `node_id + equipment_id + channel_id + metric + unit` identities;
- URL-backed free-text search and node, equipment, channel, metric, quality and alarm filters;
- deterministic latest table with units, timestamps, alarm and explicit live, stale, sensor-error, communication-error and unknown states;
- selection of up to eight channels without duplicates;
- separate synchronized comparison charts for incompatible units;
- authenticated WebSocket coverage before REST snapshots;
- startup event buffering, newest-captured-at reconciliation and duplicate suppression;
- complete history pagination against one commit-stable ingestion watermark;
- bounded downsampling after the complete requested window with first/last and outage-boundary preservation;
- delayed replay and recovery ordering protection;
- explicit loading, empty, reconnecting, offline, auth, configuration, REST and history retry states;
- deterministic browser evidence for persisted stale state, search/filtering, selection, unit-separated charts, outage gaps, range changes, history failure recovery and MQTT-to-PostgreSQL-to-WebSocket live update;
- no demo fallback, dependency migration, telemetry schema migration, Modbus write or hardware action.

## Exact executable-head verification

Verified on source head `de80cf689fc8829fdf325f8991de9e7d3533ee3e`:

- CI `30880961470` GREEN — standalone contracts, format, lint, strict typecheck, Vitest and production build;
- Authenticated Dashboard Acceptance `30880961490` GREEN — real Next.js, FastAPI, PostgreSQL, MQTT and authenticated WebSocket operator flow;
- Refrigeration Browser Acceptance `30880961482` GREEN;
- Offline Bundle `30880961442` GREEN — archive build, clean-host simulation, blocked egress, `--pull never` startup and update/rollback volume preservation.

Review audit for PR #264 is clean: no inline review threads and no submitted reviews.

The current state update changes only the four `.project` source-of-truth files. Executable source remains the verified `de80cf6…` tree; the final state-only head requires its own exact-head repository gate before PR #264 leaves draft.

## Runtime, offline and hardware evidence

```text
/live software verified; PostgreSQL REST/history and authenticated MQTT/WebSocket browser flow verified; disconnected offline bundle update/rollback verified; physical hardware unverified
```

No Raspberry Pi, physical RS-485 device, Modbus command, hardware write or production/site cutover was used. Hardware investigations #200–#202 and actual Raspberry Pi acceptance #245 remain separate evidence requirements.

## Next Ready Work Package

After PR #264 review/merge, create a focused GitHub Issue and feature branch for the queued `/equipment-layouts` catalog. Preserve the page-by-page product priority and do not insert deferred dependency migrations unless they become a concrete blocker.
