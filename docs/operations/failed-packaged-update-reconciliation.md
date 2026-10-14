# Failed protected update #1381: bounded forward reconciliation

## Site-specific scope

This runbook applies **only** to NEXOLAB incident `51dc3ae6-8e34-453c-b6ff-7ecac98b924c` and its staged, exact `ffdefc4550d71e211724de1154ffe9057f905c9c` target. It is **not** a generic rollback command.

The failed operation remains `failed`. The actual six Docker runtime OCI images match the new package, while the protected Google HTTPS frontend still runs source `29cff166` and Version Manager still correctly records `verification_failed / runtime_state_known=false`. Do **not** press Update, Rollback, re-run the installer, bootstrap a new lineage, edit `current.json`, recreate volumes or reboot to bypass this guard.

Evidence: owner read-only audit `owner-recovery-readiness-report-1384.json` reports 17/17 PASS, three physical RS-485 buses, PostgreSQL schema `20260908_0037`, backup `51dc3ae6-8e34-453c-b6ff-7ecac98b924c-postgresql.dump` (992,743,918 bytes; SHA256 `328b2a01617100472313c86a3004b3b940d086e2cd082701c594e49c9b5cf299`), `pg_restore --list` 611 entries. **Archive listing is not a full restoration test.** Protect this backup and all original operation evidence.

## Two-stage reviewed recovery

Use `scripts/reconcile-failed-packaged-update.py` only after the focused PR passes required CI and the operator has reviewed the final exact SHA256 and rollback plan. The script requires Root-owned canonical version-management paths and is fail-closed for any different operation, source, target bundle, hardware identity, active request, database schema, backup SHA or runtime OCI digest.

1. Owner-local Root **read-only** invocation, with no `--execute`, using the actual Central and Edge environment paths:
   `--central-env /home/nexolab/nexolab-platform/infrastructure/compose/.env.central --edge-env /home/nexolab/nexolab-platform/infrastructure/compose/.env.edge-central`. It must report `READ_ONLY_RECOVERY_CANDIDATE_VERIFIED`.
2. After reviewing this result and independently approving the protected HTTPS site cutover, a separate owner-local invocation with `--execute --approve RECONCILE-FAILED-51dc3ae6-8e34-453c-b6ff-7ecac98b924c`. The command must be checksum-bound to the reviewed script. Do **not** run execute as part of general CI, tests, remote Commander, or an unattended automation.

The guarded execute phase acquires native worker/update locks, rechecks all evidence and backup hash, verifies all six OCI images and three read-only Modbus buses, prepares and probes the new protected frontend through the native package transaction, activates it, re-verifies volume identities and continuing Device Agent requests, then writes a **new uniquely named recovery receipt**. Only after these proofs does it atomically publish source `ffdefc...` as the new `current.json` packaged authority, retaining package `29cff...` for rollback. The old failed operation is never modified or reclassified as succeeded.

If a gate fails before the authority commit, the candidate frontend is rolled back and native `current.json` stays unknown. If an error happens after the atomic authority file has been replaced, do **not** roll HTTPS back blindly: a durable `commit_uncertain_operator_review_required` receipt requires another owner read-only inspection before any action.

## Mandatory post-execution acceptance

Independently check the durable recovery receipt and new `current.json`, **both** LAN and HTTPS `/api/runtime-identity` source/build IDs, Google OAuth/anonymous API denial, database schema and existing data, storage and named volume identity, three physical RS-485 by-id mappings and real Modbus requests, Device Agent advancing telemetry/queue, CSV/XLSX export, and retained prior package/backup. Do not claim these production acceptance steps passed before they run.

This path performs no Modbus writes, no PostgreSQL restore, and no Docker image reinstallation. Separate rollback to 29cff requires its **own** reviewed, explicitly approved procedure.
