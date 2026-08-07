# NEXOLAB Blockers

Updated: 2026-08-07

## Active critical Work Package — Issue #368

Issue #368 — **Make telemetry latest reads independent of history volume** — is active on PR #373.

It preempted Issue #366 after controlled Raspberry Pi evidence proved that the generic latest telemetry endpoint remained history-volume-bound on the existing long-running PostgreSQL database:

```text
GET /health/ready
HTTP 200 in 0.002680 s

GET /api/v1/live-dashboards/channel-inventory
HTTP 200 in 0.050279 s
162 canonical channels

GET /api/v1/telemetry/latest?limit=1&offset=0
client timeout after 20.002650 s
HTTP 000 / zero response bytes
```

Repository diagnosis confirmed that `Database.latest_samples` ranked retained telemetry history before applying latest pagination. Caching this response in frontend route models would hide, not fix, the backend defect.

### Software status

Verified implementation head before state reconciliation:

```text
8b44241df429cedb6c28a8382bbd43ae4c285fd7
```

Software verification on that head is GREEN:

- 26 current GitHub checks completed with zero failures;
- Telemetry Service PostgreSQL migrations and full MQTT/REST/WebSocket/object-storage/dead-letter/retention suite GREEN;
- PostgreSQL outage recovery GREEN;
- offline Alembic SQL GREEN;
- container build GREEN;
- large-history latest-projection regression GREEN;
- authenticated/operator browser regressions GREEN;
- Offline Bundle disconnected startup GREEN;
- Offline Bundle update/rollback persistent-data preservation GREEN;
- Disaster Recovery TLS fleet GREEN on isolated rerun after an initial runner/startup flake that had no service/runtime diagnostics and required no code change.

### Remaining hard acceptance boundary

Issue #368 is **not yet fully accepted** because the original physical Raspberry Pi case must be rerun against the same existing long-running PostgreSQL database after deploying the candidate.

Required physical evidence:

- direct `GET /api/v1/telemetry/latest?limit=1&offset=0` completes instead of exceeding 20 seconds;
- normal LOCAL_LAN target `<500 ms` is measured, not assumed;
- central smoke completes without increasing timeout/retry budgets;
- no history truncation, reset, volume deletion or clean-database substitution is allowed.

Current classification:

```text
software verified; Raspberry Pi latest-query acceptance pending
```

The physical retest is the only remaining Issue #368 acceptance blocker after final state-head CI/review audit.

## Issue #369 — next focused Work Package after #368

Issue #369 — **Raspberry Pi browser acceptance for canonical Live Dashboard inventory** — is `status:ready`, priority critical, and must run immediately after #368 acceptance.

The same controlled Raspberry Pi evidence that exposed #368 also showed:

- canonical inventory backend: healthy, 162 items in ~50 ms;
- actual operator browser: inventory remained empty/unusable and dashboard creation could not be completed.

This is a separate browser/runtime acceptance gap. #369 owns exact browser/API capture, TypeScript runtime parser/contract validation, rendering/select/reorder/save acceptance, and a regression proving inventory loading makes zero generic `/telemetry/latest` calls.

Do not mix #369 into #368. The generic latest database fix and actual-Pi Live Dashboard browser flow remain separate focused Work Packages.

## Issue #366 — blocked by #368 and sequenced after #369

Issue #366 — **Audit and deduplicate monitoring-route read models** — remains `status:blocked`.

Reason:

- #366 must optimize route-local non-telemetry read ownership and request deduplication against a correct bounded latest telemetry contract;
- the actual-Pi Live Dashboard inventory browser gap is already isolated in #369 and should be accepted first;
- #366 must not introduce longer TTLs/timeouts or another telemetry cache to conceal the >20-second backend latest query.

Canonical sequence:

```text
#368 → #369 → #366 → #289
```

## Issue #370 — superseded state-only package

Issue #370 was created only to reconcile the same Raspberry Pi negative-acceptance evidence into `.project` files. PR #373 now performs that authoritative reconciliation as part of the active Work Package checkpoint. #370 has therefore been closed `not_planned` to avoid a duplicate state-only branch/PR.

## Issue #245 — validation track, not software Ready

Issue #245 remains `status:needs-validation`.

Reason:

- PR #246 already merged the standalone runtime software scope as `83b161ca7e26580c46789e76a7bbdc0d5e434c21`;
- exact-head software CI, Telemetry Service and Offline Bundle evidence was GREEN;
- the latest physical Raspberry Pi evidence records standalone deployment blocked on actual-host runtime health before loopback-only reboot/observation acceptance could be completed.

Do not create a second software implementation branch for #245.

## Issue #289 — needs validation

Issue #289 remains `status:needs-validation`, priority critical.

Its final acquisition, route-latency and request-count matrix should run after #368, #369, #366 and the remaining Epic #356 navigation optimization slice so measurements target the completed performance architecture.

This sequencing does not authorize any Modbus/hardware write or change the physical polling envelope.

## Toolchain lanes

Issue #257 remains blocked until the resolved Next.js ESLint plugin graph supports ESLint 10 without broad rule weakening.

Issue #256 remains deferred until TypeScript 7 support is confirmed across Next.js, Vitest/Vite and ESLint integration boundaries.

## Dependency lanes

Open unselected dependency PRs: #340, #341 and #346.

PR #347 remains obsolete because Playwright 1.62 already merged through Issue #254 / PR #352.

These dependency PRs must not interrupt #368 → #369 → #366 unless a separate dependency Work Package is selected later.

## Remaining physical acceptance

- Issue #368: software GREEN; Raspberry Pi latest-query acceptance pending on existing long-running DB.
- Issue #369: software evidence exists for canonical inventory; actual Raspberry Pi browser render/select/save acceptance pending.
- Issue #355: software fix exists; issue reopened after negative Raspberry Pi acceptance; residual browser gap is owned by #369.
- Issue #357: software fix exists; issue reopened after negative Raspberry Pi acceptance; perceived-latency evidence remains pending.
- Issue #245: actual standalone Raspberry Pi acceptance blocked on recorded actual-host runtime health.
- Issue #289: hardware performance acceptance pending.
- Issues #189, #200, #201 and #202 remain hardware-dependent according to their existing evidence boundaries.

## Security boundary

The exact `telemetry-service/libcjson1/CVE-2026-67216` exception expires on **2026-09-05**. Do not broaden it.

`/lockers`, physical cameras, ONVIF/RTSP and NVR remain blocked or unverified by their existing evidence requirements.

## Global hard-stop rules

Stop before destructive data or volume operations, production cutover, hardware writes, secret exposure, mandatory online runtime dependencies, grouped migrations or unsupported physical acceptance claims.
