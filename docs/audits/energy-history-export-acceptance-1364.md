# Energy history export — native Raspberry Pi acceptance evidence (#1364)

**Status:** native isolated synthetic 7-day export, HTTP API, persistence/API p95, independent RAW/aggregate CSV/XLSX, collector-continuity and hosted cross-device browser evidence **PASS**. Remaining gates: final exact-head CI/review after fixture correction, and independently guarded matching ARM64 package/site release. Production acceptance is **NOT** claimed.

## Follow-on native evidence (2026-10-14 UTC)

- Second exact-source candidate **HTTP API** benchmark (internal-only host, read-only source mount): `/health/ready` and 44-metric catalog 200, real `POST preview → status → start → ready → one-use ticket → streamed download` for RAW CSV (41.13 s; 24,579,510 bytes) and RAW XLSX (64.83 s; 6,236,213 bytes). 1,653/1,653 synthetically submitted events persisted, no rejection; 814 status/health HTTP measurements. 30 s pre-load baseline and 30 s post-export acquisition periods.
- Measured p95 before/during/after (milliseconds): API **5.856 / 6.426 / 5.668**; PostgreSQL persisted-event timestamp lag **3.003 / 5.314 / 2.975**; worst recorded persisted-event lag **1,196.786 ms**. Fixed budget API/persistence p95 ≤max(250 ms, 3×baseline); max lag ≤2,000 ms; all **PASS**. An earlier independent HTTP run also passed 1,608/1,608, API p95 6.35 ms, persistence p95 4.911 ms, maximum lag 964.688 ms.
- Independent PostgreSQL reconciliation of two different immutable 10-minute snapshots: **5,040 CSV rows; 257,040 validated counts/statistics**; **5,040 XLSX rows; 250,992 validated counts/statistics**, including 117,936 typed numeric Excel cells. All average/min/max/counts independently recomputed by meter, metric and UTC elapsed-time bucket. **Five cumulative energy counter decreases per format** invalidate the respective energy delta; no synthetic power integration or inferred reset. The XLSX snapshot was checked independently rather than incorrectly compared with the earlier CSV snapshot. Result **PASS**.
- Live production collector **read-only** samples (UTC): 06:32:09 before — physical requests 123,795, saved samples 95,568, queue depth 0; 06:33:47 during export — 123,967 / 95,701 / 0; 06:37:13 after — 124,365 / 96,008 / 0. The collector remained healthy, with 570 additional physical requests and 440 additional samples. Existing bus timeout counter increased 14,109→14,174; **do not attribute these to the synthetic export without independent causal evidence**. No real hardware writes/polling were initiated by the test.
- Docker network `nexolab-energy-1364-isolated` verified `internal=true`, no published container ports; candidate rootfs read-only, `privileged=false`, 512 MiB/1.25 CPU; PostgreSQL 384 MiB. Offline, local-only execution confirmed for this isolated path, **not** a completed release-bundle offline acceptance.
- Fixture latest-projection correctness (2026-10-14): replace the temporary test-only hardcoded `sample_id=1` with the actual inserted sample IDs. On a newly created private PostgreSQL test database: 880 seeded samples, `max(telemetry_samples.id)=880`, `max(telemetry_latest.sample_id)=879` (one later tied source event), startup reconciliation gap=1 within the unchanged maximum 10,000. A fresh fixed-runner isolated smoke then completed **4/4 CSV/XLSX exports and 451/451 persisted synthetic ingested events**, 0 errors, OOM=false, peak cgroup=258,326,528 bytes, export RSS=97,927,168 bytes. Previous test-only database duplication error was resolved by using a distinct dedicated disposable database; no production changes.
- Hosted exact-head CI `7b675d744068238ffcdfaf9ed72bb4006549e0dd` (historical pre-fixture-fix revision) had **5/5 successful** workflows: CI, Authenticated Dashboard Acceptance, Refrigeration Browser Acceptance, Offline Bundle, Telegram Gateway. Authenticated Dashboard: **41/41 Chromium/Playwright tests** including Energy original PostgreSQL values, XLSX aggregation and mobile, 390/768/1440/1920 responsive screenshots, focus trapping/keyboard, 9 axes/zoom, local timezone presentation. Refrigeration browser: **6/6**; completed Offline Bundle is hosted CI evidence, not proof of this Pi production cutover. A new exact-head CI run is required after publishing this final fixture correction.

