# NEXOLAB Current State

Updated: 2026-08-14

Canonical product/runtime baseline is `2cb88030cae151a95c43fe1f303a8d51b66968c1`
(Issue #440 / PR #441 acquisition-worker liveness fix merged and hardware
verified).

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

## Active critical Work Package — Issue #289

Issue #289 is open, assigned to `eNgine9r` and selected as the active
critical hardware-performance acceptance Work Package after the completed
Issue #440 worker-liveness correction and Issue #442 state reconciliation.
All explicit dependencies #283, #284, #285, #286, #287, #314 and #288 are
closed/completed, and #432 has now completed the remaining route-return
validation prerequisite.

The next product result is controlled Raspberry Pi/RS-485 acquisition-scale and
truthful-state acceptance. The physical request envelope must be compared with
no browser, Overview, one Live Dashboard, repeated navigation and multiple
browser contexts. Page/browser count must not increase normal physical Modbus
request rate. Performance, scheduler, freshness/reconnect and offline evidence
must be captured without changing controller configuration or acquisition policy.

Runtime baseline after Issue #440 merge is
`2cb88030cae151a95c43fe1f303a8d51b66968c1`. Before the next physical acceptance capture, the Issue #289
hardware-validation branch must be aligned to the post-Issue-442 `main` head.

Open dependency-update PRs remain outside this selected critical lane and must
not be mixed into Issue #289.

## Safety boundary

No Modbus or hardware write, polling amplification, persistent-data deletion,
volume deletion, production/site cutover or mandatory cloud dependency is
included. Issue #289 is read-only/evidence-first; hardware verification must not
be claimed without real Raspberry Pi evidence. Core runtime remains LOCAL_LAN
and offline-capable.

## Execution update — Issue #440 hardware verified

Issue #289 hardware execution from actual `main` `f523f14dc17b28de3683e1773a2ef5a7143a194f` exposed a production
acquisition-liveness defect before a valid performance baseline could be
established:

- registry contained 33 poll-eligible targets;
- scheduler contained 33 due jobs;
- `rs485-main.worker_count` was `0`;
- the first 60-second no-browser phase produced zero new normal physical
  requests while the Docker container remained healthy;
- Issue #289 was therefore blocked and critical Issue #440 was opened.

Issue #440 implementation:

- branch `fix/440-acquisition-worker-self-recovery`;
- PR #441;
- implementation head `97fab27dd99a8685edc6c96c8e99bc0db88e1bd7`;
- deterministic dead-worker detection and bounded single-worker recovery;
- no catch-up burst after recovery;
- truthful expected/active worker diagnostics;
- fail-closed health when eligible polling has no live worker;
- no polling-policy, registry-lifecycle, dependency or Modbus-write change.

Verification on the implementation head:

- targeted adaptive tests: 16/16 PASS;
- full Device Agent suite: 122/122 PASS;
- exact-head GitHub workflow matrix: 9/9 GREEN;
- Offline Bundle disconnected startup and persistent-data update/rollback:
  GREEN.

Controlled Raspberry Pi candidate acceptance is PASS:

- existing `nexolab-edge_edge-data` volume preserved;
- expected/active workers: 1/1;
- `workers_healthy = true`;
- `rs485-main.worker_count = 1`;
- 60-second normal physical requests: 155;
- successes: 132;
- timeouts: 23;
- retries: 18;
- bus utilization: 22.365%;
- scheduler lag maximum: 2.183755 seconds;
- missed deadlines: 41;
- deferred: 24;
- overruns: 0;
- worker failures/restarts during candidate window: 0/0.

Classification: **software verified; hardware verified for Issue #440 worker
liveness**.

The timeout/retry and degraded endpoint evidence remains truthful and transfers
to Issue #289. It is not hidden and is not classified as a #440 worker-liveness
failure.

## Post-merge reconciliation — Issue #440 complete; Issue #289 resumes

Issue #440 is closed/completed and PR #441 is squash-merged into `main` as
`2cb88030cae151a95c43fe1f303a8d51b66968c1`.

Final Issue #440 evidence:

- implementation head: `97fab27dd99a8685edc6c96c8e99bc0db88e1bd7`;
- final PR head: `b2ee4bd7bc3a7c1d3ae944ce36dc047cbebc0546`;
- final exact-head workflow matrix: 9/9 GREEN;
- targeted adaptive tests: 16/16 PASS;
- full Device Agent suite: 122/122 PASS;
- controlled Raspberry Pi candidate acceptance: PASS;
- expected/active acquisition workers: 1/1;
- `workers_healthy = true`;
- `rs485-main.worker_count = 1`;
- normal physical requests in the 60-second hardware window: 155;
- worker failures/restarts during the window: 0/0;
- existing `nexolab-edge_edge-data` volume preserved;
- no Modbus write, hardware write, polling-policy mutation, registry mutation,
  persistent-data deletion, volume deletion or site cutover occurred.

The temporary Issue #289 → Issue #440 dependency blocker is resolved.

Issue #289 is therefore selected to resume as the active critical
acquisition-scale and truthful-state acceptance Work Package after this
state-only reconciliation merges.

The first #289 execution step must be a **fresh equal-window `no-browser`
Raspberry Pi baseline** against merged post-#440 code. The original pre-fix
zero-request phase is defect evidence only and must never be reused as passing
performance evidence.

Residual physical evidence remains assigned to #289 for analysis:

- 23 timeout outcomes / 60 seconds;
- 18 retries / 60 seconds;
- 41 missed deadlines / 60 seconds;
- 24 deferred executions / 60 seconds;
- health/readiness reported degraded from real endpoint communication state.

Those residual values are not hidden or reclassified by the worker-liveness
fix.

Issue #289 execution remains read-only. Normal browser/page activity must not
alter physical polling, and Modbus/hardware writes remain forbidden.
