# Unified Chart Experience release candidate (#1866, #1867, #1868)

A consolidated **frontend-only** release built from `main` @ `84cf45e728edbe408a8881ee2ba7243f5e9eb977`, on top of production `47e9dd94` (Chart System 2.0). It also ships the merged operator-copy follow-ups #1848–#1852. The backend is unchanged and stays gated by DR #1428.

**Status (2026-11-27):** deployed to LAN, Tailscale `:8443` and `:8444`. The main HTTPS `:443` is pending the owner-run v2 tool step (see _Main HTTPS `:443`_ below).

## Contents

- **#1866 (PR #1869): no cursor flicker.**
  - Under the mouse, ECharts' axis-pointer is the single cursor source.
  - The shared cursor is never dispatched back into the hovered plot and is not re-dispatched for the same value. Linked plots still follow it.
  - Keyboard steps are explicit.
  - Series emphasis is disabled: hovering one line no longer dims the others.
  - The inspector hint has a fixed height.
  - Inspection uses a cached per-series index with binary search.
  - Browser sweep of 61 moves: 0 full rebuilds, p95 35 ms per move.
- **#1867 (PR #1870): deep zoom.**
  - Live chart groups are built from the data only; a zoom swaps the window into the cached scenes.
  - Detail is committed in the same React update as the window, so one render per step.
  - Measured in the browser in CI:
    - total chart work in the deep-zoom sweep fell by 31 % (raw) and 24 % (aggregate);
    - FPS went from 49.3 to 52.1 (raw) and from 46.1 to 48.4 (aggregate);
    - long tasks went from 10 to 9 (raw) and from 11 to 7 (aggregate).
  - Opt-in stage profiling is off in production.
- **#1868 (PR #1871): one chart system.**
  - Every analog measurement line is solid, on every surface and in saved dashboards. The refrigeration setpoint stays dashed as a reference.
  - One shared «Повернути всі» control on every chart.
  - Saved Dashboard context shows units only.
  - The contract is in `docs/ux/chart-interaction-contract.md`.
- **#1848–#1851, #1852 part 1:** operator copy on the other pages, and channel names standing alone.

## Candidate

| Field                   | Value                                                                                                                                                          |
| ----------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Source                  | `84cf45e728edbe408a8881ee2ba7243f5e9eb977`, workflow run 46021146582                                                                                           |
| LAN / `:8443` / `:8444` | ZIP `a30e461d1cc067230f0885fff08fae87168805a947c5cef6fd1602227b92f4bc`, build `hZgwiFnOtHT1zzeKaTCMl`, same-origin, contract `PASS`, 12/12 checksums           |
| `:443`                  | ZIP `fa34da0d6b7ac077a7978308653fdbc0759453bbfc88ceb0ef80018b8fa872c7`, build `hUzaQBG5v2tGcLVYrU3qL`, contract `PASS`; the v2 tool's `verify_artifact` passed |
| Replaces                | LAN, `:8443`, `:8444`: `47e9dd94` / `aZLeJ3e4oo4Xd5wTt-uRU`. `:443`: `47e9dd94` / `30zMx48UZ8ATG5QCPdL_Z`.                                                     |
| Rollback                | LAN: broker `phase=rollback`. `:443`: the v2 tool restores 47e9dd94 automatically, or use `rollback` (immediate predecessor).                                  |

## Disk

- 20.6 GiB is free, the reserve is 20 GiB, and the LAN build needs 23 GiB.
- The owner package frees about 2.5 GiB:
  - the regenerable build cache, through the broker;
  - regenerable files of the dev account (two old Claude CLI binaries, a test venv and the pip cache);
  - the LAN ZIP of `c5bb48a1`, two releases back.
- No image, volume, backup or rollback target is touched.
- Manifest D (`138955b3…`: the `c5bb48a1` and `7db6e1a8` dashboard images) was scanned and has rollback references in archived Stage 2 workspaces. It is **not** proposed for removal.

## Owner package

The package is in the agent's local file `~/.cache/nexolab-chart-p0/owner-package-1866-1868.sh`. It has five steps:

1. Archive the Stage 2 workspace.
2. Approve the build-cache cleanup.
3. Run the dev-account cleanup commands.
4. Issue three `deploy.lan-frontend` approvals: artifact `a30e461d…`, expected current `47e9dd94` / `aZLeJ3e4oo4Xd5wTt-uRU`.
5. Run the v2 HTTPS tool: `plan`, `prepare`, `execute` with artifact `fa34da0d…`, expected current `47e9dd94` / `30zMx48UZ8ATG5QCPdL_Z`.