## Immutable source and isolation

- Execution date: 2026-10-14 UTC; host: actual Raspberry Pi 5, `aarch64`, Linux, 4 GiB RAM, SSD-backed isolated validation.
- NEXOLAB source: merged `main` commit `7f7afc3b8839c56bc1b989676fdd35e156d0a9d3`; isolated clean clone under `energy-1364-validation/source`.
- Candidate: **actual merged main backend source** bind-mounted **read-only** into a preexisting native ARM64 telemetry-service Python runtime image. This is mounted-source validation, **not** a new immutable release image, signed package or controlled production deployment.
- Dataset: synthetic only, 5 supported meters (four LE-01MP, one SDM120M), 44 supported series, seven days at a three-minute simulated cadence; 147,840 original scalar events including one deliberately missing observation, one invalid reading, tied timestamp, and counter reset.
- Database: dedicated internal Docker network without published ports; dedicated PostgreSQL 16.15 ARM64 container, its own named SSD volume and test-only databases.
- Export spool: independent named SSD volume, mounted only by isolated test containers. All reads of site collector health are nonmutating; no production PostgreSQL, data, container or volume changed.
- **Safety:** no Modbus requests, hardware writes, root actions, site cutover, backup restoration or production service restart.

## Predeclared budgets and observed result

| Constraint                   |                                Fixed gate |                                                                Observation |
| ---------------------------- | ----------------------------------------: | -------------------------------------------------------------------------: |
| Candidate cgroup memory      |                                  ≤512 MiB |                                       peak 485,818,368 B (463.3 MiB), PASS |
| Export child RSS             |                                  ≤256 MiB |                                        peak 100,139,008 B (95.5 MiB), PASS |
| PostgreSQL cgroup            |                                   384 MiB |                                        limit retained; no OOM in final run |
| CPU / PIDs                   | candidate 1.25 CPU / 256 PIDs; PG 0.5 CPU |                                                  limits enforced by Docker |
| Individual spool             |                                  ≤512 MiB |                                       largest recorded 119,312,853 B, PASS |
| Total spool / reserve        |                    ≤2 GiB / ≥128 MiB free |                software guards retained; isolated SSD-backed export passed |
| Per export                   |                              ≤600 seconds |                                                      longest 73.75 s, PASS |
| Normal ingestion advancement |     zero failed/rejected/lost after drain | 2,212 accepted, 2,212 persisted, 0 rejected and 0 ingestion failures, PASS |
| OOM / container restart      |                                      zero |                                    final candidate exit 0; oom=false, PASS |

## Four actual exports: full seven-day workload

| Format                     | Source events captured at independent snapshot | Output rows | Artifact bytes | Elapsed |
| -------------------------- | ---------------------------------------------: | ----------: | -------------: | ------: |
| RAW CSV                    |                                        147,893 |      16,854 |     23,570,858 | 44.34 s |
| RAW XLSX                   |                                        148,310 |      17,271 |      6,007,624 | 73.75 s |
| 10-minute avg/min/max CSV  |                                        149,050 |       5,040 |      8,207,036 | 36.51 s |
| 10-minute avg/min/max XLSX |                                        149,400 |       5,040 |      2,137,736 | 37.61 s |

Snapshots intentionally differ: 10 synthetic events/s continue entering PostgreSQL throughout the four exports. RAW CSV was independently checked against every original source event identity and its numeric value, not only file row count. Subsequent **independent RAW XLSX read-only reconciliation** against stored PostgreSQL rows verified **147,840/147,840 original event IDs and values**, no duplicates; 17,271 Excel data rows; XLSX ZIP/typed-cell checks passed. The wide-row strategy legitimately produces fewer rows than scalar original events.

