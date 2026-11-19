# NEXOLAB — verification matrix and Definition of Done

**Scope:** source verification, PR review, offline acceptance, protected Raspberry Pi runtime and field devices. This is a procedural matrix under `docs/AI_DEVELOPMENT_OPERATING_STANDARD.md`; it does **not** replace GitHub branch protection or exact-head CI classification.

## Test levels — always distinguish them

| Gate                           | When                                     | Required evidence                                                                                                                                                  | Result status                           |
| ------------------------------ | ---------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ | --------------------------------------- |
| T0 — specification             | Before Ready                             | Issue outcome, reproduction/current vs expected, dependencies, permitted paths, out-of-scope, acceptance, safety/offline/hardware impact and verification plan     | ready / not_ready                       |
| T1 — touched source            | During code change                       | Changed-file format/lint/syntax and focused regression for the exact defect                                                                                        | software_check_pass / fail              |
| T2 — module and contracts      | Completed feature WP                     | Affected module tests, TypeScript/compile, API contracts, DB additive migration/downgrade guards where relevant                                                    | module_verified / fail                  |
| T3 — PR exact-head             | Before merge                             | Required `NEXOLAB Merge Gate` plus **all externally triggered workflows on the same head**, full production build when required, review and diff safety            | source_accepted / blocked               |
| T4 — isolated/offline          | Before risky release                     | ARM64 package identity, offline startup, no internet dependency, MQTT/API isolation, restart/outage, backup preservation and rollback as scoped                    | offline_verified / blocked              |
| T5 — real operator browser/API | After authorized staging/site activation | Actual authenticated roles/org, direct URL/API deny, sensor selection, multi-series history, WebSocket/API and data freshness, version parity across approved URLs | operator_verified / blocked             |
| T6 — physical acquisition      | Only with real device access             | Exact stable serial by-id identity, actual read-only FC03/FC04 responses, timestamps, units, quality, disconnected behavior and equipment mapping                  | hardware_verified / hardware_unverified |
| T7 — protected release         | After owner-authorized site action       | Independent complete backup/restore, exact deployed artifact, reversible transition, evidence of surviving history and off-LAN access                              | site_accepted / blocked                 |

**Do not promote T1/T2/T3 to hardware or site acceptance.** Stale data may never be described as Live. No mock/dummy/fallback qualifies as evidence of physical commissioning. T4/T5/T6/T7 are separate gates and may remain pending after source merge.

## Change-impact routing from the real repository

`scripts/classify-ci-impact.py` determines exact-head CI workflow selection from the changed-file set. An unknown path must fail closed and broaden checks; never weaken a required check just because it is slow.

| Changed surface                       | Local first                                                                                      | Required remote/final validation                                                            |
| ------------------------------------- | ------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------- |
| Only four canonical `.project/` files | Parse JSON; `python3 scripts/validate-project-state.py`; format + explicit WIP/dependency review | CI `State integrity` + `NEXOLAB Merge Gate`                                                 |
| Docs/ADR/runbooks                     | Cross-check current source/Issue; changed-file Prettier and link/contract review                 | Repository-classified full CI quality (docs-only is **not** state-only)                     |
| Frontend components                   | Focused Vitest, changed-file ESLint/format, `npm run typecheck`                                  | Core CI + appropriate authenticated Dashboard browser workflow + production `npm run build` |
| Telemetry API/migrations              | Focused Python pytest, compile, Alembic single-head and non-destructive upgrade path             | Telemetry Service + Core CI and database-backed/contract acceptance                         |
| Device Agent / RS-485                 | Recorded read-only frame tests, bus timeout/retry/quality cases, compile/pytest                  | Device Agent/Edge-related CI; actual hardware remains a separate T6                         |
| Shared auth/permissions               | Unauthorized direct-route/API tests, token scope/session invalidation, org switch                | Full routed auth/security browser acceptance, exact-head CI and offline auth                |
| Refrigeration graphs                  | Channel ID vs friendly label, cursor/zoom/cycle/CSV, missing/stale and historical intervals      | Refrigeration Browser Acceptance and full routed CI                                         |
| Offline packaging/Docker/network      | Profile invariant tests, CI-impact routing, Docker Compose validation where applicable           | Offline Bundle, security/edge checks, simulated restart/rollback, T4 + separate T7          |
| Build/dependency/toolchain            | Offline dependency and license review, ARM64 support, lockfile audit                             | Full routed quality/supply-chain, reproducible install/build and rollback                   |

Existing Windows orchestrator: `./scripts/verify-project.ps1 -Component All`. Use `-Component Frontend`, `Telemetry`, or `DeviceAgent` where the WP is bounded; add `-IncludeComposeValidation` only for Compose contracts. The script runs frontend `lint`, `typecheck`, `test`, `build`, backend Python compile/`pytest`, Device Agent compile/`pytest`. Do **not** rerun the full `All` suite after every small edit: perform T1 first, T2 at WP completion, required routed T3 before merge.

