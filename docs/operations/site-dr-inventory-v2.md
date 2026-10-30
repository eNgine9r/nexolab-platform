# NEXOLAB #1433 — offline complete-site DR inventory v2 contract

**Source-only, no site authorization.** This additive multi-store receipt contract does not change the five-asset `security/disaster-recovery-assets.json` policy, the `nexolab-dr-v1` AES-256-GCM encrypted bundle, or synthetic software DR acceptance.

Use the source-checked offline validator on an operator-supplied **sanitized** JSON file that is never committed to Git:

```bash
python3 scripts/validate-site-dr-inventory-v2.py --inventory /path/to/sanitized/site-dr-inventory-v2.json
```

Exit 78 means **BLOCKED**. Success prints `SITE_DR_V2_STRUCTURAL_GATE=PASS` alongside `SITE_DR_V2_RUNTIME_EVIDENCE=NOT_INDEPENDENTLY_VERIFIED` and `SITE_DR_V2_SITE_ACTIVATION=NOT_AUTHORIZED`. The parser checks the receipt's structure and claimed proof identifiers; it cannot independently verify real volumes, backup encryption, encrypted off-device custody, or isolated restoration.

## Required v2 receipt fields

The root JSON object must contain exactly `schema_version: 2`, `kind: "nexolab-site-dr-inventory"`, `profile: "LOCAL_LAN"`, `site_id`, `release_commit` (40 hex), `capture_id`, `observed_at` (UTC), `v1_bundle_format: "nexolab-dr-v1"`, `storage` and `assets`. Missing or unexpected fields fail closed.

`storage` requires SHA-256 hashes for the encrypted bundle, encrypted manifest, independent destination, isolated restoration target and restore receipt. It requires `encryption: "aes-256-gcm"`, `key_source: "mounted_file"`, separately verified key custody, off-device encrypted copy, source-independent backup destination, minimum 20 GiB free after capture, and fresh-host isolated restoration. Do not store key bytes, secret paths, credentials or production payloads inside the receipt.

All eight protected assets must be present and classified:

1. `postgresql` — `postgres`, logical custom-format PostgreSQL dump.
2. `object-storage` — compatibility Compose service key `minio` actually runs **VersityGW**, with `storage_backend: "versitygw"` and a volume ending in `-object-storage-versitygw-data`. The legacy MinIO volume is rejected.
3. `mqtt-dynamic-security` — `mqtt` in Compose project `nexolab-central`, persistence and clients/roles/ACLs.
4. `edge-sqlite-outbox` — `device-agent`, SQLite online snapshot, queue and sequence continuity.
5. `local-auth-private-key` — `telemetry-service`, secret-safe private PEM.
6. `local-auth-public-key` — `telemetry-service`, paired public PEM.
7. `central-ingestion-spool` — `telemetry-service`, durable SQLite ingestion state.
8. `edge-mqtt-persistence` — `mqtt` in Compose project `nexolab-edge`, broker persistence.

Every asset source observation must identify both the exact `compose_project` and `compose_service`, image SHA-256, source identity SHA-256, authority SHA-256 and UTC observation time. The central and edge brokers deliberately share service key `mqtt` but are distinct Compose projects. Volume-backed assets require **unique** volume names; local-auth keys are external-file assets, not Docker volumes.

Retained assets require `capture.status: "verified"`, exact format and consistency boundary, SHA-256, positive byte count, UTC time and shared cross-store consistency receipt hash. Each also requires `restore.status: "verified"`, isolated receipt and verification hashes, new restore target and source-untouched proof. Both local-auth entries must have the same keypair verification hash.

Only `central-ingestion-spool` and `edge-mqtt-persistence` may instead be declared `proven_rebuildable`, with `rebuild_proof_sha256`. This classification needs actual independently reviewed source evidence; it is not a claim those stores are already rebuildable on Raspberry. Missing, duplicated, unexpected and unclassified state is **BLOCKED**.

## Safety boundaries and follow-up

This validator never reads containers, production databases, source volumes or keys. It cannot perform archive capture, encrypted transfer, scheduling, service quiesce, network repair or restore. All submitted proof fields could be fabricated; independent source inspection, archive verification, key custody, operator review and actual fresh-volume restore remain mandatory.

Next focused WPs: bounded full multi-store offline capture; independent encrypted backup custody and non-destructive systemd scheduling; fresh-volume restore acceptance. Only after that may #1399 request separate Product Owner approval for exact Docker/IPAM recovery and authenticated Dashboard/API activation.

No hardware or Modbus writes are authorized. #1428 remains open. See `docs/operations/site-dr-inventory-gate-1431.md`, `docs/operations/disaster-recovery.md` and `docs/operations/edge-sqlite-cutover-recovery.md`.
