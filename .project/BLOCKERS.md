# NEXOLAB Blockers

Updated: 2026-09-03

## Issue #843 — Telemetry planner-choice CI nondeterminism

**Repository-side blocker cleared 2026-09-03.** PR #844 exact verified implementation head `fcd9d2429ef19c9410fdfe9292d6f5d04cdc7c1b` passed all 11 registered workflows, including Telemetry Service `33770161208`, Core CI/NEXOLAB Merge Gate `33770159789` and Offline Bundle `33770159680`. The repair preserves the production query and schema while replacing an optimizer-specific exact-index-name assertion with independent canonical-index catalog validation plus an index-backed latest-value probe. Local repeated PostgreSQL 16 and transactional negative evidence are GREEN. No production deployment, runtime mutation, Modbus/hardware write or data/volume mutation occurred. GitHub merge status is queried online; after PR #844 merges, integrate current `main` into TG-04 PR #842 and rerun its exact-head verification.

## Issue #845 — TG-04 scheduler activation must fail closed

**Cleared 2026-09-03.** PR #846 exact head `cae3e45ad6a11b74797dd843c187c44602f9aa81` passed the full classified workflow matrix and squash-merged to `main` at `242dd46c01109e2f75b7ac60e5bf8f7f28ac49b6`. Application, service-constructor and central Compose defaults now keep daily-report scheduling fail-closed OFF; explicit later enablement remains supported. No production migration/cutover, Telegram send, Modbus/hardware write or destructive action occurred.

## Issue #851 — Stage-2 source-authority metadata reconciliation

**Cleared 2026-09-03.** Product Owner-approved Stage-2 deployment passed on exact source `13ab26392fcb1c1385dca3c1f619da4512fe568c` with authoritative evidence `runtime/deployments/20260903T191159Z`; live Alembic is `20260902_0031`. Runtime is healthy, persistent volumes are preserved, Telegram delivery/worker remain OFF, Mini App remains ON, `last_send_at=null`, and `DAILY_REPORTS_SCHEDULER_ENABLED=false`. The canonical privileged source adopter then returned `status=recorded` for `controlled_source_deployment`, exact source `13ab2639...`, schema `0031`, health `ready`, `linux/arm64`, runtime mode `lan`, `known_packaged_release=false`, and the same authoritative evidence. #851 no longer blocks TG-04.

## Issue #854 — Telegram Mini App persisted-report schema contract drift

**Active focused blocker for #825.** Real iOS Telegram opened exact snapshot `76957482-57c4-4daf-ac30-d8592847cfbd`; gateway logs recorded HTTP 200 for the real signed Mini App request, but the browser rendered `Некоректний формат звіту`. TG-01 production payload authority is `nexolab.daily-refrigeration-report.v1`; the Mini App parser and synthetic fixtures still expected stale `refrigeration-daily-report/v1`. The repair is bounded to the browser contract/test fixtures plus truthful state. Delivery remains OFF, worker stopped, `last_send_at=null`, scheduler OFF. #825 resumes only after #854 exact-head CI is GREEN and merged.

## Issue #825 — TG-04 real Telegram acceptance

**Stage-2 deployment and source-authority reconciliation cleared; TG-04 temporarily Ready behind #854.** Exact source `13ab26392fcb1c1385dca3c1f619da4512fe568c` deployed successfully using the verified ARM64 candidate. Live schema is `20260902_0031`; Dashboard, Telemetry, MQTT and Device Agent are healthy. Telegram Gateway is `ready` with `delivery_enabled=false`, `miniapp_enabled=true`, `running=false`, `last_send_at=null`; the 07:50 scheduler remains explicitly disabled. Tailscale `:8444` proxies the deployed Dashboard on `:3000`. No TestLAB report was sent during Stage 2.

The first real signed Mini App attempt reached the persisted snapshot successfully but exposed #854 browser schema-contract drift. After #854 merges and the corrected frontend is deployed through the guarded path, repeat exact signed Mini App persisted-report acceptance. One controlled TestLAB send, reliability/no-duplicate evidence and Monday-Friday 07:50 `Europe/Kyiv` activation remain later gates and must not be conflated with this repair.

## Issue #824 — TG-03 completed and merged

