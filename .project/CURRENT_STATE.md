# NEXOLAB Current State

Updated: 2026-08-11

Canonical repository baseline on `main`: `1a4ae8026f2b70c52a5fc41a1f8d22a99897463f` — PR #398 state reconciliation after the Issue #385 / PR #390 product merge.

## Completed Work Package — Issue #385

Issue #385 / PR #390 is completed and merged.

Delivered:

- four product roles: `administrator`, `laboratory_manager`, `engineer`, `laboratory_technician`;
- local-only Users & Access workspace at `/settings/users`;
- bounded server-authoritative permission catalog;
- administrator full access including `memberships.manage` and `project_versions.manage`;
- explicit persisted permissions for non-administrator product roles;
- role/permission/account/password lifecycle with affected-session revocation;
- transactional last-active-administrator protection;
- immutable redacted security audit events;
- offline-local authentication and user management without mandatory cloud identity;
- canonical migration `20260807_0024` after telemetry latest projection `20260807_0023`.

Verification:

```text
final PR head: 5d4aacc8d6d2c7157ef42bf0356d102700f78960
PR #390 merge: e0b124e9a0152be50966daa131974b3543651e87
final exact-head CI: 19/19 GREEN
hardware-tested product candidate: d37cf08af9560ffa0d18c102656301e667299836
Raspberry Pi: PASS, aarch64 / Debian 13.6 / Docker 29.7.1
production browser acceptance: 4 passed
persistence/recreation acceptance: 1 passed
acceptance exit_code: 0
```

Hardware evidence directory:

```text
/home/nexolab/nexolab-385-hardware.VGhXYn/evidence-retry-20260811T094325Z
```

No Modbus write, hardware write, production/site cutover, named-volume deletion or mandatory online runtime dependency was introduced.

Canonical Alembic chain:

```text
20260805_0022
  -> 20260807_0023 telemetry latest projection
  -> 20260807_0024 local membership permissions (head)
```

## Active Work Package — Issue #386

Product Owner priority override selects Issue #386 — canonical Chart Domain and local renderer benchmark — as the only active implementation lane. GitHub status is `status:in-progress`; branch is `feat/386-chart-domain-renderer-benchmark`.

Repository audit completed before implementation:

- current frontend is Next.js `16.2.12`, React `19.2.8`, TypeScript `6.0.3` with no chart dependency;
- Overview, Live Data, saved Live Dashboards, Energy Monitoring, Test Sessions and compact sparklines use independent custom SVG implementations;
- Live Data has the strongest current source-gap/quality segmentation, but its last-point-per-bucket reducer can lose short extrema;
- Reports currently expose rendered artifacts rather than a client chart implementation;
- Refrigeration equipment history currently means layout revision history, not telemetry plotting;
- open PRs #391–#395 are Dependabot-only and remain excluded from #386.

Local software implementation and deterministic benchmark are complete on the feature branch:

- canonical series identity, quality/freshness separation, continuity segments, statistics scope, time ranges and compatible-unit grouping;
- fail-truthful continuity and a bounded segment-aware min/max reducer with pinned threshold/alarm/event evidence;
- direct modular ECharts `6.1.0` adapter using a persistent Canvas instance, bounded incremental live-tail updates and explicit lifecycle cleanup;
- reusable accessible Chart Shell and renderer host contracts;
- deterministic scenarios A–L, including a production bundle exercised with container networking disabled;
- Raspberry Pi 5 arm64 measurements: 1×240 median 38.9 ms, 8×240 median 103.8 ms / p95 169.0 ms, 100-update median 12.3 ms / p95 31.2 ms, 1,000-update median 6.1 ms;
- local gates: format, lint, typecheck, 76 files / 336 tests plus lint-staged compatibility, and the Next.js production build are GREEN.
- exact locally tested implementation commit: `80ff2ebd3a51398578e90c7fe36c852ce95321b7`;
- focused draft PR #399 is open with `Closes #386`; published head `6a63c04b6dee25a392a9dd370332098d9223cd20` passed all 11 exact-head GitHub checks, including Offline Bundle and acquisition-invariant integration acceptance.

The isolated renderer delta is 608,623 bytes minified / 202,927 bytes gzip. The browser observed zero public requests and no horizontal overflow at 360, 1280, 1440 or 1920 px. Published exact-head GitHub CI is 11/11 GREEN. The first Offline Auth attempt failed before the acceptance script emitted a result; the unchanged exact-head migration round trip passed locally and its focused GitHub rerun passed, so no unrelated auth change was introduced.

Issue #386 is limited to shared chart-domain, adapter, benchmark harness, tests and audit evidence. Production pages are not migrated. No REST/WebSocket, acquisition, polling, Device Agent, scheduler, registry, Modbus or hardware behavior changes are permitted.

Issue #389 remains open and `status:ready`, but is `ready_not_selected` until the Chart System lane completes. The prepared runtime sequence remains unchanged:

```text
#369 -> #366 -> #289
```

Issues #369 / #366 / #289 retain their existing product scope and ordering. Issue #245 remains a separate Raspberry Pi validation track.

## Security boundary

The existing `telemetry-service/libcjson1/CVE-2026-67216` exception still expires on 2026-09-05 and was not broadened by Issue #385.

## Next action

Refresh the four state records on PR #399, obtain exact-head CI for that state-only commit, audit unresolved reviews and mergeability against current `main`, then merge only if every required check remains GREEN. Raspberry Pi chart performance is verified; the physical acquisition invariant remains pending a controlled Device Agent/Modbus request-rate test. After a GREEN merge, create or refine the first production-consumer Work Package: migrate Live Data to the canonical Chart System.
