# NEXOLAB Current State

Updated: 2026-08-06
Verified product baseline: `37107c073fa66d8db35f44932268934d3f5cd8ae`
Active control Work Package: Issue #335 — reconcile ADR registry completion and promote dependency lanes
Branch: `docs/335-reconcile-adr-completion`
Next Ready Work Package: Issue #328 — separate dependency update lanes and retire grouped major PRs
Active epic: Issue #326 — Engineering governance, security exception lifecycle and toolchain hardening
Parallel blocked epic: Issue #282 — acquisition software complete; physical Raspberry Pi/RS-485 acceptance pending
Status confidence: high for repository, CI, offline-runtime and security evidence; physical hardware acceptance remains explicitly pending.

## ADR governance completed

Issue #300 / PR #334 was squash-merged as `37107c073fa66d8db35f44932268934d3f5cd8ae` from exact verified head `f0f3a38e3649064662de2307836a4c1e522218ac`.

Completed outcome:

- `docs/adr/` is the authoritative ADR location;
- ADR 0001, 0004, 0005, 0008 and 0009 appear exactly once in the canonical registry;
- 0002, 0003, 0006 and 0007 are documented as unassigned historical gaps without invented decisions;
- `docs/architecture/adr-0001-telemetry-ingestion.md` remains a compatibility pointer;
- deterministic validation rejects duplicate identifiers, broken targets, missing compatibility linkage and undocumented gaps;
- CI, formatting, lint, typecheck, full tests, production build and Telemetry Service checks were GREEN.

## Ordered engineering-hardening queue

1. **Issue #328 — Ready:** dependency automation lanes and major-migration policy.
2. **Issue #253 — queued:** jsdom 30 migration.
3. **Issue #254 — queued:** Playwright 1.62.x migration.
4. **Issue #252 — queued:** lint-staged 17 migration.
5. **Issue #255 — queued:** TypeScript 6 transition.

Blocked or deferred:

- **Issue #257:** ESLint 10 remains blocked until a compatible Next.js/plugin graph is demonstrated.
- **Issue #256:** TypeScript 7 remains deferred until TypeScript 6 and ecosystem support are available.

PR #271 remains closed unmerged as a superseded grouped-major update. PR #272 remains independently open and unselected.

## Security exception boundary

The exact `telemetry-service + libcjson1 + CVE-2026-67216` exception remains narrow and expires on **2026-09-05**. Fixed version remains unavailable in the verified image evidence. Do not broaden or silently renew it.

## Parallel hardware boundary

Issue #289 remains classified:

```text
software verified; hardware performance acceptance pending
```

Hardware-dependent Issues #289, #245, #189, #200, #201 and #202 remain blocked by unavailable controlled Raspberry Pi/RS-485 access. No physical acceptance claim is permitted without real evidence.

## Guardrails for Issue #328

- modify dependency automation policy only;
- do not change dependency versions or `package-lock.json`;
- production runtime, development patch/minor and major migration lanes must remain distinct;
- unrelated major migrations must never share one PR;
- every major migration requires its dedicated Issue, branch and focused PR;
- no automatic major merge path;
- Node and `@types/node` majors must remain aligned with the supported Node 22 runtime boundary;
- PR #272 remains outside the decision scope;
- no runtime, database, product, hardware, Modbus, secret or deployment changes.

## Next action

Complete Issue #335 as an exact four-file state-only PR and merge it after GREEN CI. Then execute Issue #328 from current `main`: audit `.github/dependabot.yml`, implement deterministic dependency-policy validation, document triage/rollback/offline checks, and preserve dependency closure unchanged.