**Cleared 2026-09-03.** PR #839 final head `e95b8107919d5f12ce32fc90800ff6cd7f71870f` passed the full exact-head matrix and NEXOLAB Merge Gate and squash-merged to `main` at `01ede1a23e15d9edeafd39b73521261276853160`. Immutable accepted product evidence remains `31cd4fd5e43672b81af34c8ac1f53e185cf4752e`. Issue #824 is closed completed. TG-03 introduced no real Telegram contact, secret provisioning, production cutover, Modbus/hardware write, data deletion or volume deletion.

## Issue #805 — controlled onboarding deployment and browser acceptance

**Cleared 2026-09-02.** Controlled deployment `runtime/deployments/20260902T113916Z` passed on corrected onboarding source `893573a86faf6629e5e3cefc0e41c47230a7f8c7` after #826/#827. Post-cutover Dashboard, Telemetry, MQTT and Device Agent are healthy; persistent volumes are preserved. Authenticated Chromium proved commissioning draft persistence across reload/reopen and the controlled service restart, and `Unsupported / Profile required` is now fail-closed for `Далі`, Steps 2–5, SAFE PREFLIGHT and activation. Real Embraco Unit 2 preflight passed FC03-only with `hardware_verified` evidence and no writes. Controlled source adoption is recorded for `893573a86faf6629e5e3cefc0e41c47230a7f8c7`, schema `20260902_0030`, linux/arm64, LAN, health ready. #805 no longer blocks independent work.

## Issue #792 — selected-interval relay traceability and export

**Cleared and merged 2026-09-01.** PR #793 passed all required exact-head browser/Core/DR/Merge Gate verification and squash-merged; GitHub closed #792 completed. Direct compressor-chart drag selection, synchronized KPI/relay/start/export behavior and the canonical-name DR assertion are repository-complete. No production deployment, Modbus write or hardware write occurred in #792.

## Issue #790 — controlled deployment final Device Agent health race

**Software defect cleared 2026-09-01.** Exact verified head `cd01e27054f30af85f10be0a49e13524e285abe0` passed Core Quality/build and NEXOLAB Merge Gate in run `33512424465`; all P1/P2 review threads are resolved. The bounded gate now preserves its helper across historical checkout, enforces container identity, Docker/operational convergence, required scheduler evidence and matching worker counts, and bounds every Docker/HTTP blocking I/O call by the remaining convergence deadline. At #790 completion this did **not** validate failed #789 evidence or advance the then-formal source authority from `20bb9ca...`; that historical boundary was later superseded by the successful #805 deployment on `893573a8...`. No deployment/runtime mutation or Modbus/hardware write occurred in #790.

## Issue #785 — operator-selected compressor analysis interval

**Cleared 2026-09-01.** Exact verified product head `5a1df9a08dbe39c4be0f93c6a5e6dc622136d1c3` passed Core Quality/build, Refrigeration Browser Acceptance, Authenticated Dashboard Acceptance, Disaster Recovery Browser and NEXOLAB Merge Gate; PR #786 merged and Issue #785 closed completed. No new hardware acceptance was required because the feature derives locally from already persisted read-only `compressor.speed` history. Production deployment remains a separate explicit boundary.

## Issue #772 — persisted Embraco physical-bus identity

**Cleared 2026-08-30.** PR #773 merged GREEN. Production-copy acceptance proved `EMBRACO-2` persists on `rs485-embraco`, reloads without mismatch, preserves Unit 201 as disabled on `rs485-main`, and retains legacy single-bus behavior. This safety prerequisite no longer blocks #760.

## Issue #760 — Embraco Unit 2 production activation

**Cleared 2026-08-31.** Controlled deployment `runtime/deployments/20260830T202942Z` passed on exact source `20bb9ca473395a0c64267b9b08523c31404f41e6` for physical controller #2 / Embraco Unit 2 only; controller #1 is test-only and Unit 96 is excluded. Registry revision 20 persists `embraco-2@rs485-embraco`, Unit 201 remains disabled on Bus 1, schema head is `20260828_0027`, and Device Agent is healthy in `modbus` mode with MQTT connected and queue depth 0. Real FC03-only state/RPM/relay/alarm telemetry is durable; unverified temperature/control scale remains NULL/`unknown`. `Cool jet → EMBRACO-2` is audit-backed.

