# M3 edge-to-dashboard cutover validation

## Scope

This procedure validates Issue #59 without changing the proven Modbus acquisition path.

Production input:

- node: `edge-01`;
- XJP60D: `106-03`, `106-04`;
- LE-01MP: `200`, `201`, `202`, `203`;
- 34 latest telemetry series per complete polling cycle;
- MQTT topic: `nexolab/telemetry`;
- REST: `/api/v1/telemetry/latest`, `/api/v1/telemetry/history`;
- WebSocket: `/api/v1/telemetry/live`.

The cutover changes only local Mosquitto routing:

```text
Device Agent ── MQTT QoS 1 ──> edge Mosquitto
                                  │
                                  └── persistent bridge ──> central Mosquitto
                                                              │
                                                              └── Telemetry Service
                                                                    │
                                                                    ├── PostgreSQL
                                                                    ├── REST
                                                                    └── WebSocket
```

The `device-agent` container, `DEVICE_MODE=modbus`, serial path, register profiles and polling interval remain unchanged.

## Safety invariants

The procedure must stop immediately when any invariant fails:

1. `HARDWARE_DEVICE_MODE=modbus` before and after cutover.
2. `RS485_HOST_DEVICE` uses `/dev/serial/by-id/...`.
3. The `device-agent` container ID is identical before and after broker cutover.
4. Only the edge `mqtt` service is recreated.
5. PostgreSQL and MQTT named volumes are never deleted.
6. Live frontend mode never falls back to demo data.
7. The central MQTT socket is bound only to loopback, a trusted LAN/IoT VLAN address or VPN interface.

## 1. Prepare central host

Create the environment file:

```bash
cd ~/nexolab-platform/infrastructure/compose
cp .env.central.example .env.central
chmod 600 .env.central
```

Set a strong `POSTGRES_PASSWORD` and an explicit trusted interface address. For a separate central host, use its trusted LAN or VPN address:

```dotenv
CENTRAL_BIND_ADDRESS=192.168.1.10
CENTRAL_MQTT_PORT=1884
CENTRAL_API_PORT=8082
CORS_ALLOWED_ORIGINS=http://192.168.1.20:3000
```

`0.0.0.0` is not approved while Mosquitto is anonymous.

Start the controlled central profile:

```bash
docker compose \
  --env-file .env.central \
  -f compose.central.yaml \
  up -d --build

./central-smoke.sh .env.central
```

Record:

```bash
docker compose \
  --env-file .env.central \
  -f compose.central.yaml \
  ps

curl -fsS http://192.168.1.10:8082/health/ready \
  | python3 -m json.tool
```

Expected readiness:

```text
status=ready
database=ready
mqtt=ready
```

## 2. Prepare edge cutover contract

On `edge-01`:

```bash
cd ~/nexolab-platform/infrastructure/compose
cp .env.edge-central.example .env.edge-central
chmod 600 .env.edge-central
```

Copy the already validated hardware values from the active edge environment. Do not invent a new serial path.

Required values:

```dotenv
HARDWARE_DEVICE_MODE=modbus
RS485_HOST_DEVICE=/dev/serial/by-id/<validated-adapter>
XJP60D_POINTS=106:3,106:4
LE01MP_UNIT_IDS=200,201,202,203
CENTRAL_MQTT_HOST=192.168.1.10
CENTRAL_MQTT_PORT=1884
CENTRAL_API_BASE_URL=http://192.168.1.10:8082
CENTRAL_WEBSOCKET_URL=ws://192.168.1.10:8082/api/v1/telemetry/live
```

Preflight:

```bash
docker compose \
  --env-file .env.edge-central \
  -f compose.edge.yaml \
  -f compose.hardware.yaml \
  -f compose.edge-central-bridge.yaml \
  config --quiet

curl -fsS http://127.0.0.1:8081/health \
  | python3 -m json.tool
```

The health response must show `device_mode=modbus` and no active error.

## 3. Execute cutover

```bash
cd ~/nexolab-platform/infrastructure/compose
bash m3-cutover.sh .env.edge-central
```

The script:

1. captures edge and central pre-state;
2. verifies the production hardware contract;
3. records the current `device-agent` container ID;
4. recreates only edge Mosquitto with the bridge override;
5. verifies the local broker and Device Agent recovery;
6. proves the Device Agent container was not recreated;
7. validates at least 34 production latest series;
8. requires XJP60D `106-03` and `106-04`;
9. requires at least eight series from each LE-01MP `200–203`;
10. validates units, quality and alarm fields;
11. verifies recent history;
12. waits for a newly committed WebSocket event not present in the REST snapshot;
13. writes timestamped evidence under `runtime/evidence/`.

A successful manifest includes:

```json
{
  "validation": "m3-edge-central-cutover",
  "status": "passed",
  "device_agent_container_preserved": true
}
```

## 4. Enable dashboard live mode

Create or update `.env.local` on the dashboard host:

```dotenv
NEXT_PUBLIC_NEXOLAB_DATA_MODE=live
NEXT_PUBLIC_NEXOLAB_API_BASE_URL=http://192.168.1.10:8082
NEXT_PUBLIC_NEXOLAB_WEBSOCKET_URL=ws://192.168.1.10:8082/api/v1/telemetry/live
```

