# XWEB-level Advanced Chart System — consolidated release candidate (#1662)

**Status (2026-11-22): source merged to `main`; NOT installed on any site.** Nothing in this document performs or authorises a Raspberry Pi activation. Every change in the programme is **frontend source only**: `git diff --name-only b036b98e^ main -- services infrastructure` is empty (no backend, Device Agent, Compose, migration or hardware file changed). No Modbus read or write path was touched.

## 1. What the release candidate contains

| Work package                                                     | Issue        | PR (merge commit)  | Outcome                                                                                                              |
| ---------------------------------------------------------------- | ------------ | ------------------ | -------------------------------------------------------------------------------------------------------------------- |
| WP-A per-series freshness (Saved Dashboards, Overview KPI #1634) | #1643        | #1644 (`90d46905`) | Live / stale / invalid per series from each series' own newest sample with the #1522 cadence contract                |
| WP-B interval statistics                                         | #1645        | #1646 (`b7e4cbae`) | Exact min / max / average / count / coverage / gaps from raw samples; average withheld when coverage is insufficient |
| WP-C events, alarm regions, thresholds                           | #1647        | #1648 (`805db348`) | Canonical alert entities drawn on charts plus an accessible events table                                             |
| WP-D extrema + history truncation                                | #1649        | #1650 (`aca7737f`) | Energy keeps bucket min/max; session history paginates fully and says when truncated                                 |
| WP-E point density                                               | #1620 (refs) | #1651 (`d9b807fb`) | Авто / 250 / 500 / 1 000 / 2 500 / 5 000 under an aggregate cap; benchmark recorded                                  |
| WP-F per-series freshness elsewhere                              | #1652        | #1653 (`2063d47d`) | Overview per-series; identity-stable clock overlay; Energy/Refrigeration report invalid newest samples               |
| WP-G state lanes                                                 | #1655        | #1656 (`bfe8b4ce`) | UNKNOWN vs NO DATA; derived compressor lane; legend                                                                  |
| WP-H 24+ series                                                  | #1654        | #1657 (`a894f0d3`) | Live comparison limit 8 → 24 (Saved Dashboards already 64, grouped)                                                  |
| WP-I export                                                      | #1658        | #1659 (`21a2da4a`) | Local «Зберегти PNG» on every chart; CSV uses the display time zone                                                  |
| WP-J statistics on Live                                          | #1660        | #1661 (`533185c1`) | Same statistics table on Live Data                                                                                   |
| WP-J session window + this document                              | #1662        | this PR            | Session chart domain = requested window                                                                              |

Documentation changed: `docs/architecture/nexolab-chart-system.md`, `docs/architecture/nexolab-chart-evidence-integrity.md`, `docs/audits/chart-density-benchmark-1620.md`, `AGENTS.md` (autonomous-execution authorisation and unchanged safety boundaries).

## 2. Verification actually performed

- **Per work package, local:** `vitest run` (final count at the last package: see the PR), `eslint . --max-warnings=0`, `tsc --noEmit`, `prettier --check`, `next build`, `scripts/validate-project-state.py`.
- **Per work package, GitHub exact-head CI:** Merge Gate, Static quality and build, Unit and component tests, Quality policy and contracts, JWT/REST/WebSocket acquisition-invariant job, and — where the change classifier required them — Authenticated Dashboard Acceptance (headless Chromium against a seeded stack) and Refrigeration Browser Acceptance. All were GREEN on the merged heads; two first runs failed and were fixed (WP-E: unclassified benchmark path; WP-H: stale E2E text asserting the old 8-channel guidance).
- **Performance:** `docs/audits/chart-density-benchmark-1620.md` — desktop headless Chromium matrix for 1/8/24 series × 240…5 000 points (render ≈ 33 ms + ≈ 15 ms per 1 000 aggregate points; 24 × 5 000 = 1.8 s, which is why the 6 000-point aggregate cap exists).

## 3. What is NOT proven (do not claim it)

- **No Raspberry Pi / site evidence of any kind.** Density timings on the Pi are an extrapolation (×2.4 from #1167) and must be measured on the controlled Pi browser before the manual density modes are called Pi-validated; lower the cap if that measurement misses the 250 ms p95 target.
- **No signed-in human browser review** of the new tables, lanes, events table, PNG button or Live 24-series flow. The PNG was exercised against a stub renderer in unit tests, not rasterised and inspected in a real browser.
- **No hardware acceptance.** Embraco ×0.01 °C is still an unverified operator scale (#1603/#1625); UNKNOWN/NO DATA lane semantics were tested on synthetic samples only.
- **Offline reboot / power-cycle (#1606), complete encrypted off-device DR (#1428) and the Docker/LAN CIDR overlap (#1409/#1399) remain open site gates**, unchanged by this programme.
- The alerts API behaviour (pagination, RBAC) was verified through unit tests and the existing CI stack, not against the production alert log.

## 4. Classified follow-ups (explicit, evidence-based)

1. **Shared saved analysis views** (hidden series, custom range, zoom) — need new persisted fields on Saved Dashboards (schema + Alembic migration on shared data, API contract, release sequencing). The existing Saved Dashboard model (series, colours, visualization, unit, refresh, window; ETag versioned) stays the single persistence.
2. **Saved Dashboard digital lanes** and door / fan / controller-status lanes — need item decode metadata (e.g. relay bit index) and a canonical digital-channel taxonomy in the inventory.
3. **Live device-grouped selection table** — UI rework of the Live explorer (filters by node/equipment exist; Saved Dashboards are the grouped 64-series workspace).
4. **Energy raw statistics / per-series staleness** — Energy history is reduced before the chart; needs its own raw columns and cadence source.
5. **Server-side downsampled history** for very long ranges × many channels — backend decision; clients still load raw history per channel.
6. **XLSX/PDF for Saved Dashboards** — unsupported by the existing code (Energy has its own XLSX export).
7. **Density control on Live / Energy / Refrigeration** — `src/features/charts/density.ts` is shared; only Saved Dashboards use it today (#1620 stays open for this reason).
8. **Pi measurement of the density matrix and 24-series Live**, and a signed-in browser acceptance pass.

## 5. Safe Raspberry Pi update procedure (frontend only, owner-run)

This reuses the repository's existing guarded, source-pinned frontend-only release pattern (see `docs/operations/nexolab-1560-frontend-bluegreen-handoff.md`, `docs/operations/nexolab-unified-operator-release-parity.md`, `scripts/build-frontend-release-artifact.sh`, `scripts/nexolab-protected-frontend.py`, and the #1522 / #1625 / #1638 evidence entries in `.project/CURRENT_STATE.md`). **Each step needs the Product Owner's explicit approval; an agent must not run privileged commands on the site and must not treat this document as approval.**

1. **Decide the exact source.** Pin the `main` commit to release (it must contain this PR). Require exact-head GREEN CI for that commit, including the Merge Gate.
2. **Build matching artifacts off-device.** Use the GitHub linux/arm64 workflow to produce the LAN Dashboard image and the protected HTTPS runtime for the **same** source; verify SHA-256 and the runtime identity (source + build ID) of both. Do not build on the 4 GiB Pi; keep > 20 GiB free.
3. **Preflight (read-only).** Confirm the running LAN and HTTPS identities and build IDs, backend container IDs and images, Telemetry `/health/ready`, Device Agent `/health`, the gateway configuration hash, free disk, and that the previous frontend release and rollback manifest exist.
4. **Acknowledge the open gates.** The owner records that #1428 (independent encrypted DR/restore), #1409/#1399 (network) and #1606 (offline reboot) are still open; a frontend-only release must not restart or modify backend containers, Docker/IPAM, MQTT, PostgreSQL, the object store, the Device Agent or any RS-485 bus.
5. **Activate with automatic rollback.** Run the guarded frontend-only activation for LAN (stateless Docker Dashboard container replacement) and HTTPS (user-systemd frontend with its release drop-in) as in earlier releases; it must keep the previous frontend available and roll back automatically if identity or health checks fail. Never re-run a failed `execute`; follow the journal/rollback instructions of the runbook.
6. **Verify after activation.** Identity API reports the pinned source/build on both entrypoints; five backend container IDs unchanged; telemetry still advancing; authenticated browser (LAN and signed-in HTTPS): Saved Dashboard charts, statistics table, density control, events table, Save PNG, Live with up to 24 channels, Refrigeration lanes, 390 px and desktop layouts, no client/API errors; zero acquisition requests were added by chart interactions.
7. **Roll back** with the release's rollback command if any check fails (previous frontend release and manifest preserved).
8. **Record evidence** in `.project/CURRENT_STATE.md`, `.project/LAST_CHECKPOINT.json` and the linked Issue. Do not print the operator update-ready signal or mark the site green without that runtime proof.

## 6. Hard boundaries that remained in force

No Modbus/hardware writes; no change of acquisition or polling cadence from the UI; no production or site cutover; no destructive data operation; no secret handling; RBAC and tool permissions untouched; no new mandatory CDN/remote font/cloud API (ECharts and all assets are bundled).
