# NEXOLAB Current State

Updated: 2026-08-15

## Canonical repository baseline

Current `main` is `0b378ab7d257a2fe00e9dd6aea86ce9b74ec6558`, the squash merge of state-only Issue #474 / PR #475 after Issue #468 / PR #473.

Issue #474 is closed/completed and its stale `status:in-progress` label has been removed. Issue #468 remains software-complete while its physical recovery evidence is still owned by Issue #289.

## Active Work Package — Issue #469 / PR #476

Issue #469 — **Prevent Raspberry Pi deployment evidence capture from exhausting disk** — is `priority:high`, `status:in-progress`.

Draft PR #476 (`fix/469-raspberry-pi-deployment-evidence-capacity`) implements the focused software correction:

- sourceable/standalone deployment capacity guard;
- bounded retention only for strict timestamp children of `runtime/deployments/`;
- preservation of the current deployment, newest deployment evidence, symlinks and `.nexolab-preserve` acceptance evidence;
- conservative free-space preflight before inventory/evidence capture and a second recheck immediately before large writes;
- explicit reserve/build/metadata/runtime-evidence/PostgreSQL capacity accounting;
- fail-closed behavior when a running PostgreSQL container cannot report `pg_database_size()`;
- atomic `.partial` → final rename for runtime evidence archive and PostgreSQL pre-upgrade dump;
- deterministic sufficient/insufficient capacity, retention, preservation, cleanup-failure, PostgreSQL-measurement and mutation-order regressions;
- operator documentation for low-space recovery and tunable thresholds.

Automated cleanup does **not** target `runtime/evidence`, PostgreSQL, edge SQLite, MQTT, MinIO, Docker named volumes or controller/device configuration.

Targeted software verification passed:

- temporary implementation helper run `31908201491` — PASS (`bash -n` for both deployment scripts plus deploy-capacity Python regressions);
- temporary audit-hardening verifier run `31908426084` — PASS, including fail-closed PostgreSQL-size and cleanup-failure coverage.

The temporary helper/verifier workflow files were removed. Software head before this canonical checkpoint is `933b22c27a5894c7818596fda7d734ca548da538`; its net diff contains only the four permitted product/docs/test files.

Final exact-head CI after this `.project/**` checkpoint is still required before software merge.

## Hardware acceptance

Issue #469 is not physically accepted yet. After the software PR merges, a controlled Raspberry Pi deployment must still prove:

- capacity diagnostics on the physical filesystem;
- no product-data or named-volume loss;
- successful deployment after safe bounded evidence cleanup when required;
- exact current `main` on the host;
- preserved rollback/evidence behavior.

Issue #469 must remain open after software merge until that physical evidence exists. Issue #289 remains the broader Raspberry Pi/RS-485 acquisition acceptance lane.

## Safety boundary

LOCAL_LAN and offline-first requirements remain unchanged. Read-only Modbus remains mandatory. No controller configuration, hardware write, product persistent-data/volume deletion, production/site cutover, secret/billing/DNS change or mandatory cloud runtime dependency is authorized.
