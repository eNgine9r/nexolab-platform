# M4 Gate 82 — session restart, offline recovery and real-hardware acceptance

This procedure proves the complete NEXOLAB laboratory session workflow on the real `edge-01` production contract:

- `K106 / 106-03 / temperature.probe`;
- `K106 / 106-04 / temperature.probe`;
- LE-01MP `200`, `201`, `202`, `203`;
- exactly 34 attributed series per complete production cycle.

The acceptance harness restarts services and temporarily stops central MQTT. It does **not** write Modbus registers, recreate the Device Agent, or delete Docker named volumes.

## Preconditions

1. Checkout current `main` on the Raspberry Pi.
2. Central and edge environment files exist:
   - `infrastructure/compose/.env.central`;
   - `infrastructure/compose/.env.edge-central`.
3. `RS485_HOST_DEVICE` points to a stable path under `/dev/serial/by-id/`.
4. `HARDWARE_DEVICE_MODE` is the validated production Modbus mode, never `simulator` or `demo`.
5. The dashboard is configured for live data:

   ```env
   NEXT_PUBLIC_NEXOLAB_DATA_MODE=live
   NEXT_PUBLIC_NEXOLAB_API_BASE_URL=http://<central-host>:8082
   NEXT_PUBLIC_NEXOLAB_WEBSOCKET_URL=ws://<central-host>:8082/api/v1/telemetry/live
   ```

6. The latest M3 rollback drill has passed and produced:

   ```text
   runtime/evidence/m3-rollback-*/manifest.json
   ```

The final Gate 82 manifest refuses to pass without rollback evidence proving that Device Agent polling, Modbus mode and named volumes were preserved.

## Safety contract

The harness:

- requires the explicit `--confirm-real-hardware` flag;
- rejects unstable `/dev/ttyUSB*` device paths;
- rejects simulator/demo hardware modes;
- never executes `docker compose down --volumes`;
- never sends Modbus write function codes;
- leaves evidence under ignored `runtime/evidence/`;
- uses repeatable idempotency keys for lifecycle commands.

## Phase 1 — pre-reboot drills

From the repository root:

```bash
cd ~/nexolab-platform

git switch main
git pull --ff-only

python3 infrastructure/compose/m4-session-acceptance.py \
  pre-reboot \
  --confirm-real-hardware
```

The harness will:

1. validate central and edge Compose contracts;
2. start both stacks and wait for readiness;
3. create a real laboratory session;
4. assign all 34 production bindings;
5. create limits version 1;
6. prepare and start the session;
7. enter the stabilization stage;
8. wait for a complete 34-series real-hardware cycle;
9. replay the start command and prove no duplicate event was created;
10. restart Telemetry Service and verify session, snapshot and WebSocket recovery;
11. restart PostgreSQL and verify the running session is preserved;
12. pause workflow while proving telemetry continues;
13. stop and restore central MQTT, then prove backlog recovery;
14. resume and change stage on a polling boundary;
15. capture pre-reboot REST, health, Compose, volume and log evidence.

The command prints the generated state file path. Keep it unchanged.

## Capture running-session screenshots

Before reboot, open the live dashboard and save these files into the generated evidence directory:

```text
01-sessions-list.png
02-running-session.png
```

The screenshots must show:

- the real session number;
- explicit `Live`, `Stale`, `Offline`, or `Error` state;
- `106-03` and `106-04` values;
- LE-01MP 200–203 metrics;
- current stage and configuration snapshot;
- no demo badge or synthetic fallback.

## Raspberry Pi reboot drill

```bash
sudo reboot
```

After SSH connectivity returns:

```bash
cd ~/nexolab-platform

python3 infrastructure/compose/m4-session-acceptance.py \
  post-reboot \
  --state-file runtime/evidence/m4-<timestamp>/state.json \
  --confirm-real-hardware
```

The post-reboot phase validates:

- Linux boot ID changed;
- central and edge named volumes retained their identity;
- the session is still `running`;
- the active configuration snapshot is unchanged;
- the current stage is restored;
- a fresh 34-series cycle is attributed;
- dashboard WebSocket reconnects;
- completion succeeds;
- completed evidence remains hash-identical after Telemetry Service and PostgreSQL restarts;
- replayed completion creates no duplicate event;
- a completed session rejects mutation with `session_immutable`.

## Capture completed-session screenshot

Save the completed immutable view as:

```text
03-completed-session.png
```

Place it in the same evidence directory.

## Finalize Gate 82 evidence

```bash
python3 infrastructure/compose/m4-session-acceptance.py \
  finalize \
  --state-file runtime/evidence/m4-<timestamp>/state.json \
  --confirm-real-hardware
```

A successful run writes:

```text
runtime/evidence/m4-<timestamp>/manifest.json
```

The manifest records:

- session and run identifiers;
- pre/post reboot boot IDs;
- restart and outage results;
- production series count;
- immutable evidence status;
- named-volume preservation;
- rollback evidence;
- required screenshots.

## Expected evidence bundle

At minimum:

```text
runtime/evidence/m4-<timestamp>/
├── state.json
├── manifest.json
├── 00-baseline-*.json
├── 00-baseline-*.txt
├── 01-first-34-series.json
├── 02-websocket-after-service-restart.txt
├── 03-pause-telemetry.json
├── 04-mqtt-outage-recovery.json
├── 05-pre-reboot-session-evidence.json
├── 06-post-reboot-running-session-evidence.json
├── 07-completed-evidence.json
├── 07-completed-hashes.json
├── 08-post-completion-restart-session-evidence.json
├── 01-sessions-list.png
├── 02-running-session.png
└── 03-completed-session.png
```

## Failure handling

Do not delete volumes or manually rewrite session rows after a failed drill.

Capture current state first:

```bash
docker compose \
  --env-file infrastructure/compose/.env.central \
  -f infrastructure/compose/compose.central.yaml \
  ps

docker compose \
  --env-file infrastructure/compose/.env.central \
  -f infrastructure/compose/compose.central.yaml \
  logs --tail=300 --no-color

curl -fsS http://127.0.0.1:8081/health | python3 -m json.tool
curl -fsS http://127.0.0.1:8082/health/ready | python3 -m json.tool
```

Then preserve the incomplete evidence directory and attach its path to issue #82. A failed run is useful evidence; deleting it is not debugging, it is archaeology with a flamethrower.
