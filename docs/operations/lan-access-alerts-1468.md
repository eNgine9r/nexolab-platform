# NEXOLAB #1468 — Offline LAN Dashboard and Session API alerting (source only)

## Product outcome

During the 3 November outage, NEXOLAB Dashboard port 3000 disappeared and
a separate frontend reported `SESSION_API_UNREACHABLE_OR_ORIGIN_BLOCKED`,
even though local PostgreSQL could still be healthy. After the earlier
restoration, source #1466 verifies the original local dashboard, login HTML,
API readiness, expected unauthenticated HTTP 401, and exact LAN CORS.

This Work Package adds a **source-only** local exporter and alert rules
for those five checks, using existing Prometheus/Alertmanager. No
external API, cloud, paid runtime service, new container image, live
Docker network change, credentials or hardware/Modbus write is needed.

**This source release does NOT install, enable or run an automatic
systemd probe on the production Raspberry Pi.** It does not auto-repair
networks. The physical Edge Docker CIDR/LAN collision and actual boot
hardware acceptance remain separate hard blockers #1409/#1399.

## Read-only collection

The unprivileged collector source is
`infrastructure/offline/emit-lan-access-prometheus.py`. It invokes the
fixed-path read-only #1466 probe, evaluates the five exact LAN checks
and writes **numeric-only** Prometheus metrics with an atomic
temporary-file replacement.

Example isolated test, not an activation command:

    mkdir -p /tmp/nexolab-lan-test
    python3 -I -B infrastructure/offline/emit-lan-access-prometheus.py \
      --host 172.18.48.66 --output /tmp/nexolab-lan-test/lan-access.prom

The hostname must be a literal private IPv4, with no arbitrary URI,
DNS, redirects, cookies, user sessions, passwords or login attempts.
The only output file name permitted is `lan-access.prom`. It has a
single Unix timestamp metric; five 0/1 gauges for the checks; and
an overall 0/1 check. No response bodies, IPs, hardware names, usernames,
tokens or exception text are used as Prometheus labels.

A known negative result writes a 0 to the metrics file so the system
can report the failure. An unexpected output or file security failure
refuses to write, allowing the missing/stale alert to fire.

## Existing exporter backward compatibility

The existing `scripts/serve-prometheus-textfile.py` still defaults to
the single `disaster-recovery.prom` file. Only an explicit,
separately approved `NEXOLAB_TEXTFILE_PATH=/var/lib/nexolab-observability`
setting enables directory mode. Directory mode reads at most
32 source-checked `.prom` regular files with strict names, a combined
1 MiB bound, no nested traversal, and safe no-follow file descriptors.
Any unsafe file blocks the entire scrape, rather than silently
dropping a missing or manipulated status.

The existing Docker Compose bind mount of the host observability
directory remains read-only. The optional LAN collector must write to
the **same actual host directory** bound to
`/var/lib/nexolab-observability` in the exporter. Source units use
`/var/lib/nexolab-observability` on the host as an illustrative
protected installation path; this must be mapped, owned and accepted
before activation. Never redirect output into a PostgreSQL/SQLite
persistent volume or a credentials directory.

## Optional service and alert rules — NOT ACTIVE

Two systemd **templates** are included:

- `infrastructure/systemd/nexolab-lan-access-probe.service`;
- `infrastructure/systemd/nexolab-lan-access-probe.timer`.

They specify an unprivileged `nexolab` account, private devices,
strict read-only filesystem restrictions except the metrics directory,
no additional Linux capabilities, a bounded 25-second run and a
one-minute scheduled check. They require a separately approved
`/etc/nexolab/lan-access-probe.env` file with a verified literal
`NEXOLAB_LAN_IPV4`, plus an installed source-verified
`/opt/nexolab/current` path. **Neither path or unit is assumed to be
installed or enabled on the production Pi.** Do not activate these
templates by copying them directly without a protected release/volume
mapping and tested rollback.

The new
`infrastructure/observability/prometheus/optional-rules/lan-access-alerts.yml`
is deliberately outside Prometheus's loaded
`/etc/prometheus/rules/*.yml` glob. It must not be enabled until
the collector actually runs and metrics are being scraped. Otherwise
the missing-probe alert would generate a false incident before site
activation. Once separately installed, the existing local
Alertmanager webhook sends FIRING/RESOLVED alerts to the existing
on-premises audit sink; no internet is required.

The five optional alerts cover:

1. Missing/stale probe timestamp (over 180 s).
2. Overall LAN access chain failure.
3. Dashboard HTTP/HTML failure.
4. Login HTML or API/database/MQTT readiness failure.
5. Unexpected Session API 401 or exact LAN CORS change.

## Actual source/isolated acceptance

The native Raspberry Pi source tests include 18 hermetic exporter,
safe-directory and systemd/rule contract cases, plus existing #1466
positive/negative local probe tests. Prometheus `promtool check rules`
passed the five optional alerts. An isolated native ARM64 `promtool
test rules` fixture confirmed that a Dashboard failure becomes FIRING
after the configured duration and RESOLVED after recovery, and that
missing metrics trigger the absence alarm.

The source-only collector was executed against the actual LAN entry
path and wrote only to an owner-private temporary **test** directory,
not the installed observability directory. It reported
`LOCAL_LAN_AUTH_PATH_REACHABLE` and wrote seven numeric metric families.

**Hardware remains unverified**: MQTT/DB and Dashboard readiness do
not prove fresh real readings or surviving RS-485 physical devices.
The overlapping Edge Docker bridge #1409 prevents activation of the
separate guarded site auto-repair #1399 until real cutover evidence exists.
