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

After PR review, the Overview usability boundary was tightened so every cold and
warm measurement also requires the seeded `edge-live-01` node and a rendered
`°C` value. The pre-navigation resource capture is now an acceptance assertion:
each non-Overview canonical route must have an exact-path resource URL with the
`_rsc` query parameter before its first click; the opaque parameter value and
unrelated `/_next` assets are intentionally not asserted.

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
`runtime/evidence/issue-432-navigation-final-evidence/` for evidence head
`a15026fe61cbc44e5deb19cd7fdd2f897c614522`.

### Cold time-to-usable

| Route         | Cold time-to-usable |
| ------------- | ------------------: |
| Overview      |            1,656 ms |
| Refrigeration |              670 ms |
| Energy        |              681 ms |
| Live Data     |              565 ms |
| Nodes         |              942 ms |
| Sessions      |              598 ms |

Cold routes rendered truthful live, stale or empty states. No demo preview was
used and no acquisition mutation was observed.

### First visit and warm return

| Route         | First visit | Warm samples       | Warm median |
| ------------- | ----------: | ------------------ | ----------: |
| Overview      |      405 ms | 415 / 375 / 373 ms |      375 ms |
| Refrigeration |      423 ms | 293 / 271 / 340 ms |      293 ms |
| Energy        |      473 ms | 321 / 270 / 240 ms |      270 ms |
| Live Data     |      261 ms | 266 / 180 / 173 ms |      180 ms |
| Nodes         |      469 ms | 342 / 278 / 309 ms |      309 ms |
| Sessions      |      260 ms | 190 / 210 / 170 ms |      190 ms |

Every warm median is below the required `1,000 ms`. Overview at `375 ms` is
approximately `12.3%` above the Issue #366 reference of `334 ms`, so it remains
inside the allowed 20% regression boundary while now including retained telemetry
content in the completion condition.

### Navigation and ownership invariants

- browser document loads across the complete repeated route cycle: `1`;
- captured visible loading transitions on warm navigation: `0`;
- route resources recorded before the first click: `73`;
- exact-path RSC prefetches with `_rsc` present before the first click:
  `/refrigeration`, `/energy`, `/live`, `/nodes` and `/sessions`;
- canonical channel-inventory reads before navigation: `0`;
- Node inventory reads before navigation: `0`;
- telemetry latest reads across the repeated cycle: `1`;
- equipment catalog reads across the repeated cycle: `1`;
- focused-run layout draft/published reads were `3 / 3` after the first route
  cycle and remained `3 / 3` after all warm cycles; the complete 13-test matrix
  began and ended at `8 / 8` after its larger seeded catalog, proving no warm-remount
  growth while preserving the Issue #366 composed catalog ownership;
- route-local Node list, Node operational-state and Sessions reads finished at the
  asserted `4`, `8` and `5` bounds after three warm cycles;
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

Local verification at evidence head `a15026fe61cbc44e5deb19cd7fdd2f897c614522`
passed the focused production navigation matrix (`3/3`), the complete
Authenticated Dashboard/acquisition-invariant matrix (`13/13`), Offline Auth
migration plus browser/persistence/version gates (`4 + 1 + 1` browser tests),
format, lint, typecheck, all `89` frontend test files / `384` tests, the
lint-staged contract and the production build. Exact-head CI, Acquisition Scale,
Authenticated Dashboard, Refrigeration Browser and disconnected Offline Bundle
also passed. The required exact-head workflows were rerun for the corrected
read-model assertion head before project-state reconciliation.

## Safety and offline result

No scheduler, registry, polling, Device Agent, backend, database, Modbus, hardware,
dependency or production/site-cutover behavior changed. Core runtime behavior
remains LOCAL_LAN and offline-capable. Software/browser route-prefetch is verified;
physical Raspberry Pi performance evidence remains unverified and must not be
claimed as passing.
