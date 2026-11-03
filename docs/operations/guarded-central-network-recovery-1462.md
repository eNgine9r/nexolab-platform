# NEXOLAB #1462 — Protected central Docker network recovery

## Source-only status

Original LOCAL_LAN Dashboard and API were manually restored on November 3 using
the accepted existing images, Docker networks, credentials and retained volumes.
This Work Package adds a **source-only** deterministic, fail-closed repair guard.
It is NOT installed, scheduled or activated in the live Raspberry runtime.

The accepted host currently has an **unsafe overlap** between physical LAN
172.18.48.0/21 and the edge Docker bridge 172.18.0.0/16. The real read-only
check must therefore continue to return status blocked. Source-only tests or a
successful future CI build do not waive physical IPAM safety (#1409).

## Read-only diagnostic

Run this command from a trusted NEXOLAB checkout with the accepted protected
version-manager source:

    python3 -I -B infrastructure/offline/guarded-central-network-recovery.py --check

The diagnostic reads the immutable protected package and container/bridge
inventory and never mutates them. Exit 78 means no site recovery is approved.
No credential, telemetry or hardware data appears in its report.

Guarded checks before any proposed repair: LAN/bridge CIDR disjointness;
valid installed package authority, manifest, source SHA and OCI digests;
protected version-manager update locks, existing Compose identity, exact named
volumes, known Docker networks and host-port bindings; no unrelated manual
PostgreSQL/Edge hardware drift.

## Future owner-approved execution only

An operator-scoped --execute requires root and both an explicit, current
--approved-bundle-id and --approved-source-commit from the protected package.
No automatic credentials, network or site approval are supplied in code.
The update-plane locks are held **exclusively** across all operations,
preventing overlapping recovery and version-manager updates. The central
authentication private/public key binds must both be present and read-only.

Only fixed existing central/standalone Docker bridges and four whitelisted
containers (mqtt, telemetry-service, dashboard, minio) can be reconnected,
using source-coded alias tables. Unknown containers, Docker networks, volume
mounts, changed images or source, network CIDR overlaps, partial startup and
any manual Edge/PostgreSQL drift block changes. This does not use Compose down,
recreate a container, restart a service, mutate an existing Docker subnet,
change CORS/authentication or send any Modbus writes. Partial mutation, if any,
is reported explicitly and never claimed to be production healthy.

## Remaining acceptance gates

1. Correct the overlapping edge bridge IPAM in separate #1409 using real
   authoritative LAN/VPN/reservation evidence, an offline ARM64 fixture and
   an owner-approved protected site maintenance/rollback envelope. Do not
   guess that an unexamined 10.x subnet is available.
2. Demonstrate complete unchanged PostgreSQL, Edge SQLite and MQTT storage
   identity with a recoverable rollback plan before production cutover.
3. Verify fixed Compose networks, exact aliases, negative authentication
   controls, actual local Chromium login, API/MQTT/DB readiness and fresh
   persisted telemetry in an isolated offline installation.
4. Implement a separately reviewed opt-in privileged systemd boot supervisor
   with bounded retry, durable audit, alerting and off-by-default activation.
   There is no such enabled timer in this Work Package.
5. Perform owner-authorized real reboot, restore and hardware read-only tests.
   Until these are evidenced, site and hardware acceptance remain UNVERIFIED.

Deployment constraints: offline LOCAL_LAN, no mandatory cloud/CDN/service,
no hardware/Modbus writes and no silent fake/demo telemetry.
