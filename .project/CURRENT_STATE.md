# NEXOLAB Current State

Updated: 2026-08-14

## Canonical repository baseline

Current verified `main` before Issue #451 merge is
`3ae380c9882bcd7a0c5d142404c1a64da801513a`.

Post-Issue-443 changes already present in that baseline and now reconciled here:

- Issue #445 / PR #446 restored the KK2/XJP60D discovery catalog including Unit 115. Software/CI/offline verification is complete; the separate Raspberry Pi
  field retest remains pending and is not claimed.
- Issue #447 / PR #448 removed the redundant refrigeration structural-snapshot
  wait while preserving truthful fallback/unavailable behavior. Software/browser/
  offline verification is complete; physical Raspberry Pi perceived-latency
  acceptance remains pending separately.

## Verified critical chart Work Package — Issue #451 / PR #452

Issue #451 is implemented on branch
`fix/451-chart-integrity-alarm-provenance`; PR #452 remains draft only while the
state-only reconciliation and final exact-head revalidation are completed.

Verified product head: `58639a3a19ff7ef13e37d3c2de23adf4b9c3bc02`.

The canonical Chart System now provides:

- cadence-aware render-only source-gap tolerance instead of a fixed 30-second
  assumption, while explicit communication/quality/offline/reconnect gaps remain
  truthful breaks;
- deterministic sample ordering/deduplication, malformed-time rejection and
  stable active segment identities;
- removal of synthetic `Alarm context ...` overlays and alarm pins derived only
  from `TelemetrySample.alarm` across Overview, Live Data and Saved Dashboards;
- source-provenance requirements and stable-ID deduplication for canonical event
  markers;
- collision-safe event rendering without permanent overlapping event labels;
- synchronized Exact Inspector snapshots with nearest measured sample per visible
  series and bounded tolerance;
- presentation-only two-decimal measurement formatting without changing raw
  telemetry;
- independent semantics for latest legend values versus historical cursor
  inspection;
- browser-truthful chart-host pointer handling, including the empty ECharts
  axis-pointer race regression;
- immediate selected WebSocket-tail retention by advancing the Live history
  window to the newest accepted selected sample while preserving the requested
  duration and without triggering a history refetch.

Production verification on exact head `58639a3a...` is GREEN:

- CI / Quality and build: PASS (format, lint, typecheck, full tests, production
  build);
- Authenticated Dashboard Acceptance: PASS, all 13 scenarios, including real
  mouse hover, six-series Exact Inspector, WebSocket `9.876 -> 9.88 degC`, one
  WebSocket and zero acquisition mutations;
- Refrigeration Browser Acceptance: PASS;
- disconnected Offline Bundle: PASS, including clean transferred-host startup,
  blocked container egress, update/rollback and persistent-volume preservation.

Classification: **software/browser/offline verified; Raspberry Pi operator
acceptance pending**. No physical hardware completion is claimed for Issue #451.

## Independent active hardware lane — Issue #289

Issue #289 remains open and `status:in-progress` as the independent controlled
Raspberry Pi/RS-485 acquisition-scale and truthful-state acceptance lane. Issue
#451 does not replace, close or reclassify that hardware work.

The fresh equal-window no-browser baseline and subsequent Overview / Live
Dashboard / navigation / multi-browser matrix still require real Raspberry Pi
hardware evidence. The pre-fix zero-request window remains defect evidence only
and must not be reused as passing performance evidence.

## Next chart Work Package

Issue #453 — equipment-centric multi-metric charts with dynamic Y axes — is
created under Epic #450 and intentionally `status:blocked` until Issue #451 is
merged. It is the next chart-system implementation package after the #451 merge
reconciliation; it must use a separate feature branch and PR.

## Safety boundary

LOCAL_LAN and offline-first runtime requirements remain unchanged. No Modbus
write, hardware write, polling/scheduler mutation, acquisition-registry mutation,
destructive persistent-data action, volume deletion, production/site cutover,
dependency upgrade, secret handling or mandatory public-cloud runtime dependency
is included in Issue #451.
