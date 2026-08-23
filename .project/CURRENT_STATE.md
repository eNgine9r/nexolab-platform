# NEXOLAB Current State

Updated: 2026-08-23

## State Model v2 boundary

NEXOLAB continuity uses durable repository state plus current GitHub/runtime observations. GitHub is authoritative for current `main`, Issue/PR lifecycle and merge SHA; deployed runtime evidence is authoritative for what is actually running on the Raspberry Pi.

## Durable baselines

Accepted product source remains `286a219611f95413b5580d8099a7c5665416d1ad` (Issue #590 / PR #657).

Deployed product source remains `6e387485b68fb862d9f82ae7f6000b1f5b672764`.

Current GitHub `main` observed before Issue #660 work is `4f76c3683a5a6e47d1a1115c9caa20989d28f8ee`, which includes tooling-only Issue #615 / PR #658. The Raspberry Pi Git checkout was fast-forwarded to that source commit without restarting or cutting over the immutable production dashboard release.

## Completed tooling Work Package — Issue #615

Issue #615 — **Fix authenticated dashboard acceptance Compose project-name generation** — merged through PR #658 as `4f76c3683a5a6e47d1a1115c9caa20989d28f8ee`.

Post-merge Raspberry Pi evidence:

- checkout fast-forwarded to `4f76c368...` with a clean `main`;
- focused project-name regression tests: PASS `3/3`;
- shell syntax check: PASS;
- production dashboard PID and immutable release working directory unchanged;
- production dashboard HTTP remained `200`;
- no deployment or site cutover occurred.

## Hardware/validation audit after Raspberry Pi connector recovery

Remote Desktop/Raspberry Pi access is online again. Read-only audit established:

- one enumerated RS-485 adapter only: Silicon Labs CP2104 `0133F090` resolving to `/dev/ttyUSB0`;
- production Device Agent serial profile: `9600 8N1`, timeout `0.30 s`, retries `1`;
- persisted acquisition registry revision `10` uses one logical `rs485-main` bus;
- active XJP60D Unit IDs: `102`, `104`, `106`, `108`, `126`;
- active LE-01MP Unit IDs: `200`, `202`, `203`; Unit `201` is disabled;
- Unit `115` is absent from the persisted registry and remains physically unverified;
- 60-second passive observation: 402 physical requests, 306 success, 96 timeout/retry, 210 new samples, bus load `75.591% -> 76.942%`, worker remained running, and no service/on-demand operations were introduced by the observation.

Issue #200 is therefore blocked on physical topology evidence and/or the intended second isolated adapter; draft PR #659 retains the sanitized evidence without claiming completion.

Issue #444's historical `/api/v1/admin/users` HTTP 404 no longer reproduces on the deployed runtime: the route is present in OpenAPI and unauthenticated access reaches the security layer. Full administrator create/authenticate acceptance still requires an authorized credential/security mutation.

## Completed security candidate — Issue #660

Issue #660 — **Revalidate expiring CVE-2026-14456 OpenSSL QUIC exceptions** — is software/security-complete in PR #661 and awaits final state-head verification/merge.

Verified implementation head `f03aea0ba790c038b2f7a3d32f3f5fcb971bd005` passed:

- Core CI `32626031714`;
- Telemetry Service `32626031687`;
- Container Supply Chain `32626031695`;
- `NEXOLAB Merge Gate`;
- zero unresolved review threads.

Fresh Stage 1 Container Supply Chain run `32625474615` rebuilt controlled images with `pull: true`, `no-cache: true` and current Trivy data. Exact artifacts still report the four reviewed HIGH/no-fix tuples at OpenSSL `3.5.6-1~deb13u2`; runtime audit still finds no QUIC/HTTP3/OpenSSL QUIC listener path. The four exact exceptions are renewed only through **2026-08-30** and must be removed earlier if a supported Debian Trixie fix appears, the findings disappear, QUIC reachability changes, or severity becomes Critical.

## Current blocker boundary

- #660: no product/software blocker; final state-recording head CI and merge remain.
- #200: blocked on physical topology inspection and/or the intended second isolated RS-485 adapter; no parallel Modbus master is permitted while production acquisition owns the bus.
- #607: software complete; physical dual-adapter KK1/KK2 acceptance remains unverified because only one adapter is currently enumerated.
- #590: software complete; physical cadence acceptance remains unverified.
- #646: branch-protection/rules mutation remains a soft access blocker; current GitHub observation reports `main` unprotected.
- #585: blocked pending explicit physical W2 / Unit 201 handback approval.
- #444: needs validation with an authorized administrator credential and controlled local-user mutation.
- #245: needs validation; actual standalone acceptance requires approved network isolation/reboot/cutover actions.
- #201: needs validation; approved restart/power-cycle evidence remains pending.
- #202: hardware validation requires representative KK1/KK2/display evidence and Unit 115 physical reconciliation.
- #189: blocked on controlled backup/restore/rollback/power-loss recovery evidence.

## Safety boundaries

`LOCAL_LAN`, offline-first runtime and read-only industrial boundaries remain unchanged. No Modbus/controller write, hardware write, production/site cutover, product persistent-data deletion, Docker named-volume deletion, secret/billing/DNS mutation or mandatory cloud runtime dependency is authorized by Issue #660.
