# NEXOLAB Blockers

Updated: 2026-09-22

## Issue #1104 — Eastron SDM120M production activation gate

**Software implementation is in review; production polling is intentionally blocked.** Real read-only evidence confirms Eastron SDM120M Unit `1` on stable FTDI `A10Q34QC` at `9600 8N1`, and #1104 software gates are GREEN locally. Repository defaults keep `SDM120_UNIT_IDS` empty, so merge cannot start hardware polling. After exact-head CI and merge, activation requires a separate bounded production cutover and explicit Product Owner approval. Modbus writes and hardware writes remain forbidden.

## Issue #1094 — RFX-12 frontend-only Overview production release

**Cleared and accepted in live LOCAL_LAN runtime.** Frontend compatibility source `2296e3070cbebff687418cf1ac161984086bebdb` is active with build ID `fveOqzLHugE-KZ4RRBogM`, while formal deployed product/backend authority remains `df368cfa27efa945d59de33de8268898b564a19f`. Authenticated Chromium verified the full-width temperature workspace with “Потребує уваги” and infrastructure stacked below at 360/1440/1920 px. Non-frontend container identities and health remained unchanged; rollback release is retained. No Modbus/controller write, hardware write, backend cutover, product-data deletion or volume deletion occurred.

## Issue #1055 — fresh Container Supply Chain HIGH findings

**Cleared and merged.** PR #1057 final exact head `d76852457ea0c9c8fe75d3443e7c812623bb824a` passed Container Supply Chain `35210100902`, Telemetry Service `35210100889`, and Core CI / NEXOLAB Merge Gate `35210100901`, then squash-merged to `main` as `640fd5d48ea63dc81eaeec08ba03b31feb294cd8`. The ten exact short-lived HIGH exceptions remain bounded and expire `2026-09-21`; no CRITICAL exception exists. No production/runtime/hardware mutation occurred.

## Issue #1053 — FTDI commissioning permission boundary

**Cleared in repository and live runtime on 2026-09-17.** PR #1054 merged the bounded nonroot supplementary-group fix, and the Product Owner-authorized deployment `442e0c55a87cd83fba71be769ac39d170cc0d61f → 039e37ac4b91903e5f8ee33de2603e40c308de90` completed with evidence `runtime/deployments/20260917T131852Z`. The live Device Agent now carries GID 20 and GID 46, FTDI `A10Q2SI7` is `available_for_preflight=true`, and a real Unit 35 FC03-only profile passed. No Modbus/controller write or hardware write occurred.

## Issue #1067 — CI routing for version-manager runtime tooling

**Cleared and merged.** PR #1068 exact head `dd1d9eed5779572a754e20f360336cd16e46a58f` passed Core CI / NEXOLAB Merge Gate `35288280260`, Authenticated Dashboard `35288280211`, Refrigeration Browser `35288280306`, Offline Bundle `35288280190`, and Telegram Gateway `35288280270`, then merged to `main`; GitHub closed #1067 completed. Unknown-path fail-closed behavior remains intact. No production mutation occurred.

## Issue #1065 — LOCAL_LAN commissioning inventory wiring

**Cleared in repository and live runtime.** PR #1066 final exact head `0f8342efd4c828c238912e76eb47abf3f2379f71` passed CI / NEXOLAB Merge Gate `35302450461`, Offline Bundle `35302450463`, and Telemetry Service `35302450466`, then merged. The Product Owner-authorized #1050 transition subsequently deployed exact source `df368cfa27efa945d59de33de8268898b564a19f`; Telemetry now reaches Device Agent through the bounded private `nexolab-standalone-runtime` network and `edge-device-agent` alias.

## Issue #1050 — RS-485 commissioning selector production acceptance

