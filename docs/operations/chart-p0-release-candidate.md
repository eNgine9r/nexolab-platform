# Chart P0 frontend release candidate (#1804, #1813, #1821, #1824, #1825, #1827, #1829)

One consolidated **frontend-only** release candidate for the LAN dashboard and Tailscale HTTPS `:8444`. Both are served by the same same-origin Stage 2 build. It supersedes the earlier candidate `91a1003a…` (source `10150491`).

It contains the merged chart work:

- **#1805** — no false breaks on 24 h charts.
- **#1809** — bounded parallel history loading with page retry; no queued 8 s timeouts.
- **#1810** — smooth zoom/pan: one series per channel, no animation, no React rebuild per wheel tick.
- **#1813** — Live Data: aggregated history with an automatic raw fallback, viewport detail, exact statistics of the visible period.
- **#1821** — Saved Dashboards: viewport detail (original measurements after a zoom) and cached exact statistics.
- **#1824** — progressive loading: series complete in order and Live Data / Saved Dashboards show them as they load ("N з M").
- **#1825** — Energy: raw statistics no longer O(n²) on history load.
- **#1827** — Overview: no raw re-sort per live sample, no rebuild per zoom, viewport detail.
- **#1829** — Refrigeration: lanes built once per history, clipped per zoom.

