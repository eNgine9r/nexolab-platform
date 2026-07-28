# NEXOLAB platform disaster-recovery runbook

## Scope

This runbook covers the complete central-state recovery boundary:

```text
PostgreSQL + private MinIO objects + Mosquitto persistence/Dynamic Security
                                  ↓
                    canonical manifest and hashes
                                  ↓
                       AES-256-GCM bundle
                                  ↓
                   verified fresh-volume restore
                                  ↓
          REST + WebSocket + MQTT TLS + Chromium verification
```

The software drill does not require Raspberry Pi, RS-485, Tailscale, the physical laboratory network or access to the actual central host.

Actual-host scheduling, off-host storage, hardware-backed key custody, physical-disk failure testing and production DNS/TLS restoration remain a separate operational Gate.

## Recovery policy

The authoritative inventory is `security/disaster-recovery-assets.json`.

| Order | Asset | Consistency boundary | Backup format | Restore verification |
|---:|---|---|---|---|
| 10 | PostgreSQL | logical snapshot | `pg_dump --format=custom` | archive list, Alembic head, row counts, immutable hashes |
| 20 | MinIO bucket `nexolab-equipment-images` | application quiesce | object tree + sorted metadata manifest | private bucket, count, size and SHA-256 |
| 30 | Mosquitto persistence and Dynamic Security | controlled service quiesce | deterministic tar | clients, roles, ACLs, disabled state and credential rotation |

Software acceptance objectives:

- RPO: `0 s` inside the controlled quiesced drill boundary;
- backup duration: no more than `300 s`;
- restore duration: no more than `600 s`.

These are software acceptance targets. They are not claims about the eventual production host, disks, network or off-site storage.

## Safety invariants

1. Source volumes are never restore targets.
2. Restore always uses newly named destination volumes.
3. Never run `docker compose down -v` against a source stack.
4. The encryption key is exactly 32 raw bytes in a regular non-symlink file with mode `0600` or stricter.
5. Keys, passwords and private material never appear in argv, manifests, uploaded evidence or logs.
6. A bundle is not restorable until AES-GCM authentication, archive structure and every declared component hash pass.
7. Missing, duplicate, unexpected, symbolic-link, hard-link, special-file and path-traversing entries fail closed.
8. An immutable report or published refrigeration revision is restored as-is; recovery does not bypass database immutability triggers.

## CI recovery rehearsal

Run the complete software drill from the repository root:

```bash
bash scripts/run-disaster-recovery-acceptance.sh
bash scripts/run-disaster-recovery-domain-completeness.sh
bash scripts/run-disaster-recovery-tls-fleet.sh
bash scripts/run-disaster-recovery-browser.sh
```

The corresponding GitHub Actions workflows are:

- `Disaster Recovery Acceptance`;
- `Disaster Recovery Domain Completeness`;
- `Disaster Recovery TLS Fleet`;
- `Disaster Recovery Browser`.

Acceptance requires all four workflows and the normal repository CI to pass on the same exact commit SHA.

## Bundle commands

Generate a one-time key file outside the repository:

```bash
umask 077
mkdir -p runtime/private/dr
head -c 32 /dev/urandom > runtime/private/dr/backup.key
chmod 0600 runtime/private/dr/backup.key
```

Create a bundle only after the three protected components have been captured into the policy-defined payload tree:

```bash
python3 scripts/nexolab-backup-bundle.py create \
  --policy security/disaster-recovery-assets.json \
  --payload-dir runtime/private/dr/payload \
  --key-file runtime/private/dr/backup.key \
  --output runtime/private/dr/nexolab-backup.nxl \
  --repository eNgine9r/nexolab-platform \
  --commit "$(git rev-parse HEAD)"
```

Verify before transfer or restore:

```bash
python3 scripts/nexolab-backup-bundle.py verify \
  --policy security/disaster-recovery-assets.json \
  --bundle runtime/private/dr/nexolab-backup.nxl \
  --key-file runtime/private/dr/backup.key
```

Extract only into a new, absent directory:

```bash
python3 scripts/nexolab-backup-bundle.py extract \
  --policy security/disaster-recovery-assets.json \
  --bundle runtime/private/dr/nexolab-backup.nxl \
  --key-file runtime/private/dr/backup.key \
  --output-dir runtime/private/dr/verified-restore
```

The extractor validates the encrypted bundle and canonical manifest before writing restored component files.

## Restore order

1. Create fresh PostgreSQL, MinIO and Mosquitto destination volumes with unique drill or incident identifiers.
2. Verify and extract the encrypted bundle.
3. Restore the PostgreSQL custom dump.
4. Run `alembic upgrade head` against the restored database.
5. Restore MinIO objects and keep the bucket private.
6. Restore Mosquitto persistence and Dynamic Security state while the restored broker is stopped.
7. Start the restored broker, migration job and application services.
8. Verify protected-domain hashes and counts.
9. Verify MinIO object bytes, metadata and private access.
10. Verify Dynamic Security clients, roles, ACLs, disabled state and credential generation.
11. Verify readiness, authorized REST and WebSocket reads.
12. Reconnect two Device Agent identities through CA-verified MQTT TLS.
13. Publish post-restore telemetry and prove exactly-once persistence.
14. Load `/nodes`, `/reports` and `/refrigeration/showcase-106-01` in Chromium.
15. Preserve evidence and destroy only the isolated restore stack after sign-off.

