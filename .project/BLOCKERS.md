# NEXOLAB Blockers

Updated: 2026-08-18

## Issue #584 — complete

Temporary exclusion of LE-01MP W2 / Unit 201 from active NEXOLAB polling is complete. Evidence remains `runtime/deployments/issue-584-20260818T185455Z`.

## Issue #585 — blocked physical restoration lane

Restoring W2 / Unit 201 to NEXOLAB is blocked until the Product Owner confirms that the external controller/system no longer owns the W2 RS-485 interface and approves any physical handback required to return bus ownership to NEXOLAB.

The 2026-08-21 through 2026-08-23 review window is a review window only; it is not authorization to perform physical or hardware changes.

## Issue #586 — complete

PR #592 merged GREEN as `75c6f5471d77d781b124fbd40c33ba924aec26f8`. Browser-closed Raspberry Pi evidence, Core CI, Authenticated Dashboard Acceptance and Offline Bundle are all PASS. There is no remaining #586 blocker.

## Issue #587 — Ready

Saved Live Dashboard complete persisted ranges and CSV export is the only current `status:ready` Work Package. Its dependency on #586 is satisfied.

It must reuse the canonical complete-history/reconciliation path, keep range/export actions read-only with respect to acquisition, and generate CSV from persisted telemetry rather than reduced chart/browser memory.

## Issue #594 — complete

PR #593 merged GREEN as `b46e518f8769f83ba22c608bacd5a368776e1701`. Dedicated MCP identity provisioning and authenticated Raspberry Pi acceptance are complete. The supported `laboratory_technician` account has only `telemetry.read` and `nodes.read`; all six read-only MCP tools and token refresh passed against the real LOCAL_LAN runtime. There is no remaining Issue #594 blocker.

Persistent MCP service enablement, production credential relocation, and any external tunnel/reverse-proxy exposure remain separate production/site cutover actions requiring their own approval; they are not part of the merged implementation.

## Deferred software lanes

- #588 Energy Monitoring chart parity — held behind the active single-WIP sequence;
- #589 persisted acquisition cadence/capacity validation — held behind the active single-WIP sequence;
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
