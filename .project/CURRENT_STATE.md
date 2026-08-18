# NEXOLAB Current State

Updated: 2026-08-18

## Accepted product baseline

The current accepted NEXOLAB product baseline is:

`9732b68b0d14e4056e5773e0a9bec3f3741e267f`

This is the squash merge of PR #559 — **feat: add safe GitHub update discovery plane**, closing Issue #548.

Post-merge project-state reconciliation/finalization is state-only and does not change the accepted product baseline.

## Current Raspberry Pi runtime

Before the newly approved deployment, the Raspberry Pi remains at:

`0bfc4fcc56f7a669545be166c585573550f2fb44`

Existing controlled deployment evidence:

`runtime/deployments/20260818T083157Z`

## Issue #566 — deployment approval granted

On 2026-08-18 at 16:03 Europe/Uzhgorod, the Product Owner explicitly approved updating the existing Raspberry Pi to the new project version.

The approval authorizes only the controlled LOCAL_LAN deployment/acceptance lane for Issue #566 / #560 / #548. It does not authorize Modbus/controller writes, hardware writes, persistent-data deletion, named-volume deletion, secret exposure or unrelated site changes.

Immediately before deployment, the Raspberry Pi must re-read `origin/main`; the deployment script must use `--runtime-mode lan`, run the capacity guard, preserve a clean tracked working tree, create the PostgreSQL backup when applicable, fast-forward only, build/start the runtime, run smoke/health checks and capture evidence.

## Current execution boundary

Issue #566 is now **approved for controlled deployment**.

The next physical action is to run the repository-controlled Raspberry Pi deployment contract on the existing host, then collect:

- exact deployed SHA;
- capacity preflight and PostgreSQL backup evidence;
- repository-backed local administrator login without manual auth-provider correction;
- API/Dashboard readiness;
- Device Agent worker health and telemetry freshness;
- Energy Monitoring continuity through at least one local token-rotation window;
- no recurrence of `401 invalid_bearer_token`;
- #548 automatic-update policy default OFF;
- manual update discovery and 02:00 host-local scheduler state;
- version-management runtime/package/backup/capacity evidence.

If any safety gate or deployment command fails, stop and preserve the evidence. Do not bypass the gate.

## Safety boundaries

`LOCAL_LAN`, offline-first runtime and read-only industrial boundaries remain unchanged. No Modbus/controller write, actuator/hardware write, persistent-data deletion, named-volume deletion, secret/billing/DNS mutation or mandatory cloud runtime dependency is authorized.
