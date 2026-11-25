# Network-independent LOCAL_LAN runtime (#1733, #1734, #1735)

The 2026-11-25 incident (#1733) showed that one DHCP-assigned address was used for every host publish, the Edge MQTT bridge, the HTTPS gateway origin, the dev guard and the LAN browser bundle. Target addressing (#1734):

| Plane              | Address                                                                                                                         | Used by                                                |
| ------------------ | ------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------ |
| Host-internal      | `127.0.0.1` publishes for the Telemetry API (`8082`), central MQTT (`1884`), object storage (`9000`), dashboard (`3010`)        | LAN gateway, HTTPS gateway, lab.nexolab, kiosk, guards |
| Container-internal | Compose service names on `nexolab-standalone-runtime` (`central-mqtt:1883`, `telemetry-service:8082`, `edge-device-agent:8081`) | Edge bridge, Device Agent, dashboard server            |
| LAN                | `nexolab-lan-gateway` on `0.0.0.0:3000`: dashboard plus same-origin `/api/v1/` and WebSocket                                    | Any client on Ethernet or Wi-Fi, any DHCP address      |

The browser bundle uses `same-origin` (WP2a, #1738), so no address is compiled in. Photos load through the authenticated API on the page origin, never through a signed storage URL.

## Files

| File                                                 | Purpose                                                                                                                                                                                                                                                                          |
| ---------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `nexolab-network-compat-recovery.py`                 | P0 recovery (v3.2): `172.18.48.66/32` on dummy `nxcompat0`, `repair-networks` restores lost Docker endpoints (Compose model via a privileged read-only projection helper, or `--minimal-network-model`), verification, stability window, rollback; `boot-repair` unattended mode |
| `nexolab-network-endpoint-repair.service` / `.timer` | Unattended `boot-repair` as the operator (no sudo) 90 s after boot and every 5 minutes; no-op while endpoints are intact; 30-minute backoff after a failure                                                                                                                      |
| `nexolab-lan-gateway.mjs`                            | WP2b dependency-free Node gateway; upstreams must be loopback or exact private service names; bounded; explicit 503 on API outage                                                                                                                                                |
| `nexolab-lan-gateway.service`                        | Hardened system unit (`User=nexolab`, `ProtectSystem=strict`, `MemoryMax=128M`)                                                                                                                                                                                                  |
| `wp2c-stage2-frontend.py`                            | WP2c Stage 2 owner-run tool: stage, offline build, preview, read-only check, switch with automatic verified rollback of the same-origin LAN dashboard                                                                                                                            |

The cutover (WP2c) is a separate owner-run migration with rollback: loopback publishes, Edge bridge to `central-mqtt:1883` with the same `cleansession false` client ID, dashboard on `127.0.0.1:3010`, the gateway enabled, a `same-origin` LAN build, and finally removal of the compatibility alias. Gateway health: `GET /__nexolab_lan_gateway/health`.

## WP2c Stage 2: same-origin LAN frontend (`wp2c-stage2-frontend.py`)

Owner-run as the operator account (docker group, never root) on the production host, after Stage 1 (gateway on port 80) is live. It replaces only the stateless `dashboard` service of Compose project `nexolab-central`. The tool never touches volumes, networks or other services and never uses `--remove-orphans`, `down`, `prune` or `-v`. All state lives in `--workspace` (default `/home/nexolab/commander-workspaces/nexolab-wp2c-stage2`, mode 0700).

| Mode       | What it proves or changes                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| ---------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `stage`    | ZIP SHA-256, safe flat extraction (no traversal, no links, only the known artifact files), every artifact and runtime file hash, contract `api`/`ws` = `same-origin`, local auth, `external_https_stage=false`, public contract `status=PASS` with `same_origin_browser_bundle=no-absolute-host-origin`                                                                                                                                                                     |
| `build`    | Offline image `nexolab/dashboard:wp2c-stage2-<src12>-arm64` on the base proven from the current image (layer prefix), configuration mirrored, tar-streamed context, no pull, no cache, no network; the current image identity must equal the rollback identity; file-by-file comparison of `/app` with the artifact                                                                                                                                                         |
| `preview`  | Derives `rollback.compose.yaml` (exact current container from `docker inspect`) and `candidate.compose.yaml` (only the image changes and `NEXOLAB_SERVER_API_BASE_URL=http://telemetry-service:8082` is added) and prints both. Proves each reproduces the current settings by creating (never starting) it under a scratch project, then runs a preview on `127.0.0.1:3125` and proves identity, routes, Docker DNS and a server-side call to the API. Removes the preview |
| `check`    | Read-only: lock, 20 GiB reserve, node, non-root, current dashboard unchanged since preview with the rollback identity on its port and through the gateway, images present, backends running and healthy, API readiness                                                                                                                                                                                                                                                      |
| `execute`  | `check`, then `docker compose up --no-deps --no-build --pull never --force-recreate --detach dashboard`. Verifies identity on the dashboard port and through the gateway, the recreated settings, Docker DNS and the backend snapshot; otherwise rolls back automatically. Report (0600) under `reports/`                                                                                                                                                                   |
| `rollback` | Explicit verified rollback to the configuration recorded by `preview`                                                                                                                                                                                                                                                                                                                                                                                                       |

Markers: `STAGE2_FRONTEND_GREEN` (exit 0), `STAGE2_ROLLED_BACK_VERIFIED` (exit 3 after a failed switch, 0 for an explicit rollback), `HARD_BLOCKER_ROLLBACK_UNVERIFIED` (exit 4, stop and escalate), `STOP <reason>` (exit 2, nothing switched).

Example values for the expected rollback identity (site facts of 2026-11-25; confirm them on the dashboard's `/api/runtime-identity` before use): container `nexolab-central-dashboard-1`, image `nexolab/dashboard:issue-1643-7db6e1a8-arm64`, source `7db6e1a801aa6c1a142febd4e91c79eef62d5beb`, build `CWBsCWWebOZGHa5YyWp18`.

```bash
TOOL=/home/nexolab/nexolab-platform/docs/operations/network/wp2c-stage2-frontend.py
ROLLBACK="--rollback-source 7db6e1a801aa6c1a142febd4e91c79eef62d5beb --rollback-build CWBsCWWebOZGHa5YyWp18"
python3 -I -B "$TOOL" stage --artifact-zip ~/nexolab-frontend-release-<sha>-arm64.zip --expect-zip-sha256 <artifact digest>
python3 -I -B "$TOOL" build $ROLLBACK
python3 -I -B "$TOOL" preview $ROLLBACK   # review the printed Compose files
python3 -I -B "$TOOL" check $ROLLBACK
python3 -I -B "$TOOL" execute $ROLLBACK   # separate Product Owner approval
python3 -I -B "$TOOL" rollback            # only if needed later
```

The ZIP digest is the `digest` of the `Frontend Release Artifact` run artifact. After `STAGE2_FRONTEND_GREEN`, verify manually through the gateway on Ethernet and Wi-Fi (login, Live Data WebSocket, charts, photos, logout) and re-verify `tailscale serve :8444`. The Compose files of record are not modified; a later `up` from them would recreate the dashboard with the image named there.
