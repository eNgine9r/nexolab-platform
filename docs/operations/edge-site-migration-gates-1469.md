# NEXOLAB #1469 — Protected Edge network migration evidence gate

## Purpose and status

The live physical Raspberry Pi uses eth0 **172.18.48.0/21**, while
`nexolab-edge_default` uses **172.18.0.0/16**. The overlap is a proven
unsafe configuration that must not be concealed, but it is not proven
to have independently caused all historical Docker sandbox failures.

The source-only Compose overlay from #1464/PR #1465 has already been merged.
This Work Package adds a **read-only** independently inspected production
readiness gate. It does **not** run any network migration, Docker command
that changes state, service restart, backup, Modbus command or reboot.

The original NEXOLAB Dashboard remains accessible on the physical LAN
at `http://172.18.48.66:3000`; the protected release currently on the
site is source `ffdefc4550d71e211724de1154ffe9057f905c9c` on
`linux/arm64`.

## Read-only operator command

From a verified source checkout on the Raspberry Pi:

    sudo -n python3 -I -B \
      infrastructure/offline/inspect-edge-site-migration-gates.py \
      --check --candidate 172.26.0.0/24

The example `172.26.0.0/24` is **only a locally disjoint test
candidate**, not an approved LAN/VLAN/VPN or site-reserved subnet.
Running as root may be necessary to read the currently protected
version-management authority and update locks. This source is strictly
read-only; the command supports **no --execute**.

For known additional site ranges, repeat `--reserved-cidr`. An
unavailable reservation list is _not_ treated as an empty approved list.
The #1409 read-only guard verifies literal IPv4 routing and the currently
observed Docker bridge inventory and refuses invalid, broad, used or
routed candidates.

## Evidence required before any production migration

The gate requires the installed protected version-manager bundle to
pass its actual manifest/source/platform and immutable OCI image checks;
protected update-plane and worker lock availability; the running
original MQTT and Device Agent container identities and exact Compose
labels; existing named Edge SQLite/MQTT persistent volume mounts and
Docker-volume identities; only the canonical Edge and standalone bridges;
and loopback-only MQTT/Device Agent host port bindings.

The JSON reports **only boolean checks, static refusal reasons and
false status for cutover/mutation/hardware acceptance**. A valid local
candidate can pass the software identity checks but will STILL be
`BLOCKED` / exit 78 because the following are not established by
running this tool:

1. A site administrator's explicit, authoritative nonoverlapping
   **subnet reservation**, including neighboring VLAN, VPN, upstream
   network and future-range constraints.
2. Independently recoverable exact current **Edge SQLite,
   edge MQTT spool, central PostgreSQL, object storage** and
   protected local authentication state; a real rollback procedure
   verified with no data loss. Merely observing volume names is NOT
   recoverability proof. The host SSD has limited free space; no
   destructive local copy should be started without a capacity plan.
3. Physical RS-485 serial-by-id adapter identity, 3/3 real read-only
   bus acceptance, XJP60D/SDM120/Danfoss data and comparison of fresh
   central persisted samples before and after network maintenance.
   Some expected USB identities are currently absent.
4. Explicit owner-reviewed, source-pinned, on-site protected
   maintenance with physical access and working off-device access;
   no blind Docker network remove/Compose down, no global Docker IPAM
   change and no Modbus/hardware write.
5. Isolated ARM64 offline bridge replacement proof, rollback including
   injected failed DNS/MQTT, stale-edge data and verified post-boot
   local Chromium authentication and API health.

Source-only fixture or CI GREEN is **not** a production/site cutover
approval and must not be interpreted as readiness for auto-recovery.
The #1399 guarded auto-repair remains disabled until the CIDR overlap
is fixed in production and actual reboot/hardware acceptance is proven.

## Separate future activation

The protected runbook and operator script for the exact approved site
change are separate from this read-only Work Package. Never run
`docker network rm`, `docker compose down`, service recreation or
`docker network connect` merely because this script reports the
candidate is locally disjoint.

All core runtime services must continue to function offline with
no paid service, mandatory cloud API, remote font, telemetry upload
or Modbus write.
