# NEXOLAB Blockers

Updated: 2026-08-23

## Issue #660 — implementation verified, final state-head pending

Issue #660 is software/security-complete in PR #661. Verified implementation head `f03aea0ba790c038b2f7a3d32f3f5fcb971bd005` passed Core CI `32626031714`, Telemetry Service `32626031687`, Container Supply Chain `32626031695`, `NEXOLAB Merge Gate`, and has zero unresolved review threads.

The fresh image scan still reports the same four exact `CVE-2026-14456` HIGH/no-fix tuples at OpenSSL `3.5.6-1~deb13u2`; no QUIC/HTTP3/OpenSSL QUIC listener path is present in NEXOLAB. The reviewed exceptions now expire on **2026-08-30**. Remove them earlier if a supported Debian Trixie fix becomes available, findings disappear, reachability changes, or severity becomes Critical.

There is no product/software hard blocker. Only final state-head CI and merge remain.

## Issue #200 — physical RS-485 topology evidence blocked

Read-only Raspberry Pi evidence on 2026-08-23 sees only one stable CP2104 adapter `0133F090` / `/dev/ttyUSB0`, one persisted `rs485-main` bus, and production Device Agent `9600 8N1` with timeout `0.30 s` and one retry.

A passive 60-second window observed 402 physical requests, 306 successes, 96 timeout/retries and bus load `75.591% -> 76.942%` without starting another Modbus master. Unit `115` is absent from the persisted registry but remains physically unverified.

Full Issue #200 acceptance is blocked on safe physical topology inspection, termination/biasing/shielding/grounding evidence, duplicate-ID proof, and/or the intended second isolated adapter. Draft PR #659 retains the recoverable evidence and must not be merged as completion.

## Issue #607 — dual RS-485 hardware acceptance pending

Dual-bus isolation is software-verified, but current hardware enumerates only one RS-485 adapter. Physical simultaneous KK1/KK2 acceptance, reboot-stable two-adapter mapping and one-bus disconnect isolation remain unverified.

Repository evidence maps XJP60D KK2 to Unit IDs `101..115` and KK1 to `126..138`. LE-01MP Unit IDs `200..203` still require explicit bus ownership; do not guess it.

## Issue #444 — local user administration final acceptance

The original production 404 no longer reproduces: `/api/v1/admin/users` is mounted and appears in deployed OpenAPI. An unauthenticated request reaches the security layer instead of returning route-not-found.

Remaining acceptance requires an authorized administrator identity and controlled create/authenticate/403 permission checks. Do not expose or invent credentials.

## Issue #245 — standalone offline acceptance

Actual acceptance requires intentional Ethernet/Wi-Fi isolation, no default route, reboot, standalone deployment/runtime verification and recovery checks. These are cutover/physical actions and require explicit approval before execution.

## Issue #201 — LE-01MP power-cycle evidence

Normal-operation cumulative-energy semantics are already hardware-evidenced and software-merged. Remaining acceptance is the explicitly approved restart/power-cycle observation and consequent discontinuity classification.

## Issue #202 — extended XJP60D hardware evidence

Representative KK1/KK2 portability, display correlation, Unit `115` presence/absence and extended state semantics remain hardware-unverified. Do not infer physical absence from registry absence.

## Issue #646 — branch protection settings access

Repository-side change-impact CI and merge-gate behavior are software-verified. Current GitHub observation still reports `main` protection/required checks disabled; connected mutation access remains unavailable. This is a soft access blocker.

## Other dependencies

- #585 — blocked until explicit physical W2 / Unit 201 handback approval.
- #590 — physical cadence acceptance pending.
- #189 — controlled backup/restore/rollback/power-loss recovery evidence outstanding.

## Safety boundaries

No Modbus/controller write, hardware write, product persistent-data deletion, Docker named-volume deletion, secret/billing/DNS mutation, production/site cutover or mandatory cloud runtime dependency is authorized by Issue #660.
