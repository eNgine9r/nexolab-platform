# NEXOLAB #1474 — Digest-bound optional LAN monitor source bundle

## Verified reason for this Work Package

The local NEXOLAB Dashboard and Session API are reachable through the laboratory
LAN, but the merged #1468/1472 LAN probe and alerting code has not been installed
on the Raspberry Pi. The existing offline bundle builder did not stage the probe,
the numeric collector, optional Prometheus rules or systemd templates.

The accepted Pi runtime source is ffdefc4550d71e211724de1154ffe9057f905c9c,
which differs from main. The systemd template references a future
/opt/nexolab/current source directory which is NOT present on the site.
Bundling alone does not install this path or activate a service.

## Build scope — explicit opt-in only

The existing offline bundle builder accepts an optional, off-by-default flag:
--include-lan-monitor-sources

It stages exactly these source-only files into the package:

- infrastructure/offline/inspect-site-lan-access.py
- infrastructure/offline/emit-lan-access-prometheus.py
- infrastructure/systemd/nexolab-lan-access-probe.service
- infrastructure/systemd/nexolab-lan-access-probe.timer
- infrastructure/observability/prometheus/optional-rules/lan-access-alerts.yml

No secret files, environment, tokens, source credentials, site telemetry or
production data are included. The usual file manifest includes a SHA256 and size
record for each staged source. The optional immutable provenance capability
lan-access-monitor-source-only is declared only when the source flag is selected.
The verification step requires the exact all-or-none allowlist and rejects
unclaimed, missing, symlinked or unbound sources. Previous default bundles remain
backwards compatible and do not include this optional payload.

A separately approved build operator must still supply the exact compatible
source SHA, Linux ARM64 platform, approved LAN origins, local auth mode and
verified schema compatibility. This source-only Work Package does NOT generate
or deploy an actual production release.

## Hard limits and next acceptance gate

This adds digest-bound source assets, not an installed host service, a new
privileged release path, a timer, a Prometheus rule activation or a restart.
The source unit still references /opt/nexolab/current; that path must later be
mapped to an immutable, readable release by a separate protected installation
Work Package before any actual service activation.

The future owner-approved site acceptance must preserve the private host bind
/home/nexolab/nexolab-platform/runtime/observability and existing historical
disaster-recovery.prom single-file mode. Verify the exporter supports the
optional directory mode in the accepted runtime, that a non-root service can
read exact release scripts and write numeric-only metrics, and that local
Prometheus alerts actually FIRE and RESOLVE in the on-premises audit sink.

The site has an inherited physical LAN 172.18.48.0/21 / Edge Docker
172.18.0.0/16 route overlap (#1409). The automatic network repair #1399
remains disabled. Physical USB/RS485 read acceptance is still unverified.
No Docker network operation, backup, container restart, data mutation,
Modbus/hardware write, remote service dependency or production cutover is
performed by this source-only change.

Hermetic tests exercise the actual shell staging loop in a temporary
directory and the exact provenance/hash-manifest inventory contract.
Full offline bundle integration and GitHub CI remain required for merge.

## Exact GitHub offline verification routing

The single new source test path is explicitly registered with the
fail-closed CI impact classifier and the Offline Bundle GitHub workflow
trigger. This is a narrow exact-path rule, not a wildcard exception or a
change to the required workflow policy. Tests verify that the payload file
requires Offline Bundle while an unrelated unknown script still fails closed.
Because this change also modifies CI governance, the branch correctly
requires the normal browser acceptance workflows and final Merge Gate.
