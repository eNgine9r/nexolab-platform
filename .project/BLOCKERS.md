# NEXOLAB Blockers

Updated: 2026-08-19

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

## Issue #615 — non-blocking acceptance tooling defect

The authenticated-dashboard runner's default generated `COMPOSE_PROJECT_NAME` contains uppercase timestamp characters rejected by current Docker Compose. Issue #615 tracks the isolated script repair. #604 browser gates pass with an explicit lowercase project-name override, so this is not a product or merge blocker for #604.

## Issue #605 — blocked by exact-main CI reliability prerequisites

Draft PR #621 contains the focused permissioned metadata implementation, but required checks are red because exact-current-main reliability defects reproduce independently of the #605 diff.

- #620 blocks Core CI `Quality and build`;
- #619 blocks Authenticated Dashboard Acceptance.

Do not merge PR #621 and do not mix either reliability repair into the #605 feature branch. Merge #620 and #619 independently, update #605 from the repaired `main`, then rerun all required checks.

## Issue #620 — active blocking CI defect

Persisted Live Dashboard unit fixtures used fixed 2026-08-18 telemetry with a preset window anchored to real wall-clock time. The two failures reproduce on exact `main`. #620 is the active single-WIP reliability interrupt and blocks PR #621 Core CI until merged.

## Issue #619 — Ready blocking browser reliability defect

PR #621 Authenticated Dashboard Acceptance passed 15/16 tests and failed only the repeated-navigation active-alert read bound. Exact-main focused navigation acceptance is independently unstable. #619 is Ready immediately after #620 and blocks PR #621 from becoming GREEN.

## Issue #618 — open non-blocking Saved Dashboard export reliability defect

Saved Dashboard CSV browser acceptance can time out waiting for the browser download event and reproduces on exact `main` locally. It did not fail the current PR #621 GitHub browser matrix, so it is not an immediate dependency of #605; keep it isolated as a separate high-priority reliability lane.

## Planned product queue

- #604 scalable Equipment workspace — complete in PR #616;
- #620 persisted Live Dashboard deterministic clock repair — active CI reliability interrupt;
- #619 telemetry navigation/read-model reliability — Ready after #620;
- #605 permissioned equipment metadata editing — implementation published in draft PR #621, blocked on #620 and #619;
- #606 read-only LOCAL_LAN discovery/adoption inbox — blocked on #605 canonical editing/adoption boundaries;
- #607 dual RS-485 KK1/KK2 bus isolation — software architecture before #589 cadence/capacity is finalized; hardware installation/cutover remains unapproved;
- #589 persisted cadence/capacity — held behind the user-prioritized Equipment lane and #607 bus-aware architecture;
- #590 Settings cadence controls — blocked on #589.

## Deferred software lanes

- #588 Energy Monitoring chart parity — complete in PR #602;
- #604 Equipment workspace — complete in PR #616;
- #605 Equipment metadata editing — draft PR #621 blocked on #620 and #619;
- #606 LOCAL_LAN discovery inbox — blocked on #605 boundaries;
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
