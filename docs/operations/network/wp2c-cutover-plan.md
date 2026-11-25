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

- **Build** in GitHub Actions (`Frontend Release Artifact`, ARM64) from main with `api_base_url=same-origin`, `websocket_url=same-origin`, `auth_provider=local` and no `external_origin`.
  - The builder accepts `same-origin` only for both endpoints together, with local auth and never for the protected HTTPS stage.
  - The compiled public contract must report `same_origin_browser_bundle=no-absolute-host-origin`, meaning no IP literal, `localhost` or `:8082` origin in the browser bundle.
- **Server side:** the dashboard container additionally gets `NEXOLAB_SERVER_API_BASE_URL=http://telemetry-service:8082` (allowed by #1738). Without it, server routes fail closed.
  - Before the switch, the preview container proves that Docker DNS resolves `telemetry-service` from the `nexolab-central` network.
- **Activate** with `wp2c-stage2-frontend.py` (modes `stage`, `build`, `preview`, `check`, `execute`, `rollback`; see the [README](README.md#wp2c-stage-2-same-origin-lan-frontend-wp2c-stage2-frontendpy)), which reuses the guarded #1643 frontend-only procedure:
  - candidate and rollback Compose files are derived from `docker inspect` of the current container; only the image changes and the server-only API origin is added, and both are proven by a scratch `create` before the switch;
  - preview on `127.0.0.1:3125`, switch, then automatic rollback to the current LAN image (`7db6e1a8`, build `CWBsCWWebOZGHa5YyWp18`) on identity, gateway, Docker DNS or health failure, or on any backend container change.
- **Verify** through the gateway on Ethernet and on Wi-Fi: login, Live Data over `ws://<host>/api/v1/telemetry/live`, charts, photos (authenticated API, #1740), logout.
- **Also affected:** `tailscale serve :8444` proxies to the same LAN container and must be re-verified. The HTTPS UI `:3105` is a separate release and stays unchanged.
- **Gates:** the dashboard is stateless (no mounts) and the release is frontend-only, so the #1428 backup gate does not apply to this phase (Option F). It still applies to phase 3.

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
