# NEXOLAB Current State

Updated: 2026-08-01  
Verified product baseline: `main` merge `4c980781ff1beb0afb89f1779c82750a06e8eb7e`  
Next Ready Work Package: Issue #188  
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
- PR #215 added and proved the offline installation/update bundle, merged as `4c980781ff1beb0afb89f1779c82750a06e8eb7e`.

## Issue #187 completed outcome

NEXOLAB now has a versioned offline bundle for the complete core runtime:

- dashboard;
- telemetry service and migrations;
- Device Agent;
- Mosquitto;
- PostgreSQL;
- MinIO;
- MinIO Client.

The bundle includes:

- target platform and exact source-commit manifest;
- versioned Docker image archive;
- archive and per-file SHA-256 checksums;
- image IDs and sizes;
- provenance;
- CycloneDX and SPDX SBOMs;
- offline central and edge Compose overlays;
- external environment templates;
- integrity verifier;
- disconnected installer;
- runtime smoke checks;
- update/rollback volume-preservation drill;
- operator runbook.

## Final verification

Final PR head `5dafd5b3014af69fa34b2524e00cb59cf7d5acb7` passed:

- CI run `30709170478`;
- Telemetry Service run `30709170479`;
- Offline Bundle run `30709170491`.

The final Offline Bundle gate proved:

- linux/amd64 seven-image build;
- exact source provenance;
- checksum, manifest and SBOM verification;
- deletion of all seven local runtime image references;
- clean validation-directory extraction;
- archive-only `docker load`;
- blocked container egress;
- central and edge simulator startup with `--no-build --pull never`;
- dashboard, REST, WebSocket, MQTT, PostgreSQL, MinIO and edge health;
- update and rollback container recreation;
- unchanged identities for six required persistent-data volumes;
- preserved PostgreSQL, retained MQTT, MinIO object and edge-volume markers.

Final artifact:

- artifact ID: `8821407762`;
- size: `558421492` bytes;
- digest: `sha256:39d8ae8912e813de5419f004d9a2c1e301baf498932cbc312c5d299092013c14`.

## Runtime and security boundary

- Runtime startup required no registry, npm, PyPI, external API or paid service after archive transfer.
- Environment files and secrets remain external to the bundle.
- No persistent volume was deleted.
- The isolated validation profile used `AUTH_MODE=disabled`; this does not complete offline operator authentication.
- No production/site deployment, Modbus write or hardware action was performed.

## Open Pull Requests

- #192 — separate draft formatting inventory; not mixed into product work.

## Next Ready Work Package

Issue #188 — define and prove fail-closed offline operator authentication and RBAC without a mandatory cloud identity service.

Required boundary:

- local identity must work while the LAN is disconnected from the internet;
- authentication and authorization must remain fail-closed;
- no private signing key or user password may be bundled in images or source;
- existing JWT/RBAC/audit contracts must be preserved or versioned explicitly;
- cloud identity may remain optional and isolated;
- no authentication bypass may be presented as production behavior.

## Remaining unverified areas

- linux/arm64 bundle execution on an actual Raspberry Pi 5;
- physical transfer and install on an operator-owned disconnected host;
- actual Raspberry Pi or central-host power interruption;
- physical disk-full and disk-loss recovery;
- production/site deployment;
- Modbus or other hardware writes;
- full hardware acceptance beyond previously recorded read-only evidence.
