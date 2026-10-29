# NEXOLAB Edge Docker IPAM — Site Readiness #1409

## Verified production evidence

On 2026-10-29, the Raspberry Pi had these IPv4 networks:

| Component | Network |
| --- | --- |
| Physical LAN on eth0 | `172.18.48.0/21` |
| Docker edge bridge | `172.18.0.0/16` |
| Other Docker bridges | `172.17.0.0/16`, `172.19.0.0/16` through `172.25.0.0/16` |
| Local Tailscale host address | `100.113.204.81/32` |

The edge Docker bridge overlaps the physical LAN.
This is a confirmed configuration defect.
It does not prove the root cause of the Docker sandbox failures.

Six running container image IDs match the accepted offline
`ffdefc4550d71e211724de1154ffe9057f905c9c` package.
The current manifest marker, source and package root match.
Current and previous catalog directories exist.
Expected named Docker volumes are present.

Dashboard, Telemetry API and VersityGW have no Docker networks.
MQTT has only the standalone network.
PostgreSQL remains on the central network.
The Device Agent has edge and standalone networks.

The installed Version Manager records `health=ready`, but
the site is not operationally healthy.
A listed backup file is not proof of successful restoration.

## Read-only inventory

Use only the reviewed branch or an exact validated source revision.
The Raspberry checkout was observed 23 commits behind remote `main`.
Do not run an unverified copy from the old checkout.

The stdlib Python script requires `iproute2` and Docker CLI access.
It works without internet and does not require runtime mutation.

```bash
python3 infrastructure/offline/inspect-edge-docker-ipam-readiness.py
```

It executes only these local commands:

- `ip -j -4 addr show`
- `ip -j -4 route show table all`
- `docker network ls --quiet`
- `docker network inspect` for the listed network IDs

The sanitized JSON reports physical and virtual IPv4 networks,
all route destinations and Docker bridge IPAM.
It reports `read_only=true`, `mutation_performed=false` and
`site_cutover_authorized=false`.

The script does not expose service environment values, credentials,
database contents, MAC addresses, VPN peer identities or route gateways.
The local default internet route is optional for LOCAL_LAN operation.
A connected physical LAN route remains required.

## Candidate subnet

The site route inventory showed no local overlap for the **provisional**
candidate `172.26.0.0/24`.
This is not an approved allocation.
It may still conflict with upstream VLAN, VPN or future LAN reservations.

Only after checking those reservations may an operator assess the
specific candidate without modifying any network:

```bash
python3 infrastructure/offline/inspect-edge-docker-ipam-readiness.py \
  --candidate 172.26.0.0/24
```

Include each site-reserved range using `--reserved-cidr`.
The tool does not select, allocate or activate an IP subnet.

The result `candidate_unapproved` only proves local disjointness
within the supplied inventory and reservation list.
It deliberately exits nonzero to prevent a false green deployment gate.
It does not grant permission for site deployment.

## Protected change gate — not activated

Before any production network migration, establish all of the following:

- Actual full LAN, VLAN, VPN and Docker route inventory.
- Site administrator reservation of a nonoverlapping target CIDR.
- Exact protected immutable package and Compose configuration hashes.
- Matching running container identities, labels, images and ports.
- Preserved PostgreSQL, SQLite, MQTT and VersityGW volume identities.
- A recent consistent backup with a successful isolated restore test.
- Safe rollback to the exact previous Docker IPAM and container topology.
- No active Version Manager update or acquisition operation.
- Stable serial-by-id RS-485 identities and read-only baseline.
- Owner physical access if the remote network becomes unreachable.
- Explicit Product Owner approval for the reviewed site procedure.

A source-only successful test does not satisfy these production gates.

The protected activation must target only the intended edge network.
Do not modify Docker global address pools.
Do not use blind `docker network connect` or `docker compose down`.
Do not remove volumes, downgrade Docker or restart daemons on assumptions.
Do not perform Modbus or hardware writes.

After an independently approved activation, prove LAN routing,
MQTT to API to PostgreSQL persistence, existing SQL and S3 data,
three real RS-485 read-only buses, Chromium Dashboard login,
local authentication, offline operation and rollback readiness.
Do not reconstruct historical telemetry gaps or infer live health
from the internal container process state alone.

## Related work

- #1399: protected post-boot recovery.
- #1400: private VersityGW network reachability.
- #1397: durable central telemetry acknowledgements.
- #1421: PackageKit update policy.

This Work Package is a read-only inventory and test stage.
No production network, database or hardware change is authorized.