**Cleared and completed.** The corrected runtime is deployed on `df368cfa27efa945d59de33de8268898b564a19f` with evidence `runtime/deployments/20260918T050734Z`. The final Equipment → Connect device flow then passed in the actual Chromium UI under the normal `NEXOLAB Administrator / administrator` session without reading or bypassing browser secrets. Session `7f2a5f15-6af6-4911-af32-67ad61bee25a` reached `verified`; persisted preflight `c290a1dd-1adb-4185-b6e5-5bb1e06386bb` passed `hardware_verified` in 329 ms, FC03 only, with ten valid observations, `modbus_writes=none` and `hardware_writes=none`. Activation attempts remain `0`, scheduled targets remain 53, workers remain 2/2 healthy, and AK-CC25 scheduled targets remain `0`. No #1050 blocker remains.

## Issue #1044 — Danfoss onboarding runtime promotion

**Cleared on 2026-09-16.** Compatibility source `e94808974da56461d974704e39bfbcd310a1e6f8` is active for Device Agent, Telemetry Service and Dashboard. Authenticated browser/API acceptance shows `Danfoss AK-CC25 Pro` in the supported profile list; runtime health, scheduler target identity, RS-485 identity and persistent mounts are preserved; AK-CC25 scheduled targets remain `0`; rollback images and the prior dashboard release remain retained. No Modbus/controller write or hardware write occurred.

## Issue #1042 — central MinIO registry repair

**Cleared and merged.** PR #1043 exact head `1f491ff2d1e01ba88cd0b2e324f5749756e93234` passed all registered workflows, including Offline Auth Acceptance and Capacity Release Gate that had previously failed on retired Docker Hub MinIO repositories. The pinned release versions are unchanged; central defaults now use the repository-approved Quay registry. PR #1043 squash-merged to `main` as `5cced9e2cc855bcb2899ebe76fd85d04c98f0dd5`, and GitHub Issue #1042 is closed completed. No production deployment or data mutation occurred.

## Issue #1037 — Raspberry Pi host stability

**Cleared and merged.** The repeated disconnect pattern was tied to avoidable host-wide resource starvation during heavyweight local verification, not to OOM, overheating, SSD failure or Ethernet hardware errors. Optional browser/inspection services are disabled and on-demand; the legacy duplicate `remote-desktop` tmux/npx Remote Desktop Commander path is removed and guarded; the managed RDC receives higher relative CPU/I/O weight. A 90-second bounded memory/CPU load kept RDC, Tailscale, Device Agent, Telemetry and Dashboard responsive, preserved the boot ID, and left all 12 NEXOLAB containers healthy. PR #1038 exact head `6e864c7650a0fe01a24e13e6d5ee1eadade331bd` passed Core CI, Telemetry Service and NEXOLAB Merge Gate and squash-merged to `main` as `25979534c27ba5f131cdae0caf9e29a719fa0711`. GitHub Issue #1037 is closed completed. No reboot was required.

## Issue #1031 — AK-CC25 Pro onboarding

**Cleared and merged.** PR #1041 exact head `19afc763aa9c46c0a8c9b49a5e1527eac0df9cdd` passed required exact-head verification and merged to `main` as `ddf5427483e450f2eaa37e36f9fe290c1f913331`. Danfoss onboarding is repository-complete and production activation remains fail-closed. Runtime visibility was subsequently accepted under #1044.

## Issue #1024 — AK-CC25 Pro read-only hardware discovery

**Cleared and merged.** PR #1025 exact verified head `84a47eb15517af18d5ec5139ea8fa00d8e834542` merged to `main` as `e92502ba5a372e60b9f38304372224c1ed6aa4b7`, closing #1024 completed. Real Unit 35 hardware evidence remains valid for the FC03-only discovery subset. Temperature semantics remain intentionally hardware-unverified because no sensors are connected; production polling/activation requires a separate Work Package.

## Issue #1022 — frontend release CI routing repair

