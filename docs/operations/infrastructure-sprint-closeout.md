# Infrastructure stabilization sprint: closeout and owner action package

Status as of 2026-11-26. The Operator Broker is **frozen at v1.7** (critical defects only). Exact package paths and hashes for each step are in `.project/BLOCKERS.md` (resume point).

## Where things stand

| Area                                  | State                                                                                                       | Evidence                                                                                                                                    |
| ------------------------------------- | ----------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------- |
| Operator Broker                       | v1.7.0 installed. Failed upgrades restore the previous version automatically (CI-proven)                    | owner `ACCEPTANCE_OK version=1.7.0`                                                                                                         |
| WP2c Stage 1 (LAN gateway)            | Live                                                                                                        | port 80 on `127.0.0.1`/`192.168.1.220`                                                                                                      |
| **WP2c Stage 2** (same-origin LAN UI) | **Live** (`c5bb48a1`/`xRUAt2U9…`)                                                                           | `STAGE2_FRONTEND_GREEN`; gateway, LAN and `:8444` identities; WebSocket 101; login API; telemetry continuous. **Browser acceptance: owner** |
| WP2c Stage 3 (backend loopback)       | Live plan matches. The Compose proof found one defect (`user`, fixed in #1799). **Not activated**           | `prove` (approval `85f89616`)                                                                                                               |
| Tailscale `:8443`                     | Prepared: broker `network.tailscale-inspection-route`                                                       | needs one approval                                                                                                                          |
| #1428 disaster recovery               | Tooling, package and checklist ready; **no real backup or restore yet**                                     | `dr-1428-owner-checklist.md`                                                                                                                |
| Dev session memory                    | Root cause fixed; persistent `MemoryHigh=1024M` on slice and service; `TMPDIR` on disk (next session start) | `dev-session-memory.md`                                                                                                                     |
| SSD                                   | 24 GiB free. Manifest C (20 images) has reference evidence                                                  | needs specific authorization                                                                                                                |
| Wi-Fi (#1735)                         | Router-side refusal of `2C:CF:67:A6:09:3A` most likely                                                      | owner router check                                                                                                                          |
| Reboots (#1399)                       | Cause undetermined; none since 2026-11-25 17:13; heartbeat running                                          | —                                                                                                                                           |

## Owner action package (in this order)

### 1. Stage 2 browser acceptance (about 5 min, no approval)

- Open `http://<Pi LAN address>/` and Tailscale `:8444`.
- Log in, open Live Data (values update), a chart and an equipment photo, then log out.
- Problem → `approve --op deploy.lan-frontend --arg phase=rollback …`, and the agent rolls back to `7db6e1a8`/`CWBs…`.

### 2. Tailscale `:8443` fix (one approval; network change)

```bash
sudo python3 -I /usr/local/lib/nexolab-operator/nexolab-operator-broker.py approve --op network.tailscale-inspection-route --arg action=apply --ttl-minutes 120 --reason "#1784"
```

The agent applies it: it saves the serve configuration, sets `/` and `/api` to the LAN gateway, verifies over Tailscale HTTPS, and restores the saved configuration if any check fails. `/inspection-login`, Funnel `:443`, `:8444` and `:8445` are untouched.

### 3. #1428 disaster recovery (critical path for Stage 3)

Follow `docs/operations/dr-1428-owner-checklist.md` with the pinned DR-A package (see BLOCKERS):

- **A:** activate (root config, key, `--plan`, unit only).
- **A2:** approve `backup.start`; the agent runs the first backup and records any disruption.
- **B:** key custody (stick or paper; record both fingerprints).
- **C:** off-device copy to the backup SSD.
- **D:** independent restore on an offline spare host.

Stage 3 needs the **receipt from A2 (less than 24 h old)**. Releases need **D**.

### 4. WP2c Stage 3 activation (after 3/A2; exact approval)

Owner-run as `nexolab` (docker group, never root) from the pinned Stage 3 package (path and hash in BLOCKERS).

**Window and impact:**

- about 5–10 minutes;
- five containers are recreated in order: central MQTT, telemetry, MinIO, dashboard, Edge MQTT;
- volumes, images and credentials are unchanged;
- Edge ingestion queues in the bridge between the central MQTT and Edge MQTT steps (client ID preserved, persisted queue);
- every existing address keeps working (dual publish).

```bash
P=<stage3-package-dir>; T=$(mktemp -d)
cp "$P/wp2c-stage3-backend.py" "$T/s3.py" && echo "<sha256>  $T/s3.py" | sha256sum -c -
R=$HOME/stage3-backup-receipt.json        # copy of the A2 receipt: sudo install -o nexolab -m 0600 <bundle>.receipt.json "$R"
python3 -I -B "$T/s3.py" prove   --retain-env CORS_ALLOWED_ORIGINS                       # STAGE3_PROVE_GREEN (no change)
python3 -I -B "$T/s3.py" check   --retain-env CORS_ALLOWED_ORIGINS --backup-receipt "$R" # STAGE3_CHECK_PASS NO_WRITES
python3 -I -B "$T/s3.py" execute --retain-env CORS_ALLOWED_ORIGINS --backup-receipt "$R" # STAGE3_BACKEND_GREEN
```

**Results:**

- On any failure the tool rolls back every switched service in reverse order and verifies the result: `STAGE3_ROLLED_BACK_VERIFIED`, exit 3.
- `HARD_BLOCKER_ROLLBACK_UNVERIFIED` (exit 4) means stop and call the agent.
- An explicit undo is `python3 -I -B "$T/s3.py" rollback`.
- After `STAGE3_BACKEND_GREEN` the agent verifies loopback publishes, the Edge bridge, telemetry continuity, LAN and Tailscale.

**Then retarget the consumers (owner, separate step).** Do **not** just delete the Stage 1 drop-in: the base gateway unit defaults its dashboard upstream to `127.0.0.1:3010`, while Stage 3 publishes the dashboard on `127.0.0.1:3000`.

```bash
printf '[Service]\nEnvironment=NEXOLAB_LAN_GATEWAY_ALLOW_COMPAT=\nEnvironment=NEXOLAB_LAN_GATEWAY_API=http://127.0.0.1:8082/\nEnvironment=NEXOLAB_LAN_GATEWAY_DASHBOARD=http://127.0.0.1:3000/\n' \
  | sudo tee /etc/systemd/system/nexolab-lan-gateway.service.d/10-stage1-compat.conf >/dev/null
sudo systemctl daemon-reload && sudo systemctl restart nexolab-lan-gateway.service
sudo tailscale serve --bg --yes --https=8444 --set-path=/ http://127.0.0.1:80
```

Also point the HTTPS UI's private API origin to `http://127.0.0.1:8082`.

**After the consumers:**

- `drop-compat --consumers-retargeted --object-storage-public-url http://127.0.0.1:9000` (separate approval);
- then retire `nexolab-compat-address.service`/`nxcompat0` (Phase 4);
- then the acceptance matrix, including a reboot.

### 5. Optional, independent

- **SSD manifest C:** `approve --op storage.remove-images --arg manifest_sha256=3c928c51…`. The removal re-runs the reference scan and skips anything protected.
- **Wi-Fi:**
  - router check;
  - approve unlimited autoconnect retries;
  - decide on removing the open `me_mac` and `iPhone` profiles.

## Known residual risks

- **Ambiguous `mqtt` alias:** on the shared network, telemetry and the Device Agent resolve `MQTT_HOST=mqtt` correctly only because Docker's network order favours them. This is unchanged by Stage 3 (the bridge uses `central-mqtt`) and stays a backlog item.
- **The broker's `docker.container` read op** fails on bind mounts (template `.Name`). It is diagnostics only; not fixed while the broker is frozen.
- **The broker's pinned Stage 3 handler** predates the `user` fix, which is why Stage 3 runs from the owner package.
- **Real-hardware evidence still open:** backup/restore, reboot cause, Wi-Fi.
