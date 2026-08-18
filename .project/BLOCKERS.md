# NEXOLAB Blockers

Updated: 2026-08-18

## Issue #584 — complete

Temporary exclusion of LE-01MP W2 / Unit 201 from active NEXOLAB polling is verified and reconciled on `main` through PR #591.

- registry revision `7 -> 8`;
- device lifecycle is `disabled`;
- canonical device and 9 target definitions are preserved;
- Unit 201 has zero poll-eligible targets and zero scheduler jobs;
- Device Agent health is `ok`;
- Units 200/202/203 continue advancing;
- state persists after restarting only `device-agent`;
- evidence: `runtime/deployments/issue-584-20260818T185455Z`.

There is no remaining #584 blocker.

## Issue #585 — blocked physical restoration lane

Restoring W2 / Unit 201 to NEXOLAB is blocked until the Product Owner confirms that the external controller/system no longer owns the W2 RS-485 interface and approves any physical handback required to return bus ownership to NEXOLAB.

The 2026-08-21 through 2026-08-23 review window is a review window only; it is not authorization to perform physical or hardware changes.

## Issue #586 — no product blocker; final validation in progress

Browser-closed Raspberry Pi evidence is PASS and proves Device Agent/PostgreSQL acquisition continuity without a browser. PR #592 contains the focused Overview persisted-history repair. Core formatting/lint/typecheck/tests/build are PASS on run `32179097680`; final-head required gates must be GREEN before merge.

This is validation work, not a blocker requiring Product Owner action.

## Issue #587 — dependency blocked until #586 merge

Saved Live Dashboard complete persisted ranges and CSV export must continue to consume the canonical complete-history/reconciliation foundation from #586. Do not implement a parallel loader before #586 is GREEN and merged.

## Remaining evidence lanes

- #585 W2/Unit 201 physical ownership restoration — blocked;
- #444 end-to-end local user-management acceptance;
- #201 restart/power-cycle and rollover/reset/discontinuity validation;
- #245 standalone loopback-only Raspberry Pi acceptance;
- #189 backup/restore/rollback/power-loss acceptance;
- KK2/Unit 115 field retest.

## Safety boundaries

No Modbus/controller write, actuator/hardware write, product persistent-data deletion, Docker named-volume deletion, secret/billing/DNS mutation or mandatory cloud runtime dependency is authorized.
