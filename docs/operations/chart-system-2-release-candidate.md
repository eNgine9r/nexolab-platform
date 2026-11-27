# Chart System 2.0 frontend release candidate (#1843, #1844, #1845)

One consolidated **frontend-only** release for every operator interface, built from `main` @ `47e9dd943484e58b252dfbf1d1149cf8ecf19d69`. The baseline is the production release `210b478b` (P0 charts). The backend is unchanged and stays gated by DR #1428.

**Status (2026-11-27):** deployed to LAN, Tailscale `:8443` and `:8444`. The main HTTPS `:443` is pending the owner-run tool step (step 4 of the package).

## Contents

- **#1843 (PR #1846): Y axes follow the visible window.**
  - Root cause: `scale: true` with an x-only `dataZoom` and `filterMode: "none"`.
  - Bounds are fitted per unit to the drawn measurements, excluding hidden series.
  - Nice ticks, padding and a display-resolution minimum span; hysteresis prevents jitter.
  - Modes: Auto, Full period and Manual (min/max, decimal comma accepted).
  - Distant thresholds are named off-scale.
  - The header shows the actual visible interval.
- **#1844 (PR #1847): adaptive viewport point budget.**
  - About two points per plot pixel, within a page-wide total shared by the visible series.
  - The total follows the measured render cost, with hysteresis and 480-point steps, within [0.5, 2.5] × the Pi target.
  - Aggregate detail is capped at the API's 2 000 buckets.
  - A resize refreshes committed detail but never reloads history.
  - The number of drawn points is published.
- **#1845 (PR #1854): Live Data and Overview operator copy.**
  - Developer copy moved out of the operator view.
  - One selection limit (24).
  - The "Активних сесій" KPI uses exact per-state totals from the session API, with its own status and a 10 s refresh.
  - Counters state their denominators.
  - Follow-ups: #1848–#1853.

## Candidate

| Field                   | Value                                                                                                                                                                     |
| ----------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Source                  | `47e9dd943484e58b252dfbf1d1149cf8ecf19d69`                                                                                                                                |
| Workflow                | `Frontend Release Artifact`, run 45979028259                                                                                                                              |
| LAN / `:8443` / `:8444` | ZIP SHA-256 `a7e8fbac82a116ce3c0d37a18867daca14ac9ef613950c419b3e95bea86022c7`, build `aZLeJ3e4oo4Xd5wTt-uRU`, same-origin, contract `PASS`, 12/12 internal checksums     |
| `:443` (Funnel, OAuth)  | ZIP SHA-256 `c48df0cbdd8882b5534f34f81a6f7641bac6b6883a02e04ab6cd128af2f0ac18`, build `30zMx48UZ8ATG5QCPdL_Z`, contract `PASS`, the HTTPS tool's `verify_artifact` passed |
| Staged                  | `~nexolab-dev/operator-inbox/<sha256>.zip` (read-only); both equal the GitHub digests                                                                                     |
| Replaces                | LAN, `:8443`, `:8444`: `210b478b` / `nCkLRk-U9EkiJ3PmhdBuA`. `:443`: `210b478b` / `EyZllf1uoZnxieohz2NxC`.                                                                |
| Rollback                | LAN: `deploy.lan-frontend phase=rollback`. `:443`: the tool's automatic rollback, or `rollback`. All previous releases and images are kept.                               |

## Disk

- 21.0 GiB is free (the database grows), and the reserve is 20 GiB.
- The LAN build needs at least 23 GiB, and the HTTPS release about 0.58 GiB.
- The package therefore includes:
  - the regenerable build-cache cleanup (about 1.3 GB reclaimable);
  - SSD manifest C (`3c928c51…`): 20 unused NEXOLAB candidate images, up to about 5.9 GB nominal.
