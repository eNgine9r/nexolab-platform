# NEXOLAB Blockers

Updated: 2026-08-18

## Issue #548 / PR #559 — no software blocker

Issue #548 — **Add GitHub-aware safe Raspberry Pi update orchestration** has completed implementation verification on PR #559.

Implementation exact head:

`f068192268bed20afbd4890f20f4c52d21086f71`

All 13 triggered workflows are GREEN, including CI, Telemetry service, Offline Bundle, Offline Auth, Authenticated Dashboard, Device Agent Fleet, Capacity Release Gate, Disaster Recovery browser/TLS, MQTT TLS, Broker Control, Refrigeration Browser and Container Supply Chain.

The final diff/security/offline audit is PASS:

- branch is current with `main` (`behind_by=0`), merge base `0829e758700385e15fa496e160790b061625ad94`;
- no unresolved review threads;
- GitHub remains optional update-plane only;
- automatic updates remain default OFF and use the host-local 02:00 schedule when explicitly enabled;
- exact successful `CI` evidence and validated local package identity are required before activation;
- capacity preflight and PostgreSQL backup precede runtime mutation;
- bounded local reconnect rereads durable operation state after expected restart;
- no browser-to-shell bridge or GitHub credentials in the frontend;
- no destructive fallback, persistent-data deletion, named-volume deletion, Modbus/controller write or hardware write.

The four `.project` files are being reconciled now. Their final state-only head must receive a fresh exact-head GREEN check set before PR #559 is marked Ready and merged.

## Raspberry Pi deployment after #548 — hard approval boundary

The current Raspberry Pi remains untouched at:

`0bfc4fcc56f7a669545be166c585573550f2fb44`

Evidence remains:

`runtime/deployments/20260818T083157Z`

No deployment, service restart, host package installation, hardware action or runtime mutation was performed during #548.

After PR #559 is GREEN and merged, controlled Raspberry Pi deployment/acceptance of the post-#548 `main` is the next physical runtime action. This is a **hard boundary requiring separate explicit user approval** before any Pi change.

That acceptance must also close the remaining #566/#560 permanent-fix evidence where possible: repository-backed local administrator login, access-token rotation continuity, protected history/consumption requests and no `401 invalid_bearer_token` recurrence.

## Deployment capacity — current software blocker cleared

The latest controlled deployment capacity guard passed:

- `free_bytes=20475432960`;
- `required_bytes=16999167491`;
- `reserve_bytes=2147483648`;
- root filesystem was 68% used at the recorded preflight.

Issue #548 additionally corrects version-manager capacity preflight so repository-backed runtime/evidence accounting uses the canonical repository path while the worker retains read-only access to the checkout.

Future deployments must run the guard. Do not bypass it by deleting product data, PostgreSQL history, named volumes or protected evidence.

## Issue #444 — end-to-end user-management validation pending

Issue #444 remains `status:needs-validation`. Remaining validation is the actual create/manage user flow and non-admin authorization/frontend diagnostic behavior as applicable.

## Issue #201 — final hardware boundary pending

Normal-operation cumulative-energy semantics on LE-01MP Units `200–203` remain verified. Issue #201 still requires explicitly approved restart/power-cycle and rollover/reset/discontinuity evidence before full hardware acceptance.

## Issue #189 — recovery hardware evidence pending

Issue #189 remains blocked pending controlled central-host and Raspberry Pi recovery evidence. No destructive production restore, named-volume deletion, product-data deletion or hardware write is authorized.

## Other pending physical/evidence lanes

- #566 / #560 permanent-fix LOCAL_LAN token-rotation runtime acceptance;
- #444 end-to-end local user-management acceptance;
- #201 restart/power-cycle and rollover/reset/discontinuity validation;
- #245 standalone loopback-only Raspberry Pi acceptance;
- #189 backup/restore/rollback/power-loss acceptance;
- KK2/Unit 115 field retest;
- #548 Raspberry Pi version-management acceptance after merge and separate approval.

## Safety boundaries

No Modbus/controller write, actuator/hardware write, product persistent-data deletion, Docker named-volume deletion, production/site cutover, secret/billing/DNS mutation or mandatory cloud runtime dependency is authorized.
