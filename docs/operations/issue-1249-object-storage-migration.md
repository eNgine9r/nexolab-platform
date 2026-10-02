# Issue #1249: MinIO to VersityGW migration before Raspberry update

The Product Owner authorized #1249 and the subsequent #1247 update on 2026-10-02.
ADR 0011 requires an S3 migration, rather than mounting legacy MinIO data into
VersityGW. The failed deployment `20261002T070118Z` did not activate runtime.
Its retention step did remove the historical `20260917T131852Z` deployment archive.

## Preconditions

- Use accepted `main` after this Work Package's exact-head CI and review pass.
- Run in the ordinary Raspberry terminal as `nexolab`, with Docker access and
  `sudo -v`; Commander cannot provide the required privileged execution surface.
- Keep the terminal connected throughout the operation. Do not reboot the host.
- All application S3 writes must originate from the one Telemetry Service writer.
  During the migration window, do not run independent S3 upload/admin clients.
  The script stops that writer only for the final copy and storage switch. Edge
  acquisition remains enabled and buffers incoming telemetry locally.
- The source must be private and unversioned, with owner-only ACLs, no bucket
  policies, lifecycle/replication/default-encryption/tagging configuration or object
  tags, encryption, lock or redirect semantics. Unsupported history/security semantics fail closed
  before activation; they require a separate migration implementation.
- Default installed identities must match: Compose project/network
  `nexolab-central`, source service `minio`, source volume
  `nexolab-central-object-storage-data`, and destination volume
  `nexolab-central-object-storage-versitygw-data`.
- The installed Telemetry image must contain Python and boto3. No new Python
  dependencies are installed on the Raspberry host.

## One terminal entry point

After the PR is merged, update the checkout and run:

```bash
cd ~/nexolab-platform &&
git switch main &&
git fetch origin main &&
git merge --ff-only origin/main &&
sudo -v &&
bash scripts/migrate-object-storage-raspberry-pi.sh \
  --expected-deployed-source df368cfa27efa945d59de33de8268898b564a19f
```

The wrapper pins the current accepted `main` revision for both migration and the
canonical deployment. It does not deploy an unreviewed feature branch.

## Verification and activation

1. Acquire the shared canonical deployment/recovery lock for the entire wrapper
   lifetime. Child deployment calls reuse only a verified matching inherited file
   descriptor; independent deployment and resume processes fail closed. Canonical
   source-selection preflight pins deployed authority and target source.
2. Build the existing checksum-pinned VersityGW v1.8.0 image before stopping API.
3. Create an isolated, migration-owned destination volume and candidate container.
   An existing destination without the migration ownership label is rejected.
4. Write only required credentials to mode-0600 temporary environment files.
   Compare candidate Compose credentials/region with the actual legacy runtime.
   Keep an exact private rollback Compose override with the legacy image, command,
   environment and volume. It contains credentials; never attach it to an Issue,
   PR, chat or public artifact.
5. Inventory all source buckets and current objects. Check private access and
   available space for copy, verification and a 2 GiB reserve.
6. Stop the exact Telemetry container, copy objects using conditional source GET,
   preserve content headers and user metadata, verify every destination SHA-256
   and size, compare exact bucket/key sets, repeat source inventory and byte reads.
   Unrelated destination objects are never deleted. Re-running a partial copy
   re-verifies existing bytes rather than trusting prior progress.
7. Publish protected migration authority bound to target source, exact images,
   destination volume creation identity and the stopped source writer.
8. Switch only the storage service while application writes remain frozen. Check
   its actual image and volume, all object bytes/metadata again, denied anonymous
   object/bucket access and signed object GET integrity.
9. Resume the unchanged Telemetry writer. Run the canonical controlled deployment
   against the pinned source; it owns PostgreSQL/edge snapshots, frontend candidate
   qualification, service activation and post-activation readiness.

The migration wrapper never removes a persistent volume or source object. The
legacy MinIO volume/image remain available. Temporary candidate containers and
temporary credential env files are removed; protected evidence and rollback
configuration remain under ignored `runtime/object-storage-migration`.

## Failure and rollback boundaries

Before storage switching, failure restarts only the unchanged frozen Telemetry
container. A destination copy is retained for inspection and resumption. If a
disconnected run leaves the migration candidate container present, do not launch
another migration or delete it blindly; inspect state/evidence first.

Between storage switching and resuming Telemetry writes, a failure restores the
legacy storage service using the protected exact Compose override, then restarts
the unchanged writer. If restoring storage fails, the writer remains stopped and
the script reports the blocker. This prevents writes into an unverified backend.

Before attempting to restart Telemetry, automatic storage rollback is disabled:
new uploads may exist only in VersityGW. If subsequent project deployment fails,
inspect canonical deployment evidence and recover with its established procedures.
Do not restore the legacy storage volume without reconciling post-cutover uploads
and their PostgreSQL metadata. Preserve both volumes and images until installed
acceptance succeeds.

## Evidence required before closing #1249 / #1247

- Actual Raspberry inventory, complete private migration manifest, source and
  destination image/volume identities, exact byte/metadata parity, signed GET and
  private-access verification.
- Canonical `DEPLOYMENT PASSED`, installed API/dashboard source/build identity,
  readiness, advancing telemetry and queue drainage after the write freeze.
- Authenticated operator image/layout browsing and intended Overview hierarchy.
- Offline operation/rollback scope distinguished from unit tests. No physical
  hardware acceptance is inferred from software checks; no Modbus writes occur.

Local safety unit tests cover interrupted/resumed copy, corruption, source
changes, privacy/security boundaries and migration authority. They are not real
MinIO/VersityGW or installed Raspberry acceptance evidence.