**Cleared for software scope and merged.** PR #1023 exact implementation head `4c0cdf7c55f5c92b5e153b21e29d3b41a23f890d` passed the full routed matrix and zero review threads, then merged to `main` as `5c8ade60cda6f4a5b8cac9610741e212bff0c3a3`. The false browser-workflow requirement for frontend release tooling is removed while unknown paths remain fail-closed. #1020 has resumed and is in review on current integration head `83ee68db553e70ceaa2a00a078ea0559e8924293`; its Core CI / NEXOLAB Merge Gate and Offline Bundle are GREEN, with only the final exact-head Frontend Release Artifact gate plus merge remaining. #1019 remains blocked only until #1020 merges. Production runtime is unchanged.

## Issue #1001 — Overview operator-first dashboard

**Cleared for repository/software scope.** PR #1002 product/test head `b245b48e7ab64a42680fb9d516646926b45d1b41` is GREEN in clean-worktree verification, production build, authenticated Chromium acceptance and all routed exact-head GitHub checks. The P1 hidden-fault and P2 color-only LIVE review findings are fixed, the stale Overview navigation acceptance label is aligned, and review threads are zero. Production runtime has not been changed; this presentation-only Work Package requires no hardware acceptance.

## Issue #968 — SSD migration completed; simultaneous-media boot verified

**Cleared for accepted storage scope; coexistence now hardware-verified.** Normal SSD boot and the repository-owned fail-closed `verify` had already passed with `/=/dev/sda2`, `/boot/firmware=/dev/sda1`, UAS 5000M, healthy runtime and advancing acquisition. On the 2026-09-09 `10:00:41+03:00` boot, the installed microSD was detected as `/dev/mmcblk0` at kernel ~`0.67 s`, while the Pi still selected SSD `/dev/sda2` + `/dev/sda1` under `BOOT_ORDER=0xf146`. Post-boot evidence again showed 12 healthy containers, Device Agent `ok`, MQTT connected, queue `0`, advancing samples, and Dashboard `/` + `/login` HTTP 200. Therefore simultaneous SSD+microSD boot is no longer a blocker or unverified claim. Residual maintenance risk: the auto-mounted microSD FAT boot partition emitted a `Volume was not properly unmounted` warning; no `fsck`/repair was executed. `prepare` and `cutover` must not be rerun.

## Issue #843 — Telemetry planner-choice CI nondeterminism

**Repository-side blocker cleared 2026-09-03.** PR #844 exact verified implementation head `fcd9d2429ef19c9410fdfe9292d6f5d04cdc7c1b` passed all 11 registered workflows, including Telemetry Service `33770161208`, Core CI/NEXOLAB Merge Gate `33770159789` and Offline Bundle `33770159680`. The repair preserves the production query and schema while replacing an optimizer-specific exact-index-name assertion with independent canonical-index catalog validation plus an index-backed latest-value probe. Local repeated PostgreSQL 16 and transactional negative evidence are GREEN. No production deployment, runtime mutation, Modbus/hardware write or data/volume mutation occurred. GitHub merge status is queried online; after PR #844 merges, integrate current `main` into TG-04 PR #842 and rerun its exact-head verification.

## Issue #845 — TG-04 scheduler activation must fail closed

**Cleared 2026-09-03.** PR #846 exact head `cae3e45ad6a11b74797dd843c187c44602f9aa81` passed the full classified workflow matrix and squash-merged to `main` at `242dd46c01109e2f75b7ac60e5bf8f7f28ac49b6`. Application, service-constructor and central Compose defaults now keep daily-report scheduling fail-closed OFF; explicit later enablement remains supported. No production migration/cutover, Telegram send, Modbus/hardware write or destructive action occurred.

## Issue #851 — Stage-2 source-authority metadata reconciliation

