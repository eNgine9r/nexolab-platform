# Continuous monitoring and UI visibility boundary

Status: accepted implementation boundary for Issue #627
Profile: `LOCAL_LAN`
Updated: 2026-08-20

## Product rule

NEXOLAB treats physical acquisition and UI visibility as independent state.

A temperature channel is continuously monitored only when its canonical XJP60D target is poll-eligible in the persisted Device Agent Acquisition Registry. Opening, closing, refreshing, or configuring a browser view must not change that eligibility.

The canonical flow is:

```text
read-only discovery
→ discovery-only inventory
→ explicit commissioning / monitoring enrollment
→ persisted Acquisition Registry `active` lifecycle
→ read-only Modbus FC03 scheduler
→ MQTT / PostgreSQL telemetry persistence
→ Overview / Live / equipment layouts / reports
```

Discovery is evidence of presence. It is not authorization to begin continuous polling.

## State ownership

### Device Agent Acquisition Registry

The Acquisition Registry is authoritative for physical polling eligibility. For XJP60D targets:

- `active` means monitoring enabled and poll-eligible;
- `discovery_only` means observed inventory but not poll-eligible;
- other non-active lifecycle states remain non-poll-eligible;
- registry mutations are explicit commissioning operations;
- the adaptive scheduler reconciles from the registry and remains browser-independent.

The compatibility `/api/v1/xjp60d/configuration` surface reports the registry-derived `active_points`. Its GET operation is read-only. POST discovery and PUT enrollment remain explicit service operations behind the existing permission boundary.

### Overview

Overview owns only presentation visibility. Its channel selection is organization-scoped browser state under schema-versioned local storage.

The Overview selector may hide any or all monitored channels without changing Device Agent configuration, registry revision, scheduler targets, telemetry persistence, Live Dashboard definitions, or equipment bindings.

If no Overview preference exists, all currently monitored channels are shown by default. The selector never invents a hard-coded monitoring set.

### Live Data and equipment layouts

Live Data, Saved Dashboards, refrigeration views, equipment layouts, and reports are telemetry consumers. Selecting or binding a channel in those surfaces must not mutate acquisition configuration.

A channel that is not monitored may still exist in catalog or historical data. Those surfaces must preserve truthful stale/no-data/error semantics and must never label old persisted data as live.

## Commissioning surface

Explicit XJP60D monitoring enrollment lives under Settings for operators with `equipment.manage`.

The workflow distinguishes discovery from monitoring:

1. run read-only discovery when required;
2. inspect discovered channels and diagnostics;
3. explicitly select the channels to monitor;
4. save the persisted monitoring set;
5. let the Device Agent reconcile the adaptive scheduler.

Simply viewing Settings does not mutate the registry. Discovery does not promote targets to `active`. Only the explicit save operation may change poll eligibility.

## Failure and compatibility behavior

- Browser closure or navigation has no effect on monitored acquisition.
- A temporary browser-side Device Agent control failure does not create fallback monitored channels. The UI may reuse only the last locally cached authoritative active-point set for presentation while the physical Device Agent continues independently.
- The legacy local-storage key for active points is retained as a compatibility cache, not as an acquisition source of truth.
- Existing persisted active registry targets are not rewritten by this UI migration.
- No database migration, dependency upgrade, cloud service, CDN, remote font, or external API is introduced.

## Safety invariants

- Physical XJP60D acquisition remains Modbus FC03 read-only.
- Overview visibility changes produce zero configuration mutations.
- Live Dashboard selection and equipment layout binding produce zero configuration mutations.
- Read-only discovery may extend inventory evidence but must not make a target poll-eligible.
- Monitoring enrollment is the only UI workflow in this scope allowed to change XJP60D poll eligibility.
- No Modbus write, controller write, hardware write, production/site cutover, persistent-data deletion, or named-volume deletion is authorized.

## Verification contract

Software acceptance requires focused frontend tests, Device Agent registry/boundary tests, typecheck/lint/format checks, production browser acquisition-invariant coverage, required GitHub CI, production build, and Offline Bundle. Real Raspberry Pi acceptance additionally compares registry revision, configured target count, physical request counters, and telemetry persistence before and after an Overview-only visibility change and proves continued monitored acquisition with the browser closed.