Final external gates are cleared: source/version authority is recorded as `controlled_source_deployment` for source `20bb9ca...`, linux/arm64, LAN, schema `20260828_0027`, health `ready`; production Opera acceptance entered as `ChatGPT Opera Inspection / viewer`, proved REST snapshot + active WebSocket, and displayed real `Cool jet` controller state (`Embraco Online`, `Cooling`, 2142 rpm / Running, relay states, no controller alarms, `Scale unverified`). Exact-head manual Telemetry, Refrigeration Browser, Authenticated Dashboard and Offline Bundle workflows on acceptance head `ebccb8ad...` are GREEN. Final state head `46cefa49...` also passed State integrity and NEXOLAB Merge Gate; PR #779 squash-merged at `72d67360...` and GitHub closed #760 completed.

## Issue #709 — post-merge Saved Dashboard runtime CSV verification

**Cleared 2026-08-29.** Bounded deployment `runtime/deployments/20260829T154823Z` activated `ff86b10b...`. Existing Saved Dashboard runtime export produced 120 real `108-01 / temperature.probe` rows using `K108`, with numeric valid values; inventory/latest correlation also resolves `K108`. Issue #709 is closed completed.

## Issue #711 — post-merge Energy runtime verification

**Cleared 2026-08-29.** The same bounded deployment activated the cadence-aware Energy fix. Real 24h exact-target verification reduced 8,573 raw rows to 717 render rows with 7 durable and 0 inferred continuity breaks, eliminating the previous 448 normal-jitter false breaks while preserving genuine silent gaps.

## Issue #189 — actual-host recovery acceptance

The stale hosted recovery-package blocker is **cleared by Issue #832**. Offline Bundle run `33653777090` accepted exact deployed source `893573a86faf6629e5e3cefc0e41c47230a7f8c7` on `linux/arm64` with local auth, disconnected runtime, and update/rollback preservation of required named volumes, markers and authentication continuity; artifact `9856886787`, bundle SHA-256 `234b93648d25245730c0c845c6a3cd267625d07c1f4dfbaf263fb552b1257ea1`. #189 remains blocked only on the separately gated **actual-host** current-source reboot/recovery and controlled power-loss acceptance. Those actions require explicit approval and real host evidence; hosted/QEMU acceptance does not substitute for them.

## Issue #200 — physical RS-485 topology

Issue #760 now verifies the second CP2104 production adapter `0133F246` and read-only Embraco Unit 2 ownership on isolated `rs485-embraco` at 9600 8N2 while preserving Bus 1. Full #200 acceptance still requires the remaining physical-topology evidence: Unit 115 reality, duplicate-ID isolation beyond the accepted Unit 2 scope, termination, biasing, shielding and grounding.

## Issue #201 — LE-01MP cumulative energy

Normal-operation semantics are accepted. Controlled restart/power-cycle discontinuity evidence remains pending; an unplanned hard reset cannot be reclassified as approved evidence.

## Issue #202 — XJP60D portability

Representative KK1/KK2 physical evidence, Unit 115 resolution and extended semantics still require real hardware evidence. Unconfirmed fields remain unmapped.

## Issue #585 — W2 / Unit 201 handback

Blocked until the Product Owner confirms the temporary external RS-485 owner has released W2 and approves any required physical handback/reconnection.

## Product priority hold — RFX-01 through RFX-19C

Issue #727 records an intentional Product Owner defer of **RFX-01 through RFX-19C until after the main presentation**. This is not a technical blocker and does not invalidate accepted RFX-00 / ADR 0010. Issue #717 is non-Ready/blocked by product decision; PR #718 is closed unmerged and retained only as a historical checkpoint. Do not auto-advance to RFX-02 or reopen/merge the pre-pause RFX-01 branch. Resume requires an explicit Product Owner restart plus a fresh Team Lead source-of-truth audit.

## Security maintenance — #829/#834 cleared; consolidated review due 2026-09-05

**Cleared.** #829 remains completed through PR #831, and the later TG-02-triggered shared Telemetry delta is cleared by #834 / PR #836 at exact verified head `7d4b0c8b55da862b57c16358126cfd7c856445da`. TG-02 subsequently passed its full post-#834 exact-head matrix at `25f3857f291bcada05bec09b2d8d7323c52a3b22` and merged through PR #830; it is no longer blocked by security or CI. The exact HIGH-only `telemetry-service + libsystemd0/libudev1 + CVE-2026-16742` exceptions and TG-02 gateway exceptions remain bounded to **2026-09-05**; CRITICAL remains unconditionally blocked and the consolidated review remains mandatory. No production deployment, runtime mutation, Modbus/hardware write or data/volume change is authorized by these security decisions.

