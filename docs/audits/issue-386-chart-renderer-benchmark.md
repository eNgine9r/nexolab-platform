# Issue #386 — Chart Domain and Renderer Benchmark Audit

Date: 2026-08-11

Repository baseline: `origin/main@1a4ae8026f2b70c52a5fc41a1f8d22a99897463f`

Feature branch: `feat/386-chart-domain-renderer-benchmark`

Tested exact feature SHA: `80ff2ebd3a51398578e90c7fe36c852ce95321b7`. Format, lint, typecheck, 76 files / 336 tests, lint-staged compatibility, and the Next.js production build were rerun successfully on this clean commit before PR publication. The later evidence-only commit records this SHA; GitHub CI is authoritative for the final PR head.

## Decision

ECharts accepted for NEXOLAB production chart renderer.

This acceptance covers the renderer-independent Chart Domain, the direct modular ECharts adapter, deterministic browser fixtures, local/offline bundling, and the tested Raspberry Pi 5 headless-browser lifecycle. The acquisition invariant against a running Device Agent and real Modbus request-rate evidence remains explicitly pending.

## Repository audit

The work started by fetching and fast-forwarding local `main` to the actual `origin/main` above. Issue #386 was moved from `status:ready` to `status:in-progress`; Issue #389 remains open and ready but is not selected. Open pull requests #391–#395 are Dependabot work and are excluded from this branch.

Existing chart/history implementations were inspected before introducing the shared foundation:

| Consumer              | Existing implementation                          | Finding                                                                                                         |
| --------------------- | ------------------------------------------------ | --------------------------------------------------------------------------------------------------------------- |
| Overview              | `temperature-chart.tsx`, route-local SVG         | Invalid points are filtered before path construction and can therefore bridge a truth gap.                      |
| Live Data             | `live-telemetry-explorer.tsx`, `live-history.ts` | Has the strongest existing gap/history reconciliation, but generic last-point bucketing can lose short extrema. |
| Saved Live Dashboards | Route-local SVG polylines                        | Separate rendering path with weaker explicit continuity semantics.                                              |
| Energy Monitoring     | Route-local SVG plus energy history helpers      | Has distinct cumulative/instantaneous semantics that must remain separate.                                      |
| Test Sessions         | Route-local SVG polyline                         | Filtering missing data does not provide the canonical continuity contract.                                      |
| Reports               | Rendered report/artifact UI                      | No reusable interactive client chart foundation.                                                                |
| Refrigeration history | Structural layout revision history               | Not a telemetry plot; no production migration belongs in #386.                                                  |
| Sparklines            | Compact numeric SVG trend                        | A visual cue, not an evidence-grade interval chart.                                                             |

No production page was migrated in this work package.

## Canonical domain evidence

The shared domain keeps these concepts separate:

- stable series identity: node, equipment, channel, metric, and native unit;
- numeric chart points using the existing NEXOLAB quality vocabulary: `valid`, `sensor_error`, `communication_error`, and `unknown`;
- delivery/freshness state: live, stale, reconnecting, and offline;
- explicit continuity breaks and independent continuous segments;
- full-window statistics with an explicit scope, separate from visualization reduction;
- deterministic native-unit/physical-quantity plot groups with no implicit conversion;
- renderer lifecycle, cursor, x-domain, live-tail, resize, reset, and disposal contracts.

`null`, missing, non-finite, invalid-quality, offline, reconnect, explicit communication-gap, and over-threshold source-gap samples cannot become renderable zeroes or an uninterrupted line. The ECharts adapter emits one line series per continuity segment with `smooth: false` and `connectNulls: false`.

The segment-aware reducer preserves segment first/last points, bucket minima/maxima in chronological order, boundary context, threshold-crossing context, and alarm/event pins. It never crosses segments or synthesizes measurements. If mandatory evidence cannot fit the requested bound, it fails explicitly instead of silently discarding evidence.

## Renderer candidate and dependency audit

