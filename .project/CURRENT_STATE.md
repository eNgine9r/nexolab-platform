# NEXOLAB Current State

Updated: 2026-08-07
Verified repository baseline on `main`: `9e174f60cede96cc07d96b7ce5df4e6856593ab5`
Last completed product Work Package: Issue #357 / PR #364
Post-merge state reconciliation: PR #365
Selected next Ready Work Package: Issue #366 — Audit and deduplicate monitoring-route read models
Active product epic: Issue #356 — Eliminate visible loading across monitoring routes
Parallel acquisition/hardware epic: Issue #282

## Issue #357 completed

Issue #357 is closed as completed. PR #364 merged as `f837cae493e9903b0123c8b1ba7ff3c7401eacfc`; post-merge state PR #365 merged as `9e174f60cede96cc07d96b7ce5df4e6856593ab5`.

Completion remains truthful:

```text
software verified; Raspberry Pi perceived-latency acceptance pending
```

The physical Raspberry Pi latency retest is evidence-only and does not reopen the completed software Work Package.

## Post-#357 Ready audit

Repository-backed audit of open Issues, Sprint state, blockers and open Pull Requests produced these findings:

- after reconciliation there is exactly one executable open Issue with `status:ready`: **Issue #366**;
- Issue #366 was created from the explicit third focused Work Package in Epic #356 after completed #355 and #357;
- Issue #245 was incorrectly still labelled `status:ready` even though PR #246 already merged its software scope; it is now `status:needs-validation` because only controlled Raspberry Pi standalone acceptance remains;
- the latest GitHub evidence on #245 still records actual-host standalone acceptance blocked on runtime health, so it must not be selected as a new software implementation package;
- Issue #289 is `status:needs-validation`; all of its declared dependencies #283, #284, #285, #286, #287, #314 and #288 are closed, but its scale/route-latency acceptance is sequenced after the remaining Epic #356 route-read-model/prefetch work so that final measurements are not taken against a knowingly incomplete navigation path;
- Issue #257 remains blocked by ESLint 10 plugin compatibility;
- Issue #256 remains deferred pending TypeScript 7 ecosystem compatibility;
- open dependency PRs #340, #341 and #346 remain unselected; PR #347 remains obsolete after the Playwright 1.62 migration.

## Selected next Work Package

### Issue #366 — Audit and deduplicate monitoring-route read models

Priority: `critical`  
Status: `ready`  
Assignee: `eNgine9r`  
Parent: Epic #356

Product outcome:

- audit Overview, Refrigeration, Energy, Live Data / Live Dashboard, Nodes and Test Sessions read-model ownership and request behavior;
- reuse shared telemetry state from #314 and refrigeration structural state from #357 rather than introducing duplicate caches;
- deduplicate proven equivalent non-telemetry reads with bounded organization-scoped stale-while-revalidate behavior;
- retain valid read-only state during background reconciliation;
- clear cache deterministically on logout/organization change and invalidate only affected resources after mutations;
- record cold/warm REST and WebSocket request counts across repeated route cycles;
- prove normal navigation emits zero Device Agent configuration/discovery mutations and has zero effect on physical polling.

Route prefetch and final cross-route time-to-usable thresholds remain the following focused slice of Epic #356, not part of #366.

## Parallel validation tracks

- **#245:** software merged; `status:needs-validation`; actual standalone Raspberry Pi acceptance pending and latest GitHub physical evidence remains blocked on actual-host runtime health.
- **#289:** `status:needs-validation`; software/hardware performance matrix pending after the remaining navigation optimization slices.
- **#355:** software verified; Raspberry Pi runtime latency acceptance pending.
- **#357:** software completed; Raspberry Pi perceived-latency acceptance pending.

## Security and hardware boundaries

The exact `telemetry-service/libcjson1/CVE-2026-67216` exception expires on **2026-09-05** and must not be broadened.

No Ready-audit action changed runtime code, dependencies, database schema, acquisition scheduler, registry eligibility or physical polling. No Modbus write, hardware write, destructive data operation or production/site cutover occurred.

## Next action

Start Issue #366 from current `main` in one focused feature branch and Pull Request. First produce the repository/browser read-model ownership audit, then implement only the cache/deduplication corrections proven by that evidence. Do not mix route prefetch, dependency upgrades, scheduler changes, database redesign or hardware acceptance into #366.
