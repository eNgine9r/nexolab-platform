# Chart P0 frontend release candidate (#1804, #1813)

One consolidated **frontend-only** release candidate for the LAN dashboard and Tailscale HTTPS `:8444`. Both are served by the same same-origin Stage 2 build.

It contains the merged chart work:

- **#1805** — no false breaks on 24 h charts.
- **#1809** — bounded parallel history loading with page retry; no queued 8 s timeouts.
- **#1810** — smooth zoom/pan: one series per channel, no animation, no React rebuild per wheel tick.
- **#1813:**
  - aggregated history with an automatic raw fallback;
  - scale-dependent viewport detail;
  - exact statistics of the visible period.

**Not deployed. Activation needs separate owner approval.** The backend (#1807, #1811, the #1813 server statistics) stays blocked until DR #1428. This candidate does not touch it.

## Compatibility with the running backend

The site backend (`75ceb465`) has no `/api/v1/telemetry/history/aggregate`.

- The candidate probes it once per page load, gets 404, and uses the raw history path for the rest of the page lifetime.
- No other backend contract is used.
- The browser acceptance suite runs this fallback explicitly (forced 404) next to the aggregate path.

## Candidate

| Field           | Value                                                                                                                                                                                                                                                                      |
| --------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Source          | `main` @ `101504919b6dd57e496adc17506cc1d3d1e51b5f` (merge of #1817)                                                                                                                                                                                                       |
| Workflow        | `Frontend Release Artifact`, run `45861263043`                                                                                                                                                                                                                             |
| Build inputs    | `api_base_url=same-origin`, `websocket_url=same-origin`, `auth_provider=local`, organization `00000000-0000-0000-0000-000000000001`, no `external_origin` (same as the live Stage 2 build)                                                                                 |
| Artifact        | `nexolab-frontend-release-101504919b6dd57e496adc17506cc1d3d1e51b5f-arm64`, ZIP SHA-256 `91a1003af2bf85632637f57c32851129bae373f1bd013edbf4511136b5d4b505`, build `DZ6ux7EZK-NU0NhUmnhVr`; contract same-origin/local, `same_origin_browser_bundle=no-absolute-host-origin` |
| Replaces (live) | source `c5bb48a1dad3bf9bf28ca93cf021dbc69515a5b7`, build `xRUAt2U9c3oug1ETWuLsT`                                                                                                                                                                                           |
| Rollback        | the live build above, via `deploy.lan-frontend phase=rollback`                                                                                                                                                                                                             |

## Owner procedure (broker v1.7; nothing else changes)

1. **Archive the Stage 2 workspace** (owner account `nexolab`; nothing is deleted).

   Broker v1.7 refuses `prepare` while the workspace is staged with another artifact. It currently holds the live `c5bb48a1` artifact.

   ```bash
   mv /home/nexolab/commander-workspaces/nexolab-wp2c-stage2 \
      /home/nexolab/commander-workspaces/nexolab-wp2c-stage2-c5bb48a1-archived-$(date -u +%Y%m%dT%H%M%SZ)
   ```

   The new `prepare` derives its rollback configuration from the running dashboard (`c5bb48a1`/`xRUAt2U9…`).

2. **Artifact (done):** `~nexolab-dev/operator-inbox/91a1003af2bf85632637f57c32851129bae373f1bd013edbf4511136b5d4b505.zip`, read-only, SHA-256 verified against the GitHub artifact digest (staging copy: `~nexolab-dev/recovery-p0/chart-rc-1813-20261126T164620Z/`).
3. **Prepare** (stage, offline build, preview on `127.0.0.1:3125`, check; production unchanged):

   ```bash
   sudo python3 -I /usr/local/lib/nexolab-operator/nexolab-operator-broker.py approve --op deploy.lan-frontend \
     --arg phase=prepare --arg artifact_sha256=91a1003af2bf85632637f57c32851129bae373f1bd013edbf4511136b5d4b505 \
     --arg expect_current_source=c5bb48a1dad3bf9bf28ca93cf021dbc69515a5b7 \
     --arg expect_current_build=xRUAt2U9c3oug1ETWuLsT --ttl-minutes 120 --reason "#1813 RC prepare"
   ```

4. **Execute** (switch with automatic verified rollback), only after the preview check is GREEN: the same command with `phase=execute`.
5. **Rollback** if any acceptance step fails: the same command with `phase=rollback`. This restores `c5bb48a1`.

## Browser acceptance on the deployed system (owner, real history)

Run on the LAN address and on Tailscale `https://<node>:8444`. Use one signed-in operator session each.

1. **Live Data, 24 h, 8 and then 24 channels:**
   - the charts appear without "Timeout 8000 ms";
   - no breaks where data is continuous;
   - real gaps and communication errors still show as breaks.
2. **Zoom:**
   - the mouse wheel zooms around the cursor at once;
   - after a short pause the visible window shows the original measurements;
   - peaks stay where they are.
3. **Pan:**
   - drag left and right repeatedly;
   - no flicker, no reset of the zoom;
   - new live values keep arriving while zoomed.
4. **Statistics:** they state the visible period, and min/max/average/count follow the zoom.
5. **"Скинути масштаб"** returns to the full period, and to Live when Live was selected.
6. **Saved Dashboards:** a 24 h dashboard loads, and live values continue without breaks.
7. **Telemetry:** while the charts load, the Overview and Live current values keep updating. History viewing must not delay telemetry.

Report each step as pass or fail. A Raspberry Pi browser or operator-PC FPS figure, if measured, is recorded on #1813.

## Measured performance (CI, headless Chromium, real Compose stack)

- **Scenario:** 24 channels × 24 h at 10 s (≈ 207 000 PostgreSQL rows); 10 wheel zoom steps and 3 drag pans.
- **Spec:** `e2e/chart-performance.production.e2e.ts`.
- **Before:** the identical spec on the pre-#1804 code (`1843d4e5`, closed measurement PR #1818).
- **Runner variance:** CI runner timings vary between runs; ranges come from the final runs.

| Metric                                   |                   Before (pre-#1804) |                                 After, raw fallback (current backend) |                           After, aggregated backend |
| ---------------------------------------- | -----------------------------------: | --------------------------------------------------------------------: | --------------------------------------------------: |
| First chart visible                      | 9.4–9.9 s (16.5 s in an earlier run) |                                                            8.5–12.1 s |                                       **1.4–2.6 s** |
| History requests / transferred           |                        216 / 95.5 MB |                                                         216 / 95.5 MB |                     0.5–0.7 MB (aggregate requests) |
| Ingestion latency while history loads    |                           257–316 ms |                                                            266–423 ms |                                          272–426 ms |
| Frames during zoom/pan                   |                        37.2–37.4 fps |                                                         33.4–40.9 fps |                                       35.7–45.6 fps |
| Long tasks during zoom/pan (total / max) |               2.9–3.3 s / 130–152 ms |                                                 1.8–3.1 s / 99–180 ms |                              1.4–2.2 s / 159–211 ms |
| Viewport detail after zoom               |  none (240 reduced points stretched) | ≈ 3 700–3 900 original-measurement points, ≤ 0.7 s after the last pan | ≈ 3 650–3 800 points, 0.85–2.3 s after the last pan |

### Reading the table

- The large load-time and transfer gain needs the aggregated backend. On the current backend the history volume (216 raw pages) remains, so the 2 s / 3 s / 5 s targets are not met until the #1428-gated backend release.
- Ingestion is not degraded while history loads in any configuration.
- An earlier evidence version reported 9–16 s here. That was a measurement artifact: the probe was polled only after the chart load. It was corrected before these figures.
- The raw-fallback interaction now does more work than before (detail and exact statistics per zoom), with fewer long tasks and lower peaks.
- **Not measured:**
  - the Raspberry Pi browser;
  - an operator PC;
  - 60 fps on real hardware.

  These are UNVERIFIED until the owner acceptance above.
