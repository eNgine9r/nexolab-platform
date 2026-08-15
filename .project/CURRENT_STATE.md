# NEXOLAB Current State

Updated: 2026-08-15

## Canonical baseline

Runtime/product `main` baseline is `b79bcee3670693c46219e8bc58ec3fc8ffe5095a`, the squash merge of PR #476 for Issue #469. State-only Issue #477 reconciles repository bookkeeping after that merge.

## Issue #469 — software verified, hardware pending

Issue #469 — **Prevent Raspberry Pi deployment evidence capture from exhausting disk** — remains open as `status:needs-validation`.

Software is merged and verified. PR #476 added fail-before-mutation capacity preflight, bounded retention limited to timestamped `runtime/deployments/*`, protected current/newest/marked evidence, fail-closed PostgreSQL size measurement, atomic large evidence writes, deterministic tests and operator documentation.

Merge-authoritative source head was `df2c3db389097abbfa8c647984002dc2f919c32d`; merge SHA is `b79bcee3670693c46219e8bc58ec3fc8ffe5095a`.

Verification:

- targeted capacity verification `31908201491` — PASS;
- targeted audit-hardening verification `31908426084` — PASS;
- exact-head CI `31908564398` — PASS;
- exact-head Telemetry service integration `31908564403` — PASS.

Physical acceptance is **not** claimed. A controlled Raspberry Pi run must still prove capacity diagnostics, preserved product data/named-volume identities, safe deployment behavior and exact current `main` on the host.

## Hardware lanes

Issue #469 is the immediate deployment-capacity hardware validation lane. Issue #289 remains the broader physical Raspberry Pi/RS-485 acquisition scale/recovery lane.

## Ready audit

The post-merge repository query for open `status:ready` Issues returned **none**. There is no independent Ready software Work Package to continue while the physical validation blocker remains.

## Hard blocker

Further progress now requires physical Raspberry Pi access/evidence. Running the controlled deployment can irreversibly prune only old classified timestamped deployment-evidence directories according to the new bounded retention policy. Product persistent data and Docker named volumes are outside cleanup scope, but the physical cleanup itself is irreversible and therefore requires Product Owner confirmation before execution.

LOCAL_LAN, offline-first runtime and read-only Modbus boundaries remain unchanged. No Modbus/hardware write, product persistent-data deletion, named-volume deletion or site cutover is authorized.
