# Issue #187 implementation checkpoint

Active branch: `feat/187-offline-install-bundle`

Current implementation slice:

- build a versioned `linux/amd64` bundle;
- verify archive and manifest checksums;
- remove all seven runtime image references;
- load the transferred OCI archive on a clean validation directory;
- block container egress;
- start central and edge simulator stacks with `--no-build --pull never`;
- verify dashboard, REST, WebSocket, MQTT, PostgreSQL, MinIO and edge health;
- seed PostgreSQL, MQTT, MinIO and edge-volume markers;
- recreate containers against update tags and then rollback tags;
- assert all six persistent volume identities and markers survive;
- upload the bundle and non-secret evidence.

This checkpoint is implementation evidence only. The Work Package remains in progress until the actual workflow is green.
