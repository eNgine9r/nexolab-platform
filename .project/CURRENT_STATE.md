# NEXOLAB Current State

Updated: 2026-08-11

Verified repository baseline on `main`: `d75b353435e8c613203017cb68ee68c1f63d3268`.

Active Work Package: Issue #368 / PR #373 — software and Raspberry Pi physical acceptance complete; final state-only exact-head CI pending before merge.

## Issue #368 — physical acceptance PASS

The frozen candidate `105ae34425a8937a6f61c172b52ce2c6fa09f3b3` passed the controlled Raspberry Pi migration-v2/latest-query acceptance on the existing long-running PostgreSQL database.

Measured evidence:

```text
migration 20260805_0022 -> 20260807_0023: rc=0, 330 s
ingestion remained live during backfill
projection rows / canonical series: 194 / 194
latest limit=1 p95:      0.013076 s
latest default p95:      0.023364 s
latest limit=100 p95:    0.015271 s
filtered series p95:     0.011519 s
query plan: ix_telemetry_latest_order on telemetry_latest
query execution: 0.136 ms
central smoke: PASS
final advisory lock audit: 0 granted exclusive / 0 waiting
PostgreSQL volume: nexolab-central-postgres-data preserved
Device Agent: ok, MQTT connected, no degraded/cooldown endpoints
```

The original controlled-host latest request exceeded 20 seconds. The physical candidate now answers normal latest reads in milliseconds without scanning retained history.

No Modbus write, hardware write, telemetry truncation, history deletion or volume deletion occurred.

## Final software acceptance GREEN

Content head `6c4955f73dde147f5f6797dbb04b99b1b67239ba` completed **17/17 GitHub workflows GREEN**.

This includes:

- Quality: formatting, lint, typecheck, tests and production build;
- Telemetry Service: PostgreSQL migrations, MQTT/REST/WebSocket/storage/dead-letter/retention, outage recovery, offline Alembic SQL and container build;
- Container Supply Chain exact-image SBOM/Trivy/release-manifest/secret policy;
- Authenticated Dashboard Acceptance;
- Security, Refrigeration, Reports, Test Sessions and Disaster Recovery browser acceptances;
- Device Agent and MQTT/DR TLS fleet gates;
- Capacity Release Gate;
- Offline Auth Acceptance;
- Offline Bundle clean-host transfer, egress block, disconnected startup, update/rollback persistent-data preservation and evidence upload.

Two post-hardware software findings were corrected without changing migration `20260807_0023` or the physical latest-order semantics:

1. startup gap reconciliation now reports only actual latest-projection mutations, so a delayed older history row is not reported repeatedly after correctly losing to a newer projected sample;
2. the authenticated-dashboard acceptance harness, which intentionally inserts deterministic historical samples directly through SQL, now seeds `telemetry_latest` consistently with those fixture rows instead of bypassing the bounded read model.

The Telemetry Service integration suite and Authenticated Dashboard browser acceptance are GREEN on these fixes.

## Security dependency complete

Issue #396 / PR #397 removed newly reported HIGH Python findings caused by libraries vendored inside runtime `pip`. PR #397 merged as `d75b353435e8c613203017cb68ee68c1f63d3268`; #368 inherits that hardened telemetry image construction. No new vulnerability exception was added.

## Repository reconciliation

PR #373 is based on current `main=d75b353435e8c613203017cb68ee68c1f63d3268` through reconciliation commit `97917fe627c704f7aa7fd6d32c7cfb0c459d1256` and remains mergeable. Review threads and submitted reviews requiring action are zero.

This final checkpoint changes only the four `.project` source-of-truth files after the fully GREEN content head. Runtime code is frozen. The final state head must itself receive exact-head CI before Ready/merge.

## Alembic ordering hazard with Issue #385

Issue #385 / PR #390 is software verified at `8bb31364a7523164fab95c29aef9d8a839283213`, but its unmerged migration also uses revision `20260807_0023` based on `20260805_0022`.

The controlled production Raspberry Pi database records `20260807_0023` as the #368 telemetry projection migration. Therefore #368 must merge first. Afterward #385 must be reconciled and renumbered to `20260807_0024` with `down_revision=20260807_0023` before any further user-management acceptance.

Safe ordering:

```text
#368 final state CI -> merge as canonical 20260807_0023
-> #385 reconcile with post-#368 main
-> renumber #385 migration to 20260807_0024, down_revision=20260807_0023
-> fresh #385 exact-head CI
-> isolated Raspberry Pi Users & Access acceptance
-> #385 merge
-> #389 Version Management
```

## Current safety boundary

Do not run `deploy-current-head` on the controlled Pi until #368 is canonical in `main` and a controlled follow-up deployment path is prepared. Leave the already verified candidate Telemetry Service running.

Do not downgrade or restore the production database. Do not delete persistent volumes. No Modbus or other hardware write is authorized.

## Next action

Run exact-head CI on this final state checkpoint. If GREEN, perform the final focused-diff/review/base audit, mark PR #373 Ready and squash merge with locked expected head. Then immediately resume Issue #385 migration renumber/reconciliation.
