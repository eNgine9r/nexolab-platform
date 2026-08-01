# NEXOLAB offline installation and update bundle

## Purpose

This runbook covers a disconnected `LOCAL_LAN` installation of the NEXOLAB core:

- dashboard;
- telemetry API and migrations;
- PostgreSQL;
- Mosquitto;
- MinIO and MinIO Client;
- Device Agent in simulator mode.

Hardware mode is unchanged and remains outside this Work Package. Offline operator authentication is owned by Issue #188; the validation profile uses `AUTH_MODE=disabled` only on an isolated local network.

## Supported bundle targets

A bundle is built for exactly one target platform:

- `linux/amd64` — controlled Linux workstation/server;
- `linux/arm64` — Raspberry Pi 5 or another supported ARM64 Linux host.

Do not load an `amd64` bundle on an `arm64` host or the reverse. The manifest and verifier reject a platform mismatch.

## Security and data boundary

The bundle contains images, Compose definitions, environment templates, SBOMs, provenance, checksums and operator scripts. It does **not** contain:

- `.env.central` or `.env.edge`;
- passwords, JWT private keys, access tokens or site certificates;
- PostgreSQL, MinIO, MQTT or SQLite data;
- production telemetry;
- Modbus device configuration.

Never use `docker compose down -v`. Named volumes are the persistent data boundary and must survive install, update and rollback.

## 1. Build on a connected controlled host

Requirements:

- Git checkout at the exact release commit;
- Docker Engine with Buildx;
- Git, Python 3, `sha256sum` and `tar`;
- enough free space for all image layers, SBOMs, the uncompressed image archive and the compressed bundle.

Example for a same-host dashboard:

```bash
./scripts/build-offline-bundle.sh \
  --version 0.1.0-rc1 \
  --platform linux/amd64 \
  --dashboard-origin http://127.0.0.1:3000 \
  --api-base-url http://127.0.0.1:8082 \
  --websocket-url ws://127.0.0.1:8082/api/v1/telemetry/live
```

For LAN clients, use the trusted central-host LAN address consistently in all three URL arguments. `NEXT_PUBLIC_*` values are compiled into the dashboard image, so changing the target origin requires rebuilding the dashboard bundle. The manifest records the exact values.

Outputs:

```text
dist/offline/nexolab-offline-<version>-<arch>.tar.gz
dist/offline/nexolab-offline-<version>-<arch>.tar.gz.sha256
```

The connected build stage may access registries and the Trivy database. The resulting runtime bundle does not need them.

## 2. Transfer and verify archive checksum

Transfer both files using controlled removable media or an approved local channel.

```bash
sha256sum --check nexolab-offline-0.1.0-rc1-amd64.tar.gz.sha256
tar --extract --gzip --file nexolab-offline-0.1.0-rc1-amd64.tar.gz
cd nexolab-offline-0.1.0-rc1-amd64
python3 scripts/verify-offline-bundle.py .
```

Verification checks:

- archive and file SHA-256 values;
- complete seven-image inventory;
- content-addressed Docker image IDs;
- target platform;
- CycloneDX and SPDX SBOM hashes;
- persistent-data policy;
- absence of secret files and private-key/token patterns.

## 3. Create external environment files

Copy templates outside the extracted bundle so an update cannot overwrite them:

```bash
sudo install -d -m 0750 /etc/nexolab
sudo cp deploy/compose/env.central.example /etc/nexolab/central.env
sudo cp deploy/compose/env.edge.example /etc/nexolab/edge.env
sudo chmod 0600 /etc/nexolab/central.env /etc/nexolab/edge.env
sudo editor /etc/nexolab/central.env
sudo editor /etc/nexolab/edge.env
```

Replace all placeholder passwords. Keep:

```text
AUTH_MODE=disabled
DEVICE_MODE=simulator
```

for the isolated offline validation profile. Do not configure a remote `AUTH_JWT_JWKS_URL`; that would create a runtime internet dependency. Issue #188 owns the local fail-closed operator identity design.

Ensure `CORS_ALLOWED_ORIGINS` contains the exact dashboard origin recorded in `manifest.json`.

## 4. Install without registry access

Disconnect or block external network access, then run:

```bash
./scripts/install-offline-bundle.sh \
  --central-env /etc/nexolab/central.env \
  --edge-env /etc/nexolab/edge.env
```

The installer:

1. verifies all bundle checksums and evidence;
2. loads `images/nexolab-images.tar`;
3. confirms loaded image IDs match the manifest;
4. validates both Compose projects;
5. starts them with `--no-build --pull never`;
6. waits for health checks;
7. verifies dashboard, REST readiness, WebSocket application evidence, MQTT, PostgreSQL, MinIO and edge simulator health.

No npm, PyPI, Docker Hub, GHCR, Supabase, Render, Vercel or paid service is required at runtime.

## 5. Record installation evidence

Record only non-secret outputs:

```bash
python3 scripts/verify-offline-bundle.py .
docker compose \
  --env-file /etc/nexolab/central.env \
  -f deploy/compose/compose.central.yaml \
  -f deploy/offline/compose.central.offline.yaml \
  ps -a

docker compose \
  --env-file /etc/nexolab/edge.env \
  -f deploy/compose/compose.edge.yaml \
  -f deploy/offline/compose.edge.offline.yaml \
  ps -a
```

Also record:

- bundle archive SHA-256;
- `manifest.json` source commit and image IDs;
- host OS, architecture and Docker/Compose versions;
- free disk space before and after image load;
- named volume names and IDs;
- `/health/ready`, dashboard and edge health results.

Do not include environment files or secrets in evidence.

## 6. Update

1. Build and verify a newer bundle on a connected controlled build host.
2. Transfer it beside the current bundle.
3. Back up local data under the separate recovery runbook.
4. Verify the new archive and manifest.
5. Run its installer with the same external environment files.

`docker compose up` recreates changed containers while preserving named volumes. The installer never removes volumes.

## 7. Rollback

Rollback is allowed only when the database and spool compatibility rules permit it. In particular, do not roll back to a pre-durable-ingestion image while pending/terminal spool rows exist.

To roll back application images:

```bash
cd /opt/nexolab/bundles/nexolab-offline-<previous-version>-<arch>
./scripts/install-offline-bundle.sh \
  --central-env /etc/nexolab/central.env \
  --edge-env /etc/nexolab/edge.env
```

This reloads the previous versioned images and recreates containers against the same named volumes. It does not perform a destructive database downgrade. If a release introduces an irreversible migration, stop and use the accepted backup/restore procedure instead.

## 8. Failure handling

- Checksum mismatch: quarantine the bundle; do not load it.
- Image ID mismatch after load: stop; the archive or local tag was altered.
- Compose attempts a pull: stop; the offline overlay or manifest is incomplete.
- CORS origin mismatch: correct the external central environment file or rebuild for the intended LAN origin.
- Remote JWKS configured: stop; use the local-auth Work Package.
- Migration failure: do not delete volumes; collect logs and restore only through the accepted recovery procedure.
- Hardware unavailable: keep `DEVICE_MODE=simulator`; never silently switch to Modbus.

## Storage sizing

The manifest records each image's unpacked Docker size and the image archive size. Plan free disk space for:

1. the compressed bundle;
2. the extracted bundle and uncompressed `images.tar`;
3. loaded Docker layers;
4. at least one previous bundle for rollback;
5. PostgreSQL, MinIO, MQTT, telemetry spool and edge SQLite growth;
6. backup staging space.

Do not remove old data volumes to create space. Remove only verified obsolete image layers or old bundle archives after rollback retention requirements are satisfied.