- The broker scan of 2026-11-27 covered 120 393 files and was complete.
  - It found no rollback, recovery, backup or protected-images reference.
  - Four images are only mentioned in old staging or rehearsal workspaces (#1513, #1518).
  - The removal re-runs the scan and skips anything protected.
- Rollback images and artifacts are not touched.

## Owner package (one session)

The package is in the agent's local file `~/.cache/nexolab-chart-p0/owner-package-cs2.sh` and in the agent report. It has four steps:

1. Archive the Stage 2 workspace with `mv`.
2. Issue two disk approvals: `storage.cleanup-regenerable build_cache=all-unused` and `storage.remove-images manifest_sha256=3c928c51…`.
3. Issue three `deploy.lan-frontend` approvals (prepare, execute, rollback) with `artifact_sha256=a7e8fbac…`, `expect_current_source=210b478b…` and `expect_current_build=nCkLRk-U9EkiJ3PmhdBuA`.
4. For `:443`, the tool is already installed (`9e38bbe5…`). Run `plan`, `prepare` and `execute` with artifact `c48df0cb…`, source `47e9dd94…` and build `30zMx48UZ8ATG5QCPdL_Z`, plus `--expect-current-source 210b478b… --expect-current-build EyZllf1uoZnxieohz2NxC`.

The agent then:

- runs the cleanup and the image removal;
- checks free space against 23 GiB;
- runs LAN `prepare` (`STAGE2_CHECK_PASS`) and then `execute` (`STAGE2_FRONTEND_GREEN`);
- verifies the LAN, `:8443`, `:8444` and `:3105` identities, the anonymous OAuth `302` on `:443`, the API (401 without a token), the WebSocket (101), ingestion lag, containers and memory;
- rolls back on any failure.

## Measured (CI, 24 series × 24 h, exact-head runs of #1854 / #1847)

| Mode                             | First series | Full window | Zoom/pan                  | Drawn points after zoom | `setOption` |
| -------------------------------- | -----------: | ----------: | ------------------------- | ----------------------: | ----------: |
| Live Data, aggregate backend     |    1.7–2.0 s |   1.7–2.1 s | 46–53 fps, 0–3 long tasks |             3 600–4 896 |    13–15 ms |
| Live Data, raw (current backend) |    2.0–2.3 s |       ~11 s | 50–53 fps, 0–1 long task  |             5 280–9 480 |     9–22 ms |
| Saved Dashboard, aggregate       |    1.2–1.5 s |   1.2–1.5 s | 53–59 fps, 0–2 long tasks |             3 960–5 112 |    16–17 ms |
| Saved Dashboard, raw             |    1.4–1.9 s |  7.5–10.5 s | 59 fps, 0–1 long task     |             3 840–4 416 |     7–11 ms |

- Viewport detail arrives 0.6–2.1 s after the last pan.
- Ingestion during the load was 0.27–0.39 s.
- These numbers come from GitHub runners, not from a Pi or operator PC. 60 FPS on real hardware is **not verified**.
- The 2/3/5 s full-window targets for the raw path still need the aggregated backend, which is gated by DR #1428.

## Deployment record (2026-11-27)

| Step                    | Result                                                                                                                                                                                                                                                 |
| ----------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Baseline                | LAN, `:8443` and `:8444` served `210b478b` / `nCkLRk-U9EkiJ3PmhdBuA`; `:3105` served `210b478b` / `EyZllf1uoZnxieohz2NxC`; public `:443` answered 302. Both release ZIP SHA-256 values matched.                                                        |
| Build-cache cleanup     | 21.01 → 23.09 GiB free. Volumes unchanged, 18 in-use images kept.                                                                                                                                                                                      |
| Manifest C              | A fresh scan covered 120 393 files and was complete: 0 rollback and 0 protected references (4 mentions only in old #1513/#1518 staging workspaces). The removal deleted 20 of 20 images: 23.08 → 25.08 GiB free, volumes unchanged.                    |
| `prepare`               | `STAGE_VERIFIED` `47e9dd94` / `aZLeJ3e4oo4Xd5wTt-uRU` (17 632 files). The image was compared file by file. `STAGE2_CHECK_PASS NO_WRITES`, and the live identity was unchanged.                                                                         |
| `execute`               | `ROLLBACK_IDENTITY_VERIFIED 210b478bed76`, `STAGE2_PREFLIGHT_PASS`, `STAGE2_FRONTEND_GREEN`                                                                                                                                                            |
| Identities              | LAN, `:8443` and `:8444` report `47e9dd94` / `aZLeJ3e4oo4Xd5wTt-uRU`. `:3105` is unchanged (`210b478b`).                                                                                                                                               |
| Routes                  | `/`, `/live`, `/energy`, `/refrigeration`, `/sessions` and `/alerts` answer 200 on all three interfaces. All 23 referenced static chunks answer 200.                                                                                                   |
| Auth, API and WebSocket | Public `:443` and the OAuth gateway answer 302. On the LAN and `:8443`, the API answers 401 without a token and the WebSocket upgrade answers 101.                                                                                                     |
| Telemetry, 5 minutes    | Ready throughout. Ingestion lag 0.16–0.62 s, `last_persisted_at` advancing, queue 0. All 13 containers are running (12 healthy; MinIO has no healthcheck by design). 1.9 GiB of memory available, no throttling, no failed units, about 21.7 GiB free. |
| Rollback                | Not needed. The approval stays unused and expires.                                                                                                                                                                                                     |

## Main HTTPS `:443`: v2 release tool (#1863)

On 2026-11-27 the v1 tool refused `execute` 210b478b → 47e9dd94 with `999-https-release-210b478bed76.conf is already installed; run rollback first; nothing changed`. v1 supported only a first activation. Nothing changed live: `:3105` still serves `210b478b` / `EyZllf1uoZnxieohz2NxC`.

### What v2 does

- **Consecutive upgrades A → B → C.** There is one fixed managed drop-in, `999-https-release.conf`, so its precedence never depends on the lexical order of hashes. The v1 hash-named drop-in and the v1 `state.json` are migrated, keeping their exact bytes.
- **Rollback goes to the immediate predecessor.** The state is a release stack holding each release's identity and exact drop-in bytes: from 47e9dd94, rollback returns to 210b478b, never further.
- **Checks before any change:**
  - the live identity equals the recorded top;
  - the drop-ins on disk and systemd's loaded `DropInPaths` contain exactly the recorded drop-in, last;
  - the disk reserve holds;
  - the artifact and the prepared files are re-verified.
- **Recovery and locking:**
  - a journal and an atomic transition record are written before the switch;
  - any failure restores the predecessor's exact drop-in and verifies its identity and routes;
  - `recover` completes an interrupted switch;
  - a lock allows only one operation at a time.
- **Hardening:** the drop-in is root-owned and written through a directory descriptor opened without following symlinks.
- **`plan` is a read-only preflight.** It prints `HTTPS_FRONTEND_STACK …` with the rollback target.

### Owner command (one session, checksum-pinned)

```bash
cd /home/nexolab-dev/nexolab-platform && git fetch -q origin && git checkout -q origin/main -- docs/operations/https-frontend-release/nexolab-https-frontend-release.py
echo "adbcccc654d6a1c43cc934f462b5cc80cde994b890aad56927f347b3a3da3874  docs/operations/https-frontend-release/nexolab-https-frontend-release.py" | sha256sum -c - &&
sudo install -o root -g root -m 0755 docs/operations/https-frontend-release/nexolab-https-frontend-release.py \
  /usr/local/lib/nexolab-operator/nexolab-https-frontend-release.py &&
echo "adbcccc654d6a1c43cc934f462b5cc80cde994b890aad56927f347b3a3da3874  /usr/local/lib/nexolab-operator/nexolab-https-frontend-release.py" | sha256sum -c - &&
H=(--artifact /home/nexolab-dev/operator-inbox/c48df0cbdd8882b5534f34f81a6f7641bac6b6883a02e04ab6cd128af2f0ac18.zip
   --expect-zip-sha256 c48df0cbdd8882b5534f34f81a6f7641bac6b6883a02e04ab6cd128af2f0ac18
   --expect-source 47e9dd943484e58b252dfbf1d1149cf8ecf19d69 --expect-build 30zMx48UZ8ATG5QCPdL_Z) &&
sudo python3 -I /usr/local/lib/nexolab-operator/nexolab-https-frontend-release.py plan "${H[@]}" &&
sudo python3 -I /usr/local/lib/nexolab-operator/nexolab-https-frontend-release.py prepare "${H[@]}" &&
sudo python3 -I /usr/local/lib/nexolab-operator/nexolab-https-frontend-release.py execute "${H[@]}" \
  --expect-current-source 210b478bed76d5a7cdbe7c5398cebb3d0091224f --expect-current-build EyZllf1uoZnxieohz2NxC
```

- `plan` must print `HTTPS_FRONTEND_STACK … -> 210b478bed76/EyZllf1uoZnxieohz2NxC`.
- `prepare` re-verifies the already prepared release file by file; nothing is rebuilt.
- `execute` must end with `HTTPS_FRONTEND_GREEN`. On any failure it restores 210b478b itself (`HTTPS_FRONTEND_ROLLED_BACK_VERIFIED`).
- A later rollback to 210b478b uses `… rollback --expect-current-source 47e9dd943484e58b252dfbf1d1149cf8ecf19d69 --expect-current-build 30zMx48UZ8ATG5QCPdL_Z`.
- After an interruption (power loss), run `… recover`.

**Not verified in CI:** an isolated real systemd user-unit precedence test, because GitHub runners have no user systemd session. Precedence is modelled in the tests and enforced on the host by the `DropInPaths` checks before and after `daemon-reload`.
