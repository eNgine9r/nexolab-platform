# Local NEXOLAB version management

## Boundary

`/settings/system/version` is an administrator-only LOCAL_LAN workspace. The
Telemetry Service never receives the Docker socket, host credentials or an
arbitrary command endpoint. It may only read local release evidence and enqueue
an `update` or `rollback` request for one exact validated bundle ID.

The privileged host worker is separate. It accepts only files created through
that bounded API, revalidates the offline bundle, creates a PostgreSQL backup,
runs the existing offline installer, waits for Compose readiness and verifies
the exact Alembic revision before changing `current.json`.

No path in this workflow uses `docker compose down -v`, deletes named volumes,
rewrites Git history or performs a database downgrade. A rollback is allowed
only to the explicit previous bundle and only when that bundle declares the
current database schema runtime-compatible.

## Persistent local evidence

Set this existing Compose variable in `/etc/nexolab/central.env`:

```dotenv
VERSION_MANAGEMENT_HOST_ROOT=/var/lib/nexolab/version-management
```

The directory layout is:

```text
/var/lib/nexolab/version-management/
  catalog/<bundle-id>/         verified unpacked offline bundles
  current.json                 exact deployed and previous release evidence
  operations/<operation-id>.json
  requests/<operation-id>.json
```

`operations` is append-only through the API/UI contract: there is no edit or
delete endpoint. The worker advances a record through queued, running and one
terminal result. Safe metadata includes actor, exact source/target, SHA, backup
evidence ID and timestamps; secrets and environment contents are never copied.

## Install the host worker

On the controlled host, from a validated release source:

```bash
sudo ./scripts/deploy-version-manager-service.sh --source-root "$PWD"
sudo editor /etc/nexolab/version-manager.env
sudo systemctl status nexolab-version-manager.path
```

Use `NEXOLAB_VERSION_MANAGER_FLAGS=--local-auth --skip-edge` only for a central
standalone deployment. For a normal central+edge runtime keep `--local-auth` and
the configured edge environment path. The service has a single-operation file
lock and is triggered locally by the request directory; internet is not used.

## Stage a release offline

First verify the transferred archive checksum and extract it as documented in
`offline-installation.md`. Then stage it through the host validator:

```bash
sudo python3 scripts/nexolab-version-manager.py stage \
  --root /var/lib/nexolab/version-management \
  --bundle /media/nexolab/nexolab-offline-1.2.0-arm64
```

Staging runs the bundle's own verifier before and after copying. The catalog
accepts the copy only with a host-generated marker bound to the exact manifest
SHA-256. An invalid platform, checksum, SBOM, secret scan, persistent-data
policy or compatibility contract stops staging.

## Bootstrap current evidence once

After the existing deployment is represented by a staged exact bundle:

```bash
sudo python3 scripts/nexolab-version-manager.py bootstrap \
  --root /var/lib/nexolab/version-management \
  --bundle-id 1.2.0-arm64-0123456789ab \
  --runtime-mode lan
```

Bootstrap refuses to replace existing evidence. Any mismatch between the staged
bundle, live containers and database revision requires a separately reviewed
recovery procedure outside the UI. Until trustworthy current evidence exists,
the UI remains readable but all mutations hard-stop.

## Compatibility metadata

The offline manifest records:

- target Alembic head;
- exact schema heads eligible for upgrade;
- exact newer schema heads on which this application version can run safely;
- mandatory backup, migration-before-readiness and data-preservation flags.

The default bundle build declares only its own current head. A release intended
to update an earlier head or roll back after a forward-compatible migration must
name those heads explicitly:

```bash
./scripts/build-offline-bundle.sh \
  --version 1.3.0 \
  --platform linux/arm64 \
  --upgrade-from-schema-head 20260807_0024 \
  --runtime-compatible-schema-head 20260820_0025 \
  --dashboard-origin http://nexolab.local \
  --api-base-url http://nexolab.local:8082 \
  --websocket-url ws://nexolab.local:8082/api/v1/telemetry/live \
  --auth-provider local
```

Never declare compatibility without migration and rollback evidence.

## Failure and recovery

- Verification or compatibility failure: no backup/install command runs.
- Backup failure or empty dump: installer does not run.
- Installer, migration, health or exact-schema failure: operation is marked
  failed; current evidence is not advanced; persistent data is not deleted.
- Automatic database downgrade is forbidden. If the prior application cannot
  run against the current schema, stop and use the separately approved restore
  procedure from `disaster-recovery.md`.
- Preserve the failed operation, bundle and backup evidence for review.

Actual update/rollback acceptance on the controlled Raspberry Pi remains a
separate physical Gate. Software-only evidence must not be reported as physical
acceptance.
