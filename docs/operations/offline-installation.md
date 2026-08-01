# NEXOLAB offline installation and update bundle

## Purpose

This runbook covers a disconnected `LOCAL_LAN` installation of the NEXOLAB core:

- dashboard;
- telemetry API and migrations;
- PostgreSQL;
- Mosquitto;
- MinIO and MinIO Client;
- Device Agent in simulator mode;
- optional fail-closed local operator authentication.

Hardware mode is unchanged and remains outside this Work Package.

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

The local-auth Compose overlay and runbook are included, but operator accounts and signing keys are not. Never add the volume-removal flag (`-v`) to `docker compose down`. Named volumes are the persistent data boundary and must survive install, update and rollback.

## 1. Build on a connected controlled host

Requirements:

- Git checkout at the exact release commit;
- Docker Engine with Buildx;
- Git, Python 3, `sha256sum` and `tar`;
- enough free space for all image layers, SBOMs, the uncompressed image archive and the compressed bundle.

Build a production-intended LOCAL_LAN dashboard with the local identity provider:

```bash
./scripts/build-offline-bundle.sh \
  --version 0.1.0-rc1 \
  --platform linux/amd64 \
  --dashboard-origin http://127.0.0.1:3000 \
  --api-base-url http://127.0.0.1:8082 \
  --websocket-url ws://127.0.0.1:8082/api/v1/telemetry/live \
  --auth-provider local
```

Use `--auth-provider disabled` only for an isolated acceptance profile. `acceptance` is reserved for controlled browser CI, and `supabase` remains optional external-provider behavior. The manifest records the selected provider.

For LAN clients, use the trusted central-host LAN address consistently in all three URL arguments. `NEXT_PUBLIC_*` values are compiled into the dashboard image, so changing the target origin or auth provider requires rebuilding the dashboard bundle.

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

## 3. Create external environment and local-auth files

Copy templates outside the extracted bundle so an update cannot overwrite them:

```bash
sudo install -d -m 0750 /etc/nexolab
sudo cp deploy/compose/env.central.example /etc/nexolab/central.env
sudo cp deploy/compose/env.edge.example /etc/nexolab/edge.env
sudo chmod 0600 /etc/nexolab/central.env /etc/nexolab/edge.env
sudo editor /etc/nexolab/central.env
sudo editor /etc/nexolab/edge.env
```

Replace all placeholder passwords. Keep `DEVICE_MODE=simulator` for software acceptance.

For local operator authentication, create the external key pair and first administrator by following `docs/local-operator-authentication.md`. Set these operator-owned paths in `/etc/nexolab/central.env`:

```dotenv
AUTH_LOCAL_PRIVATE_KEY_HOST_FILE=/etc/nexolab/secrets/local-auth/private.pem
AUTH_LOCAL_PUBLIC_KEY_HOST_FILE=/etc/nexolab/secrets/local-auth/public.pem
AUTH_LOCAL_ISSUER=urn:nexolab:local
AUTH_LOCAL_AUDIENCE=nexolab-api
```

Do not configure a remote `AUTH_JWT_JWKS_URL` in the local profile. Ensure `CORS_ALLOWED_ORIGINS` contains the exact dashboard origin recorded in `manifest.json`.

For isolated validation without operator authentication, keep `AUTH_MODE=disabled` and omit `compose.local-auth.yaml`. Do not present that profile as production behavior.

## 4. Install without registry access

Disconnect or block external network access. The generic installer starts the isolated validation profile:

```bash
./scripts/install-offline-bundle.sh \
  --central-env /etc/nexolab/central.env \
  --edge-env /etc/nexolab/edge.env
```

For the local-auth profile, load/verify images with the installer first, then recreate the central stack with the auth overlay and no pull:

```bash
docker compose \
  --env-file /etc/nexolab/central.env \
  -f deploy/compose/compose.central.yaml \
  -f deploy/offline/compose.central.offline.yaml \
  -f deploy/compose/compose.local-auth.yaml \
  up -d --no-build --pull never --wait
```

The workflow:

1. verifies all bundle checksums and evidence;
2. loads `images/nexolab-images.tar`;
3. confirms loaded image IDs match the manifest;
4. validates Compose projects;
5. starts them with `--no-build --pull never`;
6. waits for health checks;
7. verifies dashboard, REST readiness, WebSocket application evidence, MQTT, PostgreSQL, MinIO and edge simulator health;
8. for local auth, verifies login, organization membership, RBAC, refresh rotation and logout revocation.

No npm, PyPI, Docker Hub, GHCR, Supabase, Render, Vercel or paid service is required at runtime.

## 5. Record installation evidence

Record only non-secret outputs:

```bash
python3 scripts/verify-offline-bundle.py .
docker compose \
  --env-file /etc/nexolab/central.env \
  -f deploy/compose/compose.central.yaml \
  -f deploy/offline/compose.central.offline.yaml \
  -f deploy/compose/compose.local-auth.yaml \
  ps -a
docker compose \
  --env-file /etc/nexolab/edge.env \
  -f deploy/compose/compose.edge.yaml \
  -f deploy/offline/compose.edge.offline.yaml \
  ps -a
```

Also record:

- bundle archive SHA-256;
- `manifest.json` source commit, auth provider and image IDs;
- host OS, architecture and Docker/Compose versions;
- free disk space before and after image load;
- named volume names and IDs;
- `/health/ready`, dashboard and edge health results;
- local login/RBAC/logout result without recording credentials or token values.

Do not include environment files, passwords, keys or tokens in evidence.

## 6. Update

1. Build and verify a newer bundle on a connected controlled build host using the same auth provider.
2. Transfer it beside the current bundle.
3. Back up PostgreSQL and local signing keys.
4. Verify the new archive and manifest.
5. Run its installer with the same external environment files.
6. Reapply `compose.local-auth.yaml` with `--pull never`.
7. Verify an existing local account can log in and logout invalidates the prior token.

`docker compose up` recreates changed containers while preserving named volumes. The installer never removes volumes. Accounts, memberships and refresh sessions remain in PostgreSQL.

## 7. Rollback

Rollback is allowed only when the database, spool and authentication compatibility rules permit it. Do not roll back to a pre-durable-ingestion image while pending/terminal spool rows exist.

To roll back application images, load the previous bundle and recreate the same Compose profile, including `compose.local-auth.yaml` when rolling back between ADR-0009-capable releases. Preserve the same key files and PostgreSQL volumes.

A version before ADR 0009 cannot provide local login even though the local-auth tables remain in PostgreSQL. In that case, stop and restore the previously accepted explicit auth profile; do not delete local-auth tables or volumes. If a release introduces an irreversible migration, use the accepted backup/restore procedure instead of an application-only rollback.

## 8. Failure handling

- Checksum mismatch: quarantine the bundle; do not load it.
- Image ID mismatch after load: stop; the archive or local tag was altered.
- Compose attempts a pull: stop; the offline overlay or manifest is incomplete.
- Missing/mismatched local signing keys: stop; do not disable auth to continue.
- CORS origin mismatch: correct the external central environment file or rebuild for the intended LAN origin.
- Remote JWKS configured in the local profile: stop and remove the runtime dependency.
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