## Issue #755 — approved bounded #709 / #711 controlled deployment

**Cleared 2026-08-29.** Deployment `runtime/deployments/20260829T154823Z`, #709/#711 real runtime acceptance and controlled-source version-management adoption all passed. Deployed source authority is `ff86b10b...` with schema `20260820_0026`, `linux/arm64`, `lan`, health `ready`, and `known_packaged_release=false`. #729 and later product runtime scope remain excluded and require a separate explicit production/hardware gate.

## Issue #757 — completion candidate capacity prerequisite for #755

**Cleared.** Issue #757 / PR #758 is merged and the corrected capacity guard was used successfully by #755. No runtime/data/hardware mutation belongs to #757.

## Issue #753 — cleared

PR #754 is merged at `76fa83a80e2eef82ae6f6e7c616a0dbe9352a5c8`; implementation safety and final state heads are GREEN and clean-reviewed. #753 no longer blocks runtime activation.

## Cleared boundaries

- #730 Opera/Tailscale inspection — completed on 2026-08-29. The dedicated `ChatGPT Opera Inspection` session enters the authenticated shell automatically as `Спостерігач`; REST/WebSocket are active; the isolated `nexolab-inspection` helper and root-owned `0600` login socket remain intact; direct frontend `/inspection-login` stays 404; production `:3000` stays HTTP 200; PR #731 is merged with exact-head Core/Telemetry/Merge-Gate GREEN.
- #729 Embraco refrigeration digital twin — completed and merged in PR #736; exact-head Core/Telemetry/Refrigeration/Auth/Offline/DR/Security/Device-Agent/Container/Merge-Gate verification is GREEN. Production Embraco Unit 2 polling and migration were subsequently accepted under #760; temperature/control engineering scale remains separately hardware-unverified and fail-closed.
- #444 LOCAL_LAN user administration — completed.
- #646 main branch protection — completed; `main` requires `NEXOLAB Merge Gate`.
- #667 CVE lifecycle date reconciliation — completed and merged.
- #245 standalone offline Raspberry Pi acceptance — completed on real hardware.
- #673 production-readiness state reconciliation — completed and merged.
- #675 source-to-packaged authority tooling — completed with exact-head review and required GREEN workflows.
- #679 ARM64 QEMU package acceptance — completed with GREEN post-merge ARM64/local-auth run `32832798392` and independently verified artifact/provenance.
- #683 local-auth relocation/full source recovery — merged at PR #685 with exact-head required workflows GREEN; its post-merge acceptance correctly failed before mutation on the separate #686 hosted fixture-permission defect.
- #686 ARM64/local-auth acceptance fixture permissions — completed at PR #687; replacement run `32939760743` GREEN and accepted artifact `9584581740` published without production runtime mutation.
- #684 task-oriented Settings workspace — implementation and exact-head CI/browser/offline/merge-gate verification completed; no hardware or production cutover evidence required for this presentation-only Work Package.
- #696 refrigeration structural latest-value latency — completed; bounded `telemetry_latest` query and real Raspberry Pi benchmark evidence accepted.
- #698 GitHub-hosted runner allocation recovery — completed; exact-head workflows execute normally again.
- #704 container security reconciliation — completed with exact-head security/CI evidence; only time-bounded maintenance remains.
- #719 / PR #721 fresh Device Agent security reconciliation — completed and merged at `1f2654dec0f02263aec6c2314187cfa62e5723e9`; #722 triage is completed.
- #723 / PR #724 CI routing maintenance — completed and merged at `8e9333fe76bce4a5babccaf7a3bedf35c5fe49bb`.
- #690 risk-aware/path-targeted PR verification — completed and merged in PR #714 at `4ee7f836442fbfc9ed257c2c8eaf8ad2e22fbe51`; post-merge Core CI and Acquisition Scale Acceptance are GREEN.
- #715 RFX-00 refrigeration architecture ADR — completed and merged in PR #716; ADR 0010 remains accepted architecture authority while RFX-01 through RFX-19C are product-deferred under #727.
- #733 canonical project-state formatter boundary — completed locally; `.project/*.json` is excluded from Prettier and remains governed by State Model v2 validation.

## Safety boundaries

No blocker may be bypassed by Modbus/controller write, hardware write, production/site cutover without approval, persistent-data deletion, named-volume deletion, secret exposure or mandatory cloud dependency.
