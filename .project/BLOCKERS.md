# NEXOLAB Blockers

Updated: 2026-08-12

## Issue #404 — completed, blockers resolved

Issue #404 / PR #410 is squash-merged as `d4068e28402aa113f4485dc3afecb1f8eb44bd7b` from final product head `ce2356cfb142e241684a7a68a08969cab884c2f5`.

The earlier Raspberry Pi visual-continuity failure is resolved. Final controlled evidence established:

- acquisition invariant PASS: browser closed `192` physical requests / `3.200 req/s` versus active Saved Dashboard `181` / `3.017 req/s`;
- scheduler policy unchanged;
- configured targets `38 -> 38`;
- poll-eligible targets `38 -> 38`;
- service operations unchanged;
- real Saved Dashboard `111`, series `104-03 / temperature.probe`, received exact `dixell-xjp60d` events while the existing 24 h chart stayed visible;
- dashboard remained usable;
- library -> reopen PASS;
- final cursor retest on `ce2356cf...`: no vertical jump, graph/card fixed, zoom/pan/reset PASS;
- transient candidate stopped cleanly and production restored `active/running`, `NRestarts 0 -> 0`, HTTP 200.

The previous acceptance-harness orphan `next-server`/`EADDRINUSE` problem is also resolved. The final candidate was run as a transient systemd unit and left no orphan process.

No #404 product or merge blocker remains.

## Issue #411 — active state-only reconciliation

Issue #411 reconciles durable repository state after #404 merge. This is not a product/runtime blocker. Permitted changes are limited to `.project/**` and `docs/audits/issue-404-saved-live-dashboard-chart-system.md`.

After #411 merges, a fresh repository-backed Ready audit is required before the next implementation package is selected.

## Issue #369 — Ready, separate scope

Issue #369 remains `status:ready` for Raspberry Pi Live Dashboard inventory/filter/select/save editor acceptance. It was not absorbed by #404.

Preserved runtime sequence:

```text
#369 -> #366 -> #289
```

## Issue #389 — Ready and not selected

Issue #389 remains Ready for administrator-only local Version Management. Product Owner priority currently favors continuing the Chart System sequence, subject to the required fresh Ready audit.

## Other known boundaries

- Issue #245 remains a separate Raspberry Pi validation track.
- Issue #257 remains blocked by ESLint 10 ecosystem compatibility.
- Issue #256 remains deferred pending TypeScript 7 ecosystem compatibility.
- `max_parallel_implementation_tasks` remains 1.

## Security boundary

The `telemetry-service/libcjson1/CVE-2026-67216` exception expires on **2026-09-05**. Issue #404 did not broaden it.

## Global hard-stop rules

Stop before destructive data/volume operations, production/site cutover, Modbus or other hardware writes, secret exposure, mandatory online runtime dependencies, privileged hardware containers or unsupported physical-acceptance claims.