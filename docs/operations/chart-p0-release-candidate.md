# Chart P0 consolidated frontend release (all interfaces)

One consolidated **frontend-only** release of the modernised charts for every operator interface. It is built from one source and ships as two artifacts:

| Interface                             | Served by                                                        | Artifact              | How it is switched                    |
| ------------------------------------- | ---------------------------------------------------------------- | --------------------- | ------------------------------------- |
| LAN (`http://192.168.1.220`, gateway) | Stage 2 dashboard container                                      | LAN (same-origin)     | Operator Broker `deploy.lan-frontend` |
| Tailscale `:8444`                     | the same Stage 2 container                                       | LAN (same-origin)     | the same broker operation             |
| Tailscale `:8443`                     | routed to the LAN gateway (#1784)                                | LAN (same-origin)     | the same broker operation             |
| Main HTTPS `:443` (Funnel, OAuth)     | user unit `nexolab-external-ui-1569.service` on `127.0.0.1:3105` | HTTPS (Funnel origin) | owner-run guarded tool (#1837)        |

**Deployed on 2026-11-27 to LAN, Tailscale `:8443` and `:8444`** (see *Deployment record*). The main HTTPS `:443` is pending the owner-run tool step. The backend stays unchanged and is gated by DR #1428.

## What the release contains

- **#1805:** no false breaks on 24 h charts.
- **#1809:** bounded parallel history loading with page retry; no queued 8 s timeouts.
- **#1810:** smooth zoom and pan. There is one series per channel, no animation and no React rebuild per wheel tick.
- **#1813:** Live Data uses aggregated history with an automatic raw fallback, viewport detail and exact statistics of the visible period.
- **#1821:** Saved Dashboards get viewport detail and cached exact statistics.
- **#1824:** progressive loading. Series complete in order and appear as they load.
- **#1825:** the Energy raw statistics are no longer O(n²).
- **#1827:** Overview no longer re-sorts raw history per live sample or rebuilds per zoom.
- **#1829:** the Refrigeration lanes are built once and clipped per zoom.
- **#1833:** 7 d and 30 d history.
  - Loading uses time slices with bounded parallelism, page retry, a page limit per slice and cancellation.
  - A raw row budget gives an explicit message instead of a partial or minute-long load.
  - Overview history is kept as compact RAW columns.
- **#1835:** Saved Dashboards use aggregated history with raw fallback.
  - Exact server statistics share one range for all rows.
  - Viewport detail comes from one cancellable request.
- **#1839:** a Live Data chart build drops from ~430 ms to ~17 ms on the Pi CPU, giving smooth zoom and pan.
- **#1837:** the guarded release tool for the HTTPS frontend.

## Compatibility with the running backend

The site backend (`75ceb465`) has no `/api/v1/telemetry/history/aggregate`.

- Live Data and Saved Dashboards probe it once per page and get 404. They then use raw history for the rest of the page.
- Overview, Energy and Refrigeration use raw history.
- No other backend contract is used.
- On the current backend, a window whose raw volume exceeds the safe budget (500 000 rows) stops at once with an explicit message. For example, 24 channels over 30 days would. Such windows need the aggregated backend after DR #1428.
- The budget also protects ingestion, because the production backend does not yet have the #1807 history pool.

## Candidate

| Field          | Value                                                                                                                                                                    |
| -------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Source         | `main` @ `210b478bed76d5a7cdbe7c5398cebb3d0091224f`                                                                                                                      |
| Workflow       | `Frontend Release Artifact`, run `45900869530`                                                                                                                           |
| LAN artifact   | ZIP SHA-256 `9df9592e12f00acab4f33f9b354495ad5a6b57b5f2d5075c009b00275f1578b5`, build `nCkLRk-U9EkiJ3PmhdBuA`, contract same-origin/local, `external_https_stage=false`  |
| HTTPS artifact | ZIP SHA-256 `b26a73c788d6b5e95314490499aa422c6e977db4d79767f8db230e8a794a3b70`, build `EyZllf1uoZnxieohz2NxC`, contract Funnel origin/local, `external_https_stage=true` |
| Verification   | Both ZIPs equal the GitHub digests. All internal checksums pass, and both public contracts are `PASS`.                                                                   |
| Staged         | `~nexolab-dev/operator-inbox/<sha256>.zip` (read-only)                                                                                                                   |
| Replaces       | LAN/`:8443`/`:8444`: `c5bb48a1…` / `xRUAt2U9c3oug1ETWuLsT`. `:443`: `7db6e1a8…` / `fLvuDhT8Ol-bCkGGhHBI4`.                                                               |
| Rollback       | LAN: `deploy.lan-frontend phase=rollback` to `c5bb48a1`. `:443`: the tool's automatic rollback, or `rollback` to `7db6e1a8`. Previous releases and images are kept.      |

## Disk

About 22.1 GiB is free before the release, and the reserve is 20 GiB.

| Item                        |       Size |
| --------------------------- | ---------: |
| The HTTPS release directory | ≈ 0.58 GiB |
| The LAN image build         |  ≈ 0.6 GiB |
| The two staged ZIPs         | ≈ 0.43 GiB |

Both tools refuse to go below 20 GiB. Nothing existing is deleted.

## Owner package (one session)

Run on the Pi as the owner. Every privileged step is here; the agent does the rest.

```bash
# 1. Archive the Stage 2 workspace (nothing is deleted; broker v1.7 refuses prepare otherwise).
mv /home/nexolab/commander-workspaces/nexolab-wp2c-stage2 \
   /home/nexolab/commander-workspaces/nexolab-wp2c-stage2-c5bb48a1-archived-$(date -u +%Y%m%dT%H%M%SZ)

# 2. LAN / :8443 / :8444 - one-time approvals for prepare, execute and rollback (12 h; unused ones expire).
for phase in prepare execute rollback; do
  sudo python3 -I /usr/local/lib/nexolab-operator/nexolab-operator-broker.py approve --op deploy.lan-frontend \
    --arg phase=$phase --arg artifact_sha256=9df9592e12f00acab4f33f9b354495ad5a6b57b5f2d5075c009b00275f1578b5 \
    --arg expect_current_source=c5bb48a1dad3bf9bf28ca93cf021dbc69515a5b7 \
    --arg expect_current_build=xRUAt2U9c3oug1ETWuLsT --ttl-minutes 720 --reason "P0 charts final $phase"
done

# 3. :443 - install the reviewed tool root-owned, check its SHA-256, then plan, prepare and execute.
sudo install -o root -g root -m 0755 \
  /home/nexolab-dev/nexolab-platform/docs/operations/https-frontend-release/nexolab-https-frontend-release.py \
  /usr/local/lib/nexolab-operator/nexolab-https-frontend-release.py
sha256sum /usr/local/lib/nexolab-operator/nexolab-https-frontend-release.py   # must be 9e38bbe58b497e82420e3f6f06dd14e47a5040e03d634ee0e43663bb3c79745f
H=(--artifact /home/nexolab-dev/operator-inbox/b26a73c788d6b5e95314490499aa422c6e977db4d79767f8db230e8a794a3b70.zip --expect-zip-sha256 b26a73c788d6b5e95314490499aa422c6e977db4d79767f8db230e8a794a3b70
   --expect-source 210b478bed76d5a7cdbe7c5398cebb3d0091224f --expect-build EyZllf1uoZnxieohz2NxC)
sudo python3 -I /usr/local/lib/nexolab-operator/nexolab-https-frontend-release.py plan "${H[@]}" &&
sudo python3 -I /usr/local/lib/nexolab-operator/nexolab-https-frontend-release.py prepare "${H[@]}" &&
sudo python3 -I /usr/local/lib/nexolab-operator/nexolab-https-frontend-release.py execute "${H[@]}" \
  --expect-current-source 7db6e1a801aa6c1a142febd4e91c79eef62d5beb --expect-current-build fLvuDhT8Ol-bCkGGhHBI4
```

Send the agent the three `approval_id`s and the output of step 3.

- **Step 3** ends with `HTTPS_FRONTEND_GREEN`.
  - On any failure it removes its drop-in itself and prints `HTTPS_FRONTEND_ROLLED_BACK_VERIFIED`.
  - `plan` and `prepare` change nothing live.
- **The agent then runs each LAN phase once, with exactly the approved arguments:**
  - `prepare` must print `STAGE2_CHECK_PASS`, with the live identity unchanged;
  - `execute` must print `STAGE2_FRONTEND_GREEN`;
  - `rollback` runs only if an acceptance step fails.

After the switch, the agent verifies:

- the identities on the LAN gateway, `:8443`, `:8444` and `127.0.0.1:3105`;
- the anonymous OAuth `302` on `:443`;
- the API and WebSocket;
- telemetry continuity and ingestion lag;
- memory and disk.

An HTTPS rollback later needs one owner command: `sudo python3 -I /usr/local/lib/nexolab-operator/nexolab-https-frontend-release.py rollback`.

## Deployment record (2026-11-27)

### Blockers found after the 00:11 reboot, and how they were resolved

- **`:443` answered `503 Authentication unavailable`.**
  - Chain: Funnel `:443` → the loopback gateway `:18790` → the oauth2-proxy system unit `nexolab-google-oauth-stage.service` (`127.0.0.1:4180`) → `:3105`.
  - The oauth2-proxy unit is static (no `[Install]`). It had been started by hand, so it did not start after the reboot. Nothing listened on 4180, and `/oauth2/start` answered 502.
  - The Operator Broker can neither read nor start that unit.
  - **Fix (owner):** `systemctl start` of the same unit with the same configuration, so authentication is unchanged. The owner also added `systemctl add-wants multi-user.target`, so the unit now starts at boot. Result: the gateway and the public `:443` answer 302.
- **Disk.** The LAN build needs free space of at least the 20 GiB reserve plus 3 GiB; 22.23 GiB was free.
  - The owner approved `storage.cleanup-regenerable build_cache=all-unused`. It removed only the unused Docker build cache and trimmed the journal to 200M.
  - Result: 22.23 → 25.53 GiB free. Volumes are unchanged, the 18 in-use images were kept, and the rollback artifact `f916352c…` (`c5bb48a1`) was kept.
- **Which service owns `:3105`.** The user unit `nexolab-external-ui-1569.service` of `nexolab` (cgroup `user@1000.service/app.slice`) serves `7db6e1a8` / `fLvuDhT8Ol-bCkGGhHBI4`. That is the unit the HTTPS tool controls.
  - The system unit `nexolab-external-ui-1560.service` serves `:3104` (`lab.nexolab`, `08f1c8a4`) and is not part of this release.

### LAN, `:8443` and `:8444`: deployed

| Step | Result |
| --- | --- |
| `prepare` | `STAGE_VERIFIED` source `210b478b`, build `nCkLRk-U9EkiJ3PmhdBuA` (17 630 runtime files). The image was compared file by file with the artifact. `STAGE2_CHECK_PASS NO_WRITES`, and the live identity was unchanged. |
| `execute` | `ROLLBACK_IDENTITY_VERIFIED c5bb48a1dad3 xRUAt2U9c3oug1ETWuLsT`, `STAGE2_PREFLIGHT_PASS`, `STAGE2_FRONTEND_GREEN` |
| Identities | The LAN gateway, `:8443` and `:8444` report `210b478b` / `nCkLRk-U9EkiJ3PmhdBuA`. `:3105` is unchanged (`7db6e1a8`). |
| Routes | `/`, `/live`, `/energy` and `/refrigeration` answer 200 on all three interfaces. All 23 referenced static chunks answer 200 on each interface. |
| API and WebSocket | On the LAN and `:8443`, `/api/v1/telemetry/latest` without a token answers 401 (authentication is enforced). `/api/v1/telemetry/live` answers the WebSocket upgrade with 101. On `:8444`, `/api` answers 404, as before: that port serves the dashboard container directly, and `:8443` is the API path. |
| Telemetry | Database and MQTT were ready throughout. Ingestion lag was 0.08–0.42 s, `last_persisted_at` kept advancing and the queue stayed at 0, before and after the switch. |
| Rollback | It was not needed. The `phase=rollback` approval stays unused and expires after 12 h. |

### Main HTTPS `:443`: pending the owner-run tool

The preconditions hold: the OAuth gate answers 302, and `:3105` = unit 1569 at `7db6e1a8` / `fLvuDhT8Ol-bCkGGhHBI4`. The remaining step is the tool step of the owner package above (install, SHA-256 `9e38bbe5…`, then `plan` → `prepare` → `execute`). The disk is sufficient: the tool needs at least 20 GiB free after the ~0.58 GiB release.

## Browser acceptance on the deployed system (owner, real history)

Run on the LAN address, on Tailscale `:8443`/`:8444` and on the main HTTPS link after the Google sign-in.

1. **Live Data, 24 h, 8 and then 24 channels:**
   - the first channels appear within a few seconds ("Завантажено … з …");
   - there is no "Timeout 8000 ms";
   - there are no breaks where data is continuous;
   - real gaps and communication errors still show as breaks.
2. **Zoom and pan:**
   - the mouse wheel zooms around the cursor at once;
   - after a short pause the visible window shows the original measurements;
   - peaks stay where they are;
   - there is no flicker and the zoom does not reset;
   - new values keep arriving.
3. **Statistics:** they state their period, and min/max/average/count follow the zoom.
4. **"Скинути масштаб"** returns to the full period, and to Live when Live was selected.
5. **Saved Dashboards:** a 24 h dashboard loads, series appear progressively, zoom shows detail, and live values continue without breaks.
6. **Overview, 24 h and 7 d:**
   - the page stays responsive while values arrive;
   - zoom shows detail;
   - a channel with only failed polls is still listed.
7. **Energy (7 d) and Refrigeration (24 h / 7 d):**
   - the history loads without freezing;
   - zoom and pan respond at once.
8. **30 days:** either the chart loads or an explicit message names the period as too large for raw history. There is never a silent partial chart.
9. **Telemetry:** while charts load, the current values keep updating.

## Measured performance

CI, headless Chromium, real Compose stack. Spec `e2e/chart-performance.production.e2e.ts`. Scenario: 24 series × 24 h at 10 s (≈ 207 000 PostgreSQL rows), 10 wheel zoom steps and 3 drag pans. Final run `45899508658` on all the frontend changes of this release.

**Correctness (asserted, all four modes):** for every one of the 24 series, the full-window statistics show:

- the exact PostgreSQL peak (25 + channel);
- the communication errors as failed polls;
- the 5 min silent gap as a gap.

| 24 series × 24 h                      |                       Before P0 |                          Current backend (raw) | Aggregated backend (after DR #1428) |
| ------------------------------------- | ------------------------------: | ---------------------------------------------: | ----------------------------------: |
| Live Data: first channel visible      |         9.4–16.5 s (whole load) |                                          2.4 s |                               2.5 s |
| Live Data: complete window            |                      9.4–16.5 s |                                         10.3 s |                               2.5 s |
| Live Data: zoom/pan                   | 37 fps, long tasks up to 152 ms |                    51 fps, 1 long task (52 ms) |                              48 fps |
| Saved Dashboard: first series visible |             11.4 s (whole load) |                                          1.7 s |                               1.5 s |
| Saved Dashboard: complete window      |                          11.4 s |                                          9.7 s |                               1.5 s |
| Saved Dashboard: zoom/pan             |               58 fps, no detail |                                         59 fps |                              54 fps |
| History transferred                   |                         95.5 MB |                                        95.5 MB |                              0.5 MB |
| Viewport detail after the last pan    |                            none | ≈ 3 800–3 900 original measurements, 0.6–0.7 s |     ≈ 3 650–3 700 points, 0.7–2.2 s |
| Ingestion while history loads         |                     0.26–0.32 s |                                         0.37 s |                              0.40 s |

Raspberry Pi 5 CPU (Node, same code as the browser):

| Work                                                  |                              Before |                   After |
| ----------------------------------------------------- | ----------------------------------: | ----------------------: |
| Live Data chart build, 24 channels                    | 415–502 ms per zoom, tick or sample |                  ~17 ms |
| Overview, 8 probes × 24 h: one live sample            |             401 + 911 ms per sample | 48 ms + ~400 ms per 5 s |
| Overview zoom commit                                  |                              911 ms |                   17 ms |
| Overview 7 d: memory / exact statistics / zoom detail |                 ~167 MB raw objects |   28 MB / 99 ms / 28 ms |
| Overview 30 d (one series, newest-first slices)       |                    ~36 s of inserts | ≈ 4 s (whole test file) |
| Energy, one meter 7 d: raw statistics                 |                            2 331 ms |                  145 ms |
| Refrigeration lanes per zoom                          |                          336–380 ms |           clipping only |

**Reading the tables:**

- On the current backend, loading the complete 24-channel window still takes about 10 s, because 216 raw pages remain.
- The 2 s / 3 s / 5 s full-load targets are reached only with the aggregated backend, which is gated by DR #1428.
- Ranges vary between CI runs.

**Not measured:** a Raspberry Pi browser, an operator PC and 60 fps on real hardware. These are UNVERIFIED until the owner acceptance above.
