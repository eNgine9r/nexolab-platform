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
`runtime/evidence/issue-432-navigation-live-final-2/` for evidence head
`5390bc42cde8de6885267eabe3df421fa32b7266`.

### Cold time-to-usable

| Route         | Cold time-to-usable |
| ------------- | ------------------: |
| Overview      |            1,568 ms |
| Refrigeration |              673 ms |
| Energy        |              623 ms |
| Live Data     |              833 ms |
| Nodes         |              735 ms |
| Sessions      |              606 ms |

Cold routes rendered truthful live, stale or empty states. No demo preview was
used and no acquisition mutation was observed.

### First visit and warm return

| Route         | First visit | Warm samples       | Warm median |
| ------------- | ----------: | ------------------ | ----------: |
| Overview      |      394 ms | 398 / 475 / 387 ms |      398 ms |
| Refrigeration |      461 ms | 244 / 231 / 214 ms |      231 ms |
| Energy        |      275 ms | 312 / 273 / 232 ms |      273 ms |
| Live Data     |      277 ms | 346 / 314 / 300 ms |      314 ms |
| Nodes         |      244 ms | 277 / 340 / 306 ms |      306 ms |
| Sessions      |      264 ms | 201 / 306 / 199 ms |      201 ms |

Every warm median is below the required `1,000 ms`. Overview at `398 ms` is
approximately `19.2%` above the Issue #366 reference of `334 ms`, so it remains
inside the allowed 20% regression boundary while now including retained telemetry
content in the completion condition.

### Navigation and ownership invariants

- browser document loads across the complete repeated route cycle: `1`;
- captured visible loading transitions on warm navigation: `0`;
- warm timing starts only after cold observations are cleared, and the acceptance
  fails if any subsequent visible loading transition is captured;
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
- Live Data usability requires the saved-dashboard library loading state to end
  and a rendered dashboard, truthful empty state, forbidden state or error state
  to be visible before the timer stops;
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

Local verification at evidence head `5390bc42cde8de6885267eabe3df421fa32b7266`
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