## Recovery evidence

Every rehearsal or incident record must contain:

- repository and exact commit SHA;
- backup timestamp;
- encrypted bundle byte size and SHA-256;
- backup and restore durations;
- PostgreSQL dump size, schema head, protected counts and canonical hashes;
- MinIO object count, byte sizes and SHA-256 values;
- Mosquitto policy-state hash and TLS boundary results;
- restored application readiness;
- REST, WebSocket, MQTT TLS and Chromium results;
- confirmation that fresh destination volumes were used;
- confirmation that source volumes were not mutated;
- operator, reviewer and final disposition.

Evidence must be sanitized before upload. Database dumps, object archives, encryption keys, credentials and plaintext secret files are never uploaded as CI artifacts.

## Scheduling and retention baseline

Until the actual central-host Gate is available, GitHub Actions provides repeatable software rehearsal only. The production scheduler must not be claimed as deployed.

Recommended production baseline after host validation:

- encrypted backup every 24 hours;
- additional backup before schema migration or security-policy rotation;
- retain 7 daily, 4 weekly and 12 monthly verified bundles;
- copy encrypted bundles to an off-host destination after local verification;
- run a fresh-volume restore rehearsal at least monthly and after any backup-format change;
- run a full browser/MQTT operational rehearsal before a production release.

Retention deletion is allowed only after a newer bundle has passed verification and at least one off-host copy is confirmed.

## Key custody

- Keep the bundle and its key in separate administrative systems.
- Do not store the key in Git, container images, CI artifacts, shell history or the backup directory.
- Grant key access only to designated recovery operators.
- Record key identifier and custodian, never key bytes, in the incident record.
- Rotate the backup key on the approved custody schedule and after suspected exposure.
- Retain old keys for as long as retained bundles depend on them.
- A lost key makes the encrypted bundle unrecoverable; a copied key without the bundle is insufficient.

Hardware-backed or external secret-manager custody is deferred until the actual central host and operating environment are available.

## Monitoring contract

A production deployment should expose these recovery signals to the monitoring system:

- age of last successful backup;
- backup duration and encrypted bundle bytes;
- verification success/failure;
- protected PostgreSQL, MinIO and Mosquitto component counts;
- off-host copy success and age;
- free space in the backup destination;
- age and result of the last restore rehearsal;
- measured RPO and RTO against policy targets;
- consecutive backup failures;
- key-expiry or custody-review due date.

Minimum alerts:

| Severity | Condition |
|---|---|
| warning | no successful verified backup for 30 hours |
| critical | no successful verified backup for 48 hours |
| critical | bundle verification, manifest hash or AES-GCM authentication fails |
| warning | backup or restore exceeds its software target |
| critical | off-host copy is missing for the newest verified bundle |
| warning | restore rehearsal is older than 35 days |
| critical | backup destination free space is below the approved reserve |

The monitoring implementation and dashboards are a separate production-observability scope; this section defines its required contract.

## Incident recovery procedure

1. Declare the incident and freeze destructive automation.
2. Preserve failed hosts, disks, logs and source volumes for investigation.
3. Select the newest bundle whose key is available and whose verification succeeds.
4. Record the expected commit and container image digests from the manifest/release evidence.
5. Restore into fresh infrastructure; never overwrite the damaged source in place.
6. Complete database, object and broker-policy verification before enabling clients.
7. Run readiness, REST, WebSocket, MQTT TLS and browser acceptance.
8. Reconnect edge identities in a controlled order and observe duplicate/dead-letter counters.
9. Obtain operator and incident-owner approval before traffic cutover.
10. Keep the previous environment isolated until the rollback window closes.

If any component cannot be verified, stop the recovery and select an earlier verified bundle. Partial unverified restoration is not an accepted operating state.

## Rollback

Rollback is a routing and deployment decision, not an in-place database rewrite:

1. stop new writes to the candidate restored environment;
2. route clients back to the previously approved environment if it remains valid;
3. preserve the failed candidate for evidence;
4. record the failed Gate and reason;
5. do not delete either environment until incident sign-off;
6. if schema compatibility prevents application rollback, restore the last compatible verified bundle into another fresh environment.

## Actual-host Gate checklist

When access to the central host is available, complete and record:

- scheduler installation and service account;
- exact source volume and bucket names;
- encrypted local and off-host destinations;
- key-custody implementation;
- filesystem permissions and capacity thresholds;
- real DNS and TLS restoration;
- real host backup/restore timing;
- physical disk-loss simulation;
- multi-day retention and automatic expiry;
- alert delivery to the responsible operators;
- signed acceptance by the laboratory operations owner.