**Cleared 2026-09-03.** Product Owner-approved Stage-2 deployment passed on exact source `13ab26392fcb1c1385dca3c1f619da4512fe568c` with authoritative evidence `runtime/deployments/20260903T191159Z`; live Alembic is `20260902_0031`. Runtime is healthy, persistent volumes are preserved, Telegram delivery/worker remain OFF, Mini App remains ON, `last_send_at=null`, and `DAILY_REPORTS_SCHEDULER_ENABLED=false`. The canonical privileged source adopter then returned `status=recorded` for `controlled_source_deployment`, exact source `13ab2639...`, schema `0031`, health `ready`, `linux/arm64`, runtime mode `lan`, `known_packaged_release=false`, and the same authoritative evidence. #851 no longer blocks TG-04.

## Issue #854 — Telegram Mini App persisted-report schema contract drift

**Cleared 2026-09-04.** PR #855 exact verified head `cb4db273ab15e42654ee53ef6629e8021d182f7c` passed Core Quality/build + NEXOLAB Merge Gate (`33820118255`), Offline Bundle (`33820118249`), Telegram Gateway (`33820118259`) and Container Supply Chain (`33820118311`), then merged and closed #854. The Mini App now accepts canonical TG-01 schema `nexolab.daily-refrigeration-report.v1` while stale/unknown values remain fail-closed. No runtime mutation or Telegram send occurred.

## Issue #884 — local candidate Compose overlay validation

**Cleared 2026-09-04.** PR #885 exact head `e63e3c91bf41b312613d07474462a84df5cf8bd5` passed exact local candidate verification (143/143 frontend files, 697/697 tests, format/lint/typecheck/build GREEN), Core Quality and NEXOLAB Merge Gate in run `33855597946`, then squash-merged to `main` as `71ffd1a367d510a58d5147efec07d96cbe0ac8cb`. The local verifier now validates canonical Compose bundles, validates a changed Telegram overlay with its central base, and fails closed on unregistered changed Compose files. No runtime mutation, Telegram send, scheduler activation, Modbus write or hardware write occurred. #884 no longer blocks #883.

## Issue #883 — TestLAB morning-report forum-topic routing

**Cleared 2026-09-04.** PR #886 exact head `0d4c4880bc62743ac88bccb80b3331559760ccca` passed local exact-candidate verification, Telegram Gateway `33857478217`, disconnected Offline Bundle `33857478142`, Telemetry Service `33857478227`, Container Supply Chain `33857478251`, Core Quality/build and NEXOLAB Merge Gate `33857478294`, then squash-merged to `main` as `6ea1996ef7bf3da6bed35220b813d0706d64a17f`. Topic-aware destination identity is repository-complete; no runtime topic capture/configuration or real topic send occurred in #883.

## Issue #893 — guarded topic-aware persistent Gateway refresh

**Active focused prerequisite; no repository blocker.** The persistent Telegram Gateway is still the pre-topic Stage-1 image and lacks the topic env contract, while one-shot topic delivery has already passed. #893 adds a repository-owned Gateway-only refresh guard that pins exact source and exact current image, requires protected delivery OFF + topic present + scheduler OFF, preserves the delivery volume and core-container identities, force-recreates only `telegram-gateway`, and verifies rollback to the exact previous image if post-recreate validation fails. Production execution remains a separate Product Owner cutover gate. No Telegram send, scheduler activation, Modbus write or hardware write belongs to repository implementation.

## Issue #898 — guarded recurring 07:50 activation

**Cleared 2026-09-04.** PR #900 exact head `e0f36abc2d028f640ea81795e0ee3ddea287e7d5` passed canonical local verification, Core CI, Telemetry Service, Telegram Gateway, disconnected Offline Bundle, Container Supply Chain and NEXOLAB Merge Gate. Fresh exact-head Codex review found no major issues and all inline threads are resolved. The final guard behaviorally rejects any pinned Gateway image that cannot enforce the activation cutoff/bootstrap allow-set before mutation. No production runtime mutation or Telegram send occurred in #898.

## Issue #901 — boundary-aware persistent Gateway refresh

