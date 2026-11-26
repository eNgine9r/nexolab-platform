# Chart P0 performance and reliability — baseline (#1804)

Product Owner P0 addendum to #1638 (2026-11-26). Operators report:

- slow loading;
- breaks on 24 h charts;
- unstable zoom;
- stuttering pan;
- `Timeout 8000 ms` on standard and custom ranges.

This file records the **measured** baseline and the root causes. Each fix in the leaf PRs is measured against it.

## Method

- Repository code (`src/features/live/live-history.ts`, `src/lib/telemetry/history.ts`) executed directly with Node 22.23.1 on the Raspberry Pi 5 development account (1 CPU, cgroup-limited). Node uses the same V8 engine family as Chromium. These are client-CPU costs only.
- Synthetic channel:
  - 10 s cadence, the standard preset;
  - smooth drift, an 8 °C excursion every ~4 h, deterministic noise;
  - no missing samples.
- History is served by a fake adapter. It builds each page and parses it with `JSON.parse`, as the browser does, with **zero** network and server latency. The server-side cost is measured separately in PostgreSQL CI (L4).
- **Not measured here:**
  - browser rendering and FPS on the Pi or an operator PC (no browser on the dev account);
  - production PostgreSQL rows and query plans (production database access is not permitted).

## 1. Breaks on 24 h charts (display defect, data present)

| Step                               | Segments | Single-point segments |
| ---------------------------------- | -------: | --------------------: |
| 24 h history reduced to 240 points |        1 |                     0 |
| after 10 min in Live               |  **114** |                **40** |
| after 60 min in Live               |      113 |                    37 |

**Root cause:** `mergeLiveHistoryTail` re-ran the full downsampler on already-reduced points plus raw live points on every sample and on every 5 s clock tick. `annotateSourceSegments` then re-derived the gap tolerance (`median Δt × 3`) from that mix: reduced points are minutes apart, live points 10 s apart. Every reduced gap became a false "source gap".

Saved Dashboards have the same live-tail path. They also re-segmented reduced points in `buildChartSegments` (30 s cadence / 6 h: 14 false segments on continuous data).

**After the fix (#1805):**

- 1 segment through 60 min of live tail and clock ticks;
- the excursion is still plotted;
- merge 1.82 → 1.04 ms per call.

A real silent gap and an invalid sample still break the line (regression tests).

## 2. Slow loading — history pipeline cost (client CPU only)

History is fetched as raw 1000-row pages, **sequentially per channel**. Every raw sample is held in the browser before reduction to about 240 points per channel.

| Channels × period | Raw / channel | Requests (sequential) | JSON transferred |                     Client CPU |   Heap |
| ----------------- | ------------: | --------------------: | ---------------: | -----------------------------: | -----: |
| 1 × 1 h           |           361 |                     1 |           0.1 MB |                         0.07 s |   9 MB |
| 1 × 24 h          |         8 641 |                     9 |           2.3 MB |                         0.42 s |  15 MB |
| 8 × 1 h           |           361 |                     8 |           0.8 MB |                         0.11 s |  10 MB |
| 8 × 6 h           |         2 161 |                    24 |           4.6 MB |                         0.66 s |  17 MB |
| 8 × 12 h          |         4 321 |                    40 |           9.2 MB |                         1.35 s |  24 MB |
| 8 × 24 h          |         8 641 |                    72 |          18.5 MB |                         2.19 s |  32 MB |
| 24 × 24 h         |         8 641 |                   216 |          55.8 MB |                         6.25 s |  82 MB |
| 1 × 7 d           |        60 481 |                    61 |          16.2 MB |                         2.28 s |  44 MB |
| 8 × 7 d           |        60 481 |                   488 |         129.9 MB |                         15.1 s | 178 MB |
| 1 × 30 d          |       259 201 |                   260 |          69.8 MB | **crash** → 12.0 s after #1805 | 115 MB |

- **30-day crash:** `RangeError: Maximum call stack size exceeded` at `allSamples.push(...result.samples)` (259 201 spread arguments). Fixed in #1805 (`concat`).
- Server time per page is added to every sequential request above. At 100 ms per page, 8 × 24 h adds about 7 s and 8 × 7 d about 49 s.
- The 3 s (7 d) and 5 s (30 d) targets therefore cannot be met by shipping raw rows. Server-side, extremum-preserving aggregation is required (L4).

## 3. `Timeout 8000 ms`

`src/lib/telemetry/rest-client.ts` aborts **each** request after 8 s. A timeout therefore means that one `/history` page (≤ 1 000 rows) took more than 8 s on the server. Code findings in `services/telemetry-service/app/db.py` `history_snapshot_samples`:

- **Snapshot lock held for the whole query.**
  - The first page of every channel takes the **exclusive** `pg_advisory_xact_lock(263000001)` and keeps it while the history `SELECT` runs.
  - Every telemetry insert takes the same lock **shared**. A slow history page therefore stalls ingestion, and concurrent first pages (several charts or dashboards) run strictly one after another.
  - Energy export (`energy_export/source.py` `establish_snapshot`) shows the correct pattern: fix the snapshot in a short transaction, then query without the lock.
- **One query per page, ordered `captured_at DESC, event_id DESC LIMIT 1001`**, with filters on node, equipment, channel, metric and `received_at`. The plan choice between `ix_telemetry_history_lookup` and `ix_telemetry_metric_captured` decides whether a sparse channel or a custom range scans far more rows than it returns. It is measured on PostgreSQL 16 in CI (L4) because production `EXPLAIN` is not available to the agent.
- **No cancellation of superseded loads across pages for every surface, and no retry state that distinguishes a timeout:** covered in L2.

Raising the timeout is explicitly **not** the fix.

## 4. Zoom/pan jank (code evidence)

- Each wheel or drag step goes through React:
  - `onXDomainChange` → `setViewportDomain`;
  - all chart groups are rebuilt;
  - `setScene` → `setOption(replaceMerge: ["series", "yAxis"])` on every panel.

  The data does not change; only the viewport does.

- Animation is on (`animation: !reducedMotion`). Every update therefore tweens for about 300 ms, which shows as flicker and lag.
- The renderer creates **one ECharts series per continuity segment**. With the false breaks above, that is more than 100 series per channel.
- On zoom, the reduced 240 points are stretched; no viewport detail is loaded.

## Decision

- **Keep ECharts.** The measured bottlenecks are data transfer, repeated reduction and the React round trip. #1620 measured ≈ 33 ms + 15 ms per 1 000 points for an initial render.
- Web Workers and WebGL are deferred until the after-fix measurements show that main-thread work is still the bottleneck.