- Candidate: Apache ECharts `6.1.0`, exact npm version.
- Direct modular imports: `echarts/core`, `echarts/charts`, `echarts/components`, and `echarts/renderers`.
- Registered modules: line chart; ARIA, data zoom, grid, legend, mark area, mark line, and tooltip components; Canvas and SVG renderers.
- Interactive default: Canvas.
- React wrapper: none.
- CDN/runtime import: none.
- Lockfile additions: ECharts `6.1.0`, zrender `6.1.0`, and ECharts' nested tslib `2.3.0`.
- Manifest delta: one production dependency; no unrelated upgrades.
- Uncompressed installed sizes observed: ECharts 60,336,735 bytes and zrender 4,340,420 bytes.
- Production vulnerability audit: no advisory was attributed to ECharts, zrender, or their new tslib entry. Existing advisories remain in `nanoid` (high) and Next.js/PostCSS (moderate); upgrading them is outside #386.

The application-facing barrel deliberately does not export ECharts or benchmark fixtures. Consumers must opt into the heavy renderer adapter explicitly, preventing unrelated client chunks from acquiring the renderer by importing lightweight domain contracts.

## Benchmark environment

- Host: Raspberry Pi 5 Model B Rev 1.1, aarch64/arm64.
- Host OS/runtime: Debian 13.6, kernel `6.18.39+rpt-rpi-2712`, Docker Engine `29.7.1`.
- Node/build image: `node:22.23.1-bookworm`, image digest `sha256:5647dad78b713290296686efbcca442c06858b843a426fa4024bf94d629fd5bb`.
- Browser image: `mcr.microsoft.com/playwright:v1.62.0-noble`, image digest `sha256:baed2032d533817f3dbe6425de795788430ba345e819a1201337009ba17c9d07`.
- Browser: Headless Chrome `151.0.7922.34` in an arm64 Playwright image. The Chrome Linux user-agent compatibility token says `x86_64`; the benchmark runtime and inspected image both report `arm64`.
- Renderer: ECharts Canvas.
- Data: deterministic local fixtures; no live equipment or network telemetry.
- Network mode: Docker `--network none`; the browser and local preview server shared only the container loopback interface.
- Measurements use browser `performance.now()`. Memory uses forced-GC heap observations and is a trend signal, not a leak proof.

## Deterministic scenarios

| Scenario | Coverage                                                  |
| -------- | --------------------------------------------------------- |
| A        | 1 series × 240 rendered points                            |
| B        | 8 series × 240 rendered points                            |
| C        | Three synchronized compatible-unit plot groups            |
| D        | Explicit communication/data gap rendered as two segments  |
| E        | Short extrema inside reduction buckets                    |
| F        | Threshold crossing and alarm-pinned evidence              |
| G        | 100 incremental live-tail updates                         |
| H        | Five resize widths without reload                         |
| I        | Ten dispose/reinitialize cycles                           |
| J        | 360, 1280, 1440, and 1920 px viewports                    |
| K        | 1,000-update bounded live loop                            |
| L        | Production bundle with public network blocked and audited |

## Measurements

These are the measured results from the deterministic arm64 headless-browser run on the controlled Raspberry Pi 5 host. They isolate renderer work from backend/network latency and do not prove the physical acquisition invariant.

| Operation                 | Samples |   Median |  p95 / maximum | Additional evidence                                           |
| ------------------------- | ------: | -------: | -------------: | ------------------------------------------------------------- |
| Initial render, 1×240     |      10 |  38.9 ms |        66.1 ms | One renderer instance                                         |
| Initial render, 8×240     |      10 | 103.8 ms |       169.0 ms | Passes the ≤250 ms Raspberry Pi p95 target                    |
| Three synchronized groups |       1 | 146.3 ms |       146.3 ms | Shared time domain                                            |
| Gap/extrema scene         |       1 |  65.7 ms |        65.7 ms | 1,200 source → 240 rendered; two segments; exact max retained |
| Incremental append        |     100 |  12.3 ms | 31.2 / 59.1 ms | Passes the ≤100 ms p95 target; one renderer; bounded at 240   |
| Resize                    |       5 |  70.9 ms |        82.8 ms | No page reload                                                |
| Dispose/reinitialize      |      10 | 105.2 ms |       134.7 ms | One active instance after each cycle                          |
| Long-lived append loop    |   1,000 |   6.1 ms | 12.7 / 33.9 ms | One renderer; window bounded at 240                           |

