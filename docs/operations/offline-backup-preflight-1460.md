# NEXOLAB #1460 — Read-only offline backup completeness and capacity preflight

## Status and limitations

**Source-only, not a working backup scheduler or restore gate.** The diagnostic
does not create, delete, encrypt, rotate, move, mount or restore data; never
connects to PostgreSQL, Docker, MQTT, Modbus, the internet or cloud APIs.
It reports machine-readable JSON, returns exit code **78 (BLOCKED)** and must
not be treated as proof of backup recovery.

The current recovery policy **omits Edge SQLite/outbox**. It declares old
object-storage service **minio**, while current physical site authority
references VersityGW and still requires independent reconciliation (#1431).
The source identity and live volume or bucket names must not be assumed.
No real off-device encrypted backup, independent restore, approved quiesce
boundary or backup scheduler has been verified.

## Read-only operator command

Run only against an existing directory from a checked-out NEXOLAB source
tree; this command does not require root and does not write anything.

    python3 -I -B scripts/nexolab-offline-backup-preflight.py --check \
      --policy security/disaster-recovery-assets.json \
      --staging-dir /var/backups/nexolab

Exit 78 means **blocked**. JSON explicitly reports
backup_performed:false and restore_performed:false. Unsupported flags
including --execute, --force, --delete fail instead of taking action.
No paths, passwords, tokens or actual device values are printed in JSON.

The gate reads the policy with duplicate-key rejection and checks mandatory
PostgreSQL, object storage, MQTT, Edge SQLite/outbox and local-auth key pair.
It rejects missing or duplicate required assets, legacy unverified storage
authority, inadequate consistency boundary, policy/staging symlinks, staging
directories that allow untrusted writes, and available disk headroom below
20 GiB reserve + 4 GiB maximum new bounded archive. The current owner-only
directory had **27,934,715,904 available bytes** when checked; this amount
can change and alone authorizes no copy.

The diagnostic intentionally never returns production-ready: it cannot
independently verify asset source mapping, consistency of quiesced stores,
protected key custody, actual backup medium, encrypted off-device copy,
isolated restoration, timer hardening, owner approval or power-loss safety.
This source-only safety slice under parent #1428 is a **preflight blocker/report**, not a backup job.

## Follow-on protected delivery gate

1. Complete read-only #1431 VersityGW, MQTT Dynamic Security/persistence,
   edge SQLite and local-auth asset inventory with authoritative provenance.
2. Preserve and reuse the existing NEXOLAB encrypted bundle and PostgreSQL
   backup tooling; never introduce a parallel unreviewed archive format.
3. Verify capacity and encrypted off-device medium, and custodied encryption
   key without disclosing secrets in Git, argv or diagnostic logs. Never use
   the mounted old microSD as backup media by assumption.
4. Build a lock-protected and explicitly opt-in systemd timer, with actual
   missed-run and offline monitoring, no unapproved data pruning.
5. Test an **actual fresh-volume isolated multi-store restore**, with hashes,
   identities, MQTT ACLs, Edge queue high-water, authentication and Dashboard.
6. Obtain separate Product Owner approval before production installation,
   backup capture, service quiesce, mount changes, hardware or cutover.

Permitted scope: the diagnostic, hermetic tests, this runbook, canonical
project state. No hardware, database, production files, or services changed.

The targeted tests are explicitly registered in the existing Telemetry service
GitHub Actions PostgreSQL 16 test workflow and its pull-request path filters.
This CI contract does **not** claim PostgreSQL, backup or site activation
from the read-only preflight itself.

## GitHub exact-head release gate

Initial source-only CI completed Telemetry service and Core quality but
correctly failed Merge Gate: two new DR script/test paths were unregistered,
so the fail-closed impact classifier required Dashboard, Offline Bundle and
Refrigeration browser workflows, which could not start from path filters.

The correction explicitly registers both exact paths as known DR tooling,
requires Offline Bundle, and adds them to its pull-request trigger. Changing
the central classifier itself STILL requires all three external workflows;
the existing Dashboard/Refrigeration triggers include that exact file.
A narrowly scoped regression in tests/test_ci_change_impact.py verifies both
behaviors. The Merge Gate is not disabled or weakened. Any future GitHub GREEN
is still not evidence of live backup or independent recovery acceptance.
