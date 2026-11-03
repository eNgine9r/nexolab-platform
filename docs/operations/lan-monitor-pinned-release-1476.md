# NEXOLAB #1476 — Immutable LAN monitor source pin, read-only gate

## Actual Raspberry Pi evidence, 2026-11-03

The Dashboard and API remain reachable through the physical local LAN at
http://172.18.48.66:3000 and :8082. Source-only LAN monitor assets are now
optionally included in the validated offline bundle (#1474, merged #1475),
but the accepted on-site runtime is still source
ffdefc4550d71e211724de1154ffe9057f905c9c and lacks them.

The protected version-management root is
/var/lib/nexolab/version-management (mode 0750, owned by uid/gid 10001).
An unprivileged nexolab systemd service must **not** access it by changing
protected directory permissions. The accepted catalog entry is root-owned
and is not an approved source for the non-root service. The existing
source-only systemd template still points to /opt/nexolab/current, which
does not exist on the real site.

## Safe source-only solution

The new read-only inspector
infrastructure/offline/inspect-lan-monitor-pinned-release.py
verifies the planned dedicated runtime layout:

    /opt/nexolab-lan-monitor/releases/<exact-40-hex-source-SHA>/

The parent directories and leaf must be root-owned real directories
with 0755 or 0555 modes. All five assets from the accepted SHA256-bound
offline monitor payload must be present as root-owned, regular,
non-symlink files with modes 0644/0444 and exact expected SHA256/size.

Both the accepted site package and its provenance must identify the
requested exact source commit and the
lan-access-monitor-source-only capability. The observed manifest must
contain the original five allowlisted asset paths without suspicious
monitor-named extras. The existing user and security sandbox settings
in the source systemd template must remain unchanged.

A pure renderer constructs a source-pinned ExecStart referencing
the exact release directory above, instead of a mutable current
alias or an inaccessible protected catalog path. It refuses duplicate
User directives, altered ExecStart sources, pre/post hooks or missing
NoNewPrivileges/PrivateDevices/ProtectSystem restrictions. The renderer
does not write or install the unit.

**No directories are created, copied, chmodded, activated or restarted
by this Work Package.** The candidate release directory does not yet
exist on the real Pi; this is a source-only verification contract for
a separately reviewed protected operator install.

## Read-only operator inspection

From the trusted NEXOLAB checkout:

    sudo -n python3 -I -B \
      infrastructure/offline/inspect-lan-monitor-pinned-release.py \
      --check \
      --required-source-commit bce9095e9b2c1657d10b47dd6d7ad3b478948951

The source in this example is the earlier merged #1474 commit;
it is **not** accepted on the Raspberry. The inspector returns JSON
BLOCKED and exit code **78**. Its flags contain no execute/install
mode. Every reported value is a boolean or sanitized reason code.
Even if all software evidence passes, the explicit operator rollback
and site activation gate remains false.

## Next actual installation gates — separate owner approval needed

1. Pin an approved release build/source/provenance and validate every
   protected package manifest hash, offline source and runtime policy.
2. Provision the dedicated non-root-readable source tree through an
   explicitly reviewed, transactional **site installer** with root-owned
   immutable paths. Do not chmod the existing protected package root.
3. Render and install the exact source-pinned unit only after verifying
   the source tree and service user can traverse/read it. Preserve the
   existing production Dashboard/MQTT/PostgreSQL/Edge containers.
4. Confirm private host metrics bind
   /home/nexolab/nexolab-platform/runtime/observability, single-file DR
   fallback, an opt-in directory-mode exporter and exact Prometheus
   metrics. Enable the optional alert rules **after** metrics exist.
5. Validate timer recovery, failure/stale/FIRING/RESOLVED delivery to
   local offline Alertmanager and a documented safe rollback.
6. Obtain separate owner approval for production activation. Physical
   RS-485 data/USB acceptance and a real power/reboot test are still
   unverified and cannot be inferred from an API readiness HTTP 200.

This does not resolve the physical LAN 172.18.48.0/21 vs Edge Docker
172.18.0.0/16 collision (#1409), does not enable #1399 automatic
boot recovery, and performs no Modbus or hardware writes, site
network changes, container recreation, database mutation, backup or
cloud runtime access.

## Source acceptance

Unit tests cover source commit/version drift, provenance tampering,
missing or unsafe manifest records, symlink/mutable/nontraversable
directories, asset hash/mode drift, duplicate root user directives,
unsafe systemd hooks and absence of an actual operator approval. The
full standalone offline runtime contract and CI must be GREEN on
the exact feature branch HEAD before merging.
