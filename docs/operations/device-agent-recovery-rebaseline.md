# Device Agent recovery-authority rebaseline

This runbook applies only when a healthy production Device Agent container is
still running but its historical Docker image ID is no longer addressable. It
creates a new local rollback authority from that exact running container
filesystem. It must not be used to disguise a fresh source rebuild as the lost
image.

## Safety boundary

The rebaseline command never stops, pauses, restarts, recreates, or starts the
production Device Agent. It performs no Modbus operation, controller action,
Embraco activation, PostgreSQL restore, edge SQLite edit/restore, named-volume
deletion, or product-data deletion.

The helper never requests the source container's environment array. `docker
export` contributes filesystem content only; mounted edge-data and `/host/dev`
content are excluded. `docker import` restores only this fixed non-secret image
configuration allowlist:

- user `nonroot` and working directory `/app`;
- entrypoint `/usr/bin/python3.13` and command `dual_bus_main.py`;
- `PYTHONDONTWRITEBYTECODE=1`, `PYTHONUNBUFFERED=1`, and
  `PYTHONPATH=/app/site-packages`;
- port `8081` and the repository-defined local healthcheck.

If the running container differs from that allowlist, has writable-layer drift
beyond the known `/host` mount-point artifacts, has unexpected mounts, is not
healthy/MQTT-connected with queue depth zero, or does not match the explicit
lost image ID, the command fails before export. The central PostgreSQL boundary
is also exact: the one healthy production container must mount only
`nexolab-central-postgres-data` at `/var/lib/postgresql/data` read-write; an
alternate name, destination, mode, or extra persistent-volume identity is rejected.

## Read-only preflight

Run from the repository branch that owns the approved rebaseline:

```bash
python3 scripts/rebaseline-device-agent-recovery.py \
  --check-only \
  --deployment-evidence runtime/deployments/<successful-deployment-UTC> \
  --expected-deployed-source <deployed-40-character-SHA> \
  --lost-image-id sha256:<lost-historical-image-ID> \
  --expected-container <running-container-ID-or-unique-prefix>
```

Preflight verifies the latest successful deployment authority and rejects any
later unrecovered mutation boundary. A completed guarded rollback is recognized
as deployment authority only when `edge-sqlite-restore-result.json` and
`edge-sqlite-pre-cutover.json` are safe regular files and their schema, kind,
status, source/target SHAs, recovery image ID, SQLite integrity fields, queue
metadata, stream sequences, and deployment evidence ID match exactly; malformed
or inconsistent restore evidence fails closed. It independently checks the local Git
lineage, controlled-source version record, central PostgreSQL health/volume
identity, exact running Device Agent identity/config/mounts, local health,
writable-layer drift, and edge SQLite integrity/metadata. SQLite is opened
query-only inside the running container; only its integrity result, serialized
snapshot hash/size, registry revision, queue counters, and stream sequences are
returned. No telemetry payload is written to evidence.

## Explicit rebaseline

After focused repository tests and the read-only preflight pass, replace
`--check-only` with `--execute` using the same exact arguments. The helper:

1. exports the running container without pausing it;
2. hashes the temporary rootfs archive and scans its tar members, failing closed if `/var/lib/nexolab` or `/host/dev` contains any mounted payload rather than an empty directory placeholder;
3. imports it for `linux/arm64` with only the fixed safe configuration above;
4. creates both an evidence-bound `rebaseline-*` tag and the #767-compatible
   `recovery-<new-image-id>` tag;
5. verifies both tags resolve to the exact new image ID;
6. runs `docker create` with network disabled and a read-only root filesystem,
   never starts that validation container, then removes it;
7. rechecks the unchanged production container, health, and writable-layer
   drift; and
8. atomically publishes matching ignored local authority records.

The temporary export is deleted. The resulting sanitized evidence is under
`runtime/evidence/issue-768-device-agent-rebaseline-<UTC>/`, while the local
deployment authority pointer is
`runtime/recovery-authority/device-agent/current.json`. All paths are ignored by
Git and mode-restricted. Evidence records IDs, hashes, safe config, volume and
database metadata, but never runtime environment values or telemetry payloads.

## Future deployment behavior

The #767 pre-build preservation guard validates the current pointer against its
immutable copies, the still-running source container ID/historical image ID, and
the addressable rebaseline image/tag. It preserves the new image before any
candidate build. The pointer is consulted only while its `deployed_source` equals
the latest authoritative deployed source; after a later successful deployment
supersedes that source, the old pointer remains historical evidence and is
ignored rather than blocking future source-selection checks. A malformed pointer
remains fail-closed.

Until a later approved cutover recreates Device Agent, two identities are
intentionally retained:

- the existing container continues to report the lost historical image ID;
- snapshot/restore authority uses the addressable rebaseline image ID derived
  from that container filesystem.

At the #759 snapshot boundary, deployment tooling verifies both sides of that
mapping. A pre-mutation failure may restart only the same unchanged container.
The recovery image is used for the read-only snapshot helper and recorded as the
restorable Device Agent image. This rebaseline does not itself authorize or run
the #760 Embraco cutover.
