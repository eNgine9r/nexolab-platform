# Issue #366 — Monitoring Route Read-Model Audit

Baseline: `main` at `3a91a180ff6b842321c18a2273f405bcdd42e149`

Active branch: `perf/366-monitoring-read-model-deduplication`

Audit date: 2026-08-13

## Objective

Identify read-only REST models recreated by monitoring-route mounts, preserve the
existing shared owners from Issues #314 and #357, and apply one bounded
organization-scoped SWR/deduplication contract only where equivalent non-telemetry
reads are proven or directly implied by route-local lifecycle code.

This audit does **not** authorize route prefetch, polling changes, Device Agent
configuration/discovery, scheduler/registry changes, Modbus writes, database
changes or a second telemetry cache.

## Evidence classes

- **Repository fact** — directly established from current code or merged Issue/PR
  state.
- **Physical browser fact** — observed on the controlled Raspberry Pi / Chromium
  LOCAL_LAN runtime.
- **Pending measurement** — repository structure indicates a repeated mount path,
  but exact route-cycle request counts still require browser instrumentation.

## Existing canonical owners

### Telemetry — Issue #314

The live telemetry adapter uses the route-persistent telemetry client. The shared
client owns persisted latest snapshots, exact-query request coordination and the
shared WebSocket across route transitions. Existing authenticated navigation
acceptance already proved one WebSocket, bounded latest/history REST work and zero
acquisition mutations across Overview -> Refrigeration -> Energy -> Overview.

Consequences for #366:

- Overview latest/stream telemetry stays under #314;
- Energy latest/stream telemetry stays under #314;
- Live Data / selected Live Dashboard latest/stream telemetry stays under #314;
- route-owned bounded history is not copied into the new non-telemetry cache;
- no second telemetry cache is permitted.

Evidence class: **Repository fact**.

### Refrigeration structural state — Issue #357

The refrigeration structural repositories already implement scope-keyed caching,
30-second fresh TTL, 5-minute stale TTL, bounded entries, in-flight deduplication
and targeted invalidation for structural/layout/sensor changes.

Consequences for #366:

- reuse the #357 cache for equipment/layout consumers;
- do not introduce a competing refrigeration cache;
- retain explicit empty, stale and error semantics;
- structural hydration must remain independent of physical polling.

Evidence class: **Repository fact**.

## Route/read-model inventory

| Route / surface            | Read model                             | Baseline owner                                             | Baseline remount behavior                                                           | #366 classification                                           |
| -------------------------- | -------------------------------------- | ---------------------------------------------------------- | ----------------------------------------------------------------------------------- | ------------------------------------------------------------- |
| Overview                   | latest telemetry + WebSocket           | #314 route-persistent telemetry runtime                    | shared below route hook                                                             | keep existing owner                                           |
| Overview                   | equipment layout summary (`LabMap`)    | Equipment Layouts hook + raw equipment/layout repositories | local items start empty; mount loads equipment then draft + published per equipment | proven cache bypass; reuse #357 + retain composed catalog     |
| Overview                   | active sessions panel                  | route-local `SessionApiClient.listSessions`                | local state starts empty; polls every 10 s                                          | pending exact-query cache/browser count                       |
| Refrigeration              | equipment catalog                      | raw `HttpRefrigerationEquipmentRepository`                 | local items load on mount                                                           | proven non-telemetry candidate; reuse #357 scope              |
| Refrigeration              | lifecycle channels/bindings/images     | #357 cached lifecycle repository                           | shared scope cache                                                                  | keep existing owner                                           |
| Refrigeration              | structural snapshot                    | #357 structural snapshot repository                        | shared scope cache                                                                  | keep existing owner                                           |
| Energy                     | latest telemetry + WebSocket           | #314 route-persistent telemetry runtime                    | shared below route hook                                                             | keep existing owner                                           |
| Energy                     | bounded selected-metric history        | Energy route hook                                          | route-owned bounded history                                                         | no generic cache migration without separate proof             |
| Live Data / Live Dashboard | selected telemetry                     | #314 route-persistent telemetry runtime                    | shared below route hook                                                             | keep existing owner                                           |
| Live Dashboard editor      | canonical channel inventory            | route-local inventory hook                                 | local items start empty and canonical inventory reloads when editor remounts        | proven warm-remount candidate; bounded retained inventory     |
| Live Dashboard library     | dashboard definitions                  | route-local library hook                                   | local list reset on effect/remount                                                  | pending browser count and mutation-invalidation integration   |
| Nodes                      | node list + per-node operational state | route-local Nodes workspace                                | local state starts empty; list + per-node operational reads on mount                | pending route-cycle measurement; likely exact-query candidate |
| Test Sessions              | sessions list                          | route-local Sessions screen                                | local state starts empty; list call on mount/filter                                 | pending route-cycle measurement; exact-query candidate        |

## Physical browser evidence carried from Issue #369

The controlled Raspberry Pi / Chromium acceptance for Issue #369 observed:

- canonical Live Dashboard inventory: `200 OK`;
- `total: 162`;
- request duration approximately `44.84 ms`;
- no generic `/telemetry/latest` request used as inventory dependency;
- repeated `GET .../layout/published` requests were visible in the browser console
  for equipment without a published layout.

The `layout/published` 404 response is **not** classified as an API defect when the
backend detail is `layout_not_published`; the layout repository intentionally maps
that result to `value: null`. The useful #366 evidence is the repetition of the
read, not the 404 status itself.

Evidence class: **Physical browser fact**.

## Proven baseline cache bypass

Before the #366 branch correction, `createEquipmentLayoutsRuntime` constructed raw
`HttpRefrigerationEquipmentRepository` and `HttpRefrigerationLayoutRepository`
instances. `loadLayoutCatalog` then performed:

1. one equipment catalog request;
2. one draft request per equipment;
3. one published-layout request per equipment.

Both Overview `LabMap` and the Equipment Layouts workspace consume the same hook,
but the hook kept only route-local component state. A route remount therefore had
no application-shell retained composed catalog and did not use the existing #357
layout cache.

Evidence class: **Repository fact**, corroborated by the physical repeated
`layout/published` reads above.

## #366 correction on the active branch

The active branch currently introduces:

- one generic bounded non-telemetry read-model cache contract with organization
  scope, fresh/stale TTL, SWR, in-flight deduplication, bounded entries, retained
  stale value on refresh failure, subscriptions, targeted invalidation and scope
  clearing;
- cross-runtime equipment catalog caching added to the existing #357 refrigeration
  cache;
- Equipment Layouts wired to the existing #357 equipment/layout cache scope;
- the composed Equipment Layouts catalog retained through the generic read-model
  hook, so a warm remount can render the last valid catalog while reconciliation
  occurs;
- Live Dashboard canonical inventory retained with a short bounded freshness
  window, without changing its endpoint or falling back to `/telemetry/latest`.

The branch also adds a narrow Overview active+acknowledged alerts read model after
Authenticated Dashboard #1676 proved two copies of each exact query across one
route cycle. It uses a 5-second fresh TTL, preserves explicit 5-second polling,
retains the last valid snapshot on refresh failure and is invalidated after
acknowledge/close.

Local format, ESLint, strict TypeScript, full Vitest (86 files / 375 tests),
lint-staged contract and production build are GREEN. Exact-head CI remains
required after the final docs-only reconciliation is committed and pushed. PR
head `78ba940f4f4936dc1810f58c7891362816dcc387` passed CI, all relevant
browser gates, Offline Auth, Offline Bundle and both Disaster Recovery jobs.
Final PR head `11a58e99a69ec04eea38316553724cdad4c83493` repeated the complete
matrix GREEN; Offline Auth required one runner-transient rerun without code
changes. PR #423 was squash-merged as
`a8daee3468e2384c505f988eb006fca05c2afa3f`.

## Invalidation policy

The correction must preserve these rules:

- equipment create invalidates the equipment catalog;
- equipment update/remove invalidates the catalog and that equipment scope;
- layout save/publish/restore/image upload invalidates that equipment scope;
- generic cache keys are organization-scoped;
- logout and organization change must clear newly introduced retained read-model
  state deterministically;
- mutations, credentials, one-time secrets and arbitrary command responses are
  never retained as reusable read models.

## Do-not-cache boundary

Do not place the following in the generic #366 cache:

- telemetry latest/history/WebSocket state already owned by #314;
- refrigeration structural data already owned by #357;
- Device Agent configuration or discovery operations;
- scheduler/registry state used to change physical polling;
- POST/PATCH/PUT/DELETE results as generic reusable cache entries;
- provisioning or credential secrets;
- fabricated fallback/demo values for unavailable production APIs.

## Browser request-count evidence

The canonical local Authenticated Dashboard gate exercised:

```text
Overview
-> Refrigeration
-> Energy
-> Live Data
-> Nodes
-> Sessions
-> Overview
```

The 12-scenario gate passed and recorded:

```text
active_alert_reads=1
acknowledged_alert_reads=1
overview_return_ms=334
latest_requests=1
history_requests=3
session_list_total=2
node_list_reads=1
node_operational_reads=2
equipment_catalog_reads=1
layout_draft_reads=8
layout_published_reads=8
security_session_reads=2
websocket_opened=1
websocket_max_concurrent=1
acquisition_mutations=0
```

This reduces the proven Overview alerts duplicate from `2 + 2` exact reads to
`1 + 1` while preserving the polling cadence. Nodes remain unchanged because the
measured route cycle still shows no duplicate node-list read. The acquisition
invariant also passed across navigation, multiple authenticated contexts,
WebSocket reconnect and telemetry-service restart.

## Safety result

No Issue #366 change performed so far modifies Device Agent configuration,
discovery, scheduler, registry eligibility, physical polling cadence, Modbus,
hardware state, database schema, persistent data or site deployment topology.