For the gap/extrema fixture, the exact source and reduced maxima both measured `8.496204670435898`.

Forced-GC heap used before the long loop was 10,948,216 bytes and after was 7,998,132 bytes, a -2,950,084-byte observation. The bounded point count, stable renderer count, handler cleanup tests, and remount test provide lifecycle evidence; this single heap observation does not prove the absence of all browser-engine caching or leaks.

## Bundle evidence

The isolated production build emitted:

| Bundle                          |      Minified |          Gzip |
| ------------------------------- | ------------: | ------------: |
| Renderer benchmark JavaScript   | 612,576 bytes | 204,726 bytes |
| Domain-only baseline JavaScript |   3,953 bytes |   1,799 bytes |
| Renderer delta                  | 608,623 bytes | 202,927 bytes |

Vite warned that the renderer chunk exceeds 500 kB minified. This is accepted for the isolated benchmark but remains a production-consumer risk to control through explicit/lazy renderer loading when the first route migrates.

## Responsive and accessibility evidence

At 360, 1280, 1440, and 1920 px, document `scrollWidth` equaled `clientWidth`; each viewport retained eight legend buttons and one Canvas plot. Resize completed without a reload.

The shell exposes keyboard-operable legend controls, show/hide and solo semantics, visible keyboard focus, explicit textual freshness and quality, a screen-reader summary, exact timestamp/value inspection, and a reduced-motion-safe renderer mode. State is reinforced through text, dash styles, marker shapes, and pinned markers rather than color alone.

Known accessibility limitation: the benchmark did not observe a native ARIA label on the ECharts Canvas element. The NEXOLAB shell therefore owns the accessible summary, controls, and inspector equivalent. This must be retained and rechecked during the Live Data migration.

## Offline and public-network evidence

The browser scenario aborted any public request and recorded only three local requests: the harness HTML, local JavaScript, and local CSS from `127.0.0.1`. Public request count was zero. No CDN, remote font, analytics, telemetry SaaS, cloud visualization, or external licensing request was required.

The adapter contains no telemetry transport, acquisition, registry, scheduler, Modbus, authorization, persistence, or freshness-calculation code. The deterministic benchmark performed no REST/WebSocket request, hardware write, or Modbus write. Real-hardware verification that browser count and interaction cannot affect acquisition cadence remains pending.

## Local software gates

Focused chart tests cover continuity, all specified reducer cases, unit grouping, statistics scope, annotations, show/hide filtering, adapter persistence/reconnect/cursor/zoom/disposal, component lifecycle, and accessible legend interaction. The focused run completed 8 files and 34 tests successfully.

The local required gate completed with format, lint, typecheck, 76 test files / 336 tests, lint-staged compatibility, and the Next.js production build all GREEN. Existing unrelated React test warnings were printed by refrigeration/dashboard tests, but no test failed. The repository Offline Bundle job and other exact-head CI results remain pending PR publication; no unexecuted CI gate is claimed here.

## Known limitations and remaining acceptance

- The physical acquisition invariant is supported by the dependency boundary but is not verified against real Device Agent/Modbus hardware in this benchmark.
- Canvas-native accessibility is insufficient on its own; the shared shell fallback is required.
- The roughly 198 KiB gzip renderer delta warrants route-level lazy loading during the first production migration.
- Production route migrations, controls, backend contracts, polling, telemetry schemas, and hardware behavior are intentionally outside #386.

Completion classification: **software verified; Raspberry Pi chart performance verified; acquisition-invariant acceptance pending**.
