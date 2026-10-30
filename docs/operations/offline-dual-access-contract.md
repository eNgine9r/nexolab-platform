# NEXOLAB offline dual-access browser contract

## Product outcome

A Raspberry Pi 5 collects real read-only RS-485 telemetry, stores it locally and
serves its Dashboard without internet or site LAN.
The Pi-attached screen uses `http://127.0.0.1:3000`.
An independently connected PC may use a trusted private Raspberry Pi IPv4
address on a direct Ethernet link or the Pi's secured local Wi-Fi access point.
Neither client may rely on public DNS, internet, Tailscale or paid APIs.

A separate PC still needs a physical Ethernet or wireless link to the Pi.
No network connection is needed for the Pi to continue acquisition.

## Explicit opt-in client contract

The normal approved production build keeps its existing absolute API and
WebSocket origins. A future isolated-client offline build may explicitly
enable `NEXT_PUBLIC_NEXOLAB_OFFLINE_DUAL_ACCESS=true`.

When enabled, the browser-side origin resolver may only replace a pinned
`127.0.0.1:8082` or `localhost:8082` REST/WebSocket host with the private
IPv4 host of a Dashboard opened using `http://<private-Pi-IP>:3000`.
It must reject public/WAN DNS, non-private IPv4, unexpected schemes, ports,
credentials and altered WebSocket paths.
The Pi-attached Dashboard keeps using loopback.
Server-side rendering keeps the installed API origin rather than trusting
request Host headers.

Next.js inlines `NEXT_PUBLIC_*` settings at build time.
Setting this flag on a running container **does not change** an already
built frontend bundle. It must be included in a separately validated
offline package build, not patched into the protected ffdefc runtime.

The client resolver is not a security control. A production rollout must
also provide exact trusted Pi link IPv4 allocations, local authentication,
explicit CORS Origin allowlists, host header checks, firewall isolation
and controlled host-port bindings for both the Pi screen and isolated PC.
Do not expose the sensitive API on every interface or disable authorization.

## Current implementation boundary

This is a source-only, opt-in client foundation.
The protected production Raspberry Pi is still running in `lan` mode,
and its existing Dashboard, Telemetry and VersityGW Docker networks are
detached after the October 29 reboot.
This code does not restore networks, activate a Wi-Fi access point, assign
an Ethernet link address or repair host port publication.

Sessions workspace and other authentication-dependent features require
an additional contract audit before accepting this as complete.
No deployment or hardware acceptance is claimed.
Keep the Pull Request in Draft until all consumers and exact browser
security tests pass.

## Acceptance required before protected site activation

- Offline boot with no physical Ethernet, Wi-Fi, DNS or default route.
- Pi-attached loopback Dashboard, login, REST and WebSocket verified.
- Direct Ethernet isolated-PC Dashboard with working authentication.
- Independent secure Pi Wi-Fi AP with working authentication.
- Database, local MQTT, edge SQLite and object storage preserved.
- New samples from all real read-only RS-485 buses persist in PostgreSQL.
- No demo fallback, stale-as-live UI or missing-sample fabrication.
- Full build, unit, browser security and disconnected OCI-bundle CI GREEN.
- Current consistent backup restored in an isolated environment.
- Exact approved network, Docker, CORS, authentication and rollback plan.
- Separate owner approval for production network, service or access changes.

Dependent incidents: #1399 Docker boot-network recovery, #1409 IPAM overlap,
#1400 VersityGW private network and #1397 persisted telemetry receipts.