## Not verified

- An operator PC and 60 FPS on real hardware.
- The owner's browser acceptance.

## Deployment record (2026-11-27)

| Step                    | Result                                                                                                                                                                                                                                                                                                                                                                        |
| ----------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Owner preparation       | Stage 2 workspace archived; dev-account files removed (old Claude CLI 2.1.323/2.1.325, test venv, pip cache; 2.1.326 kept). The `c5bb48a1` LAN ZIP was kept for recovery.                                                                                                                                                                                                     |
| Build-cache cleanup     | 21.65 → 23.75 GiB free. Volumes unchanged, 18 in-use images kept.                                                                                                                                                                                                                                                                                                             |
| Artifacts               | Both ZIP SHA-256 values matched (`a30e461d…`, `fa34da0d…`).                                                                                                                                                                                                                                                                                                                   |
| `prepare`               | Preview `84cf45e728ed` / `hZgwiFnOtHT1zzeKaTCMl`, Docker DNS and server API verified, compose fidelity proven, `ROLLBACK_IDENTITY_VERIFIED 47e9dd943484`, `STAGE2_CHECK_PASS NO_WRITES`.                                                                                                                                                                                      |
| `execute`               | `STAGE2_PREFLIGHT_PASS`, `STAGE2_FRONTEND_GREEN`.                                                                                                                                                                                                                                                                                                                             |
| Identities              | LAN, `:8443` and `:8444` report `84cf45e7` / `hZgwiFnOtHT1zzeKaTCMl`. `:3105` is unchanged (`47e9dd94` / `30zMx48UZ8ATG5QCPdL_Z`).                                                                                                                                                                                                                                            |
| Routes                  | `/`, `/live`, `/energy`, `/refrigeration`, `/sessions` and `/alerts` answer 200 on all three interfaces. All 23 referenced static chunks answer 200.                                                                                                                                                                                                                          |
| Auth, API and WebSocket | Public `:443` and the OAuth gateway answer 302. On the LAN and `:8443`, the API answers 401 without a token and the WebSocket upgrade answers 101. `:8444` proxies straight to the dashboard container (unchanged serve configuration), so `/api` there is a Next.js 404, as before.                                                                                          |
| Telemetry, 5 minutes    | Ready, ingestion lag 0.07–0.40 s, `last_persisted_at` advancing, queue 0. One `/health/ready` probe at 16:56 UTC timed out after 10 s; persistence continued and the next probe was ready, with no service log errors. 13 containers running (12 healthy; MinIO has no healthcheck). 1.9 GiB memory available, no throttling, no failed units, 20.4 GiB free after the build. |
| Rollback                | Not needed. The approval stays unused and expires.                                                                                                                                                                                                                                                                                                                            |

## Main HTTPS `:443`

Owner command (installed v2 tool `00fd14a3…`):

```bash
echo "00fd14a363b804f1289df515e2063eec250bb6b9537ff050b395243f25ce6c07  /usr/local/lib/nexolab-operator/nexolab-https-frontend-release.py" | sudo sha256sum -c - &&
H=(--artifact /home/nexolab-dev/operator-inbox/fa34da0d6b7ac077a7978308653fdbc0759453bbfc88ceb0ef80018b8fa872c7.zip
   --expect-zip-sha256 fa34da0d6b7ac077a7978308653fdbc0759453bbfc88ceb0ef80018b8fa872c7
   --expect-source 84cf45e728edbe408a8881ee2ba7243f5e9eb977 --expect-build hUzaQBG5v2tGcLVYrU3qL) &&
sudo python3 -I /usr/local/lib/nexolab-operator/nexolab-https-frontend-release.py plan "${H[@]}" &&
sudo python3 -I /usr/local/lib/nexolab-operator/nexolab-https-frontend-release.py prepare "${H[@]}" &&
sudo python3 -I /usr/local/lib/nexolab-operator/nexolab-https-frontend-release.py execute "${H[@]}" \
  --expect-current-source 47e9dd943484e58b252dfbf1d1149cf8ecf19d69 --expect-current-build 30zMx48UZ8ATG5QCPdL_Z
```

Expected: `plan` shows the stack with rollback target `47e9dd943484/30zMx48UZ8ATG5QCPdL_Z`; `execute` ends `HTTPS_FRONTEND_GREEN`. On failure the tool restores `47e9dd94` itself.
