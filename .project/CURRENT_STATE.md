# NEXOLAB Current State

Updated: 2026-08-18

## Repository and runtime baseline

Repository `main` is `c7052d0749f673bf8ee952f20c47762b6d7b1848`.

The Raspberry Pi source runtime remains deployed at `7a19f53950492a40255c53b1d2018bbdff9466e2`. Issue #584 changed only the persisted local AcquisitionRegistry; it did not change the deployed source revision.

## Issue #584 — temporary Unit 201 exclusion PASS

LE-01MP W2 / Unit 201 is temporarily externally owned on RS-485 and is now intentionally excluded from active NEXOLAB polling while remaining in canonical inventory/history.

Real Raspberry Pi evidence:

- acquisition registry revision `7 -> 8`;
- `le01mp-201` lifecycle `active -> disabled`;
- 9 Unit 201 target definitions preserved;
- Unit 201 poll-eligible targets `9 -> 0`;
- Unit 201 scheduler jobs `9 -> 0`;
- Device Agent health `degraded -> ok`;
- scheduler workers remained healthy;
- Units 200/202/203 continued advancing during a bounded 35-second verification window;
- after restarting only `device-agent`, revision 8 and the disabled lifecycle persisted and health remained `ok`.

Evidence: `runtime/deployments/issue-584-20260818T185455Z`.

No Modbus write, meter configuration/address change, wiring change, power/reset operation or persistent telemetry deletion occurred.

## Restoration lane

Issue #585 remains blocked. Do not restore Unit 201 until the Product Owner confirms the external controller no longer owns W2 and explicitly approves any required physical handback. Review window remains 2026-08-21 through 2026-08-23, but the date alone does not authorize restoration.

## Current execution boundary

Next Ready Work Package: **Issue #586 — Prove and repair persistent telemetry history across browser-offline intervals**.

Issue #586 is software-first and independent of the blocked physical restoration lane. Its first step is to prove whether acquisition/PostgreSQL continue advancing with browsers closed, then repair Overview persisted-history loading/reconciliation without allowing UI activity to affect physical polling.

## Safety boundaries

`LOCAL_LAN`, offline-first runtime and read-only industrial boundaries remain unchanged. No Modbus/controller write, hardware write, production/site cutover, persistent-data deletion, named-volume deletion, secret/billing/DNS mutation or mandatory cloud runtime dependency is authorized.