**Not deployed. Activation needs the owner approvals below.** The backend (#1807, #1811, the #1813 server statistics) stays blocked until DR #1428. This candidate does not touch it.

## Compatibility with the running backend

The site backend (`75ceb465`) has no `/api/v1/telemetry/history/aggregate`.

- Live Data probes it once per page load, gets 404, and uses the raw history path for the rest of the page lifetime.
- Saved Dashboards, Overview, Energy and Refrigeration use the raw history API as before.
- No other backend contract is used. The browser acceptance suite runs the raw path explicitly (forced 404) next to the aggregate path.

## Candidate

| Field           | Value                                                                                                                                                                                                                                                                                                                                                |
| --------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Source          | `main` @ `f3c12ac4ebe7d5ef118f842af15d92d17ef0e8d5` (merge of #1831)                                                                                                                                                                                                                                                                                 |
| Workflow        | `Frontend Release Artifact`, run `45883419993`                                                                                                                                                                                                                                                                                                       |
| Build inputs    | `api_base_url=same-origin`, `websocket_url=same-origin`, `auth_provider=local`, organization `00000000-0000-0000-0000-000000000001`, no `external_origin` (same as the live Stage 2 build)                                                                                                                                                           |
| Artifact        | `nexolab-frontend-release-f3c12ac4ebe7d5ef118f842af15d92d17ef0e8d5-arm64`, ZIP SHA-256 `c10c1f87ee0ae83288bed82ba9d38d5172aa2848f9d61dd792a80486041248ce` (= GitHub digest; 12/12 internal checksums), build `14UxZmS8dvkAlrpEYt1xV`; contract same-origin/local, `same_origin_browser_bundle=no-absolute-host-origin`, `external_https_stage=false` |
| Replaces (live) | source `c5bb48a1dad3bf9bf28ca93cf021dbc69515a5b7`, build `xRUAt2U9c3oug1ETWuLsT`                                                                                                                                                                                                                                                                     |
| Rollback        | the live build above, via `deploy.lan-frontend phase=rollback`                                                                                                                                                                                                                                                                                       |

## Owner approval package (one session; broker v1.7, nothing else changes)

The agent cannot approve or run privileged steps itself. One owner session covers the whole release:

1. **Archive the Stage 2 workspace** (owner account `nexolab`; nothing is deleted). Broker v1.7 refuses `prepare` while the workspace holds another artifact (it holds the live `c5bb48a1` one):

   ```bash
   mv /home/nexolab/commander-workspaces/nexolab-wp2c-stage2 \
      /home/nexolab/commander-workspaces/nexolab-wp2c-stage2-c5bb48a1-archived-$(date -u +%Y%m%dT%H%M%SZ)
   ```

2. **Approve prepare, execute and rollback at once** (each prints one `approval_id`; an approval only records consent and runs nothing; unused approvals expire after 12 h):

   ```bash
   for phase in prepare execute rollback; do
     sudo python3 -I /usr/local/lib/nexolab-operator/nexolab-operator-broker.py approve --op deploy.lan-frontend \
       --arg phase=$phase --arg artifact_sha256=c10c1f87ee0ae83288bed82ba9d38d5172aa2848f9d61dd792a80486041248ce \
       --arg expect_current_source=c5bb48a1dad3bf9bf28ca93cf021dbc69515a5b7 \
       --arg expect_current_build=xRUAt2U9c3oug1ETWuLsT --ttl-minutes 720 --reason "P0 charts RC f3c12ac4 $phase"
   done
   ```

3. **Give the three `approval_id`s to the agent.** The agent then runs, each once and with exactly the approved arguments:
   - `prepare`: stage, offline build, preview on `127.0.0.1:3125`, check. Complete only with `STAGE2_CHECK_PASS`, and the live dashboard must still report `c5bb48a1`/`xRUAt2U9…`.
   - `execute`: only after a passing prepare. Switch with automatic verified rollback; complete only on `STAGE2_FRONTEND_GREEN`. The agent then verifies the new identity `f3c12ac4`/`14UxZmS8dvkAlrpEYt1xV` on the LAN gateway and on Tailscale `:8444`, API and WebSocket, telemetry continuity and system resources.
   - `rollback`: only if an acceptance step fails. Recovery is complete only on `STAGE2_ROLLED_BACK_VERIFIED`, with `c5bb48a1`/`xRUAt2U9…` confirmed on the LAN gateway and on `:8444`. If it is not needed, the approval expires unused.

The artifact is already in `~nexolab-dev/operator-inbox/c10c1f87ee0ae83288bed82ba9d38d5172aa2848f9d61dd792a80486041248ce.zip` (read-only, SHA-256 verified against the GitHub artifact digest).

**HTTPS `:443` (OAuth Funnel, `:3105`, source `7db6e1a8`)** is a separate frontend with no broker operation. It stays unchanged by this release. Updating it needs a second artifact built with the Funnel origin and the owner's guarded HTTPS procedure. That is optional and not part of this package.

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
8. **Progressive loading:** with many channels, the first ones appear within a few seconds, with "Завантажено … з …". The rest follow, and the statistics appear once all are loaded.
9. **Overview (24 h):**
   - the page stays responsive while values arrive;
   - after a zoom, the visible window shows detailed measurements;
   - peaks stay where they are.
10. **Energy (7 d) and Refrigeration (24 h):**
    - the history loads without the page freezing;
    - zoom and pan on the Refrigeration lanes respond at once.

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

### Progressive loading and Saved Dashboards (#1821, #1824; same spec, run 45880829330)

| Metric (24 series × 24 h, current backend, raw) |             Live Data | Saved Dashboard before (main `5aada27a`) |                 Saved Dashboard after |
| ----------------------------------------------- | --------------------: | ---------------------------------------: | ------------------------------------: |
| First series visible                            |            **1.96 s** |    11.4 s (nothing before the full load) |                            **1.49 s** |
| Complete window                                 |                 9.7 s |                                   11.4 s |                                 8.6 s |
| Frames during zoom/pan                          |              40.5 fps |                                 57.9 fps |                             57–59 fps |
| Long tasks during zoom/pan                      |    1.8 s / max 101 ms |                                     none |                                  none |
| Viewport detail after zoom                      | ≈ 3 700 points, 0.7 s |                                     none | ≈ 3 900 original measurements, 0.63 s |

### Overview, Energy and Refrigeration (#1825, #1827, #1829; Raspberry Pi 5 CPU, Node, 24 h at 10 s)

| Work                                                 |            Before |                                       After |
| ---------------------------------------------------- | ----------------: | ------------------------------------------: |
| Overview, 8 probes: apply one live sample to history | 401 ms per sample | 48 ms per flush (1 s up to 6 h, 5 s beyond) |
| Overview: rebuild series                             | 911 ms per sample |                           ~400 ms per flush |
| Overview: zoom/pan commit                            |            911 ms |                 17 ms, with viewport detail |
| Energy, one meter: raw statistics on a 7 d load      |          2 331 ms |                                      145 ms |
| Refrigeration: lanes per zoom commit                 |        336–380 ms |                      interval clipping only |

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
