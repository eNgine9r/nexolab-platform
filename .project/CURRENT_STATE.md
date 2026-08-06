# NEXOLAB Current State

Updated: 2026-08-06
Verified software baseline: `37107c073fa66d8db35f44932268934d3f5cd8ae`
Active control Work Package: Issue #335 — reconcile ADR registry completion and promote dependency lanes
Branch: `docs/335-reconcile-adr-completion`
Next Ready Work Package: Issue #328 — separate dependency update lanes and retire grouped major PRs
Active epic: Issue #326 — Engineering governance, security exception lifecycle and toolchain hardening
Parallel blocked epic: Issue #282 — acquisition software complete; physical Raspberry Pi/RS-485 acceptance pending
Status confidence: high for ADR governance, exact-image security evidence, merged software and disconnected runtime; physical hardware acceptance remains explicitly pending.

## ADR registry completed

Issue #300 / PR #334 was squash-merged as `37107c073fa66d8db35f44932268934d3f5cd8ae` from exact verified head `f0f3a38e3649064662de2307836a4c1e522218ac`.

The merged governance boundary provides:

- `docs/adr/` as the authoritative ADR location;
- a canonical registry containing ADR 0001, 0004, 0005, 0008 and 0009 exactly once;
- unchanged accepted ADR-0001 decision content at `docs/adr/0001-central-telemetry-ingestion.md`;
- an explicit compatibility pointer at the published `docs/architecture/adr-0001-telemetry-ingestion.md` path;
- truthful classification of 0002, 0003, 0006 and 0007 as unassigned historical gaps because no supported repository evidence assigns them;
- permanent identifier, filename, status and supersession conventions;
- a standard-library validator for filesystem, heading, registry, gap and link integrity;
- deterministic tests for valid registry, duplicate identifier, broken target, missing legacy pointer and undocumented gap;
- mandatory ADR validation in CI.

Published ADR identifiers were not renumbered and existing decision content was not rewritten.

## Exact-head evidence for PR #334

GREEN on `f0f3a38e3649064662de2307836a4c1e522218ac`:

- standalone Raspberry Pi runtime contract validation;
- ADR registry validation;
- all five ADR validator fixtures;
- formatting;
- lint;
- typecheck;
- full tests;
- production build;
- Telemetry Service integration, outage recovery, migration SQL and container build.

Final focused diff contained six documentation/validation files. Temporary formatter workflow was absent. No runtime dependency, database migration, frontend, backend, acquisition, Modbus, hardware or production-cutover behavior changed.

## Ordered engineering-hardening queue

1. **Issue #328 — Ready:** separate dependency update lanes and retire grouped major PRs.
2. **Issue #253 — queued:** jsdom 30 migration.
3. **Issue #254 — queued:** Playwright 1.62.x migration.
4. **Issue #252 — queued:** lint-staged 17 migration.
5. **Issue #255 — queued:** TypeScript 6 transition.

Deferred or blocked:

- **Issue #257:** ESLint 10 remains blocked until a compatible Next.js/plugin graph is demonstrated.
- **Issue #256:** TypeScript 7 remains deferred until TypeScript 6 and ecosystem support are available.

PR #271 remains closed unmerged as a superseded grouped-major update. PR #272 remains independently open and unselected.

## Security review boundary

The exact `telemetry-service/libcjson1/CVE-2026-67216` exception remains narrow, owned by `platform-security` and due for exact-image review on **2026-09-05**. Do not broaden it or infer that a fixed package exists without rebuilding and rescanning the current image.

## Parallel acquisition and hardware boundary

Issue #289 remains:

```text
software verified; hardware performance acceptance pending
```

Hardware-dependent Issues #289, #245, #189, #200, #201 and #202 remain blocked by unavailable controlled Raspberry Pi/RS-485 access. Independent software hardening may continue without changing their classification.

## Next action

Complete Issue #335 as an exact four-file state-only PR. Then execute Issue #328 from current `main`: inspect `.github/dependabot.yml`, define focused production/dev/major update lanes, add deterministic policy validation, preserve Node 22 alignment, and make no dependency-version changes.
