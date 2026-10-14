# Energy history export — native Raspberry Pi acceptance evidence (#1364)

**Status:** native isolated synthetic large-export/resource slice PASS; **full WP acceptance OPEN** pending the remaining latency, browser and release gates below.

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
- The benchmark measures `p95_enqueue_ms = 0.246` for 2,212 normal submitted events. **This is not persisted-event p95, API p95 or worst-case persistence lag**; those fixed Issue #1364 budgets still need independent native measurements. Baseline telemetry 30 s before ingestion started, therefore a proper pre-load persistence/API baseline has **not** been established by this run.
- Full mobile 390/768/1440/1920, DST, auth-denial and PostgreSQL data semantics were tested previously in scoped frontend/backend/browser CI; actual production Pi browser UI against this candidate has not yet been accepted.
- Independent exact-cell XLSX checks covered **RAW original identities and values**, not a full independent recomputation of all 10-minute statistics/counter anchors; the latter remain supported by existing suite and need final WP evidence reconciliation.
- Offline bundle matching selected revision/ARM64, protected backup/restore, guarded install and verified rollback are separate #1313/#1323/release gates. Accepted and deployed **C296** remains unchanged. **Do not display `🟢 Оновлюйся` yet.**

## Next checks

Complete native persisted-event/API p95 and max-lag budgets, before/during/after collector counters, full independent aggregation and required browser paths, smoke-test final hardened runner; publish focused #1364 PR with required CI/review and keep Issue open until all acceptance items actually pass. No automatic production activation.
