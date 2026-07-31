# NEXOLAB Current State

Updated: 2026-07-31
Status confidence: provisional until the architecture and roadmap reconciliation Work Package is completed.

## Profile

- Project type: LOCAL_LAN
- Development internet: allowed
- Runtime internet: not required
- Mandatory paid runtime services: not allowed
- Central data: local PostgreSQL
- Edge continuity: local SQLite outbox
- Device transport: read-only Modbus RTU and MQTT QoS 1
- User interface: local web application

## Repository facts already confirmed

- The repository contains a Next.js dashboard, FastAPI telemetry service, edge device agent, MQTT, PostgreSQL, Docker Compose and operations documentation.
- The edge path is designed offline-first and can queue telemetry locally.
- Existing project rules prohibit Modbus writes.
- Operational acceptance on real hardware and the controlled central host is distinct from code completion.

## Active process Sprint

Development standard adoption and offline architecture reconciliation.

- Work Package 182: workflow foundation — in progress.
- Work Package 183: reconcile architecture, roadmap, offline dependencies and current state — Ready after the foundation.

## Operating decision

All new work follows this path:

Product request → vertical Work Package → scoped Issue → branch → implementation → targeted checks → Pull Request → CI/local runtime/offline evidence → state update → Done.

Disconnected page changes are not accepted as a roadmap. UI, API, data, edge, deployment and recovery requirements are grouped by complete user or operator outcome.

## Items still requiring verification

- exact completed milestone boundary versus unverified real-hardware acceptance;
- mandatory versus optional online dependencies;
- current active roadmap and open Issue alignment;
- offline installation and update packaging;
- backup and restore evidence;
- power-loss and service-restart behavior;
- current quality-gate status on main.

## Next action

Complete Work Package 183 and replace this provisional baseline with code-, configuration-, GitHub- and runtime-backed state.
