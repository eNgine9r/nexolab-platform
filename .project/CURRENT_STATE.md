# NEXOLAB Current State

Updated: 2026-08-14

Canonical product baseline is `e384b663f949b8e069b4b488a22cd7d2f7d90502`
(Issue #432 / PR #437 route-prefetch/time-to-usable acceptance merged).

## Completed critical Work Package — Issue #433 / PR #434

Issue #433 is closed and PR #434 is squash-merged. Final PR head
`236019f9929aa230ff1f2f6ff0954ecee3bde6f1` passed the required exact-head
verification: 15 checks passed, the disconnected Offline Bundle runtime passed,
and one image-attestation publish matrix entry was intentionally skipped.

The merged LOCAL_LAN implementation provides:

- atomic audited enrollment of newly discovered configured XJP60D Unit IDs into
  the existing #284 registry as `discovery_only` FC03 inventory;
- zero new scheduler jobs until explicit operator activation;
- live #285 scheduler reconciliation after enrollment/activation with cadence,
  fairness, retry and cooldown policy unchanged;
- bounded per-target attempt/success/failure/cooldown/recovery diagnostics;
- truthful initializing UI before the first sample and explicit sensor /
  communication error states without demo fallback;
- unchanged #378 stable `/dev/serial/by-id/...` transport recovery.

Local verification was GREEN: 30 focused Device Agent tests, all 120 Device
Agent tests, 4 focused UI tests, all 384 frontend tests, formatting, lint,
typecheck and production build. Evidence is recorded in
`docs/audits/issue-433-sensor-enrollment-recovery.md`.

Classification: software verified; post-change Raspberry Pi sensor enrollment
and recovery acceptance remains pending and is not claimed.

## Completed software/browser Work Package — Issue #432 / PR #437

Issue #432 is closed and PR #437 is squash-merged as
`e384b663f949b8e069b4b488a22cd7d2f7d90502`. Final PR head was
`1509fb30e1e558d4585e403d606c5253d87255da`; review-corrected measured-code
evidence head was `5390bc42cde8de6885267eabe3df421fa32b7266`.

Deterministic production-browser evidence proved that the installed Next.js
16.2.12 automatic `<Link>` prefetch already warms all six canonical static
monitoring routes, so no product navigation correction was required.

Final warm median time-to-usable was `398 ms` Overview, `231 ms`
Refrigeration, `273 ms` Energy, `314 ms` Live Data, `306 ms` Nodes and `201 ms`
Sessions. Overview completion requires seeded node `edge-live-01` and a rendered
`°C` value; every non-Overview canonical route proves an exact-path RSC resource
with `_rsc` before first navigation. The repeated route cycle kept one document
load, zero warm loading transitions, no eager channel or Node inventory fetch,
no retained equipment/layout read growth across warm remounts,
`websocket_max_concurrent = 1` and zero acquisition mutations.

Local verification passed format, lint, typecheck, all 89 frontend test files /
384 tests, lint-staged behavior, production build, the focused production route
matrix, the 13-scenario Authenticated Dashboard/acquisition-invariant gate and
Offline Auth migration/browser/persistence gates. Final PR head
`1509fb30e1e558d4585e403d606c5253d87255da` passed CI, Acquisition Scale,
Authenticated Dashboard, Refrigeration Browser, Offline Auth and the complete
disconnected Offline Bundle with update/rollback volume preservation.

Evidence is recorded in
`docs/audits/issue-432-route-prefetch-time-to-usable.md`.

Classification: software/browser route-prefetch verified; physical Raspberry Pi
performance acceptance remains intentionally unclaimed until Issue #289 executes.

## Selected Next Ready Work Package — Issue #289

Issue #289 is open, assigned to `eNgine9r`, labelled `status:ready` and selected
as the single next critical Work Package after the post-#432 dependency audit.
All explicit dependencies #283, #284, #285, #286, #287, #314 and #288 are
closed/completed, and #432 has now completed the remaining route-return
validation prerequisite.

The next product result is controlled Raspberry Pi/RS-485 acquisition-scale and
truthful-state acceptance. The physical request envelope must be compared with
no browser, Overview, one Live Dashboard, repeated navigation and multiple
browser contexts. Page/browser count must not increase normal physical Modbus
request rate. Performance, scheduler, freshness/reconnect and offline evidence
must be captured without changing controller configuration or acquisition policy.

Execution baseline before this state-only reconciliation is
`e384b663f949b8e069b4b488a22cd7d2f7d90502`. Any implementation/acceptance branch
must still verify the actual current `main` head before work begins.

Open dependency-update PRs remain outside this selected critical lane and must
not be mixed into Issue #289.

## Safety boundary

No Modbus or hardware write, polling amplification, persistent-data deletion,
volume deletion, production/site cutover or mandatory cloud dependency is
included. Issue #289 is read-only/evidence-first; hardware verification must not
be claimed without real Raspberry Pi evidence. Core runtime remains LOCAL_LAN
and offline-capable.
