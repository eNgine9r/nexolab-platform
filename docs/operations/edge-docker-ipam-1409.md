# #1409 — NEXOLAB Edge Docker IPAM: read-only site inventory and protected migration

## Incident and accepted authority (2026-10-29)

The Raspberry Pi physical `eth0=172.18.48.66/21` (LAN `172.18.48.0/21`) overlaps Docker `nexolab-edge_default=172.18.0.0/16` with `172.18.0.1` gateway. This is a proven routing ambiguity, **not** proven to be the sole cause of Docker's stale sandbox faults after reboot. Dashboard, Telemetry API and VersityGW have no Docker networks; MQTT is only attached to `nexolab-standalone-runtime`, PostgreSQL has central, Device Agent has edge and standalone. All six actual Docker image IDs match the digest sets of the accepted `ffdefc4550d71e211724de1154ffe9057f905c9c` offline package; its manifest marker SHA and source match. Current and previous package catalog directories and named volumes exist. This is **not** evidence that all database samples or existing S3 assets are available or backed up today.

Issue #1399 owns the original boot/sandbox recovery, #1400 object-storage, #1397 telemetry persistence and #1421 PackageKit policy. This #1409 read-only stage does **not** modify Docker or fix the outage.

## Inventory — source-only read-only step

Use the exact reviewed branch/commit. Do not copy scripts from an old Raspberry Pi checkout (`main` was observed behind `origin/main`). The script requires Python 3 standard library, `iproute2`, and local Docker CLI permissions; it does not need internet or elevated writes.

```bash
python3 infrastructure/offline/inspect-edge-docker-ipam-readiness.py
```

This reads only:
- `ip -j -4 addr show`;
- `ip -j -4 route show table all` (including non-main VPN/policy tables);
- `docker network ls --quiet` and `docker network inspect <listed ID...>`.

The sanitized JSON reports physical and virtual IPv4 subnets, routed IPv4 destinations, Docker bridge subnets, the current physical-versus-Docker conflict and the explicit flags `read_only=true`, `mutation_performed=false`, `site_cutover_authorized=false`. A current conflict exits nonzero. This script prints **no Docker environment, tokens, passwords, service logs, database values, MAC addresses, personal VPN peers or route gateways**.

No target subnet is approved yet. After the site administrator inventories full site topology and **explicitly reserves** a candidate with LAN/VLAN/VPN administrators, the script can evaluate that specific candidate read-only:

```bash
python3 infrastructure/offline/inspect-edge-docker-ipam-readiness.py \
  --candidate <SITE_RESERVED_RFC1918_CIDR> \
  --reserved-cidr <OTHER_RESERVED_SITE_CIDR>
```

A `candidate_unapproved` / `locally_disjoint_not_site_approved` result means **only** that the proposed subnet did not overlap networks visible in this snapshot. It is not proof of upstream allocations, VLAN/IPAM reservations, future VPN ads, or offline/post-reboot reachability; it cannot satisfy the release gate by itself. Unknown/inaccessible inventories, absent physical LAN, absent default route, absent edge bridge, missing IPAM, malformed route and occupied candidate all fail closed. Do not select a convenient `10.x` range on speculation.

## Protected production cutover — NOT authorized by this source-only work

Before proposing a concrete owner-reviewed migration command:
1. Collect and retain sanitized current IPv4 addresses, **all routing tables**, every Docker bridge/IPAM, Tailscale-advertised subnets and confirmed future site reservations. Confirm owner and administrators have physical LAN access for rollback if remote network access fails.
2. Verify the root-protected current immutable package identity, manifest and six runtime digests; immutable Compose network/IPAM file hashes, exact current container IDs, project labels, network names, labels/aliases, ports and published host bindings. Resolve necessary network ownership in the *installed* package, not only in source checkout.
3. Verify actual PostgreSQL, edge SQLite, MQTT spool and VersityGW *named volume identities*; inventory and independently **restore-test a recent consistent backup in an isolated disposable environment** before changing live production. A directory listing of 2026-10-14 dumps does not prove a recoverable October 29 state.
4. Verify no Version Manager operations or acquisition migrations are running; verify serial-by-id bus and read-only Modbus baseline, local-auth, frontend gateway, dashboard and admin access policies.
5. Prepare deterministic exact accepted-image Compose change for *only the edge bridge*, a checksum-pinned owner-local dry-run, a reversible restoration of the original bridge/IPAM and original container attachments, hard time bounds and fail-closed halt conditions. No broad Docker network connect, global default-address-pools changes, Compose down, volume removal, daemon restart or live cutover on assumptions.
6. Obtain **separate explicit Product Owner approval of the exact, reviewed, snapshot-bound site operation**. A general "continue" instruction is not authorization for the cutover, especially with the current Docker/LAN collision and unavailable verified backup restore.
7. During separately approved maintenance, independently verify the physical LAN route, MQTT → API → PostgreSQL newly persisted samples, existing PostgreSQL rows, retained edge SQLite/outbox, three actual RS-485 read-only workers, Chromium LAN Dashboard login, existing VersityGW assets, rollback readiness, and offline/post-reboot behavior. Never infer telemetry continuity from process health, fill data gaps, or claim hardware acceptance from mock data.

## Safe failures and scope

Missing local inventory, a conflicting candidate, unknown upstream reservations, missing rollback assets, active update lock, inadequate recent backup, stale immutable authority or missing physical recovery contact must stop before production mutation. The read-only script has **no** `--execute`, no network setter and no operator approval bypass. Its source tests use isolated mocked data only; native site acceptance and offline reboot have not been performed in this stage.
