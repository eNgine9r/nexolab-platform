# NEXOLAB #1464 — Source-only explicit Edge bridge IPAM overlay

## Problem

The original Raspberry Pi LOCAL_LAN monitoring system uses an existing
physical eth0 LAN of 172.18.48.0/21. The old Docker project
nexolab-edge_default uses 172.18.0.0/16, which **overlaps the physical LAN**.
This can lead to misrouted Modbus TCP targets, incorrect Docker network
recovery acceptance and a repeat of manual Docker network repair. Actual
post-boot recovery remains Issue #1399.

This Work Package provides an **opt-in** Compose network override, but does
not modify the live bridge, any Docker container, hardware or volume.

## Source-only Compose override

The additional Compose file is:

    infrastructure/compose/compose.edge-safe-ipam.yaml

It only sets the default existing edge bridge's driver and an explicitly
required NEXOLAB_EDGE_DOCKER_SUBNET variable. There is **no default** IP
address in the file: no unapproved site IP range may silently be used.

Illustrative synthetic configuration-only test (no Docker daemon mutation):

    NEXOLAB_EDGE_DOCKER_SUBNET=172.26.0.0/24 docker compose \
      -f infrastructure/compose/compose.edge.yaml \
      -f infrastructure/compose/compose.edge-standalone.yaml \
      -f infrastructure/compose/compose.edge-safe-ipam.yaml \
      config --format json

The address above is **not approved for production**. It is a locally disjoint
synthetic test candidate, not a verified site-reserved subnet. The source-only
model retains the exact nexolab-edge project, device-agent and mqtt services,
both named persistent volumes, existing loopback-host port binds and the
standalone external MQTT network.

Without the variable, Compose config must **fail** rather than choose a
new subnet or implicitly assign another overlapping bridge.

## Non-mutating real-host preflight

To inspect an operator-nominated subnet and all known host/network routes:

    python3 -I -B infrastructure/offline/inspect-edge-docker-ipam-readiness.py \
      --candidate 172.26.0.0/24

Supply separate --reserved-cidr values for **every** site-admin-reserved
physical, VPN, upstream and future segment. Confirm actual network inventory
before using the candidate. Even a locally conflict-free result deliberately
returns status candidate_unapproved, exit 1, and sets
site_cutover_authorized=false. Never turn this into green/approved via a test
or forced flag.

## Production activation — NOT IN THIS WP

The accepted installed ffdefc immutable package, MQTT bridge identity,
PostgreSQL/Edge SQLite contents, serial-by-id devices and protected volumes
must be verified with an exact owner-reviewed recovery/rollback plan. First
confirm the real network administrator's reserved subnet and all physical,
VPN and Docker routes, and prove the proposed bridge in an isolated/offline
ARM64 runtime fixture. Do not change Docker daemon default-address-pools.

The actual bridge is currently attached to the still-operating Device Agent.
Changing it would be a **production network cutover** with potential
collection interruption: no Docker network rm, Compose down/up, iptables,
systemd or reboot is permitted here. Obtain explicit approval for the exact
future site maintenance action and rollback, then demonstrate actual local
Chromium login, Session API, fresh MQTT→PostgreSQL metrics, durable Edge
SQLite continuity and real RS-485 read-only acceptance. Never use Modbus write.

There is no production subnet migration, device acceptance or new automatic
recovery enabled by this source-only change.