**Cleared 2026-09-05.** PR #904 exact head `f3975ff2727035b2c1c8ffb0d5aec4b70863a5e3` passed fresh Core Quality/build, Telemetry Service and NEXOLAB Merge Gate; fresh Codex review found no major issues and all inline threads were resolved. It squash-merged to `main` as `c19158b22a1632945a961726b4b6b0794d1ae330`. After a fresh exact-main immutable-image/read-only preflight, the Product Owner explicitly approved the exact Gateway-only tuple and the repository guard completed with exit 0. Persistent Gateway image is now `sha256:f3f846a21b946ccef6ae61879777cab08bf9334f0207ccf070aed0a2b64a7ffd`; delivery/worker and weekday scheduler remain OFF, Mini App remains ON, `last_send_at=null`, outbox remains the exact accepted two historical sent rows with canonical full-row hash `0cdbb20560d2e1cf5137d257044e64cfcb1d26ce7246a0ffc3637bbc42e1c15a`, core container IDs and Tailscale Serve are unchanged, and the exact previous image is retained for rollback. Evidence: `runtime/evidence/tg04-telegram-refresh-20260905T034958Z`. No Telegram send, Modbus/hardware write, volume deletion or unrelated service restart occurred.

## Issue #825 — TG-04 real Telegram acceptance

**Cleared 2026-09-05.** The Product Owner-approved guarded recurring activation passed on exact source `9310ab30d735eb6253316230c7c479df0e3339a4` with evidence `runtime/evidence/tg04-recurring-activation-20260905T085419Z`. The `Europe/Kyiv` Monday-Friday 07:50 scheduler is enabled, Telegram topic delivery is enabled, the Gateway worker is healthy/running, and exactly one approved immediate due report for `2026-09-04` was generated and delivered to `Ранковий звіт`. Post-activation outbox state is three sent rows, non-sent `0`, duplicate-risk `0`; a fresh planner predicts generation `0` and immediate delivery `0`. Product Owner visual evidence confirms the report and `Відкрити NEXOLAB` action in the target topic. Core container identities and Tailscale Serve are unchanged, and no Modbus/hardware/controller write or destructive data/volume operation occurred. The first natural next weekday 07:50 delivery is post-acceptance operational evidence, not a blocker. State reconciliation is tracked by #907.

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

## Issue #200 — physical RS-485 topology — cleared for current scope

Software/runtime topology is reconciled: production has two stable healthy workers, `rs485-main` on `0133F090` at 9600 8N1 and `rs485-embraco` on `0133F246` at 9600 8N2 with Embraco Unit 2 only. Current scheduler ownership has no cross-bus duplicate Unit ID, both stable paths are present, and the commissioning helper protects every runtime-reported production adapter from active discovery while failing closed on incomplete/malformed ownership diagnostics. On 2026-09-05 the Product Owner explicitly de-scoped the remaining photo/physical-inspection items from #200 acceptance. Unit 115 physical reality/location, cable topology, termination, biasing, shielding/ground/common-reference and electrical duplicate-ID exclusion remain **not hardware-verified**, but they are no longer current-scope blockers. No physical action was performed in this reconciliation.

## Issue #201 — LE-01MP cumulative energy

Normal-operation semantics are accepted. Controlled restart/power-cycle discontinuity evidence remains pending; an unplanned hard reset cannot be reclassified as approved evidence.

## Issue #202 — XJP60D portability

Representative KK1/KK2 physical evidence, Unit 115 resolution and extended semantics still require real hardware evidence. Unconfirmed fields remain unmapped.

## Issue #866 — recurring XJP60D recovered FC03 retries

**Cleared and completed 2026-09-05.** Read-only historical and live evidence proves the retry pattern existed before the 2026-09-04 restart and remains XJP60D-specific: LE-01MP on the same `rs485-main` bus and Embraco on the second bus are retry-free in the bounded comparison, while queue depth stays 0 and bus workers remain healthy. Recovered retries do not duplicate logical telemetry; terminal failures are explicitly represented as `communication_error`. Exact candidate `8ff18c4097ff0c51f81b0c7f98fbaea683938719` passed Core CI / NEXOLAB Merge Gate `33962777794` and Telemetry Service `33962777924`; PR #917 closed #866. No production timing/topology/runtime change occurred.

