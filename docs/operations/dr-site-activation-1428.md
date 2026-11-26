# #1428 DR-A site activation on `nexolab-edge-01` (#1786)

Status: **prepared, owner-run**. This procedure installs the reviewed DR-A tooling (#1630) on the Raspberry Pi and takes the first real encrypted backup. Each step names who acts and whether data or services change.

> A captured bundle is `CAPTURED_RESTORE_UNVERIFIED`. #1428 counts as recovered only after the off-device copy (#1631) **and** an isolated restore (#1632) pass. Stage 3 network work (#1734) needs a fresh receipt from this procedure.

## Site facts (2026-11-26, read-only via the Operator Broker)

| Item                            | Value                                                                                                                                                                |
| ------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Code path in the source unit    | `/opt/nexolab/current/scripts/…`, which **does not exist** on the Pi. This procedure installs to `/usr/local/lib/nexolab-dr/`                                        |
| PostgreSQL                      | `nexolab-central-postgres-1`, volume `nexolab-central-postgres-data` (database about 25 GB, mostly `telemetry_samples`)                                              |
| Object storage                  | `nexolab-central-minio-1:/data` → `nexolab-central-object-storage-versitygw-data`                                                                                    |
| Central MQTT (dynamic security) | `nexolab-central-mqtt-1:/mosquitto/data` → `nexolab-central-mqtt-data`                                                                                               |
| Edge MQTT persistence           | `nexolab-edge-mqtt-1:/mosquitto/data` → `nexolab-edge_mqtt-data`                                                                                                     |
| Edge SQLite                     | `nexolab-edge-device-agent-1:/var/lib/nexolab` → `nexolab-edge_edge-data`, file `edge.db` (default `DATABASE_PATH`)                                                  |
| Central ingestion spool         | `nexolab-central-telemetry-service-1:/app/data/telemetry-ingestion` → `nexolab-central-telemetry-ingestion-data`, file `spool.db`                                    |
| Local-auth keys                 | telemetry mounts `/run/secrets/nexolab_local_auth_private_key` and `…_public_key`. The template's `/run/secrets/nexolab/local-auth-*.pem` is **wrong for this site** |
| Host `python3`                  | `cryptography` 43.0.0 present                                                                                                                                        |
| Free space                      | about 29 GiB after the 2026-11-26 cleanup. The backup needs `free − 8 GiB ≥ 20 GiB`                                                                                  |

`scripts/nexolab-dr-site-config.py` resolves all of these from `docker inspect` on the host itself. Nothing is copied from this table.

## 0. Package (agent, no host change)

The agent stages these files from a merged `main` commit into a new directory under `~nexolab-dev/recovery-p0/`, together with a `SHA256SUMS` list:

- `nexolab-dr-scheduled-backup.py`
- `nexolab-dr-stream.py`
- `nexolab-volume-archive.py`
- `nexolab-dr-site-config.py`
- `nexolab-dr-backup.example.json`
- `nexolab-dr-backup.service`
- `nexolab-dr-backup.timer`

The owner gets the exact directory and the hash of `SHA256SUMS`.

## 1. Verify and install the code (owner; no data, no service change)

```bash
P=<package-dir>; T=$(mktemp -d)
sudo cp -a "$P"/. "$T"/ && cd "$T"
echo "<sha256-of-SHA256SUMS>  SHA256SUMS" | sha256sum -c - && sha256sum -c SHA256SUMS
sudo install -d -o root -g root -m 0755 /usr/local/lib/nexolab-dr
sudo install -o root -g root -m 0755 nexolab-dr-scheduled-backup.py nexolab-dr-stream.py nexolab-volume-archive.py /usr/local/lib/nexolab-dr/
echo "<merged-main-commit>" | sudo tee /usr/local/lib/nexolab-dr/SOURCE_COMMIT >/dev/null
```

## 2. Render the site config (owner; read-only, writes one root file)

```bash
sudo python3 -I -B "$T/nexolab-dr-site-config.py" --template "$T/nexolab-dr-backup.example.json"            # report only
sudo install -d -o root -g root -m 0700 /etc/nexolab
sudo python3 -I -B "$T/nexolab-dr-site-config.py" --template "$T/nexolab-dr-backup.example.json" \
     --install-dir /usr/local/lib/nexolab-dr --output /etc/nexolab/dr-backup.json
```

Expected:

- one `STORE_OK` line per store, with its size against the cap;
- then `DR_SITE_CONFIG_WRITTEN /etc/nexolab/dr-backup.json (0600)`.

Anything else is `BLOCKED <reason>` (exit 78). An existing config is never overwritten.

## 3. Key and custody (owner only; the agent never sees the key)

```bash
sudo sh -c 'umask 077; test -e /etc/nexolab/dr-backup.key || head -c 32 /dev/urandom > /etc/nexolab/dr-backup.key'
sudo stat -c '%U:%G %a %s' /etc/nexolab/dr-backup.key          # root:root 600 32
sudo python3 -I -B -c 'import hashlib,sys; k=open(sys.argv[1],"rb").read(); print(hashlib.sha256(b"nexolab-dr-stream-key-id\x00"+k).hexdigest()[:32])' /etc/nexolab/dr-backup.key
```

The last command prints the public key fingerprint, the same value every receipt shows; record only that. Copy the key to offline custody media **separately from every bundle** (#1631, `dr-offdevice-copy-1631.md`). Losing the key makes every bundle unrecoverable.

## 4. Dry plan (owner; reads no data, writes nothing)

```bash
sudo install -d -o root -g root -m 0700 /var/backups/nexolab/dr
sudo python3 -I -B /usr/local/lib/nexolab-dr/nexolab-dr-scheduled-backup.py --config /etc/nexolab/dr-backup.json --plan
```

Exit 78 means capacity or configuration refused. Fix the cause; never lower the 20 GiB reserve.

## 5. Install the unit, not the timer (owner; no service change)

```bash
sudo install -o root -g root -m 0644 "$T/nexolab-dr-backup.service" /etc/systemd/system/
sudo install -d -m 0755 /etc/systemd/system/nexolab-dr-backup.service.d
sudo tee /etc/systemd/system/nexolab-dr-backup.service.d/10-site.conf >/dev/null <<'CONF'
# #1786: site install path (the source unit names /opt/nexolab/current, absent on this host)
[Service]
ExecStart=
ExecStart=/usr/bin/python3 -I -B /usr/local/lib/nexolab-dr/nexolab-dr-scheduled-backup.py --config /etc/nexolab/dr-backup.json
ReadWritePaths=
ReadWritePaths=/var/backups/nexolab/dr -/home/nexolab/nexolab-platform/runtime/observability
CONF
sudo systemctl daemon-reload
systemd-analyze verify /etc/systemd/system/nexolab-dr-backup.service
```

The timer stays uninstalled; enabling it needs a separate approval (step 8).

## 6. First backup (owner approval → agent through the broker)

The owner grants one approval:

```bash
sudo python3 -I /usr/local/lib/nexolab-operator/nexolab-operator-broker.py approve --op backup.start --ttl-minutes 120 --reason "#1428 first DR-A backup"
```

The agent then:

1. records the baseline: readiness and ingestion lag, the Device Agent queue, container `StartedAt`/`RestartCount`;
2. runs `backup.start` (the unit, at idle CPU and I/O priority);
3. follows `backup.health` and `logs.unit unit=nexolab-dr-backup.service` until it finishes;
4. records the same metrics during and after the run.

No container is stopped, restarted or recreated.

## 7. Verify (owner; reads the bundle, writes no plaintext)

```bash
B=$(sudo ls -1t /var/backups/nexolab/dr/*.nxs | head -1)
sudo python3 -I -B /usr/local/lib/nexolab-dr/nexolab-dr-stream.py verify --stream "$B" --key-file /etc/nexolab/dr-backup.key
```

Then follow #1631 (off-device copy with custody receipt) and #1632 (isolated restore on another host, never on the Pi).

## 8. Timer (separate approval)

```bash
sudo install -o root -g root -m 0644 "$T/nexolab-dr-backup.timer" /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now nexolab-dr-backup.timer
```

## Rollback

```bash
sudo systemctl disable --now nexolab-dr-backup.timer 2>/dev/null || true
sudo rm -f /etc/systemd/system/nexolab-dr-backup.timer /etc/systemd/system/nexolab-dr-backup.service
sudo rm -f /etc/systemd/system/nexolab-dr-backup.service.d/10-site.conf
sudo systemctl daemon-reload
```

The rollback never touches bundles, receipts, the key, the config or production data. The installed scripts in `/usr/local/lib/nexolab-dr/` are inert without the unit.
