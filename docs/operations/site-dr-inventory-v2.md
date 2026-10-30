# NEXOLAB #1433 — offline complete-site DR inventory v2 contract

**Source-only, no site authorization.** This v2 receipt *adds* a strictly validated
multi-store inventory contract. It does not change, migrate, auto-deploy or claim to
replace the five-asset `security/disaster-recovery-assets.json` policy, the
`nexolab-dr-v1` AES-256-GCM encrypted bundle or synthetic software DR drills.

Use the source-checked validator with an operator-supplied **sanitized** JSON
inventory file stored outside Git:

```bash
python3 scripts/validate-site-dr-inventory-v2.py \
  --inventory /path/to/sanitized/site-dr-inventory-v2.json
```

Exit 78 means **BLOCKED**. A successful exit prints
`SITE_DR_V2_STRUCTURAL_GATE=PASS` and always prints
`SITE_DR_V2_RUNTIME_EVIDENCE=NOT_INDEPENDENTLY_VERIFIED` and
`SITE_DR_V2_SITE_ACTIVATION=NOT_AUTHORIZED`. This parser checks the declared
structure and proof identifiers; it **cannot independently prove** those hashes
correspond to real volumes, that encryption was performed, or that the restore
ran on a separate host. The operator/reviewer must separately attest those facts.

## Required v2 receipt fields

A root JSON object must have exactly the keys `schema_version: 2`,
`kind: "nexolab-site-dr-inventory"`, `profile: "LOCAL_LAN"`,
`site_id`, `release_commit` (40 hex), `capture_id`,
`observed_at` (UTC), `v1_bundle_format: "nexolab-dr-v1"`,
`storage` and `assets`. Unknown fields fail closed.

`storage` must contain SHA-256 identifiers for the encrypted bundle,
encrypted manifest, independent destination, isolated restoration target
and restore receipt. It also requires `encryption: "aes-256-gcm"`,
`key_source: "mounted_file"`, independently verified key custody and
off-device encrypted copy, independent source disk, separate host/dedicated
media, minimum 20 GiB free after capture, and independently verified isolated
host restoration. Key content, secret paths, plaintext credentials and
production payloads must never be embedded.

`assets` must include every one of the following eight distinct IDs:

1. `postgresql` — `postgres`, logical `pg_custom` snapshot.
2. `object-storage` — Compose service key `minio` **runs VersityGW**;
   `storage_backend: "versitygw"` and source volume ending in
   `-object-storage-versitygw-data`. Legacy MinIO source volume fails.
3. `mqtt-dynamic-security` — central `mqtt`, consistent persistence and
   security identities/roles/ACLs.
4. `edge-sqlite-outbox` — `device-agent`, SQLite online backup with
   queue, high-water and sequence continuity evidence.
5. `local-auth-private-key` — `telemetry-service`, secret-safe PEM backup.
6. `local-auth-public-key` — `telemetry-service`, matching PEM proof.
7. `central-ingestion-spool` — `telemetry-service`, SQLite state.
8. `edge-mqtt-persistence` — `edge-mqtt`, retained broker state.

Every asset requires a source observation with exact Compose service key,
image SHA-256, source identity SHA-256, authority SHA-256 and UTC observation
time. Volume-backed assets require a source volume identity. The auth pair is
an external file boundary and **does not require a Docker volume**.

Retained assets require exact `capture` status `verified`, per-asset format
and consistency boundary, SHA-256, positive bytes, UTC snapshot time and
a **shared** cross-store consistency receipt hash. Each also needs `restore`
status `verified`, an isolated receipt/verification hash, a new destination
and proof that the source was untouched. Both local-auth key records must
carry the same keypair matching verification hash.

Only `central-ingestion-spool` and `edge-mqtt-persistence` may be declared
`proven_rebuildable`, and only with an explicit `rebuild_proof_sha256`.
Unknown, missing, duplicated or unclassified protected state is **BLOCKED**.
This is not a claim that those auxiliary stores are actually rebuildable on
the Raspberry: that classification requires separate source-specific evidence.

## Boundaries and follow-up

The contract **never reads containers, source data, key bytes or site volumes**.
It cannot capture archives, transfer encrypted data, schedule backups,
quiesce applications, stop acquisition, modify Docker/IPAM or restore anything.
An attacker can fabricate metadata fields, so independent observation,
cryptographic archive verification, chain of custody and fresh-volume
restoration are separate mandatory gates.

A future focused WP must implement actual bounded offline collection of
source-mapped VersityGW, MQTT, SQLite and local-auth state with verified
consistency. Subsequent independent WPs implement off-device encrypted
retention/systemd scheduling and real isolated restore verification.
`#1399` Dashboard/API site recovery still requires an independent complete
restore, exact installed package and network authority, rollback, and
**explicit Product Owner approval** for any production change.

No hardware or Modbus write is authorized. `#1428` remains open for full
operational DR. Cross-references: `docs/operations/site-dr-inventory-gate-1431.md`,
`docs/operations/disaster-recovery.md`, and
`docs/operations/edge-sqlite-cutover-recovery.md`.
