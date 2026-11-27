# Unified Chart Experience release candidate (#1866, #1867, #1868)

A consolidated **frontend-only** release built from `main` @ `84cf45e728edbe408a8881ee2ba7243f5e9eb977`, on top of production `47e9dd94` (Chart System 2.0). It also ships the merged operator-copy follow-ups #1848–#1852. The backend is unchanged and stays gated by DR #1428.

**Status: built, verified and staged. Not deployed.**

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
