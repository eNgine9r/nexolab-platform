# NEXOLAB Current State

Updated: 2026-08-15

## Canonical repository baseline

Current `main` is `a90c38da5d83c5c557dd7dce72227b86099c6120`, the squash merge of state-only Issue #471 / PR #472 after Issue #465 / PR #470.

Issue #471 is closed/completed. The selected critical software Work Package is now Issue #468, with Issue #469 next Ready. Issue #289 remains the independent physical Raspberry Pi/RS-485 acceptance lane.

## Active Work Package — Issue #468 / PR #473

Issue #468 — **Keep Device Agent acquisition alive across SQLite queue lock contention** — is `priority:critical`, `status:in-progress`.

Draft PR #473 (`fix/468-device-agent-sqlite-lock-recovery`) implements the focused software correction:

- explicit SQLite `busy_timeout` plus bounded retry for queue operations;
- complete-operation retry/rollback without resetting or deleting edge SQLite;
- coverage for enqueue, backlog reads, delete, queue depth and monotonic stream-sequence allocation;
- process-level supervision that ties HTTP availability to the top-level Device Agent runtime instead of hiding an unexpectedly dead acquisition runtime behind a live health server;
- deterministic real-SQLite lock-contention and runtime-supervision regressions;
- preserved polling cadence, target eligibility, one-serialized-worker-per-bus behavior and read-only Modbus boundary.

Implementation head `4bb8ec501dae069240098f669b4d047b90c6bc47` passed the pre-state verification set:

- CI `31905533519` — PASS;
- Device Agent Fleet Acceptance `31905533550` — PASS;
- Acquisition Scale Acceptance `31905533534` — PASS software-only;
- Offline Bundle `31905533532` — PASS;
- Authenticated Dashboard Acceptance `31905533538` — PASS;
- MQTT TLS Fleet Acceptance `31905533541` — PASS;
- Disaster Recovery TLS Fleet `31905533533` — PASS;
- Container Supply Chain `31905533549` — PASS;
- Edge image `31905533542` — PASS.

No reviews or unresolved review threads are present on PR #473. The implementation diff before this checkpoint contains only five intended Device Agent product/test files.

Final exact-head CI after this `.project/**` reconciliation is still required before PR #473 can leave draft/merge. Physical Raspberry Pi evidence is also still required after merge and is not claimed here.

## Next Ready software Work Package — Issue #469

Issue #469 — **Prevent Raspberry Pi deployment evidence capture from exhausting disk** — remains open, `priority:high`, `status:ready`.

It is ordered immediately after #468 because repeated controlled Raspberry Pi deployment/evidence capture must become capacity-safe before final hardware acceptance work continues.

## Independent hardware lane — Issue #289

Issue #289 remains open and `status:in-progress`. Fresh physical Raspberry Pi/RS-485 evidence is required after #468 and #469, including active worker recovery/fail-closed restart and advancing telemetry freshness. Software workflow evidence does not count as hardware acceptance.

Other pending physical evidence includes KK2/Unit 115 field retest, refrigeration perceived-latency acceptance and Raspberry Pi version-management acceptance.

## Safety boundary

LOCAL_LAN and offline-first requirements remain unchanged. Read-only Modbus remains mandatory. No controller configuration, hardware write, destructive persistent-data/volume action, site cutover, secret/billing/DNS change or mandatory cloud runtime dependency is authorized.