## Risk-specific regression suites, in milestone order

| Milestone                     | Tests that must be demonstrated before declaring that result Done                                                                                                                                                                                                                                                                                   |
| ----------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| G1 DR                         | Inventory ALL local stores (PostgreSQL, object store/metadata, MQTT/dynamic ACLs, edge SQLite/outbox, auth signing pair/config); prove bounded capacity/headroom; encrypted independent off-device copy and isolated restore; check schema, counts, object hashes, queue/identity, offline login. Synthetic harness is **not** a substitute for T7. |
| G2 offline/local              | Wired/Wi-Fi route/bridge conflict detector, controlled Docker restart, ports, DNS and tailscaled restart from authorized client; no WAN core dependency; MQTT/API and acquisition remain independently diagnosable; rollback after approved protected change.                                                                                       |
| G3 telemetry reliability      | Accepted event_id dedupe, captured_at recency, QoS1 reconnect/outbox, bounded retries, receipt only after PostgreSQL commit, replay after broker drop, persisted data across restarts, backlog overflow cases. T6 for each actual instrument.                                                                                                       |
| G4 version parity and release | Exact approved source manifest (different origin-specific build IDs documented, not silently normalized), schema/API and Device Agent compatibility, local auth/Google access, all operator URLs, preserved 6+2 Dixell channels and four reserve channels, 10-second series advancing, multi-series history, rollback and off-device backup.        |
| G5 access and onboarding      | UI navigation hidden when not granted AND direct route/API returns deny; org switch invalidates state; 401 reauth; USB adapter hotplug; read-only search finds multiple responders; named instrument with no chamber; SDM120/Waveshare read-only, unavailable sensors show honest quality; no fake completed setup.                                 |
| G6 analytics                  | Metrological instrument calibration provenance, gauge/absolute pressure and atmospheric reference, offline property-engine golden points, quality propagation, versioned derived metrics, real physical sensor placement and uncertainty before kW/COP.                                                                                             |

## Evidence record attached to each Issue / PR

```text
Work Package / Issue:
Feature branch / PR:
Approved scope and permitted paths:
Exact source head SHA:
Reviewed diff and detected overlaps:
T1 targeted checks (commands, result, environment):
T2 module/contract checks (commands, result):
T3 required GitHub workflows (names, run IDs, exact head, GREEN/FAIL):
T4 isolated/offline tests (artifact ID, source, result):
T5 real browser/API acceptance (environment, URL class, auth/role, result):
T6 hardware (device by-id/model/firmware, read-only evidence, quality): UNVERIFIED / VERIFIED
T7 protected release (operator approval, SHA, backup, rollback, site evidence): NOT_DEPLOYED / VERIFIED
Open blockers (soft/hard):
Risks:
Next genuinely Ready Issue:
```

## Work Package checkpoints and failure rules

- A CI rerun invalidates prior GREEN if product source changes after that run. Every final merge must target the **same exact head** used for review and required workflows.
- **Merge** only when required CI GREEN. Do not close a hardware/site acceptance Issue at mere PR merge if the Issue requires physical evidence.
- An unavailable physical device must be `hardware_unverified`, never green by synthetic fixtures.
- Test cases must use real permission-denied and stale data conditions as negative tests. Do not suppress failures by loosening selectors without preserving the actual user behavior.
- No FC05/FC06/FC15/FC16, Modbus writes, controller configuration or production-site cutover in tests.
- Any migration, volume or protected network action requires a separate preflight and owner-authorized execution after complete rollback and backup proof.
- Every failed gate records the narrowest cause and one next action. Resume an independent Ready task instead of repeatedly rerunning broad unchanged CI.
- Only emit the final operator signal `🟢 Оновлюйся` once an exact approved ARM64/site package, recovery point, rollback, CI, and authorization are all established; never on source merge alone.

## Portfolio health checks at every Sprint planning pass

Maintain one active **implementation** (a coordinating parent Epic is not the implementation WP), no more than three independent Ready candidates, blockers with owners/evidence, a traceable PR for every source WP, and an up-to-date T0–T7 gate map. Freeze dependency-bot churn while high-priority recovery and critical security work is unresolved; assess urgent security fixes separately. Verify that all pending review PRs correspond to a live Issue or a documented orphan/maintenance proposal before reusing code.

Source of truth remains `PROJECT_PROFILE.yaml`, `AGENTS.md`, `docs/AI_DEVELOPMENT_OPERATING_STANDARD.md`, four canonical `.project/` files, live GitHub issue/PR/CI state, and actual installed runtime/hardware evidence. This document is a gate map, not a claim that any currently missing physical test has been performed.
