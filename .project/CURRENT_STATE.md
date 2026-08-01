# NEXOLAB Current State

Updated: 2026-08-01  
Verified baseline: `main` at `6635892cc14c44f90e6357646496ffe782335e83`  
Active Work Package: Issue #187 / PR #215 — GREEN and ready to merge  
Status confidence: high for repository, linux/amd64 software-CI and disconnected container-runtime boundaries; partial for ARM64 actual-host, Raspberry Pi and hardware acceptance.

## Profile

- Project type: `LOCAL_LAN`
- Development internet: allowed
- Runtime internet: not required
- Mandatory paid runtime services: prohibited
- Device transport: read-only Modbus RTU and MQTT QoS 1
- No Modbus write, hardware write or production/site cutover is authorized.

## Completed baseline

- PR #184 merged the AI Development Operating Standard.
- PR #190 merged the verified architecture and offline boundary.
- PR #206 reconciled stale Pull Requests, trackers and successor Issues.
- PR #209 hardened Device Agent supply-chain evidence.
- PR #207 completed durable central telemetry ingestion.
- PR #213 restored actionable dashboard security bootstrap diagnostics.
- PR #214 stabilized the live telemetry WebSocket lifecycle.

## Issue #187 verified outcome

Issue #187 is implemented in branch `feat/187-offline-install-bundle` through PR #215.

Implemented bundle contract:

- separate `linux/amd64` and `linux/arm64` target manifests;
- seven runtime images: dashboard, telemetry service, Device Agent, Mosquitto, PostgreSQL, MinIO and MinIO Client;
- versioned Docker image archive;
- manifest with source commit, platform, image references, image IDs and sizes;
- SHA-256 checksums for the archive and all bundle files;
- CycloneDX and SPDX SBOMs;
- provenance record;
- external environment files and secrets;
- offline Compose overlays with `pull_policy: never` and no inherited build contracts;
- disconnected installer and runtime smoke scripts;
- update and rollback volume-preservation verification;
- operator runbook for build, transfer, install, evidence, update and rollback.

## Disconnected runtime verification

Verified code/runtime head: `f21d9effe079e07ad3d8d163f029f26d06292556`.

Offline Bundle run `30708470343` passed:

- exact PR-head checkout and provenance;
- linux/amd64 bundle build;
- seven-image inventory;
- archive and file checksum verification;
- CycloneDX and SPDX SBOM generation;
- removal of all seven local runtime image references;
- extraction into a clean validation directory;
- `docker load` from the transferred archive;
- blocked container egress;
- central and edge simulator startup with `--no-build --pull never`;
- dashboard HTTP readiness;
- telemetry REST readiness;
- WebSocket application-level evidence;
- MQTT, PostgreSQL and MinIO readiness;
- edge simulator health;
- update recreation against alternate image tags;
- rollback recreation against original image tags;
- preservation of six required destination-bound persistent-data volumes;
- preservation of PostgreSQL, retained MQTT, MinIO object and edge-volume markers.

Artifact evidence:

- artifact ID: `8821187814`;
- artifact size: `558407971` bytes;
- artifact digest: `sha256:d7400b9edc7fafeb99bae5795427c5b64041e534668d82891b0adfc9d87bbee9`.

Additional GREEN checks on the same verified code head:

- CI run `30708470342`;
- Telemetry Service run `30708470344`.

## Runtime and security boundary

- Runtime startup made no registry pull and no local image build.
- Container egress was blocked after bundle creation.
- No npm, PyPI, Docker Hub, GHCR, external API or paid service was required after archive transfer.
- `.env` files and secrets are external to the bundle.
- No persistent volume was deleted.
- The validation profile uses `AUTH_MODE=disabled` only for isolated LOCAL_LAN proof; offline fail-closed operator authentication remains Issue #188.

## Open Pull Requests

- #215 — GREEN and ready for final review/merge.
- #192 — separate draft formatting inventory; not mixed into product work.

## Next Ready Work Package

After PR #215 is merged, activate Issue #188 — define and prove fail-closed offline operator authentication and RBAC without a mandatory cloud identity service.

## Remaining unverified areas

- `linux/arm64` bundle execution on an actual Raspberry Pi 5;
- physical transfer and install on an operator-owned disconnected host;
- actual Raspberry Pi or central-host power interruption;
- physical disk-full and disk-loss recovery;
- production/site deployment;
- Modbus or other hardware writes;
- full hardware acceptance beyond previously recorded read-only evidence.
