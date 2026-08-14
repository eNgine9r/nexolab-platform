# NEXOLAB Blockers

Updated: 2026-08-14

## Issue #433 / PR #434 — merged

PR #434 is squash-merged as `06f78b178acfed72033bf607099d827eca1a9f9a`.
Final PR head `236019f9929aa230ff1f2f6ff0954ecee3bde6f1` passed 15 exact-head
checks. Disconnected Offline Bundle runtime passed; one attestation publish
matrix entry was intentionally skipped.

Post-change Raspberry Pi enrollment/recovery acceptance was not performed and
is not claimed. This remains separate hardware evidence and does not authorize
any Modbus or hardware write.

## Issue #432 / PR #437 — merged, software/browser verified

PR #437 is squash-merged as `e384b663f949b8e069b4b488a22cd7d2f7d90502`.
Final PR head `1509fb30e1e558d4585e403d606c5253d87255da` passed CI, Acquisition Scale,
Authenticated Dashboard, Refrigeration Browser, Offline Auth and disconnected
Offline Bundle. All eight review threads were resolved before merge.

Review-corrected warm navigation passed at `201..398 ms` median across the six
canonical routes with one document load, `websocket_max_concurrent = 1`, no
eager channel/Node inventory fetch, no retained equipment/layout read growth
across warm remounts and zero acquisition mutations. No product navigation code
was required.

No Issue #432 blocker remains. Raspberry Pi physical/performance acceptance is
intentionally delegated to Issue #289 and is not yet claimed.

## Ready/dependency audit

- Issue #289 is open, assigned and `status:ready`; it is selected as the next
  critical Work Package.
- All explicit #289 dependencies #283, #284, #285, #286, #287, #314 and #288 are
  closed/completed; #432 is also closed/completed as the final route-return
  prerequisite.
- No open `status:ready` product package competes with #289 in the critical lane.
- Open Dependabot PRs remain outside the selected Sprint lane and must not be
  mixed with #289.
- Issue #415 remains an unselected Chart System UX follow-up.
- Issue #245 remains a separate Raspberry Pi validation track.
- Issue #257 remains blocked; Issue #256 remains deferred.
- Raspberry Pi version-management acceptance for #389 remains pending separately.

## Issue #289 execution blocker state

No pre-execution software dependency blocker is open. Completion still requires
real controlled Raspberry Pi/RS-485 evidence. Hardware verification must remain
`pending` until that matrix is actually captured.

Any Modbus write, controller configuration change, hardware write, destructive
data action or production/site cutover is a hard blocker requiring separate
explicit approval and is outside Issue #289.

## Safety

Existing LOCAL_LAN, offline-runtime, read-only acquisition and hardware-safety
boundaries remain unchanged.

## Resolved blocker — Issue #289 / Issue #440

**Resolved by merge `2cb88030cae151a95c43fe1f303a8d51b66968c1`.**

Issue #440 is closed/completed and PR #441 is squash-merged. Controlled
Raspberry Pi acceptance proved one expected and one active acquisition worker,
155 normal physical requests in 60 seconds, and zero worker failures/restarts
during the candidate window.

The former #289 → #440 dependency blocker is therefore removed.

Issue #289 resumes after Issue #442 state reconciliation from a fresh
`no-browser` baseline. The pre-fix zero-request window remains defect evidence
only.

Residual evidence remains active inside Issue #289 rather than being treated as
a blocker:

- 23 timeout outcomes;
- 18 retries;
- 41 missed deadlines;
- 24 deferred executions;
- degraded health/readiness from actual endpoint communication state.

No Modbus/hardware write, controller change, destructive data action, volume
deletion or site cutover is authorized.
