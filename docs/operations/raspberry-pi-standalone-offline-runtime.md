# Raspberry Pi 5 standalone offline runtime

## Purpose

This runbook operates an already installed NEXOLAB Raspberry Pi 5 as a single-host monitoring station with a locally attached display and browser. The runtime remains usable when Ethernet, Wi-Fi, default route, DNS and internet are absent.

This procedure does not create an offline installation bundle. The deployment step must run while the Pi can fetch the accepted `main` commit and required build inputs. After deployment completes, the runtime is local-only.

## Safety boundary

- Modbus communication remains read-only.
- Do not run `docker compose down -v`.
- Do not run `docker volume rm`.
- Do not delete PostgreSQL, MQTT, MinIO, telemetry-ingestion or edge SQLite data.
- Do not replace failed live telemetry with demo data.
- Do not use wildcard CORS.

## Prerequisites

- Raspberry Pi 5 with the repository at `~/nexolab-platform`.
- Docker Engine and Docker Compose v2.
- Node.js 22 or newer and npm.
- Existing `.env.central` and `.env.edge-central` settings.
- Stable `RS485_HOST_DEVICE=/dev/serial/by-id/...` path.
- Existing operator authentication configuration. The deployment preserves `AUTH_MODE`; it does not disable authentication for standalone operation.
- A locally attached display/browser for `127.0.0.1` access.

## Deploy standalone mode

Run while controlled update access is available:

```bash
cd ~/nexolab-platform
bash scripts/deploy-current-head-raspberry-pi.sh --runtime-mode standalone
```

The deployment:

- backs up the current PostgreSQL database when available;
- preserves named volumes;
- fetches the accepted `main` commit;
- compiles the dashboard for loopback REST and WebSocket origins;
- binds dashboard, API, MQTT and MinIO host ports to `127.0.0.1`;
- connects edge and central MQTT through Docker service discovery on the local Docker network;
- installs a dashboard systemd unit that starts after Docker without waiting for `network-online.target`;
- records `runtime/runtime-mode` and non-secret deployment evidence.

Expected local URL:

```text
http://127.0.0.1:3000
```

## Disconnect all external networking

After deployment succeeds:

```bash
sudo nmcli radio wifi off 2>/dev/null || true
sudo ip link set eth0 down 2>/dev/null || true
ip -4 -br address
ip route
```

Docker bridge addresses may remain. The acceptance requirement is that physical uplinks have no active IPv4 and there is no default route.

Reboot without reconnecting networking:

```bash
sudo reboot
```

After login, open the local browser at:

```text
http://127.0.0.1:3000
```

## Verification

For `AUTH_MODE=disabled`:

```bash
cd ~/nexolab-platform
bash scripts/verify-standalone-offline-raspberry-pi.sh \
  --require-loopback-only \
  --observation-seconds 60
```

For `AUTH_MODE=jwt`, provide an operator-owned short-lived token file and organization ID. The script does not print the token:

```bash
cd ~/nexolab-platform
bash scripts/verify-standalone-offline-raspberry-pi.sh \
  --require-loopback-only \
  --observation-seconds 60 \
  --access-token-file /run/user/$(id -u)/nexolab-access-token \
  --organization-id YOUR_ORGANIZATION_UUID
```

Expected final output:

```text
STANDALONE OFFLINE VERIFICATION PASSED
Evidence: .../runtime/evidence/standalone-offline-...
```

The verification checks:

- active runtime mode;
- no default route and no IPv4 on physical uplinks when requested;
- dashboard HTTP response;
- REST readiness;
- security-session contract;
- Device Agent health;
- WebSocket application handshake;
- central and edge container states;
- Alembic head state;
- MQTT readiness;
- advancing telemetry during the observation window.

## Reboot and persistence acceptance

After the first successful verification:

```bash
cd ~/nexolab-platform/infrastructure/compose

docker compose \
  --env-file .env.central \
  -f compose.central.yaml \
  -f compose.observability.yaml \
  -f compose.central-standalone.yaml \
  restart telemetry-service
```

Repeat the verification command. Then reboot once more and repeat verification. Record only non-secret evidence paths and timestamps.

Actual Raspberry Pi acceptance requires at least 15 minutes of operation without physical networking and proof that telemetry continues after service restart and reboot.

## Roll back to trusted LAN mode

Reconnect the intended LAN interface, then run:

```bash
cd ~/nexolab-platform
bash scripts/deploy-current-head-raspberry-pi.sh --runtime-mode lan
```

LAN mode restores the trusted LAN dashboard/API origins and `network-online.target` ordering. It preserves the same PostgreSQL, MQTT, MinIO, telemetry-ingestion and edge SQLite volumes.

## Troubleshooting

### Security Gate shows `SESSION_API_UNREACHABLE_OR_ORIGIN_BLOCKED`

Confirm the browser uses exactly:

```text
http://127.0.0.1:3000
```

Check:

```bash
curl -fsS http://127.0.0.1:8082/health/ready | python3 -m json.tool
curl -fsS http://127.0.0.1:8082/api/v1/auth/session | python3 -m json.tool
cat ~/nexolab-platform/runtime/runtime-mode
```

### Dashboard waits for networking

Inspect the generated unit:

```bash
systemctl cat nexolab-dashboard.service
```

Standalone mode must contain:

```text
After=docker.service
```

and must not contain `Wants=network-online.target`.

### Edge telemetry stops

Inspect the bridge and service discovery:

```bash
cd ~/nexolab-platform/infrastructure/compose

docker compose \
  --env-file .env.edge-central \
  -f compose.edge.yaml \
  -f compose.hardware.yaml \
  -f compose.edge-central-bridge.yaml \
  -f compose.edge-standalone.yaml \
  ps -a

docker logs nexolab-edge-mqtt-1 --tail 200
```

The bridge must use `central-mqtt:1883`, not a host LAN address.

### Migration failure

Do not delete volumes. Collect logs and use the accepted recovery procedure:

```bash
cd ~/nexolab-platform/infrastructure/compose

docker compose \
  --env-file .env.central \
  -f compose.central.yaml \
  -f compose.observability.yaml \
  -f compose.central-standalone.yaml \
  logs --tail 250 --no-color telemetry-migrate telemetry-service postgres
```

## Evidence status language

Before the physical test completes, report:

```text
software verified; actual standalone Raspberry Pi acceptance pending
```

After the real Pi test, report hardware acceptance only with the generated evidence and observed telemetry timestamps.
