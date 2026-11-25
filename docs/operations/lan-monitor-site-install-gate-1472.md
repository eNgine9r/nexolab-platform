# NEXOLAB #1472 — Protected offline LAN alert installation gate

## Verified site baseline, 2026-11-03

Original LOCAL_LAN Dashboard at http://172.18.48.66:3000 works and the read-only five-check Session API probe passes. The new #1468 source-only collector and optional alert rules were merged at commit 4f0923c0a4c7aa7f89a09a3309e0b13141dc7302 with 7/7 GitHub GREEN, but are NOT installed as an active systemd service or enabled Prometheus alert rules on the Raspberry.

The accepted protected installed package is still source ffdefc4550d71e211724de1154ffe9057f905c9c, not the current source branch. Neither this document nor the source checker approves a site cutover or silently installs code.

The installed observability textfile exporter has a read-only bind:

- Host: /home/nexolab/nexolab-platform/runtime/observability
- Container: /var/lib/nexolab-observability
- Current single-file mode: /var/lib/nexolab-observability/disaster-recovery.prom
- Host directory owned by nexolab, mode 0700; legacy file mode 0600, already populated

The original #1468 systemd unit incorrectly targeted the container-only path on the host. This #1472 source revision corrects the output to the ACTUAL host bind /home/nexolab/nexolab-platform/runtime/observability/lan-access.prom. The unit keeps unprivileged nexolab identity, ProtectSystem=strict, NoNewPrivileges, PrivateDevices, ProtectHome=read-only with just one exact ReadWritePaths exception. The corrected service and timer are SOURCE-ONLY, not installed.

## Read-only preflight

Run from the engineering checkout on an authorized Pi:

    sudo -n python3 -I -B infrastructure/offline/inspect-lan-monitor-install-readiness.py --check --required-source-commit 4f0923c0a4c7aa7f89a09a3309e0b13141dc7302

The requested hash above is an example of a source merge, NOT the accepted installed site release. The checker validates the immutable installed bundle authority, exact accepted source, protected update locks, Docker exporter Compose identity, exact host and script mounts both read-only, existing single-file mode, local file ownership/permissions, no symlinks, source template identity, absent unreviewed timer and absent premature optional alert rules.

Its response always returns BLOCKED / exit 78. There is no execute mode. Even after a future accepted release matches the requested source, it still requires separate operator-reviewed source installation, rollback and physical site acceptance. It does not log credentials, raw HTTP responses, or sensor values.

## Protected future site activation conditions

1. Build, pin and validate a local offline ARM64 package containing the #1468 collector and corrected #1472 unit, through the existing NEXOLAB immutable release authority. Do not copy scripts from development worktrees into production.
2. Verify the nexolab system user can write the exact host directory under the unit sandbox. Keep the preexisting disaster-recovery.prom file intact and retain an exact rollback to its single-file input.
3. Verify the installed exporter source supports directory mode before switching its setting in a separate protected release. Do not restart the telemetry data plane or make an unreviewed Docker network change.
4. Install the probe timer disabled, verify real localhost/LAN probe metrics and local Prometheus scrape, THEN enable optional alert rules. Never enable a missing-probe alert before the probe has first reported safely.
5. Prove FIRING and RESOLVED to the existing offline local Alertmanager audit sink using isolated source fixture; verify missing probe and stale data alarms. Demonstrate operator-approved rollback without lost historical DR metrics.
6. A separately approved site activation and real boot test is required. Do not run Modbus/hardware writes, recreate containers, change Edge Docker IPAM or claim full hardware acceptance from a software-only test.

The Edge Docker physical LAN CIDR overlap (#1409), protected automatic boot recovery (#1399) and degraded physical RS485 acceptance (#1429) remain separate work and are not solved by source-only local alerts.
