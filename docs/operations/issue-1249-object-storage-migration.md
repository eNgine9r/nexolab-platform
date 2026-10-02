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
  tags, encryption, lock or redirect semantics. Bucket-level Object Lock is
  queried even for empty buckets; enabled or unreadable configurations fail closed. Unsupported history/security semantics fail closed
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
   source-selection preflight pins deployed authority and target source. If it
   changes the checkout after the target was captured, abort before migration and
   rerun from synchronized accepted main.
2. Reuse a preloaded VersityGW v1.8.0 image after checking Linux/arm64,
   the expected entrypoint and a network-isolated version probe. Offline bundle
   transport/integrity checks remain required. Resolve the bundle tag
   `nexolab/object-storage:versitygw-v1.8.0-arm64` when the standard tag is absent,
   and assign its verified immutable image ID to the standard tag only after the
   checks pass. Build the checksum-pinned image
   only when it is absent, before stopping API; missing offline prerequisites
   fail before migration. This does not remove canonical deployment prerequisites.
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
   qualification, service activation and post-activation readiness. Canonical
   deployment requires completed cutover authority; frozen pre-cutover proof is
   accepted only by the migration wrapper and cannot authorize deployment.
   Build other configured services separately, recheck accepted storage authority,
   and activate with no build/no pull so the verified storage image is retained.

The migration wrapper never removes a persistent volume or source object. The
legacy MinIO volume/image remain available. Temporary candidate containers and
temporary credential env files are removed; protected evidence and rollback
configuration remain under ignored `runtime/object-storage-migration`.

## Post-cutover application deployment recovery

Once `runtime/object-storage-migration/authority.json` has
`status=verified` and `cutover_verified=true`, and Telemetry writes have been
resumed against VersityGW, the storage migration is complete even if the later
application deployment fails.

At that boundary:

- **do not rerun** `migrate-object-storage-raspberry-pi.sh`; the active storage
  service is no longer the legacy MinIO source expected by that wrapper;
- **do not automatically restore MinIO**; post-cutover uploads may exist only in
  VersityGW and must not be orphaned from PostgreSQL metadata;
- preserve both storage volumes/images and the protected migration authority;
- do not use the legacy `resume-current-head-raspberry-pi.sh` as a shortcut
  around current deployment guards;
- after any source fix has merged GREEN, continue only through
  `deploy-current-head-raspberry-pi.sh`. Its storage guard accepts the verified
  migration source itself or a Git descendant only when the retained target
  image/volume and live VersityGW service still match the published authority.

The current controlled deployment also supports a separately accepted layered
Device Agent runtime only through canonical tracked Sprint baselines plus
checksum-protected runtime evidence. That authority never comes from the live
container alone and does not weaken image, source-lineage, edge-SQLite or
hardware-write guards.

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

## Disconnected migration before an offline bundle update

The normal entry point above performs the connected canonical update. On a
disconnected host, prepare the accepted clean main checkout, its cached
origin/main and verified preloaded arm64 bundle image before disconnecting.
Run the wrapper with both exact SHA arguments and `--offline-source-ref SHA`.
The requested offline SHA must equal HEAD and cached origin/main; ordinary
deployed-authority and ancestry checks still run, with no fetch or checkout
mutation. Missing preloaded images fail before migration; no online build is
attempted. After verified storage cutover and writer resume, the wrapper reports
`OFFLINE_STORAGE_CUTOVER_VERIFIED` and leaves the application update pending.
Continue with the existing verified offline bundle/version-manager procedure.
It does not run the networked current-head build/deployment or claim installed
application update acceptance. Do not treat a cached ref as proof of current
remote freshness or use a feature-branch SHA.

Offline bundles package the same stdlib authority validator and shared deployment
lock. The installer requires completed cutover proof whenever legacy storage
exists, checks the proposed bundle storage image against the accepted image,
and excludes concurrent migration/deployment before any activation. Supply
`--object-storage-migration-authority PATH` if evidence is outside the installed
repository's default runtime path. Bundle source must match migration authority
or descend from it in the local repository's available Git history; missing
lineage fails closed. A partial destination volume never authorizes installation.


### Durable layered Device Agent authority

A successful storage cutover may coexist with a separately accepted Device Agent
compatibility runtime that predates the current one-commit
compatibility-authority format. Controlled deployment resolves that layered
baseline only after synchronizing tracked main state. It requires the formal
deployed source from canonical deployment evidence, tracked compatibility
lineage `df368cfa… → 2296e307… → 7db6c8c3…`, checksum-verified #1117 runtime
evidence, exact current/rollback image IDs, Product Owner cutover authorization
and no-write/no-delete safety invariants. It does not require the historical
fork commit to remain reachable in the local Git object database. If any
identity or checksum disagrees, deployment fails closed.
