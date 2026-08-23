# NEXOLAB Current State

Updated: 2026-08-23

## Current Sprint

`CHART-RELIABILITY-1` is active under Epic #450 — canonical chart interaction and reliability.

Issue #415 is completed and squash-merged through PR #662. Exact-head Core CI, Authenticated Dashboard Acceptance, Refrigeration Browser Acceptance, Offline Bundle and NEXOLAB Merge Gate were GREEN before merge. The production Live Chart System acceptance proved zoom → left-button drag pan → constant visible span → Exact Inspector resume → reset with no history/acquisition side effects.

Active Work Package: Issue #663 — **Trigger authenticated chart acceptance for canonical Chart System changes** on branch `chore/663-authenticated-chart-acceptance-routing`. It closes the CI routing gap exposed by #415 without changing chart product behavior.

## Durable baselines

Accepted product source: `286a219611f95413b5580d8099a7c5665416d1ad`.

Deployed product source: `6e387485b68fb862d9f82ae7f6000b1f5b672764`.

The Raspberry Pi Git checkout is synchronized with current GitHub `main`, but the running Dashboard remains pinned to the immutable deployed release above. Repository synchronization is not a deployment or cutover.

## Issue #663 architecture boundary

Authenticated Dashboard Acceptance already executes `live-chart-system.production.e2e.ts` and `equipment-multi-axis-chart.production.e2e.ts`, but its `pull_request.paths` contract omitted the canonical shared chart directories and both chart E2E files.

Issue #663 is CI-governance only:

- add `src/features/charts/**` and `src/components/charts/**` to the existing dashboard trigger contract;
- add the two canonical chart E2E files already executed by `playwright.dashboard.config.ts`;
- add dependency-free policy regression coverage;
- preserve the workflow body, isolated Compose stack, Playwright configuration, runtime behavior and hardware boundaries.

## Recently completed security maintenance

Issue #660 / PR #661 is merged. Four exact OpenSSL QUIC `CVE-2026-14456` HIGH/no-fix exceptions remain reviewed only through **2026-08-30**.

Final exact-head Container Supply Chain run `32626324921` was GREEN. Remove the decisions earlier if a supported fixed Debian Trixie package appears, the exact findings disappear, QUIC reachability changes, or severity becomes Critical.

## Raspberry Pi and RS-485 boundary

The Remote Desktop/Raspberry Pi connector is online. Passive Issue #200 evidence confirms only one CP2104 RS-485 adapter is currently enumerated and the running Device Agent uses one `rs485-main` bus. Draft PR #659 remains intentionally unmerged because physical dual-bus/topology acceptance is incomplete.

Do not start a second Modbus master/scanner while the production Device Agent owns the bus. No Modbus write is permitted.

## Validation boundaries retained outside the active Sprint

- #444 — local-admin route is mounted in the current deployed runtime; full acceptance still needs an authorized administrator identity and local-user create/auth verification.
- #245 — standalone loopback acceptance still requires an explicitly approved network-isolation/reboot/cutover exercise.
- #200 — physical topology, second adapter, Unit 115 reality and electrical observations remain hardware-unverified.
- #201 — approved restart/power-cycle discontinuity evidence remains pending.
- #202 — representative KK1/KK2 and Unit 115 physical evidence remains pending.
- #585 — W2 / Unit 201 physical handback still requires Product Owner confirmation/approval.
- #189 — controlled actual-host recovery/power-loss evidence remains outstanding.
- #646 — repository branch protection/rules remain a soft settings-access blocker.

## Runtime and offline boundary

Issue #663 is CI-governance only. It must not change chart product behavior, telemetry acquisition, persistence, polling cadence, WebSocket topology, offline operation, authentication, database schema, deployment or device configuration.

Core NEXOLAB runtime remains LOCAL_LAN/offline-first with no mandatory public internet, paid service, CDN, remote font or external runtime API.

## Safety boundaries

No Modbus/controller write, hardware write, product persistent-data deletion, Docker named-volume deletion, secret/billing/DNS mutation or production/site cutover is authorized by Issue #663.
