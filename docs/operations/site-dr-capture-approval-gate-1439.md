# NEXOLAB #1439 — protected eight-store capture handoff gate

**Source-only. No production backup, off-device transfer, restore, or site activation.**

This is the next planning gate after #1433 (v2 DR inventory), #1435
(read-only source preflight), and #1437 (isolated synthetic encryption fixture).
The gate accepts two **sanitized** JSON receipts and returns only an
operator-reviewable, non-executable capture plan.

## Inputs and safe invocation

The first input is the complete, protected read-only preflight receipt from
`scripts/nexolab-site-dr-preflight.py`. The second is a separately reviewed
handoff receipt with exact source references, archive size budgets,
consistency methods and **non-secret SHA-256 proof identifiers**.

Both inputs must be ordinary regular JSON files, mode 0600, without symlinks.
No raw key bytes, passwords, customer records, SQL contents, private paths,
hardware serial numbers or telemetry samples are accepted as receipt fields.

```bash
python3 scripts/nexolab-site-dr-capture-handoff.py \
  --preflight /path/to/sanitized-preflight.json \
  --handoff /path/to/sanitized-handoff.json
```

The command **never invokes Docker, MQTT, SQLite, PostgreSQL or the network**.
It cannot capture, schedule, encrypt, upload or restore real data and it
cannot create an authorization to operate on Raspberry.

The handoff requires `schema_version: 1`, `kind:
"nexolab-site-capture-handoff"`, `profile: "LOCAL_LAN"`,
`site_id: "nexolab-edge-01"`, a UTC `observed_at`, and a canonical
`preflight_sha256`. The handoff timestamp must be within 30 minutes after
the source observation.

## Required independent operator review evidence

The handoff includes `source_device_sha256` and
`destination_device_sha256`; they must differ. This checks only the
reported metadata. It **cannot independently prove** physical media
separation or reject a forged attestation.

Its `custody` object must contain `encryption: "aes-256-gcm"`,
`key_source: "mounted_file"`, separate key-custody proof hash and
destination review proof hash, with independently reviewed boolean
attestations for physical separation, encrypted off-device destination
and separate key custody. No actual key is supplied to the program.

Its `continuity` object must attest a ten-second sample interval,
LAN/offline operation, edge outbox high-water integrity, retention of
the legacy MinIO rollback volume and active VersityGW volume, and
prohibition of Modbus/hardware writes. These claims require independent
site evidence; the script merely checks the declarations.

No retention/consistency class may remain `unclassified` in the
**handoff**. All eight assets are explicitly marked `retain`, including
the central ingestion spool and edge MQTT state. An unclassified
source may only proceed when the handoff separately classifies it
with a non-secret `review_evidence_sha256`.

## Per-store consistency design

Every asset requires an immutable image/container identity matching the
source preflight, expected Compose project/service, bounded estimated
archive bytes, explicit `retain`, and the following method:

1. PostgreSQL: `online_pg_dump_custom` (logical consistent snapshot).
2. VersityGW: `separately_approved_s3_quiesce` (objects and metadata;
   never copy legacy MinIO data into VersityGW storage).
3. Central MQTT: `separately_approved_mqtt_quiesce` (persistence,
   Dynamic Security clients, roles and ACLs).
4. Edge SQLite/outbox: `sqlite_online_backup_with_high_water` (WAL,
   queue checkpoint, sequence and no dropped telemetry).
5. Local-auth private key: `protected_keypair_snapshot`.
6. Local-auth public key: `protected_keypair_snapshot`.
7. Central ingestion spool: `sqlite_online_backup_with_high_water`.
8. Edge MQTT: `separately_approved_mqtt_quiesce`.

**These are names of future separately approved procedures, not commands.**
No service stop/quiesce, database query or secret access is performed here.

## Capacity and activation boundaries

The protected work filesystem must have at least 24 GiB free:
20 GiB preserved headroom plus a maximum 4 GiB proposed staging.
The backup destination must have at least 16 GiB free and the aggregate
estimated encrypted archive size must fit with 2 GiB left over.
Every store must respect a hard source cap; changed or missing
volumes, image IDs, migration authority and backup methods fail closed.

The report `STRUCTURAL_PLAN_READY_FOR_INDEPENDENT_REVIEW` only means
the two JSON receipts are structurally compatible. It always carries:

- `encrypted_backup: NOT_PERFORMED`
- `off_device_copy: NOT_PERFORMED`
- `actual_isolated_restore: NOT_PERFORMED`
- `hardware_acceptance: UNVERIFIED`
- `production_capture: NOT_AUTHORIZED`
- `site_activation: NOT_AUTHORIZED`
- `operator_attestations: NOT_INDEPENDENTLY_VERIFIED`

Exit 78 means the plan is **BLOCKED**. A zero exit does not approve a
site operation, and these receipt fields can be forged. Full #1428
recovery requires a separate protected capture implementation, actual
encrypted off-device custody, key verification and fresh-volume
restore on an isolated host. Only then can #1399 consider the
Product Owner's separate approval for guarded Dashboard/API recovery.

No production data/hardware actions or new internet/runtime dependencies.