Smoke on the final class of SSD-backed test setup: 4/4 artifacts, 504 accepted/persisted; no errors, RSS peak 98,467,840 B, cgroup peak 277,725,184 B. The full 147,840-event run lasted 292.34 s including setup, 30 s pre-load and 30 s post-export; final benchmark `result=PASS`. Final stricter database/volume fail-closed runner was independently smoke-validated with 4/4 exports, 411/411 submitted/persisted events, zero rejection and OOM=false (runner SHA-256 `784cb471f3dc962b7157391bba981a99ed764bb98fb8f726eb1ccd5de2085e17`).

## Traceable test-environment repairs (not product defects)

1. Early full run used a 256 MiB PostgreSQL tmpfs: PostgreSQL ran out of space and that **isolated test database container** was OOM-killed. Replaced that tmpfs **only for the test** with a separate 384 MiB-capped PostgreSQL container and dedicated SSD volume.
2. Next early full run had a 512 MiB tmpfs for export staging: expected free-reserve gate correctly rejected export before rendering. Replaced only the isolated spool with its own SSD volume, without relaxing 512 MiB/job, 2 GiB total, or 128 MiB reserve.
3. A benchmark-only SQLAlchemy 2 `CursorResult` → dictionary conversion error was fixed in the new test runner, and the smoke-test was repeated.
4. The successful full run used test-runner SHA-256 `011f56c8dafdd6aaaec5da37221292f90cced677101e81b6e5fbc51913b7cf26`; a later stricter fail-closed runner plus read-only XLSX verifier uses SHA-256 `784cb471f3dc962b7157391bba981a99ed764bb98fb8f726eb1ccd5de2085e17` before final post-edit verification. Candidate product implementation code remained unchanged.

## Distinct evidence, omissions and gates

- Real PostgreSQL/MQTT authenticated browser/software CI for graph #1362 and export #1363 was GREEN on merged feature heads. The native Pi benchmark is a separate read-only source-mount/isolated PostgreSQL resource test, **not** production deployment.
- The first direct benchmark measured only `p95_enqueue_ms = 0.246` for 2,212 events; that alone was **not** a persistence/API latency measurement. This gap was closed by two later isolated native HTTP scenarios, including a separate 30-second before-load live-ingestion baseline, measured persisted-event p95, API p95 and maximum lag; see the follow-on evidence above.
- Hosted Chrome E2E exact-head had 41/41 browser tests, with Energy responsive evidence at 390/768/1440/1920 widths, focus controls, chart interactions and original PostgreSQL history; focused backend API/owner denial and DST regressions are independently present in the existing test suite. **Actual production Pi browser UI** against a versioned protected release remains unverified, separate from hosted candidate acceptance.
- RAW XLSX identity/value reconciliation covered all 147,840 original saved events. Subsequently both 10-minute CSV and XLSX were independently recalculated against **their own** persisted PostgreSQL snapshots for source/valid/invalid counts and average/min/max, with five invalidated reset deltas per format; the more exhaustive separate hardware/site or release verification remains outside this synthetic fixture.
- Offline bundle matching selected revision/ARM64, protected backup/restore, guarded install and verified rollback are separate #1313/#1323/release gates. Accepted and deployed **C296** remains unchanged. **Do not display `🟢 Оновлюйся` yet.**

## Next checks

The native persisted-event/API p95, maximum-lag budgets, read-only collector sampling, independent CSV/XLSX aggregation, isolated smoke and hosted browser accessibility/keyboard/mobile paths now PASS. Publish final fixture correction to PR #1371; obtain refreshed exact-head CI and code review, then merge only on GREEN. Preserve separate #1313/#1323 immutable package, backup, rollback and guarded site-release gates; do not claim production acceptance or perform automatic production activation.
