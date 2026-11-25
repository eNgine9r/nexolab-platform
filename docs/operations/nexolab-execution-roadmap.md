# NEXOLAB — dependency-driven roadmap and work queue

> **Snapshot:** 2026-11-19, `eNgine9r/nexolab-platform`. The live GitHub Issue/PR state and four canonical `.project/` files remain authoritative; this inventory is a dated reconciliation, **not a continuously updated automation**. Generated from 73 open Issues (including #1598) and 46 open PRs. No issue or PR was closed or deployed as a consequence of classification.

## Purpose and hard constraints

Restore predictable feature development for a laboratory operator without harming the existing offline-first LOCAL_LAN monitoring system. Every feature must improve a tested vertical workflow, not merely add another page or preview. One executable Work Package = one Issue + one feature branch + one focused PR. Parents/Epics are coordination containers and must not be marked executable Ready. **Max one implementation in progress** and **max three genuinely independent Ready Work Packages**; a review candidate does not consume the implementation slot but must have explicit acceptance ownership. Critical bugs may interrupt with documented priority.

Never require internet, CDN, paid runtime, remote fonts, SaaS telemetry or cloud backup for the core product. Modbus/hardware writes, destructive data changes, DNS/billing and production/site cutover remain prohibited without separate explicit approval.

## Milestone order and release criteria

| Gate | Product milestone                                      | Entry / exit (minimum evidence)                                                                                                                                          | Prominent existing work                                          |
| ---- | ------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------- |
| G0   | Execution control and backlog ownership                | Every open Issue/PR classified; active=1; no fake Ready; checkpoint and test matrix reviewed                                                                             | #1598                                                            |
| G1   | Proven recoverability and storage headroom             | Read-only DR inventory and capacity first; encrypted independent off-device full-store backup **and an isolated restore** are required before risky deployment           | #1460 → #1428; #1551 only after proof                            |
| G2   | Reliable offline boot, routes and network topology     | On-device read-only route/IPAM and rollback baseline; protected network change only after G1 with owner approval; real offline/reboot acceptance                         | #1409 → #1392/#1393/#1400 → #1399; #1567 independent tunnel gate |
| G3   | Durable measurement delivery                           | Committed ACK + edge replay across outages, no silently lost or fabricated readings; honest freshness by cadence                                                         | #1397 → #1445/#1449/#1451; #1522 independent source              |
| G4   | One supported operator release                         | One source lineage with approved per-origin build manifests, retained commissioning Agent, matched API/schema; auth, charts, LAN/Funnel and rollback accepted on real Pi | #1587 after G1+required G2/G3 gates; #1577, #1564, #1569         |
| G5   | Operator productivity, permissions, device onboarding  | Reliable RBAC + direct URL denial, simple standalone RS-485 device flow, validated Energy/Waveshare/Dixell, truthful series naming and Live UI                           | #1528 → #1530 under #1526; #1518 / stacked onboarding; #1191     |
| G6   | New scientific measurement and refrigeration analytics | Only after base runtime is stable; start RFX-00 ADR, then generic measurement registry and verified read-only physical pathways                                          | RFX-00…RFX-19 proposals, **not yet declared completed or Ready** |

**Critical dependency correction:** #1428's full DR preparation cannot wait on #1399 protected network _activation_, because #1399 activation itself must be protected by DR. Source-only DR inventory/preflight (#1460) is independent. On-site activation for #1399/#1409 is a **downstream** gate from verified #1428 recovery evidence, not a prerequisite for collecting backup readiness evidence. Separate read-only software readiness, deployment authorization and hardware acceptance in every Issue.

## Short execution window (not permission for production cutover)

| Slot | Work Package                        | State / exact next gate                                                                                                                               | Why                                                   |
| ---- | ----------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------- |
| 0    | #1598                               | This governance Issue/PR, no product code                                                                                                             | Establish deterministic execution policy              |
| 1    | #1460 / PR #1461                    | **First source review candidate:** reconcile exact diff against current main, run required CI and validate read-only inventory/capacity preflight     | Reduces uncertainty before protected DR               |
| 2    | #1428                               | **Site-evidence blocked:** actual complete encrypted backup, verified separate custody, isolated restore, operator approval if physical action needed | Stops unsafe releases                                 |
| 3    | #1409, then #1392/#1393/#1400/#1399 | **Source review permitted; site change blocked** until G1 and separately scoped owner approval                                                        | Fix LAN collision, boot recovery safely               |
| 4    | #1397 → #1445/#1449/#1451           | Validate separate staged source PRs, exact committed-receipt contract and offline replay                                                              | Prevent silent data loss                              |
| 5    | #1587 + #1577                       | Prepare one approved versioned release; exact hardware and browser evidence only after guarded activation                                             | One truthful operator version                         |
| 6    | #1522                               | **Next independent source Ready candidate**, focused freshness regression and no site mutation                                                        | Fix false Live/Stale                                  |
| 7    | #1528 → #1530 / umbrella #1526      | Review security-grant foundation PR #1529 before PR #1531; server-side enforcement first                                                              | No UI-only access illusion                            |
| 8    | #1518 / onboarding and #1191        | Reconcile stacked PR history and do operator acceptance vertically; preserve tested devices/history                                                   | Usable equipment workflow                             |
| 9    | RFX-00                              | Backlog until G1–G5 release/architecture review                                                                                                       | Avoid building advanced calculations on unstable data |

## Intake, execution and WIP rules

1. **New request:** record one problem/outcome, assign Epic and priority; do not enter Sprint before verification and dependencies are specified.
2. **Ready gate:** Issue has current vs desired behavior, dependencies, acceptance criteria, explicit scope/out-of-scope, permitted paths, test plan, offline/security/hardware needs. No unresolved architectural decision or conflicting live ownership.
3. **Active gate:** choose highest-priority truly Ready Issue; exactly one feature branch and one focused PR. A parent with many child PRs is not an executable Work Package.
4. **Review gate:** reconcile stacked/open branch with accepted main, run affected local checks then required exact-head workflows; no old-green reuse.
5. **Source Done:** exact-head CI GREEN, review accepted, no unresolved source blockers, Issue updated. Site acceptance is separate and stays open when required.
6. **Release/Hardware Done:** actual approved package, off-device DR protection, rollback, authenticated API/browser, offline readiness and real read-only device evidence. No mocked acceptance.
7. **Soft blocker:** record owner and evidence in `.project/BLOCKERS.md`, move task to blocked, pick next independent Ready. **Hard blocker** stops only affected irreversible work, not all safe analysis.
8. **PR backlog:** preserve all 46 currently open PRs. Do not merge or close based on age. For every stacked PR: compare to main → identify already-merged overlap → test source scope → choose rebase/recreate/close with evidence. Dependency bot PRs are frozen outside a distinct security/toolchain maintenance WP.

## Portfolio snapshot: every open Issue exactly once

The `Sprint` column below reports the previously recorded `.project/ACTIVE_SPRINT.json` lifecycle, or `untracked` if absent. This is descriptive evidence, not proof that work is currently running. Real tasks may be blocked at the site stage after code is merged.

### E0 — Управління виконанням, CI та toolchain (9)

_Queue:_ Поточна підготовка / відкладені оновлення.

| GitHub Issue                                                                                                                                                          | Current Sprint marker |
| --------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------- |
| [#1598 — [GOVERNANCE][WP] Organize NEXOLAB roadmap, all open work and verification gates](https://github.com/eNgine9r/nexolab-platform/issues/1598)                   | `untracked`           |
| [#1401 — [P1][DEVENV] Repair zero-byte Git object in shared Raspberry Pi engineering worktree](https://github.com/eNgine9r/nexolab-platform/issues/1401)              | `untracked`           |
| [#1402 — [P0][CI] Register scoped offline recovery verification files without weakening unknown-path gates](https://github.com/eNgine9r/nexolab-platform/issues/1402) | `untracked`           |
| [#1372 — Fix CI unreachable required workflows for isolated Energy acceptance runner](https://github.com/eNgine9r/nexolab-platform/issues/1372)                       | `untracked`           |
| [#1356 — Stabilize the terminal Live Retry acceptance stimulus after real WebSocket authentication](https://github.com/eNgine9r/nexolab-platform/issues/1356)         | `untracked`           |
| [#1487 — [CI][BLOCKER] Trivy installation exits 6 before container evidence generation](https://github.com/eNgine9r/nexolab-platform/issues/1487)                     | `blocked`             |
| [#1064 — [SHADOW ACCEPTANCE] Autopilot v3 one-shot coding worker](https://github.com/eNgine9r/nexolab-platform/issues/1064)                                           | `untracked`           |
| [#257 — [MAINT] Upgrade ESLint 9 to 10 only with a compatible Next plugin graph](https://github.com/eNgine9r/nexolab-platform/issues/257)                             | `untracked`           |
| [#256 — [MAINT] Evaluate TypeScript 7 native compiler after the TypeScript 6 transition](https://github.com/eNgine9r/nexolab-platform/issues/256)                     | `untracked`           |

### E1 — Збереження даних, DR та контроль диска (5)

_Queue:_ P0 — перша виробнича передумова.

| GitHub Issue                                                                                                                                                                  | Current Sprint marker |
| ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------- |
| [#1428 — [P0][OFFLINE DR] Schedule complete, space-bounded recoverable local backups and isolated restore on Raspb](https://github.com/eNgine9r/nexolab-platform/issues/1428) | `in_progress`         |
| [#1460 — [P0][OFFLINE DR][WP] Fail-closed read-only complete-backup inventory and capacity preflight](https://github.com/eNgine9r/nexolab-platform/issues/1460)               | `untracked`           |
| [#1555 — [STORAGE] Reclaim only regenerable caches on inactive fallback microSD, preserve NEXOLAB emergency boot](https://github.com/eNgine9r/nexolab-platform/issues/1555)   | `untracked`           |
| [#1551 — [P1][STORAGE] Evidence-safe 30-day telemetry retention and bounded Raspberry Pi disk reclamation](https://github.com/eNgine9r/nexolab-platform/issues/1551)          | `untracked`           |
| [#189 — [WP] Prove backup, restore, rollback and power-loss recovery](https://github.com/eNgine9r/nexolab-platform/issues/189)                                                | `blocked`             |

### E2 — Стабільний LOCAL_LAN / автономний runtime (9)

_Queue:_ P0 — після незалежного DR-доказу для site-change.

| GitHub Issue                                                                                                                                                            | Current Sprint marker |
| ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------- |
| [#1409 — [P0][SITE NETWORK] Migrate live edge Docker bridge away from physical LAN without losing telemetry](https://github.com/eNgine9r/nexolab-platform/issues/1409)  | `in_progress`         |
| [#1399 — [P0][RUNTIME] Guarded offline Docker network auto-recovery on validated Raspberry Pi boot](https://github.com/eNgine9r/nexolab-platform/issues/1399)           | `in_progress`         |
| [#1392 — [P0][RUNTIME] Restore central MQTT/API network topology reliably after reboot](https://github.com/eNgine9r/nexolab-platform/issues/1392)                       | `untracked`           |
| [#1393 — [P0][RUNTIME] Recover packaged Dashboard network/port after reboot, preserve approved service state](https://github.com/eNgine9r/nexolab-platform/issues/1393) | `untracked`           |
| [#1400 — [P1][RUNTIME] Diagnose detached packaged object-storage network after Pi reboot](https://github.com/eNgine9r/nexolab-platform/issues/1400)                     | `in_progress`         |
| [#1426 — [P0][OFFLINE] Dual-access Raspberry Pi: local kiosk and isolated PC without internet or site LAN](https://github.com/eNgine9r/nexolab-platform/issues/1426)    | `untracked`           |
| [#1476 — [P0][LOCAL LAN][WP] Verify immutable runnable monitor release and pinned systemd ExecStart](https://github.com/eNgine9r/nexolab-platform/issues/1476)          | `untracked`           |
| [#1567 — [P0][ACCESS] Restore private NEXOLAB entry points after Raspberry Pi or tunnel restart](https://github.com/eNgine9r/nexolab-platform/issues/1567)              | `review`              |
| [#108 — feat: deploy remote Tailscale TLS acceptance gate on central host](https://github.com/eNgine9r/nexolab-platform/issues/108)                                     | `untracked`           |

### E3 — Надійність телеметрії, ACK і чесні Live-стани (7)

_Queue:_ P0/P1 — після відокремлення мережевої та DR-бази.

| GitHub Issue                                                                                                                                                                  | Current Sprint marker |
| ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------- |
| [#1397 — [P0][RELIABILITY] Central durable ACK and edge replay beyond broker queue capacity](https://github.com/eNgine9r/nexolab-platform/issues/1397)                        | `untracked`           |
| [#1394 — [P0][RELIABILITY] Prove durable telemetry delivery while central API is offline](https://github.com/eNgine9r/nexolab-platform/issues/1394)                           | `untracked`           |
| [#1445 — [P0][RELIABILITY] Central PostgreSQL-committed telemetry receipt publisher with durable retry](https://github.com/eNgine9r/nexolab-platform/issues/1445)             | `untracked`           |
| [#1449 — [P0][SECURITY][WP] Dedicated MQTT receipt publisher and per-node subscriber ACL, isolated acceptance](https://github.com/eNgine9r/nexolab-platform/issues/1449)      | `untracked`           |
| [#1451 — [P0][RELIABILITY][WP] Edge-only authenticated committed-receipt consumer and atomic SQLite prune](https://github.com/eNgine9r/nexolab-platform/issues/1451)          | `untracked`           |
| [#1522 — [BUG][LIVE] Match telemetry freshness to the actual acquisition cadence](https://github.com/eNgine9r/nexolab-platform/issues/1522)                                   | `untracked`           |
| [#1577 — [BUG][TELEMETRY] Restore replacement Dixell temperature channels and diagnose protected monitoring access](https://github.com/eNgine9r/nexolab-platform/issues/1577) | `review`              |

### E4 — Єдиний реліз, доступ і керування версіями (15)

_Queue:_ Після P0 release gate; гранулярні права — незалежна source-гілка.

| GitHub Issue                                                                                                                                                               | Current Sprint marker |
| -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------- |
| [#1587 — [RELEASE][WP] Prepare and verify protected Raspberry activation of commissioned Dixell labels](https://github.com/eNgine9r/nexolab-platform/issues/1587)          | `untracked`           |
| [#1564 — [P0][FRONTEND] Fix nginx DynamicUser runuser validator blocking safe UI promotion](https://github.com/eNgine9r/nexolab-platform/issues/1564)                      | `review`              |
| [#1569 — [BUG][ACCESS] Reauthenticate when the Users & Access session is lost](https://github.com/eNgine9r/nexolab-platform/issues/1569)                                   | `needs_validation`    |
| [#1526 — [ACCESS][WP] Independently grant and enforce per-page access for local users](https://github.com/eNgine9r/nexolab-platform/issues/1526)                           | `ready`               |
| [#1528 — [ACCESS][WP1] Add guarded per-page grant contracts and upgrade foundation](https://github.com/eNgine9r/nexolab-platform/issues/1528)                              | `untracked`           |
| [#1530 — [ACCESS][WP2] Apply per-user page grants to navigation and direct page views](https://github.com/eNgine9r/nexolab-platform/issues/1530)                           | `untracked`           |
| [#1523 — [WP] Enable named multi-user access through the protected Google gateway](https://github.com/eNgine9r/nexolab-platform/issues/1523)                               | `untracked`           |
| [#1381 — [NEXOLAB][RELEASE] Safely activate fixed LAN runtime identity on Raspberry Pi](https://github.com/eNgine9r/nexolab-platform/issues/1381)                          | `untracked`           |
| [#1382 — [NEXOLAB][P0] Diagnose RS-485 acceptance race and recover failed protected version authority](https://github.com/eNgine9r/nexolab-platform/issues/1382)           | `untracked`           |
| [#1384 — [NEXOLAB][P0][RECOVERY] Verify failed update evidence and safely reconcile installed package authority](https://github.com/eNgine9r/nexolab-platform/issues/1384) | `untracked`           |
| [#1323 — [WP] Reconcile partial unified activation after verified agent recovery](https://github.com/eNgine9r/nexolab-platform/issues/1323)                                | `blocked`             |
| [#1317 — [WP] Record prepared unified update installation and privilege checkpoint](https://github.com/eNgine9r/nexolab-platform/issues/1317)                              | `untracked`           |
| [#1313 — [WP] Synchronize LAN and Google HTTPS releases and expose truthful update readiness](https://github.com/eNgine9r/nexolab-platform/issues/1313)                    | `blocked`             |
| [#1351 — Pin native worker Git trust to the configured site repository](https://github.com/eNgine9r/nexolab-platform/issues/1351)                                          | `needs_validation`    |
| [#1349 — Constrain native version worker writes and verify protected update/rollback](https://github.com/eNgine9r/nexolab-platform/issues/1349)                            | `needs_validation`    |

### E5 — Підключення RS-485, енерголічильники, instrument registry (25)

_Queue:_ Після стабілізації приймання; ізольовані source-PR дозволені.

| GitHub Issue                                                                                                                                                                 | Current Sprint marker |
| ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------- |
| [#1429 — [P0][HARDWARE] Restore Embraco and SDM120 USB RS-485 identities after Pi enclosure relocation](https://github.com/eNgine9r/nexolab-platform/issues/1429)            | `untracked`           |
| [#1126 — [RUNTIME][RS485] Restore missing rs485-main CP2104 0133F090 adapter](https://github.com/eNgine9r/nexolab-platform/issues/1126)                                      | `blocked`             |
| [#1125 — [ANALOG][WAVESHARE] Discover 8CH Modbus RTU acquisition path for humidity and future 4–20 mA instruments](https://github.com/eNgine9r/nexolab-platform/issues/1125) | `blocked`             |
| [#585 — [RESTORE] Return LE-01MP W2 / Unit 201 to NEXOLAB after temporary external RS-485 ownership](https://github.com/eNgine9r/nexolab-platform/issues/585)                | `blocked`             |
| [#201 — [WP] Validate LE-01MP cumulative energy, scale and rollover](https://github.com/eNgine9r/nexolab-platform/issues/201)                                                | `needs_validation`    |
| [#202 — [WP] Validate extended XJP60D semantics and firmware portability](https://github.com/eNgine9r/nexolab-platform/issues/202)                                           | `hardware_validation` |
| [#17 — [Profiles] Сформувати versioned device profiles і register-map документацію](https://github.com/eNgine9r/nexolab-platform/issues/17)                                  | `untracked`           |
| [#1518 — Integrate and validate SDM120M, Waveshare 8AI and Energy for Raspberry update](https://github.com/eNgine9r/nexolab-platform/issues/1518)                            | `untracked`           |
| [#1514 — Update dashboard acceptance for advanced onboarding after quick-add redesign](https://github.com/eNgine9r/nexolab-platform/issues/1514)                             | `review`              |
| [#1513 — Plan retirement of obsolete CP2104 bus bindings without losing device history](https://github.com/eNgine9r/nexolab-platform/issues/1513)                            | `blocked`             |
| [#1508 — [ENERGY] Support bus-scoped commissioned SDM120 meters without mixing history](https://github.com/eNgine9r/nexolab-platform/issues/1508)                            | `review`              |
| [#1505 — [ONBOARDING][RS485] Design persistent activation of free commissioning adapters](https://github.com/eNgine9r/nexolab-platform/issues/1505)                          | `review`              |
| [#1503 — [ONBOARDING][SDM120] Add Eastron SDM120M to standalone instrument setup](https://github.com/eNgine9r/nexolab-platform/issues/1503)                                  | `review`              |
| [#1502 — [ONBOARDING][WAVESHARE] Add Waveshare 8CH (B) analog input to standalone setup](https://github.com/eNgine9r/nexolab-platform/issues/1502)                           | `review`              |
| [#1500 — Support section-addressed XJP60D modules without misattributing physical instruments](https://github.com/eNgine9r/nexolab-platform/issues/1500)                     | `untracked`           |
| [#1498 — Simplify instrument connections and open filtered live readings directly](https://github.com/eNgine9r/nexolab-platform/issues/1498)                                 | `untracked`           |
| [#1496 — [ONBOARDING] Add named standalone instruments without creating or requiring refrigeration equipment](https://github.com/eNgine9r/nexolab-platform/issues/1496)      | `untracked`           |
| [#1494 — [ONBOARDING] Search all devices on any connected adapter with response counts](https://github.com/eNgine9r/nexolab-platform/issues/1494)                            | `untracked`           |
| [#1492 — [ONBOARDING] Refresh adapter dropdown on USB connect/disconnect](https://github.com/eNgine9r/nexolab-platform/issues/1492)                                          | `untracked`           |
| [#1490 — [ONBOARDING] One-page quick device setup for disposable lab testing](https://github.com/eNgine9r/nexolab-platform/issues/1490)                                      | `untracked`           |
| [#1486 — [ONBOARDING][WP2B] Connect bounded XJP address search to authenticated wizard](https://github.com/eNgine9r/nexolab-platform/issues/1486)                            | `blocked`             |
| [#1482 — [ONBOARDING][WP2A] Bounded XJP60D read-only address-search foundation](https://github.com/eNgine9r/nexolab-platform/issues/1482)                                    | `blocked`             |
| [#1481 — [ONBOARDING][WP2] Guided read-only Modbus address search on an isolated RS-485 adapter](https://github.com/eNgine9r/nexolab-platform/issues/1481)                   | `untracked`           |
| [#1478 — [DISCOVERY][UX] Simplify read-only device and RS-485 onboarding](https://github.com/eNgine9r/nexolab-platform/issues/1478)                                          | `untracked`           |
| [#1520 — [ONBOARDING] Preserve adapter list after a commissioned bus becomes active](https://github.com/eNgine9r/nexolab-platform/issues/1520)                               | `untracked`           |

### E6 — Операторський UX, аудит сценаріїв і додаткові інтеграції (3)

_Queue:_ Після надійного базового моніторингу.

| GitHub Issue                                                                                                                                      | Current Sprint marker |
| ------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------- |
| [#1191 — [UX AUDIT] All-page operator workflow review and simplification evidence gate](https://github.com/eNgine9r/nexolab-platform/issues/1191) | `untracked`           |
| [#1300 — [UX AUDIT] Production operator Wave 2: Sessions to Reports read-only journey](https://github.com/eNgine9r/nexolab-platform/issues/1300)  | `untracked`           |
| [#1571 — [CAMERA][DISCOVERY] Ajax local video feasibility and door-test evidence pilot](https://github.com/eNgine9r/nexolab-platform/issues/1571) | `untracked`           |

## Open PR portfolio snapshot (all 46)

These are **unmerged proposals**. Inclusion in an Epic is not a review approval, CI result or hardware verification. A separate exact-head check must precede each merge. Do not automatically convert old draft PRs to Ready.

### Автоматичні dependency/toolchain оновлення — окремий maintenance lane (10)

[#1566 — chore(deps): bump lucide-react from 1.26.0 to 1.72.0](https://github.com/eNgine9r/nexolab-platform/pull/1566) · [#1565 — chore(deps): bump next from 16.3.6 to 16.4.6](https://github.com/eNgine9r/nexolab-platform/pull/1565) · [#1543 — chore(deps): bump @supabase/supabase-js from 2.112.0 to 2.119.0](https://github.com/eNgine9r/nexolab-platform/pull/1543) · [#1540 — chore(deps): bump the development-build-patch-minor group across 1 directory with 2 updates](https://github.com/eNgine9r/nexolab-platform/pull/1540) · [#1455 — chore(deps): bump actions/cache from 4 to 6](https://github.com/eNgine9r/nexolab-platform/pull/1455) · [#1420 — chore(deps): bump the development-quality-patch-minor group across 1 directory with 5 updates](https://github.com/eNgine9r/nexolab-platform/pull/1420) · [#1416 — chore(deps): bump the development-test-patch-minor group across 1 directory with 3 updates](https://github.com/eNgine9r/nexolab-platform/pull/1416) · [#1415 — chore(deps): bump react-dom from 19.3.0 to 19.3.1](https://github.com/eNgine9r/nexolab-platform/pull/1415) · [#1414 — chore(deps): bump react from 19.3.0 to 19.3.1](https://github.com/eNgine9r/nexolab-platform/pull/1414) · [#1273 — chore(deps): bump @types/node from 22.20.4 to 22.20.5](https://github.com/eNgine9r/nexolab-platform/pull/1273)

### DR, storage та доказ збереження (3)

[#1556 — [STORAGE] Record verified fallback microSD cache-only reclamation (#1555)](https://github.com/eNgine9r/nexolab-platform/pull/1556) · [#1552 — [STORAGE] Protect laboratory evidence in 30-day telemetry retention (#1551)](https://github.com/eNgine9r/nexolab-platform/pull/1552) · [#1461 — feat(dr): fail-closed read-only backup inventory and capacity preflight (#1460)](https://github.com/eNgine9r/nexolab-platform/pull/1461)

### Доступ і granular permissions (3)

[#1531 — feat: apply individually granted navigation visibility (#1530)](https://github.com/eNgine9r/nexolab-platform/pull/1531) · [#1529 — Add guarded navigation grant foundation (#1528)](https://github.com/eNgine9r/nexolab-platform/pull/1529) · [#1524 — Allow explicitly approved Google gateway users (#1523)](https://github.com/eNgine9r/nexolab-platform/pull/1524)

### RS-485 onboarding / Energy — взаємопов'язані source candidates (15)

[#1521 — Fix adapter inventory after commissioning activation](https://github.com/eNgine9r/nexolab-platform/pull/1521) · [#1519 — Integrate SDM120M, Waveshare 8AI and Energy for Raspberry](https://github.com/eNgine9r/nexolab-platform/pull/1519) · [#1515 — test: enter advanced onboarding before unsupported draft](https://github.com/eNgine9r/nexolab-platform/pull/1515) · [#1509 — Energy: show commissioned SDM120M meters per node (#1508)](https://github.com/eNgine9r/nexolab-platform/pull/1509) · [#1507 — [WIP] Add Waveshare 8CH (B) read-only onboarding](https://github.com/eNgine9r/nexolab-platform/pull/1507) · [#1506 — [WIP] Persist read-only commissioning buses across restarts](https://github.com/eNgine9r/nexolab-platform/pull/1506) · [#1504 — [WIP] Prepare SDM120M read-only FC04 commissioning](https://github.com/eNgine9r/nexolab-platform/pull/1504) · [#1501 — Support section-addressed XJP60D instruments with attached and reserve inputs](https://github.com/eNgine9r/nexolab-platform/pull/1501) · [#1499 — Open instrument readings directly from simplified Connections](https://github.com/eNgine9r/nexolab-platform/pull/1499) · [#1497 — feat(equipment): add standalone instruments without requiring a showcase](https://github.com/eNgine9r/nexolab-platform/pull/1497) · [#1495 — feat(equipment): discover all devices on configured and free RS485 adapters](https://github.com/eNgine9r/nexolab-platform/pull/1495) · [#1493 — fix(equipment): refresh RS485 adapters on USB connect/disconnect](https://github.com/eNgine9r/nexolab-platform/pull/1493) · [#1491 — feat(equipment): one-page quick device setup for the test lab (#1490)](https://github.com/eNgine9r/nexolab-platform/pull/1491) · [#1488 — feat(commissioning): find unknown XJP address from wizard (#1486)](https://github.com/eNgine9r/nexolab-platform/pull/1488) · [#1483 — feat(edge): bounded read-only XJP address search foundation (#1482)](https://github.com/eNgine9r/nexolab-platform/pull/1483)

### CI та supply-chain без змін runtime (4)

[#1489 — fix(ci): restore pinned Trivy download from official release (#1487)](https://github.com/eNgine9r/nexolab-platform/pull/1489) · [#1403 — fix(ci): classify known offline recovery guards without unrelated browser workflows (#1402)](https://github.com/eNgine9r/nexolab-platform/pull/1403) · [#1373 — fix(ci): route isolated Energy acceptance runner through achievable checks (#1372)](https://github.com/eNgine9r/nexolab-platform/pull/1373) · [#1279 — perf(ci): fast affected checks and artifact-first Pi deploy](https://github.com/eNgine9r/nexolab-platform/pull/1279)

### Offline, LAN, release authority та зовнішній доступ (6)

[#1477 — feat(offline): source-pin safe local LAN monitor runtime (#1476)](https://github.com/eNgine9r/nexolab-platform/pull/1477) · [#1427 — feat(offline): opt-in private browser host API/WS contract for Pi + isolated PC (#1426)](https://github.com/eNgine9r/nexolab-platform/pull/1427) · [#1396 — fix(runtime): detect packaged Dashboard host-port loss after reboot (#1393)](https://github.com/eNgine9r/nexolab-platform/pull/1396) · [#1395 — fix(runtime): fail closed on MQTT/API Docker network drift (#1392)](https://github.com/eNgine9r/nexolab-platform/pull/1395) · [#1318 — Record verified ARM64 packages and stopped owner authority handoff](https://github.com/eNgine9r/nexolab-platform/pull/1318) · [#1311 — docs(security): draft Cloudflare Access/Tunnel boundary for NEXOLAB (no deployment)](https://github.com/eNgine9r/nexolab-platform/pull/1311)

### Durable MQTT ACK, Replay, reliability (4)

[#1452 — feat(edge): stage isolated atomic committed-receipt SQLite ledger (#1451)](https://github.com/eNgine9r/nexolab-platform/pull/1452) · [#1450 — feat(security): dedicated MQTT receipt ACL and isolated broker acceptance (#1449)](https://github.com/eNgine9r/nexolab-platform/pull/1450) · [#1446 — feat(reliability): stage atomic PostgreSQL receipt outbox foundation (#1445)](https://github.com/eNgine9r/nexolab-platform/pull/1446) · [#1398 — docs(reliability): prove offline MQTT broker queue durability limit (#1394)](https://github.com/eNgine9r/nexolab-platform/pull/1398)

### UX evidence-only (1)

[#1301 — docs(ux): Wave 2 Sessions → Reports production audit evidence](https://github.com/eNgine9r/nexolab-platform/pull/1301)

## Reconciliation procedure at each Sprint boundary

- Re-fetch live GitHub open Issues/PRs, `main`, CI and four canonical `.project` files; calculate missing/duplicate IDs against this dated snapshot and update the plan with a new observation date.
- Check that source-accepted issues are not quietly treated as installed. Separate `software_verified`, `hardware_unverified`, `hardware_verified`.
- Check active implementation count <=1; Ready <=3; Review has a PR/owner; blockers have one next evidence step; dependency graph is acyclic at the **same gate level**.
- Do not replace `ACTIVE_SPRINT.json` with this roadmap. GitHub is current for issue/PR lifecycle; Sprint selection is current for execution; this roadmap conveys dependencies and portfolio grouping.