## Issue #916 — exact XJP60D first-request timeout mechanism

**Cleared and completed 2026-09-05.** Product Owner-authorized passive attempt-level observation proved `value attempt 1 success → status attempt 1 timeout → status attempt 2 success` on Units 102, 104 and 106, refuted first-after-idle, and showed retry-free same-bus LE-01MP with zero protocol/CRC, I/O or Modbus exception-response errors. Exact candidate `d431d75b24140761edaae3fca1ccb38cc89857f4` passed Core CI / NEXOLAB Merge Gate `33965131628` and Telemetry Service `33965131627`; PR #920 closed #916. No production change is justified or authorized. A future inter-register-pacing experiment, restart/adapter reset, topology/termination/bias action, cable move or power cycle is a separate gated Work Package; Modbus/controller writes remain forbidden.

## Issue #585 — W2 / Unit 201 handback

Blocked until the Product Owner confirms the temporary external RS-485 owner has released W2 and approves any required physical handback/reconnection.

## RFX programme — RFX-12 merged; no RFX-13 Work Package defined

RFX-01 through RFX-12 are repository-complete. RFX-12 / #1088 / PR #1089 final head `621d70605856e07bdfc6003c851ca2ddbb593f4f` passed Core Quality/build + NEXOLAB Merge Gate `35368527778` and Authenticated Dashboard Acceptance `35368527798`. The accepted product baseline is `1a0644497e4cfd10ce7ba0366772955c72f4711a`; production remains deployed at `df368cfa27efa945d59de33de8268898b564a19f`.

RFX-12 makes the Overview temperature workspace full width and moves “Потребує уваги” below it. No backend, telemetry, alarm logic, dependency, deployment or hardware scope changed.

There is no repository-backed RFX-13 Issue and no independent Ready Work Package. Existing non-Ready boundaries remain: #585 external RS-485 handback, #189 actual-host recovery evidence, #201/#202 real hardware validation, #17 dependencies on hardware semantics, #257/#256 toolchain dependencies, and stale #1019 production-release planning.

This empty Ready queue remains a hard scheduling blocker under Autonomous Sprint Mode. The next product Work Package requires Product Owner prioritization unless a critical defect/security interruption creates a higher-priority scoped Issue.

## Issue #909 — consolidated HIGH container exception review

**Cleared and merged 2026-09-05.** First exact-head no-cache scan `33957510014` correctly failed closed on two stale `libexpat1 / CVE-2026-66046` exceptions, one in Device Agent and one in Telegram Gateway; both were removed. Final candidate `8c314af3e372ab2720d7570662929f51c932ab60` passed Container Supply Chain `33959133577` and Core CI / NEXOLAB Merge Gate `33959133555`; PR #910 then squash-merged to `main` as `6bb92e3d952d77e7f25bd75cf470f5b2884f7606` and GitHub closed #909 completed. The scheduled 2026-09-12 review is now active as Issue #994. After the four #978 Expat tuples, the current registry contains 95 exact HIGH exceptions; none may be retained beyond today without #994 fresh no-cache scan and current evidence. CVE-2026-78409 and the #978 Expat findings require explicit revalidation. No production deployment, runtime mutation, Modbus/hardware write or data/volume change is authorized by the review.

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
- #715 RFX-00 refrigeration architecture ADR — completed and merged in PR #716; ADR 0010 remains accepted architecture authority. The former #727 presentation hold was lifted; RFX-01 through RFX-08B are completed through GREEN focused PRs, including #953 / PR #954, #957 / PR #958 and #960 / PR #962. RFX state remains completed through #960; current independent maintenance is tracked separately by the active Work Package.
- #733 canonical project-state formatter boundary — completed locally; `.project/*.json` is excluded from Prettier and remains governed by State Model v2 validation.

