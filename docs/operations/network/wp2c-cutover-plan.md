# WP2c — remove the fixed-IP dependency (#1734): cutover plan

**Status: plan, not approved.** No step runs before (a) the backlog from #1733 is fully synchronised (done at 11:04Z, ingestion lag < 1 s), (b) a fresh backup per the #1428 policy, and (c) separate Product Owner approval of each phase. Every phase is reversible on its own and keeps volumes, PostgreSQL, MQTT persistence, the Edge bridge client ID, credentials and hardware configuration.

## Facts from the site (2026-11-25)

| Path                    | Today                                                                                                                                                                                                                           |
| ----------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Backend publishes       | Telemetry API `172.18.48.66:8082`, central MQTT `:1884`, MinIO `:9000`, Dashboard `:3000`. The address exists only through the interim `nxcompat0` boot unit                                                                    |
| Edge bridge             | `CENTRAL_MQTT_HOST=172.18.48.66`, port `1884`                                                                                                                                                                                   |
| HTTPS / Tailscale serve | `tailscaled` proxies to `http://172.18.48.66:3000` and `http://172.18.48.66:8082/api`; external UI `:3105` private API origin `172.18.48.66:8082`                                                                               |
| LAN browser bundle      | `7db6e1a8 CWBsCWWebOZGHa5YyWp18` compiles `http://172.18.48.66:8082`. Other LAN clients cannot reach the interim address                                                                                                        |
| Compose authority       | central files under `/var/backups/nexolab/live-1575-*/compose/` (root-only). `docker compose config` fails on `OFFLINE_DASHBOARD_IMAGE`; the Dashboard comes from the version-management catalog and the XWEB candidate compose |
| Networks                | `nexolab-central`, `nexolab-standalone-runtime` (central MQTT alias `central-mqtt`), `nexolab-edge_default`                                                                                                                     |

A wildcard listener cannot share a port with a specific-address bind, so the LAN gateway cannot take `0.0.0.0:3000` while Docker publishes `172.18.48.66:3000`.

## Phases

### Phase 0 — authority and preflight (read-only)

1. Export the effective Compose model per project through the privileged projection helper of the recovery tool, with `OFFLINE_DASHBOARD_IMAGE` resolved from the version-management catalog. Record image digests, named volumes, networks, aliases, port bindings and restart policies.
2. Record a baseline: readiness, `last_persisted_at`, Edge `$SYS` sent/stored/dropped, PostgreSQL max id, identities of LAN, HTTPS and lab, `tailscale serve status`.
3. Gate: fresh backup per #1428, free disk ≥ 28 GiB, no update lock held, ingestion lag < 5 s.

### Phase 1 — LAN gateway on port 80 (additive, no container change)

- Install `nexolab-lan-gateway` (merged #1740) on `0.0.0.0:80` with upstreams that stay loopback-only after phase 3. During phases 1–2 they point at the compatibility address through an explicit, temporary allow flag that ends with phase 3.
- Verify `http://<eth0>/` and `http://<wlan0>/` from a LAN client, plus the health endpoint and the API outage 503 behaviour.
- Rollback: `systemctl disable --now nexolab-lan-gateway`.

### Phase 2 — same-origin LAN frontend (frontend-only release, Option F pattern)

- Build a LAN artifact from main with `NEXT_PUBLIC_NEXOLAB_API_BASE_URL=same-origin` (WP2a #1738). Server-side private origin `http://telemetry-service:8082`, allowed by #1738.
- Activate with the guarded #1643 procedure: preview, switch, automatic rollback to the current LAN image.
- Verify through the gateway on Ethernet and on Wi-Fi: login, Live Data, WebSocket, charts, photos (authenticated API, #1740).

### Phase 3 — backend on loopback and Docker DNS (container recreation, approval required)

- Change only these values; images, volumes and credentials are unchanged:
  - `CENTRAL_BIND_ADDRESS=127.0.0.1`, so the API, MQTT and MinIO publish on loopback;
  - Dashboard on `127.0.0.1:3010`;
  - Edge `CENTRAL_MQTT_HOST=central-mqtt`, `CENTRAL_MQTT_PORT=1883` over `nexolab-standalone-runtime`, with the same `CENTRAL_BRIDGE_CLIENT_ID` and `cleansession false`;
  - Device Agent central URLs `http://telemetry-service:8082`;
  - HTTPS external UI private origin `http://127.0.0.1:8082`;
  - Tailscale serve targets → the gateway or loopback.
- Order:
  1. central MQTT, then wait;
  2. Telemetry Service, then wait for readiness;
  3. MinIO;
  4. Dashboard;
  5. Edge MQTT. The bridge queue is persisted, the client ID is unchanged, and it is recreated last.
- Verify the full matrix below. Rollback: recreate from the phase-0 recorded configuration (same images and volumes) and restore the compatibility address.

### Phase 4 — retire the interim address

- Disable `nexolab-compat-address.service`, remove `nxcompat0`, and remove the temporary gateway allow flag.
- `boot-repair` (#1748) stays as a guard against endpoint loss.
- Repeat the acceptance matrix, including a reboot.

## Verification at every phase

Readiness `ready`, `ingestion_lag_seconds` < 5, PostgreSQL max id growing, Edge `publish/messages/sent` growing and `store/messages/count` not growing, Dashboard and identities, no container restart loop, no Modbus write.
