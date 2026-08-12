# NEXOLAB Current State

Updated: 2026-08-12

Canonical repository baseline on `main`: `d4068e28402aa113f4485dc3afecb1f8eb44bd7b` — Issue #404 / PR #410 Saved Live Dashboard canonical Chart System merge.

## Completed — Issue #385

Issue #385 / PR #390 is merged as `e0b124e9a0152be50966daa131974b3543651e87`. Local users, four roles, administrator-managed permissions and offline-local authentication are software- and Raspberry-Pi-verified.

## Completed — Issue #386

Issue #386 / PR #399 is merged as `3b34ec321c2453778b20b6bf8e4cc232970e5e1e`. Canonical Chart Domain, truthful continuity, compatible-unit grouping, evidence-preserving reduction, ECharts 6.1.0 Canvas adapter, Chart Shell and renderer host are canonical.

## Completed — Issue #400

Issue #400 / PR #402 is merged as `afdfa387a7aa988a49e010d75c27d59a7cdf74d2`. Live Data uses the canonical Chart System. Controlled Raspberry Pi acquisition-invariant acceptance was PASS.

## Completed — Issue #406

Issue #406 / PR #407 is merged as `457923927052ed91a23f396b2285e0cfaf6096ad`. The Live Data chart-disappearance regression is fixed and protected by real local MQTT browser continuity coverage.

## Completed — Issue #408

Issue #408 / PR #409 is merged as `f3462861db2a3593e2072a7bad70d557c009b323`. It reconciled #406 and selected Issue #404.

## Completed — Issue #404

Issue #404 / PR #410 is squash-merged as `d4068e28402aa113f4485dc3afecb1f8eb44bd7b`.

Final product head before squash merge: `ce2356cfb142e241684a7a68a08969cab884c2f5`.

Product result:

- persisted Saved Dashboard `line` and `area` series use the canonical Chart System;
- legacy independent SVG history renderer is removed;
- persisted order, saved colors and native units remain stable;
- quality, freshness and continuity remain independent;
- invalid-quality and source-gap events create truthful gaps instead of erasing or bridging history;
- alarm evidence pins and bounded evidence-preserving reduction remain canonical;
- compatible-unit grouping and cumulative-energy semantics are preserved;
- shared cursor, show/hide/solo, zoom/pan/reset are canonical;
- persisted `time_window` remains the initial/reset viewport;
- `refresh_seconds` remains display-only and does not alter physical acquisition;
- value/gauge remain truthful current-value cards;
- rolling Saved Dashboard updates are non-animated through the persistent Canvas renderer;
- cursor/tooltip interaction is layout-stable with no vertical card/chart jump.

Final exact-head software gates on `ce2356cf...`:

- CI #2910: GREEN;
- Authenticated Dashboard Acceptance #1607: GREEN, 12/12 production Playwright;
- Acquisition Scale Acceptance #84: GREEN;
- Refrigeration Browser Acceptance #1581: GREEN;
- Offline Bundle #990: GREEN;
- unresolved review threads: 0;
- final compare: ahead 48, behind 0 against `f3462861...`.

Controlled Raspberry Pi evidence:

- browser-closed acquisition: 192 physical requests / 3.200 req/s;
- active Saved Dashboard: 181 physical requests / 3.017 req/s;
- scheduler policy unchanged;
- configured targets `38 -> 38`;
- poll-eligible targets `38 -> 38`;
- service operations unchanged;
- real Saved Dashboard `111`, series `104-03 / temperature.probe`, received exact `dixell-xjp60d` events at `10:47:34`, `10:47:39`, and `10:47:44 UTC` with truthful `communication_error` quality;
- existing 24 h graph stayed visible through those events;
- dashboard remained usable;
- library -> reopen PASS;
- final Pi cursor retest on `ce2356cf...`: no vertical jump, graph/card fixed, zoom/pan/reset PASS;
- transient candidate stopped cleanly and production restored `active/running`, `NRestarts 0 -> 0`, HTTP 200.

No Modbus write, hardware write, database mutation, polling/scheduler/registry change, mandatory public runtime dependency or site cutover occurred.

## Active Work Package

Issue #411 — **Reconcile Issue #404 merge and Chart System continuation** — is the current state-only Work Package on `chore/411-reconcile-issue-404-state`.

No product/runtime implementation is active while #411 is open.

## Preserved lanes

Issue #369 remains Ready and separate for Raspberry Pi Live Dashboard inventory/filter/select/save editor acceptance.

Preserved runtime sequence:

```text
#369 -> #366 -> #289
```

Issue #389 remains Ready/not selected for administrator-only Version Management.

Issue #245 remains a separate Raspberry Pi validation track. Issue #257 remains blocked. Issue #256 remains deferred.

## Security boundary

The `telemetry-service/libcjson1/CVE-2026-67216` exception expires on 2026-09-05. Issue #404 did not broaden it.

## Next action

Complete and merge state-only Issue #411, then run a fresh repository-backed Ready audit across open `status:ready` Issues, blockers, dependencies, open PRs, CI and current `main`. The Product Owner priority is to continue Chart System migration with Overview, but the Overview Work Package must be created/refined only after that audit confirms it is the next unblocked package.
