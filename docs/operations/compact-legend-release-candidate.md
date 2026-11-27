# Compact chart legend release candidate (#1878)

A frontend-only release built from `main` @ `0b07c693f04c86d7b7f5ee44e755a5316a2a0cc8` on top of production `84cf45e7` (Unified Chart Experience). It ships #1878: the shared compact `ChartSeriesLegend` on every chart surface. The backend is unchanged and stays gated by DR #1428.

**Status (2026-11-27): built, verified and staged. Not deployed.** The LAN build is blocked by SSD headroom (see _Release gates_).

## Candidate

| Field                   | Value                                                                                                                                                                                                                           |
| ----------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Source                  | `0b07c693f04c86d7b7f5ee44e755a5316a2a0cc8`, `Frontend Release Artifact` run 46070234260                                                                                                                                         |
| LAN / `:8443` / `:8444` | ZIP `ba539baae6942d0ad4ba9aae977155d17a2a3081ce958bfbde0cc8e38a0a92c2` (= GitHub artifact digest), build `EbyMPXd60YY5pAvkTzEvC`, same-origin, contract `PASS`, 12/12 internal checksums                                        |
| `:443`                  | ZIP `5665ccf99b0f30bef27fe5e643250c8dc972a8a865ca90f45e030dd27075b9c8` (= GitHub digest), build `Xvkh7UYHlK25RwKbhiH4g`, contract `PASS`; the v2 tool's `verify_artifact` passed; unpacks to 621 954 427 bytes (19 023 members) |
| Replaces                | LAN, `:8443`, `:8444`: `84cf45e7` / `hZgwiFnOtHT1zzeKaTCMl`. `:443`: `84cf45e7` / `hUzaQBG5v2tGcLVYrU3qL`                                                                                                                       |
| Rollback                | LAN: broker `phase=rollback` to `84cf45e7`. `:443`: the v2 tool restores `84cf45e7` automatically, or `rollback`                                                                                                                |

## Evidence (PR #1879)

- Exact-head GREEN on `e6d3c2ac` (Merge Gate, unit/component, authenticated dashboard acceptance, PostgreSQL/S3 browser, truthful delivery matrix). Codex review had no findings.
- Browser screenshots in the acceptance artifact (`issue-1878-legend-*`, `issue-1878-page-*`):
  - Overview;
  - Live Data;
  - multi-axis Live at desktop and 360 px;
  - Saved Dashboards at 360, 1440 and 1920 px;
  - Energy.
- Refrigeration and Test Sessions render the same `ChartShell` legend. Their browser fixtures have no plotted series, so they are covered by component tests only.
- Fixture evidence only: operator PC and site acceptance are separate.

## Release gates

| Gate              | State                                                                                                                                                                       |
| ----------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Artifacts         | Pass: both digests, 12/12 internal checksums, contracts `PASS`                                                                                                              |
| SSD, LAN          | **Blocked.** The Stage 2 `prepare` needs reserve 20 GiB + working 3 GiB = 24 696 061 952 bytes free; 22 857 244 672 are free (short 1.71 GiB). Build cache is already empty |
| SSD, `:443`       | Pass on its own: the tool needs free − 621 954 427 ≥ 20 GiB                                                                                                                 |
| Stage 2 workspace | The owner archives `nexolab-wp2c-stage2` (from `84cf45e7`) before `prepare`                                                                                                 |
| Owner approvals   | `deploy.lan-frontend` prepare/execute/rollback with expect-current `84cf45e7…` / `hZgwiFnOtHT1zzeKaTCMl`; `:443` v2 tool run                                                |

Order: LAN first, then `:443`, so all interfaces move together.

### SSD options (owner decision; nothing removed)

| Source                                                                          | Size                | Note                                                                                                                                                                    |
| ------------------------------------------------------------------------------- | ------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Two Python test venvs in Commander workspaces (#1445, #1615)                    | ~0.63 GiB           | Regenerable                                                                                                                                                             |
| Inbox ZIPs of `210b478b` (LAN and HTTPS) and `c5bb48a1` (LAN)                   | ~0.61 GiB           | Byte-identical copies stay downloadable from GitHub until 2026-12-02/03; rollback uses images and release directories, not these ZIPs                                   |
| Dashboard images two or more releases back (`210b478b`, `c5bb48a1`, `7db6e1a8`) | Unknown unique size | Referenced only as `previous_image_id` in archived Stage 2 workspaces; the broker scan treats that as rollback context, so they need the retention policy (#1876) first |

The first two sources together reach about 22.5 GiB, which is still short of 23 GiB. The LAN release therefore waits for the retention policy (#1876), which is the top storage priority anyway.
