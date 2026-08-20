# NEXOLAB Blockers

Updated: 2026-08-20

## Issue #584 — complete

Temporary exclusion of LE-01MP W2 / Unit 201 from active NEXOLAB polling is complete. Evidence remains `runtime/deployments/issue-584-20260818T185455Z`.

## Issue #585 — blocked physical restoration lane

Restoring W2 / Unit 201 to NEXOLAB is blocked until the Product Owner confirms that the external controller/system no longer owns the W2 RS-485 interface and approves any physical handback required to return bus ownership to NEXOLAB.

The 2026-08-21 through 2026-08-23 review window is a review window only; it is not authorization to perform physical or hardware changes.

## Issue #586 — complete

PR #592 merged GREEN as `75c6f5471d77d781b124fbd40c33ba924aec26f8`. Browser-closed Raspberry Pi evidence, Core CI, Authenticated Dashboard Acceptance and Offline Bundle are all PASS. There is no remaining #586 blocker.

## Issue #598 — complete security prerequisite

PR #599 merged GREEN as `b25ae18e196eb84fc56ae951003d0820a22dc579`. Container Supply Chain `32219772068`, Core CI `32219771902` and Telemetry Service `32219771893` all PASS. The exact CVE-2026-14456 decisions expire 2026-08-26 and must be removed earlier if Debian publishes a fixed package or QUIC runtime reachability changes.

There is no remaining #598 blocker.

## Issue #587 — complete

PR #597 merged GREEN as `84584640246f8985c0c303654def99365c8458c4`. Core CI, Telemetry Service, Authenticated Dashboard Acceptance, Offline Bundle, Acquisition Scale and Container Supply Chain are PASS. There is no remaining #587 blocker.

## Issue #588 — complete

PR #602 merged GREEN as `62e94ea02b2f4c7da03d1a5fa11cc1e24459f6f7`. Core CI, Refrigeration Browser Acceptance, Authenticated Dashboard Acceptance and Offline Bundle are PASS. There is no remaining #588 blocker.

## Issue #594 — complete

PR #593 merged GREEN as `b46e518f8769f83ba22c608bacd5a368776e1701`. Dedicated MCP identity provisioning and authenticated Raspberry Pi acceptance are complete. The supported `laboratory_technician` account has only `telemetry.read` and `nodes.read`; all six read-only MCP tools and token refresh passed against the real LOCAL_LAN runtime. There is no remaining Issue #594 blocker.

Persistent MCP service enablement, production credential relocation, and any external tunnel/reverse-proxy exposure remain separate production/site cutover actions requiring their own approval; they are not part of the merged implementation.

## Issue #608 — complete CI reliability interrupt

PR #609 merged GREEN as `3e13800f413eb2255b992b6ff9f3aec935acf602`. The blocking Playwright `--with-deps` / Ubuntu APT bootstrap dependency is removed from Authenticated Dashboard and Refrigeration Browser acceptance. There is no remaining #608 blocker.

## Issue #611 — complete browser-readiness reliability interrupt

PR #612 merged GREEN as `57908efc7f27598f5a991e2a009aaab0f6b92676`. Live retry browser acceptance now proves one routed WebSocket plus a fresh local telemetry sample before requiring the truthful Live state, and changes to that test now trigger Authenticated Dashboard Acceptance. There is no remaining #611 blocker.

## Issue #604 — complete

PR #616 merged GREEN as `f1d13bc2401ba16ef76b95bec5f31e9a9d969c76`. Core CI `32263137097`, Refrigeration Browser Acceptance `32263134788`, Offline Bundle `32263135467`, focused large-inventory Equipment browser acceptance and acquisition-invariant acceptance all PASS. There is no remaining #604 blocker.

## Issue #619 — complete

PR #623 merged fully GREEN as `4ab72f1c3c51a8822723e9a53c4881b0415ee9c1`. Core CI `32329087115`, Authenticated Dashboard `32329087128`, Refrigeration Browser `32329087103`, Disaster Recovery `32329087134` and Offline Bundle `32329087175` all passed. There is no remaining #619 blocker.

## Issue #620 / PR #622 — complete controlled exception

PR #622 merged as `9f54faa25c2f6c0d7e0f1bf84e772c0e3fa6ab6f` under the single Product Owner-approved controlled exception. The known #619 Auth failure was subsequently repaired and PR #623 merged fully GREEN. There is no remaining #620 blocker.

## Issue #605 / PR #621 — complete GREEN

PR #621 merged as `ad2a49473c9798dc8e4f374ec031b2144c0606e2` after fully GREEN exact-head CI. There is no remaining #605 product blocker. The Raspberry Pi full-ESLint resource incident remains a verification-host constraint only; heavy repository-wide lint/build should continue on GitHub CI.

## Issue #606 — Ready

The #605 dependency is complete. Issue #606 is `status:ready` for repository/architecture audit and a focused read-only LOCAL_LAN discovery implementation. Hardware/public-network scanning and Modbus/device writes remain prohibited.

## Issue #618 — independent reliability lane

Saved Dashboard CSV browser download can time out in the local Raspberry Pi full dashboard matrix. Final #623 GitHub Authenticated Dashboard Acceptance passed, so #618 does not currently block #605. Keep it isolated unless a required #605 check makes it a direct dependency.

## Issue #615 — non-blocking acceptance tooling defect

The authenticated-dashboard runner's default generated `COMPOSE_PROJECT_NAME` contains uppercase timestamp characters rejected by current Docker Compose. Issue #615 tracks the isolated repair; explicit lowercase overrides remain the local workaround.

## Planned product queue

- #619 telemetry-navigation/read-model reliability — complete in PR #623;
- #620 persisted Live Dashboard deterministic clock repair — complete in PR #622;
- #605 / PR #621 permissioned equipment metadata editing — complete GREEN;
- #618 Saved Dashboard CSV export — independent reliability lane;
- #606 discovery/adoption inbox — Ready;
- #607 dual RS-485 KK1/KK2 bus isolation — software architecture before #589; hardware cutover remains unapproved;
- #589 persisted cadence/capacity — held behind #607;
- #590 Settings cadence controls — blocked on #589.

## Deferred software lanes

- #588 Energy Monitoring chart parity — complete in PR #602;
- #604 Equipment workspace — complete in PR #616;
- #605 Equipment metadata editing — complete GREEN in PR #621;
- #606 LOCAL_LAN discovery inbox — Ready after #605;
- #607 dual RS-485 KK1/KK2 architecture — queued before #589;
- #589 persisted acquisition cadence/capacity validation — held behind #607 and current product priority;
- #590 Settings acquisition cadence controls — blocked on #589;

## Remaining evidence lanes

- #585 W2/Unit 201 physical ownership restoration — blocked;
- #444 end-to-end local user-management acceptance;
- #201 restart/power-cycle and rollover/reset/discontinuity validation;
- #245 standalone loopback-only Raspberry Pi acceptance;
- #189 backup/restore/rollback/power-loss acceptance;
- KK2/Unit 115 field retest.

## Safety boundaries

No Modbus/controller write, actuator/hardware write, product persistent-data deletion, Docker named-volume deletion, secret/billing/DNS mutation or mandatory cloud runtime dependency is authorized.
