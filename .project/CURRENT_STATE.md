# NEXOLAB Current State

Updated: 2026-08-14

## Canonical repository baseline

Current product/runtime `main` after Issue #451 merge is
`6286e8ed4ccb3d5d0e5f34d7b62fd6cb15fdedc0`.

Post-Issue-443 corrections already included in this baseline remain classified
separately:

- Issue #445 / PR #446 restored the KK2/XJP60D discovery catalog including Unit
  115. Software/CI/offline verification is complete; the Raspberry Pi field
  retest remains pending and is not claimed.
- Issue #447 / PR #448 removed the redundant refrigeration structural-snapshot
  wait while preserving truthful fallback/unavailable behavior. Software/browser/
  offline verification is complete; physical Raspberry Pi perceived-latency
  acceptance remains pending separately.

## Completed critical chart Work Package — Issue #451 / PR #452

Issue #451 is closed/completed. PR #452 was exact-head guarded and squash-merged
into `main` as `6286e8ed4ccb3d5d0e5f34d7b62fd6cb15fdedc0` from final PR head
`795cff9a309fcb70981293c29009682fdafddfba`.

The canonical Chart System now provides:

- cadence-aware render-only source-gap tolerance while explicit
  communication/quality/offline/reconnect gaps remain truthful breaks;
- deterministic ordering/deduplication, malformed-time rejection and stable
  active segment identities;
- canonical event provenance without sample-derived `Alarm context ...`
  overlays or alarm pins;
- collision-safe event rendering without permanent overlapping labels;
- synchronized Exact Inspector snapshots with nearest measured sample per
  visible series and bounded tolerance;
- presentation-only two-decimal default measurement formatting without changing
  raw telemetry;
- independent latest-legend and historical cursor-inspection semantics;
- browser-truthful chart-host pointer handling, including protection from empty
  ECharts axis-pointer events clearing a valid hover snapshot;
- immediate selected WebSocket-tail retention by advancing the Live history
  window to the newest accepted selected sample while preserving the requested
  duration and without a REST history refetch.

Final exact-head verification on `795cff9a...` is GREEN:

- CI / Quality and build: PASS — repository formatting, lint, typecheck, full
  tests and production build;
- Authenticated Dashboard Acceptance: 13/13 PASS, including real mouse hover,
  six-series Exact Inspector, WebSocket `9.876 -> 9.88 degC`, one WebSocket and
  zero acquisition mutations;
- Refrigeration Browser Acceptance: PASS;
- disconnected Offline Bundle: PASS, including clean transferred-host startup,
  blocked container egress, update/rollback and persistent-volume preservation.

Classification: **software/browser/offline verified; Raspberry Pi operator
acceptance pending**. No physical hardware completion is claimed for Issue #451.

## Active state reconciliation — Issue #454

Issue #454 is the state-only post-merge reconciliation Work Package. Its scope is
limited to `.project/**`: record the #451 merge truth, preserve the independent
hardware lane and make the next Chart System package resumable from repository
state. No runtime/product code belongs in this Work Package.

## Independent active hardware lane — Issue #289

Issue #289 remains open and `status:in-progress` as the independent controlled
Raspberry Pi/RS-485 acquisition-scale and truthful-state acceptance lane. The
fresh equal-window no-browser baseline and subsequent Overview / Live Dashboard /
navigation / multi-browser matrix still require real Raspberry Pi hardware
evidence.

The pre-fix zero-request window remains defect evidence only and must not be
reused as passing performance evidence.

## Next independent Chart System Work Package

Issue #453 — equipment-centric multi-metric charts with dynamic Y axes — has its
#451 dependency resolved by merge `6286e8ed...`. It becomes `status:ready` after
Issue #454 state reconciliation merges and must then start on its own feature
branch and focused PR.

## Safety boundary

LOCAL_LAN and offline-first runtime requirements remain unchanged. No Modbus
write, hardware write, polling/scheduler mutation, acquisition-registry mutation,
destructive persistent-data action, volume deletion, production/site cutover,
dependency upgrade, secret handling or mandatory public-cloud runtime dependency
is included in Issue #454 or authorized by the #451 merge.