Restart only the frontend process. Do not restart the Device Agent.

Operator checks:

- state progresses through `connecting` to `live`;
- node card identifies `edge-01`;
- freshness updates from real `captured_at` timestamps;
- XJP60D cards show only `106-03` and `106-04` records;
- power KPI uses valid `active_power` values from LE-01MP `200–203`;
- quality and alarm states remain visible when `value=null`;
- a transport failure becomes `reconnecting`, `stale`, `offline` or `error`;
- no live failure silently displays demo KPI values or demo chart curves.

## 5. MQTT outage drill

On the central host:

```bash
docker compose \
  --env-file .env.central \
  -f compose.central.yaml \
  stop mqtt
```

Observe:

- edge Device Agent remains in `modbus` mode;
- the local edge broker remains available;
- bridge reconnect messages appear in edge MQTT logs;
- central readiness reports `mqtt=not_ready`;
- dashboard moves away from `live` after freshness expires;
- no demo fallback occurs.

Restore:

```bash
docker compose \
  --env-file .env.central \
  -f compose.central.yaml \
  start mqtt

curl -fsS http://192.168.1.10:8082/health/ready \
  | python3 -m json.tool
```

Run the cutover validator again and retain the new evidence directory.

## 6. PostgreSQL outage drill

Before the drill, read the bounded in-memory queue warning in `telemetry-backend-runbook.md`. Do not restart Telemetry Service while PostgreSQL is unavailable.

```bash
docker compose \
  --env-file .env.central \
  -f compose.central.yaml \
  stop postgres
```

Observe:

- `/health/ready` reports `database=not_ready`;
- MQTT may remain connected;
- `queue_size` and retry counters are bounded and visible;
- the Device Agent and Modbus polling continue unchanged;
- dashboard eventually becomes stale/offline instead of showing demo data.

Restore:

```bash
docker compose \
  --env-file .env.central \
  -f compose.central.yaml \
  start postgres
```

Verify queue drain, database recovery counters and a fresh 34-series validation.

## 7. WebSocket reconnect and duplicate drill

1. Keep REST and PostgreSQL available.
2. Restart only Telemetry Service:

```bash
docker compose \
  --env-file .env.central \
  -f compose.central.yaml \
  restart telemetry-service
```

3. Observe `reconnecting` in the dashboard.
4. Confirm the adapter resumes from the last committed `captured_at`.
5. Confirm repeated `event_id` values do not increase the number of UI series.
6. Confirm the dashboard returns to `live` after a new committed event.

Backend persistence is idempotent through unique `event_id`, and frontend state independently suppresses duplicate `event_id` values.

## 8. Backend restart persistence drill

Record a known history count:

```bash
curl -fsS \
  'http://192.168.1.10:8082/api/v1/telemetry/history?node_id=edge-01&from=<UTC_FROM>&to=<UTC_TO>&limit=1000' \
  > /tmp/m3-history-before.json
```

Restart the central application stack without deleting volumes:

```bash
docker compose \
  --env-file .env.central \
  -f compose.central.yaml \
  restart postgres telemetry-service
```

After readiness returns, repeat the same history query. The pre-restart records and count must remain available.

Never run:

```text
docker compose down -v
```

## 9. Controlled rollback

Rollback order:

### Edge host

Remove only the bridge override and preserve the Device Agent:

```bash
cd ~/nexolab-platform/infrastructure/compose
bash m3-edge-rollback.sh .env.edge-central
```

Expected evidence:

```json
{
  "status": "passed",
  "bridge_override_active": false,
  "device_agent_container_preserved": true,
  "modbus_mode_preserved": true,
  "volumes_deleted": false
}
```

### Central host

Stop the central services while retaining PostgreSQL and MQTT volumes:

```bash
cd ~/nexolab-platform/infrastructure/compose
bash m3-central-stop.sh .env.central
```

The script verifies these volumes still exist:

```text
nexolab-central-postgres-data
nexolab-central-mqtt-data
```

### Dashboard

Set the frontend explicitly to demo only when the operator intends to use the demonstration environment:

```dotenv
NEXT_PUBLIC_NEXOLAB_DATA_MODE=demo
```

Do not remove live URLs and leave the mode ambiguous. Live mode with an unavailable backend must remain an explicit error/offline state.

## 10. Evidence checklist

Attach or summarize the following in Issue #59:

- UTC cutover start and completion timestamps;
- central `health/ready` before and after;
- edge health before and after;
- unchanged Device Agent container ID;
- 34-series latest summary;
- XJP60D channels and LE-01MP per-meter series counts;
- recent history count;
- newly committed WebSocket event ID;
- MQTT outage observation;
- PostgreSQL outage and recovery observation;
- WebSocket reconnect observation;
- duplicate suppression observation;
- history persistence before and after restart;
- rollback manifests;
- confirmation that `DEVICE_MODE=modbus` remained unchanged.

Issue #59 is complete only after the physical host evidence is recorded. Repository CI validates the contract and scripts, but it cannot replace the live Raspberry Pi and central-host acceptance run.
