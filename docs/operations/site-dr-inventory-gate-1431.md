# NEXOLAB #1431 — actual-site DR inventory and recovery decision gate

Status: **source-only discovery; no live backup or site restoration accepted**.  
Profile: `LOCAL_LAN`; mandatory operations must work offline.  
Related: [#1428](https://github.com/eNgine9r/nexolab-platform/issues/1428), [#1399](https://github.com/eNgine9r/nexolab-platform/issues/1399), [#1409](https://github.com/eNgine9r/nexolab-platform/issues/1409), [#189](https://github.com/eNgine9r/nexolab-platform/issues/189).

## Product outcome and current evidence

An authenticated Dashboard/API recovery must never depend on an unproven partial backup. A **one-time PostgreSQL** snapshot is available according to the operator terminal on 2026-10-30:

- `/var/backups/nexolab/pg-incident-20261030T090951Z.dump`
- `1,181,154,608` bytes; reported SHA-256 `3726b69b6a10b3cebe56b1982459126c68e25daa86958cd410fdd3d894722f06`
- Exact executed helper SHA-256 `634758e1585d92efd7dce74433afec4796e81e4b5349fe213439c21c5a86a7bc`
- `PG_BACKUP_PREFLIGHT=PASS`, `PG_BACKUP_ARCHIVE=CREATED`, `PG_RESTORE_TOC=PASS`; **`PG_RESTORE_ACTUAL=NOT_PERFORMED`**.
- Root SSD approximately 28G free, 88% used. No approved independent backup disk or off-device encrypted copy evidenced.

This proves neither physical off-device custody nor actual restore. It also does not authorize a Docker/network repair.

## Source-of-truth and consistency matrix

The existing synthetic software DR drill documents **five** entries in `security/disaster-recovery-assets.json`; `scripts/validate-disaster-recovery-assets.py` requires **exactly** these five IDs. Its bundle implementation is `scripts/nexolab-backup-bundle.py` (`nexolab-dr-v1`, AES-256-GCM, 32-byte file key), and `scripts/run-disaster-recovery-acceptance.sh` tests a synthetic isolated stack. Do not interpret simulated acceptance as a site recovery receipt or casually add another entry to the v1 policy.

| Protection boundary | Current source-backed mapping | Consistency/capture requirement | Site status |
| --- | --- | --- | --- |
| Central PostgreSQL | `postgres` and `nexolab-central-postgres-data`; v1 policy uses logical `pg_custom` | Bounded read-only logical snapshot, TOC **and restore to new database**; verify schema head, protected rows, immutable evidence and timestamps | **Partial**: owner-reported archive/TOC, no actual restore |
| Private S3 object store | Central Compose deliberately retains logical service **`minio`**, but its image runs **VersityGW**; current Compose volume resolves to `nexolab-central-object-storage-versitygw-data` with default prefix. Existing v1 policy still names **`nexolab-central-object-storage-data`** (legacy). | Verify `runtime/object-storage-migration/authority.json`, installed immutable image/volume and active bucket first. Protect actual VersityGW POSIX object tree, metadata, ACL/private access, object size/count/hash; require a bounded consistent snapshot and no source deletion. | **Mapping conflict** between v1 policy and current Compose; no fresh site capture |
| Central MQTT / Dynamic Security | `mqtt` and `nexolab-central-mqtt-data` in version-manager inventory and v1 policy | Consistency of persistence + security identities, ACLs, roles, disabled clients; determine controlled quiesce or safe snapshot gate; never reset broker | **Unverified**; no fresh matching-site snapshot |
| Edge Device Agent SQLite/outbox | Current source inventory lists `nexolab-edge_edge-data`; existing `docs/operations/edge-sqlite-cutover-recovery.md` supports guarded `sqlite3.Connection.backup()` with quick_check, queue/high-water and sequence evidence | Capture source and WAL-consistent SQLite snapshot, registry revision, queue depth, high-water/sequence counters and post-capture delta; **do not copy a live .db directly** or restore stale state over newer samples | **Missing from DR v1 policy** and full central DR drill |
| Edge MQTT persistence | Version manager also preserves `nexolab-edge_mqtt-data` | Determine whether durable queued telemetry or unique broker state requires protection independently of central MQTT | **Unclassified**; do not assume disposable |
| Central Telemetry ingestion data | Current Compose lists `central-telemetry-ingestion-data`; version manager retains `nexolab-central-telemetry-ingestion-data` | Establish if this is rebuildable transient state, non-replayable ingestion data, or part of the recovery boundary; verify without deleting | **Unclassified** |
| Local authentication | v1 policy protects RSA private/public key pair from `/run/secrets/nexolab/local-auth-*.pem` | Capture as one protected keypair into encrypted custody without plaintext logs; verify mode, match, restored existing sessions/login/permissions; tokens/passwords are not bundled by v1 drill | **Unverified actual-site custody**, even though synthetic drill covers keypair |
| Release and storage authority | Pinned installed `ffdefc4550d71e211724de1154ffe9057f905c9c` baseline, source/bundle identities and migration authority are referenced by checkpoint | Preserve manifest/hash lineage and exact volume/image matching; never retarget production to guessed source names | **Site authority referenced, current read-only recheck required** |

A meaningful backup is an **application-consistent set**, not an unordered concatenation of unrelated copies. If service quiesce is required for MQTT, S3 or edge state, that is a **separate owner-reviewed protected operation**; no implied permission to stop acquisition.

## Read-only source-to-site inventory gate

Before any capture runner is implemented or used:

1. On the installed Raspberry, independently read the exact **container ID/image digest/Compose labels, mounts and named-volume identities** for PostgreSQL, VersityGW, MQTT, Telemetry and Device Agent. Compare with the immutable installed package and migration authority. Do **not** infer the physical source from a Compose service key.
2. Identify whether `/run/secrets/nexolab/local-auth-*.pem` is actually mounted and owner-protected, without copying or printing secret bytes.
3. Inspect PostgreSQL readiness only with read-only queries; inspect edge SQLite and MQTT **without live file writes**. Capture sanitized metadata/quick-check only using vetted guardrails.
4. Establish the backup destination: independently identifiable removable disk/another controlled host, write permissions, capacity/quota, filesystem and route, and the custody of an encryption key **separate from the bundle**. The old 57.4G microSD partition is not evidence of an empty or approved destination.
5. Confirm timestamp/consistency boundaries across components, remaining free-space reserve (at least 20GiB) and what must be excluded from source-local root snapshots. No speculative disk cleanup.
6. Record evidence as sanitized manifest with snapshot time, immutable image and volume IDs/hashes, per-store consistency status, archive hash/bytes, capture duration and approved restoration target. No secrets, raw sensor archives or user data in Git/CI.

A missing, changed, inaccessible, ambiguous or unstable source identity is **BLOCKED**, not a reason to use a legacy path, automatically stop Docker or skip an asset.

## Actual isolated recovery gate

Restore to a separate host or **new isolated volumes**, never existing production volumes. On a controlled offline machine verify:

- encrypted bundle authentication and every manifest/component hash before extraction;
- PostgreSQL actual `pg_restore`, database schema head, protected row counts, relevant immutable/history hashes and authentication dependencies;
- actual VersityGW objects and metadata by count, bytes, hashes and private bucket permissions using the source-backed storage authority;
- MQTT restored Dynamic Security identities/ACLs and retained queue/persistence semantics;
- edge SQLite `quick_check`, queued events, idempotency/high-water/sequence continuity, no stale backup overwrite;
- matching local-auth private/public keys, existing protected local-account/session behavior, API denial without key, and successful authenticated local reads;
- independent offline Dashboard `:3000` / Telemetry API `:8082` and WebSocket result **on the isolated restored stack**, not on a mock/demo fallback;
- separate exact release/rollback identity and evidence that all original source volumes were untouched.

`pg_restore --list`, archive SHA and synthetic browser tests alone are insufficient. No real-site acceptance without actual evidence.

## Follow-up implementation boundary

1. **Next engineering WP: multi-store protected capture & manifest v2 design** — reconcile the existing five-asset v1 policy with actual VersityGW storage plus edge SQLite and other uniquely durable state. Preserve v1 synthetic drill; use typed versioned contracts/migrations and offline encryption instead of breaking existing archives.
2. **Separate WP: schedule and off-device retention** — bounded lock-protected systemd timer, protected destination, missed-run alerts and non-destructive retention; requires actual storage/capacity and key-custody decision.
3. **Separate WP: independently restored release gate** — verified off-device recovery, rollback and exact package/Compose IPAM decision. Only after these pass may #1399 request explicit owner approval for targeted Docker port/network recovery.

## Safety and ownership

No production commands in this Work Package. No Modbus writes, network reconfiguration, secret extraction, volume movement, container restart, off-site transfer or site update. Runtime remains offline-first. Source-only documentation acceptance is **not** hardware acceptance, full DR acceptance or permission to show `🟢 Оновлюйся`.
