# Edge SQLite cutover snapshot and recovery

This runbook defines the rollback-safe acquisition-registry boundary used by controlled Raspberry Pi deployments. It protects the Device Agent SQLite database before a source change can persist registry families that an older source cannot parse.

## Automatic pre-cutover snapshot

When `nexolab-edge_edge-data` exists, `scripts/deploy-current-head-raspberry-pi.sh` fails closed unless it can identify exactly one Device Agent container and capture:

- `edge-sqlite-pre-cutover.db` through `sqlite3.Connection.backup()` while the current database may remain live;
- `edge-sqlite-pre-cutover.json` with source/snapshot integrity results, SHA-256, byte size, registry revision, outbound queue count and high-water mark, per-stream sequence counters, deployed source, exact pre-cutover Device Agent image ID, target source and deployment evidence ID;
- `edge-sqlite-capture-result.json`, containing the same sanitized result.

All files remain in the ignored `runtime/deployments/<UTC timestamp>/` audit directory. The evidence contains no telemetry payloads. The helper itself is checksum-staged in that directory before any historical source checkout. After candidate verification, the deployment gracefully stops and verifies the existing Device Agent, captures the quiesced production database, and only then writes `runtime-mutation-started`. This prevents central-only activation failure from advancing the SQLite outbox or stream sequences beyond the recovery snapshot. Source and snapshot must both pass `PRAGMA quick_check`; snapshot and metadata contents plus their directory entries are fsynced before capture succeeds. The mutation marker is likewise atomically written and fsynced with its parent directory before any runtime-mutating Compose activation can start. Device Agent remains stopped until the later target edge activation; any failure in this interval is fail-closed and must use the explicit recovery procedure below.

A successful deployment never invokes restore. The new edge database and any post-cutover queue remain untouched.

## Decide whether restore is safe

Restore is limited to an immediate failed activation whose exact pre-cutover evidence is known. Before restoring, record the failed target SHA and the previously deployed SHA.

Stop and request a separate recovery decision if telemetry has been accepted after cutover or the outbound queue may contain post-cutover records. Restoring the older snapshot would discard that newer edge state. Do not hand-edit SQLite, copy the live database file, redirect Unit 2 to Bus 1, delete the named volume or restore PostgreSQL as part of this procedure.

## Explicit stopped-agent restore

From `infrastructure/compose`, stop only Device Agent without removing its container or volume:

```bash
docker compose \
  --env-file .env.edge-central \
  -f compose.edge.yaml \
  -f compose.hardware.yaml \
  -f compose.edge-central-bridge.yaml \
  stop device-agent
```

Return to the repository root and run the guarded restore with the exact deployment evidence directory and both exact source SHAs:

```bash
bash scripts/deploy-current-head-raspberry-pi.sh \
  --restore-edge-snapshot runtime/deployments/<UTC timestamp> \
  --expected-deployed-source <previous 40-character SHA> \
  --expected-target-source <failed target 40-character SHA>
```

The command rejects a running or ambiguous Device Agent, an unexpected volume, an unavailable pre-cutover Device Agent image, any remaining SQLite WAL/SHM/journal sidecar that could contain newer state, queue or stream-sequence advancement after capture, a corrupt snapshot, a mismatched filename/size/hash/revision/queue count, and wrong source or deployment evidence. Only after the guarded atomic SQLite replacement has the exact captured SHA and revision does it retag and verify the exact captured pre-cutover image as `nexolab-device-agent:local`. It then durably publishes `edge-sqlite-restore-result.json` by fsyncing its contents, atomically replacing it and fsyncing the evidence directory. That result is the recovery authority record: future controlled deployments accept it only when its restored source, failed target, evidence ID, database integrity metadata and image ID exactly match the pre-cutover metadata. A later snapshot also requires the container image to match recovered image authority, so recovery is not considered operationally complete until the explicit force-recreate verification below succeeds. Malformed or inconsistent recovery evidence fails closed. The Device Agent remains stopped throughout; if image selection fails after database replacement, no success result is published and restart remains prohibited.

Review the sanitized result and only then restart Device Agent as a separate operator action:

```bash
docker compose \
  --env-file infrastructure/compose/.env.edge-central \
  -f infrastructure/compose/compose.edge.yaml \
  -f infrastructure/compose/compose.hardware.yaml \
  -f infrastructure/compose/compose.edge-central-bridge.yaml \
  up -d --force-recreate device-agent
```

After restart, verify that the recreated container image ID exactly matches `deployed_device_agent_image_id` in `edge-sqlite-restore-result.json`, then verify Device Agent health, MQTT connectivity, queue depth and the expected acquisition-registry revision before continuing. A failed verification is not permission to delete data or retry with a different snapshot.

## Safety boundary

- Modbus and controller writes are forbidden.
- Restore never starts Device Agent automatically.
- If deployment quiesces Device Agent but fails before writing the durable runtime-mutation marker, it verifies and restarts only that same unchanged container/image. After the mutation marker exists, no automatic restart or restore is attempted.
- No `docker compose down -v`, volume deletion or product-data deletion is allowed.
- Snapshot evidence must stay associated with its exact deployment audit directory.
- PostgreSQL recovery remains a separate decision and is never implicit in edge SQLite restore.
