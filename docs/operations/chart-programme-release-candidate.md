# XWEB-level Advanced Chart System — consolidated release candidate (#1662, #1682)

**Status (2026-11-22): source merged to `main`; NOT installed on any site.** Nothing in this document performs or authorises a Raspberry Pi activation. Everything merged by this programme is **frontend source**; the only backend work (Saved Analysis Views API, PR #1667) is **not merged** (section 4). No Modbus read or write path was touched, no hardware configuration changed, no production migration run.

## 1. Merged work packages

| Work package                                               | Issue        | PR (merge commit)  | Outcome                                                                                                                                                           |
| ---------------------------------------------------------- | ------------ | ------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| WP-A per-series freshness (Saved Dashboards, Overview KPI) | #1643        | #1644 (`90d46905`) | Live / stale / invalid per series from each series' own newest sample with the #1522 cadence contract                                                             |
| WP-B interval statistics                                   | #1645        | #1646 (`b7e4cbae`) | Exact min / max / average / count / coverage / gaps from raw samples; average withheld when coverage is insufficient                                              |
| WP-C events, alarm regions, thresholds                     | #1647        | #1648 (`805db348`) | Canonical alert entities drawn on charts plus an accessible events table                                                                                          |
| WP-D extrema + history truncation                          | #1649        | #1650 (`aca7737f`) | Energy keeps bucket min/max; session history paginates fully and says when truncated                                                                              |
| WP-E point density                                         | #1620 (refs) | #1651 (`d9b807fb`) | Авто / 250 / 500 / 1 000 / 2 500 / 5 000 under an aggregate cap; benchmark recorded                                                                               |
| WP-F per-series freshness elsewhere                        | #1652        | #1653 (`2063d47d`) | Overview per-series; identity-stable clock overlay; Energy/Refrigeration report invalid newest samples                                                            |
| WP-G state lanes                                           | #1655        | #1656 (`bfe8b4ce`) | UNKNOWN vs NO DATA; derived compressor lane; legend                                                                                                               |
| WP-H 24+ series                                            | #1654        | #1657 (`a894f0d3`) | Live comparison limit 8 → 24 (Saved Dashboards already 64, grouped)                                                                                               |
| WP-I export                                                | #1658        | #1659 (`21a2da4a`) | Local «Зберегти PNG» on every chart; CSV uses the display time zone                                                                                               |
| WP-J statistics on Live + session window                   | #1660, #1662 | #1661, #1663       | Same statistics table on Live Data; session chart domain = requested window                                                                                       |
| WP-K density control on Live Data                          | #1664        | #1665 (`9e601a57`) | Live gets the same capped detail control                                                                                                                          |
| WP-L Saved Analysis Views — frontend                       | #1666        | #1669 (`c621a8ec`) | Save / restore hidden series, range, zoom and density through the existing Saved Dashboard persistence (see section 4)                                            |
| WP-M universal density (Energy, Refrigeration)             | #1668        | #1670 (`6a24635a`) | Same capped detail control on Energy and Refrigeration; completes #1620                                                                                           |
| WP-P device-grouped Live channel selection                 | #1671        | #1672 (`5b3e4fa9`) | Searchable, collapsible per-device groups, select-all/none within the 24 limit, operator names                                                                    |
| WP-R lab export                                            | #1673        | #1674 (`929a7823`) | Offline dependency-free XLSX for Saved Dashboards, printable (print-to-PDF) report, authoritative CSV, local PNG                                                  |
| WP-N exact interval statistics everywhere                  | #1675        | #1676 (`f80aa2d5`) | Energy exact from raw samples; Overview, session and Refrigeration statistics from raw columns, never reduced vertices                                            |
| WP-Q alerts on Live                                        | #1677        | #1678 (`874215fa`) | Canonical alert markers/regions/thresholds and an events table on Live Data                                                                                       |
| WP-O digital state lanes                                   | #1679        | #1680 (`fbcf62b1`) | Canonical digital-channel taxonomy; Saved Dashboard lanes (relay bits, compressor, evaporator fan, defrost, alarm); ON / OFF / UNKNOWN / NO DATA with cursor sync |
| WP-Q per-series staleness, presets, coverage               | #1677        | #1681 (`d411df6d`) | Energy/Refrigeration per-series staleness; unified presets; partial-history notice; °C display unit                                                               |
| WP-Q custom period (Overview, Energy)                      | #1683        | #1684 (PR)         | Fixed custom window with its own history key, no live tail, «historical» freshness                                                                                |
| WP-S acceptance evidence + this document                   | #1682        | docs-only PR       | 27/27 real-browser checks, harness sources (`docs/audits/chart-system-acceptance-1682.md`)                                                                        |

Documentation changed: `docs/architecture/nexolab-chart-system.md`, `docs/architecture/nexolab-chart-evidence-integrity.md`, `docs/audits/chart-density-benchmark-1620.md`, `docs/audits/chart-system-acceptance-1682.md`, `AGENTS.md` (autonomous-execution authorisation and unchanged safety boundaries).

## 2. Capability matrix

| Capability                                                                 | Status                                                                                                                                        |
| -------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| Saved Dashboard persistence of series, colours, order, units               | Existing, unchanged (ETag-versioned)                                                                                                          |
| Saved analysis view (hidden series, range, zoom, density)                  | **Frontend merged; backend PR #1667 blocked** — until it ships the UI refuses to claim a save the server ignored                              |
| Point density control                                                      | Saved Dashboards, Live, Energy, Refrigeration (shared `density.ts`, aggregate cap)                                                            |
| Interval statistics from raw measurements                                  | Saved Dashboards, Live, Overview, session, Energy, Refrigeration                                                                              |
| Digital state lanes                                                        | Saved Dashboards (all real digital metrics) + Refrigeration compressor lane; **no lanes for sources that do not exist** (door, fan contactor) |
| Per-series freshness                                                       | All chart surfaces (Saved Dashboards, Overview, Live, Energy, Refrigeration)                                                                  |
| Canonical alarms/events on charts                                          | Saved Dashboards, Live, Energy, Refrigeration, Overview                                                                                       |
| Device-grouped Live selection (24 channels)                                | Merged                                                                                                                                        |
| Unified presets `1 година / 6 годин / 24 години / 7 днів / Власний період` | All chart surfaces. Overview and Energy custom periods are fixed windows (no live tail, series marked «Фіксований період»), max 31 days       |
| Requested range vs available history notice                                | All `ChartShell` surfaces                                                                                                                     |
| Exports                                                                    | CSV (display time zone), PNG (local canvas), XLSX (offline, Saved Dashboards), print-to-PDF report                                            |
| Real-browser acceptance                                                    | 27/27 on a desktop (not Pi)                                                                                                                   |

## 3. Verification actually performed

- **Per work package, local:** `vitest run`, `eslint . --max-warnings=0`, `tsc --noEmit`, `prettier --check`, `next build`, `scripts/validate-project-state.py`.
- **Per work package, GitHub exact-head CI:** Merge Gate and the classifier-selected checks were GREEN on every merged head. First-run failures that were fixed rather than bypassed: unclassified benchmark path (WP-E), stale E2E text (WP-H), and for WP-Q the E2E text for renamed preset buttons and the `°C` display unit, plus a layout shift caused by a notice placed above the plot (moved below it).
- **Real browser:** `docs/audits/chart-system-acceptance-1682.md` (27/27: 1/8/24 series × 360/1440/1920 px offline, 24 h and 7 d, interactions, keyboard basics, PNG, XLSX, PDF, saved view round trip, RBAC, 32-channel picker). Desktop only.
- **Performance:** `docs/audits/chart-density-benchmark-1620.md` and the acceptance timings; the Raspberry Pi has not been measured.

## 4. Blockers and honest gaps

1. **Saved Analysis Views backend — PR #1667 (migration `20261122_0041`, 17 backend tests).** Not merged. The container vulnerability policy gate fails on HIGH CVE-2026-124709 in the Device Agent image (Debian `libssl3t64`, no fixed package). This is a Product Owner risk decision (`security/vulnerability-exceptions.json` entries are risk acceptances), a Debian fix, or an image change — the gate was **not** bypassed. The branch is kept current with `main`. The PostgreSQL migration has only been verified in CI-style tests, never on a production database; applying it needs separately approved release authority.
2. **Custom period on Overview and Energy history (#1683)** is delivered as a fixed window (no live tail, never claims liveness, 31-day limit). It is covered by unit/hook tests only — it has not been exercised in a real browser against a seeded stack.
3. **Server-side downsampling for very long ranges × many channels** is a backend decision; clients still load raw history per channel (7 d × 8 series ≈ 600 k raw samples: 2.7 s on a desktop).
4. **Overview/Live/Energy/Refrigeration real-data acceptance** (alerts, lanes, scale) needs the site.

## 5. What is NOT proven (do not claim it)

- No Raspberry Pi / site evidence: density timings on the Pi remain an extrapolation (×2.4 from #1167); lower the cap if a Pi measurement misses the 250 ms p95 target.
- No signed-in human review on the controlled Pi browser.
- Embraco ×0.01 °C remains an unverified operator scale (#1603/#1625); lane semantics for relay bits, defrost code and alarm bits were validated on synthetic samples only.
- Offline reboot / power-cycle (#1606), encrypted off-device DR (#1428) and the Docker/LAN CIDR overlap (#1409/#1399) remain open site gates, unchanged by this programme.

## 6. Safe Raspberry Pi update procedure (frontend only, owner-run)

This reuses the repository's guarded, source-pinned frontend-only release pattern (see `docs/operations/nexolab-1560-frontend-bluegreen-handoff.md`, `docs/operations/nexolab-unified-operator-release-parity.md`, `scripts/build-frontend-release-artifact.sh`, `scripts/nexolab-protected-frontend.py`, and the #1522 / #1625 / #1638 evidence entries in `.project/CURRENT_STATE.md`). **Each step needs the Product Owner's explicit approval; an agent must not run privileged commands on the site and must not treat this document as approval.**

1. **Decide the exact source.** Pin the `main` commit to release. Require exact-head GREEN CI for that commit, including the Merge Gate.
2. **Backend is separate.** The frontend-only release does **not** include PR #1667. Until #1667 and its migration are separately approved and released, saved views fail with an explicit message instead of silently not saving. If the backend is released later, release it **before** the frontend that depends on it, take the standard database backup first, and apply the migration only under its own approval.
3. **Build matching artifacts off-device.** Use the GitHub linux/arm64 workflow to produce the LAN Dashboard image and the protected HTTPS runtime for the **same** source; verify SHA-256 and the runtime identity (source + build ID). Do not build on the 4 GiB Pi; keep > 20 GiB free.
4. **Preflight (read-only).** Confirm running LAN and HTTPS identities and build IDs, backend container IDs and images, Telemetry `/health/ready`, Device Agent `/health`, the gateway configuration hash, free disk, and that the previous frontend release and rollback manifest exist.
5. **Acknowledge the open gates.** The owner records that #1428, #1409/#1399 and #1606 are still open; a frontend-only release must not restart or modify backend containers, Docker/IPAM, MQTT, PostgreSQL, the object store, the Device Agent or any RS-485 bus.
6. **Activate with automatic rollback.** Run the guarded frontend-only activation for LAN (stateless Docker Dashboard container replacement) and HTTPS (user-systemd frontend with its release drop-in); it must keep the previous frontend available and roll back automatically if identity or health checks fail. Never re-run a failed `execute`; follow the journal/rollback instructions.
7. **Verify after activation.** Identity API reports the pinned source/build on both entrypoints; backend container IDs unchanged; telemetry still advancing; authenticated browser (LAN and signed-in HTTPS): Saved Dashboard charts, statistics table, density control (also on Energy and Refrigeration), state lanes, events table, presets and partial-history notice, Save PNG / XLSX / print report, Live with up to 24 channels grouped by device, 390 px and desktop layouts, no client/API errors; zero acquisition requests added by chart interactions. Measure density timings on the Pi and record them labelled as Pi measurements.
8. **Roll back** with the release's rollback command if any check fails.
9. **Record evidence** in `.project/CURRENT_STATE.md`, `.project/LAST_CHECKPOINT.json` and the linked Issue. Do not print the operator update-ready signal or mark the site green without that runtime proof.

## 7. Hard boundaries that remained in force

No Modbus/hardware writes; no change of acquisition or polling cadence from the UI; no production or site cutover; no destructive data operation; no production migration; no secret handling; RBAC and tool permissions untouched; no new mandatory CDN/remote font/cloud API (ECharts and all assets are bundled); no CI or security check bypassed.
