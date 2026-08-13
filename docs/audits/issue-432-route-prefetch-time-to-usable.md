# Issue #432 — monitoring-route prefetch and time-to-usable audit

Baseline: `9ddef4445b2894f25a6e93267f497d0e5b09b970`

Branch: `perf/432-route-prefetch-time-to-usable`

Evidence classification: deterministic local production-build browser evidence.
Raspberry Pi performance acceptance remains pending under Issue #289.

## Objective and boundary

Issue #432 measures the canonical authenticated route cycle:

```text
Overview -> Refrigeration -> Energy -> Live Data -> Nodes -> Sessions -> Overview
```

The acceptance harness records cold and warm time-to-usable, browser route-resource
timing, REST reads, visible loading transitions, document loads, WebSocket
concurrency and acquisition mutations. It does not change the Device Agent,
registry, scheduler, polling cadence, Modbus behavior, backend, database or
dependency graph.

## Installed Next.js contract

The repository installs Next.js `16.2.12`. Repository-local documentation under
`node_modules/next/dist/docs/` establishes that:

- a visible App Router `<Link>` automatically prefetches in production;
- a static route receives a full-route prefetch and a five-minute default client
  cache lifetime;
- Next.js 16 deduplicates shared layouts and incrementally prefetches only missing
  route segments;
- manual `router.prefetch()` is intended for routes outside the viewport or a
  measured custom strategy, and custom link behavior adds cache-invalidation and
  accessibility maintenance responsibility.

The canonical sidebar already renders plain `<Link>` elements for all six routes.
The production build classifies `/`, `/refrigeration`, `/energy`, `/live`, `/nodes`
and `/sessions` as static. Browser resource timing before the first route click
recorded RSC prefetches for every non-Overview canonical route, including
`/refrigeration?_rsc=...`, `/energy?_rsc=...`, `/live?_rsc=...`,
`/nodes?_rsc=...` and `/sessions?_rsc=...`.

## Deterministic browser evidence

The focused production acceptance used the isolated seeded Compose profile and
Chromium. Evidence is stored locally at
`runtime/evidence/issue-432-navigation-9ddef444/`.

### Cold time-to-usable

| Route         | Cold time-to-usable |
| ------------- | ------------------: |
| Overview      |            1,259 ms |
| Refrigeration |              724 ms |
| Energy        |              528 ms |
| Live Data     |              499 ms |
| Nodes         |              828 ms |
| Sessions      |              597 ms |

Cold routes rendered truthful live, stale or empty states. No demo preview was
used and no acquisition mutation was observed.

### First visit and warm return

| Route         | First visit | Warm samples       | Warm median |
| ------------- | ----------: | ------------------ | ----------: |
| Overview      |      259 ms | 263 / 248 / 283 ms |      263 ms |
| Refrigeration |      521 ms | 275 / 224 / 376 ms |      275 ms |
| Energy        |      407 ms | 282 / 276 / 309 ms |      282 ms |
| Live Data     |      270 ms | 192 / 198 / 234 ms |      198 ms |
| Nodes         |      407 ms | 265 / 336 / 263 ms |      265 ms |
| Sessions      |      267 ms | 200 / 210 / 208 ms |      208 ms |

Every warm median is below the required `1,000 ms`. Overview at `263 ms` is also
below the Issue #366 reference of approximately `334 ms`, so there is no greater
than 20% regression.

### Navigation and ownership invariants

- browser document loads across the complete repeated route cycle: `1`;
- captured visible loading transitions on warm navigation: `0`;
- route resources recorded before the first click: `73`;
- canonical channel-inventory reads before navigation: `0`;
- Node inventory reads before navigation: `0`;
- telemetry latest reads across the repeated cycle: `1`;
- equipment catalog reads across the repeated cycle: `1`;
- layout draft/published reads across the repeated cycle: `3 / 3`, one per seeded
  equipment, preserving the Issue #366 composed catalog ownership;
- WebSockets opened: `1`;
- `websocket_max_concurrent`: `1`;
- navigation-driven acquisition mutations: `0`.

The route-local Nodes, Sessions and Live Dashboard library reads still reconcile
when those routes remount. The evidence does not introduce a second cache or alter
the Issue #366 ownership boundaries. Overview alert reads remain bounded by the
existing five-second polling contract rather than navigation prefetch.

## Decision

No product implementation is required. The installed Next.js automatic prefetch
already warms all canonical static route modules, and the measured route cycle
passes every warm time-to-usable target with substantial margin. Adding manual
prefetch would duplicate the framework scheduler without a measured gap.

The only repository changes for Issue #432 are deterministic acceptance
instrumentation, a focused test-selection option for local evidence runs, this
audit, and final project-state reconciliation.

## Safety and offline result

No scheduler, registry, polling, Device Agent, backend, database, Modbus, hardware,
dependency or production/site-cutover behavior changed. Core runtime behavior
remains LOCAL_LAN and offline-capable. Software/browser route-prefetch is verified;
physical Raspberry Pi performance evidence remains unverified and must not be
claimed as passing.