## Sprint execution gate — #1045 completed candidate; #1050 auth gate remains

Issue #1045 is software-complete on product commit `9edf33764cda95da912a6140db8e51cf0cd9d623`. The frontend cadence contract now accepts the already production-supported `embraco` family, renders `Embraco Sync Controller`, and preserves strict rejection of `akcc25`/unknown families. Targeted tests are 11/11 PASS with ESLint, Prettier, TypeScript and `git diff --check` GREEN. No deployment or hardware action belongs to #1045. The only current hard blocker in the active chain remains #1050: a normal authenticated operator session with `equipment.manage` is required for the final Equipment → Connect device live UI/API walkthrough.

#189/#585 remain blocked, #201 remains `needs_validation`, #202 remains `hardware_validation`, and K96–K100 remain hardware-unverified/excluded from automatic production polling. Issue #1012 completed the previously scheduled 2026-09-15 security review early; the next fail-closed exception boundary is 2026-09-21.

The exact cause of the earlier unplanned 2026-09-10 reboot remains unknown because Raspberry Pi OS used volatile journald at the time. Current evidence does not support changing UAS, disabling the hardware watchdog, changing power hardware or modifying swap. Any such change requires new retained failure evidence.

## Issue #978 — new libexpat1 HIGH supply-chain gate

**Cleared and merged 2026-09-09.** Trigger run `34307375095` correctly failed closed on exactly four new HIGH tuples: Device Agent and Telegram Gateway each contained `libexpat1 2.8.3-1~deb13u1` with `CVE-2026-76956` and `CVE-2026-76957`. The bounded four-tuple exception disposition expires `2026-09-12`. PR #979 final head `b3c7cd94f7861ddc7491e18b85ce8342af0a33fe` passed Container Supply Chain `34312069721`, Core/NEXOLAB Merge Gate `34312069737` and Telemetry Service `34312069846`, with zero review threads, then merged to `main` as `7252295de3d76dab1f3554b1f257918f1e9a5891`; Issue #978 closed. No production deployment, runtime mutation, Modbus/hardware write, data deletion or volume deletion occurred.

## Issue #970 — SSD migration mountpoint defect completed

**Cleared and merged 2026-09-08.** Exact verified head `50de09b63093fdaca27e82d51b0767bb6b472c30` hardened required target-root mountpoints, deterministic FAT mount permissions and CI regression routing. All required exact-head workflows were GREEN with zero unresolved review threads; PR #971 squash-merged to `main` as `88d484dc8007469d1654fb17434e22ef1cfbc1eb` and GitHub closed #970 completed. Real repaired-target boot and the later official #968 verify prove the operational fix. No SSD reformat, product-data deletion, Docker-volume deletion, Modbus write or hardware write belonged to #970.

## Issue #1012 — HIGH container exception review — cleared for repository scope

**Cleared 2026-09-14.** Fresh no-cache evidence retired 12 stale tuples and leaves 80 exact HIGH / 0 CRITICAL findings with 1:1 registry reconciliation. Verified implementation head `24d99f6f30b90ca4bb3d4fca00515ddec11981cf` passed Container Supply Chain `34828653792`, Telemetry Service `34828653794`, Core CI / NEXOLAB Merge Gate `34828653811`, focused policy tests and zero-thread review. Retained exceptions expire **2026-09-21** and fail closed after that boundary. PR #1013 passed the final state-only exact-head gate and squash-merged to `main` as `2c30e7cb11eed892093f8ceb8bf94cb88fee7f75`; Issue #1012 is closed completed. No production/hardware action was authorized or performed.

## Safety boundaries

No blocker may be bypassed by Modbus/controller write, hardware write, production/site cutover without approval, persistent-data deletion, named-volume deletion, secret exposure or mandatory cloud dependency.
