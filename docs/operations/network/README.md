# Network-independent LOCAL_LAN runtime (#1733, #1734, #1735)

The 2026-11-25 incident (#1733) showed that one DHCP-assigned address was used for every host publish, the Edge MQTT bridge, the HTTPS gateway origin, the dev guard and the LAN browser bundle. Target addressing (#1734):

| Plane              | Address                                                                                                                         | Used by                                                |
| ------------------ | ------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------ |
| Host-internal      | `127.0.0.1` publishes for the Telemetry API (`8082`), central MQTT (`1884`), object storage (`9000`), dashboard (`3010`)        | LAN gateway, HTTPS gateway, lab.nexolab, kiosk, guards |
| Container-internal | Compose service names on `nexolab-standalone-runtime` (`central-mqtt:1883`, `telemetry-service:8082`, `edge-device-agent:8081`) | Edge bridge, Device Agent, dashboard server            |
| LAN                | `nexolab-lan-gateway` on `0.0.0.0:3000`: dashboard plus same-origin `/api/v1/` and WebSocket                                    | Any client on Ethernet or Wi-Fi, any DHCP address      |

The browser bundle uses `same-origin` (WP2a, #1738), so no address is compiled in. Photos load through the authenticated API on the page origin, never through a signed storage URL.

## Files

| File                                 | Purpose                                                                                                                           |
| ------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------- |
| `nexolab-network-compat-recovery.py` | WP1 interim recovery: `172.18.48.66/32` on `lo`, start/rebind of existing containers, rollback, optional boot unit                |
| `nexolab-lan-gateway.mjs`            | WP2b dependency-free Node gateway; upstreams must be loopback or exact private service names; bounded; explicit 503 on API outage |
| `nexolab-lan-gateway.service`        | Hardened system unit (`User=nexolab`, `ProtectSystem=strict`, `MemoryMax=128M`)                                                   |

The cutover (WP2c) is a separate owner-run migration with rollback: loopback publishes, Edge bridge to `central-mqtt:1883` with the same `cleansession false` client ID, dashboard on `127.0.0.1:3010`, the gateway enabled, a `same-origin` LAN build, and finally removal of the compatibility alias. Gateway health: `GET /__nexolab_lan_gateway/health`.
