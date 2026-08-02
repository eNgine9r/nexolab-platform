# NEXOLAB production observability runbook

## Scope

This runbook covers the software observability boundary for the NEXOLAB central platform:

```text
Telemetry Service + MQTT + PostgreSQL + DR status
                         ↓
                   Prometheus
                         ↓
            recording rules and alerts
                         ↓
                   Alertmanager
                         ↓
          local audit sink / operator route
                         ↓
             provisioned Grafana dashboard
```

The stack is designed for local, offline-first operation. Prometheus, Alertmanager and Grafana bind to loopback by default. Raspberry Pi hardware, RS-485 devices, Tailscale, public DNS, external notification credentials and the actual central host are not required for the software acceptance Gate.

## Pinned components

| Component    | Image                       | Purpose                             |
| ------------ | --------------------------- | ----------------------------------- |
| Prometheus   | `prom/prometheus:v3.13.0`   | scrape, recording rules and alerts  |
| Alertmanager | `prom/alertmanager:v0.32.1` | grouping, inhibition and delivery   |
| Grafana      | `grafana/grafana:13.1.0`    | provisioned operator dashboard      |
| Alert sink   | `python:3.13-alpine`        | local append-only delivery evidence |
| DR exporter  | `python:3.13-alpine`        | safe Prometheus textfile bridge     |

Image versions are policy-validated. `latest` tags are not accepted.

## Security defaults

- Operator ports bind to `127.0.0.1` unless `OBSERVABILITY_BIND_ADDRESS` is explicitly changed.
- Grafana anonymous access, self-registration and organization creation are disabled.
- Grafana plugin administration, suggested plugin preinstallation and plugin auto-update are disabled.
- Grafana credentials must be supplied through runtime environment or an external secret system.
- Prometheus and Alertmanager configurations contain no delivery credentials.
- The default Alertmanager receiver is an internal audit sink; production email, chat and on-call credentials remain an actual-host secret-provisioning task.
- Runtime evidence is scanned for generated credentials and private-key or token patterns.

Do not expose Prometheus, Alertmanager or Grafana directly to the public internet. Use the approved reverse proxy, VPN or secure access layer after the actual-host Gate.

## Start the stack

Create a protected environment file outside version control:

```bash
cd infrastructure/compose
umask 077
cat > .env.observability.local <<'EOF'
POSTGRES_DB=nexolab
POSTGRES_USER=nexolab
POSTGRES_PASSWORD=replace-with-generated-value
MINIO_ROOT_USER=nexolab
MINIO_ROOT_PASSWORD=replace-with-generated-value
GRAFANA_ADMIN_USER=nexolab-admin
GRAFANA_ADMIN_PASSWORD=replace-with-generated-value
OBSERVABILITY_BIND_ADDRESS=127.0.0.1
PROMETHEUS_PORT=9090
ALERTMANAGER_PORT=9093
GRAFANA_PORT=3000
EOF
chmod 0600 .env.observability.local
```

Create the local disaster-recovery textfile directory:

```bash
mkdir -p ../../runtime/observability
chmod 0700 ../../runtime/observability
```

Start central services and observability:

```bash
docker compose \
  --env-file .env.observability.local \
  -f compose.central.yaml \
  -f compose.observability.yaml \
  up -d --build
```

Inspect container state:

```bash
docker compose \
  --env-file .env.observability.local \
  -f compose.central.yaml \
  -f compose.observability.yaml \
  ps
```

## Operator endpoints

Default local endpoints:

| Service      | Endpoint                        |
| ------------ | ------------------------------- |
| Telemetry    | `http://127.0.0.1:8082/metrics` |
| Prometheus   | `http://127.0.0.1:9090`         |
| Alertmanager | `http://127.0.0.1:9093`         |
| Grafana      | `http://127.0.0.1:3000`         |

Grafana provisions:

- datasource UID: `nexolab-prometheus`;
- dashboard UID: `nexolab-platform-overview`;
- folder UID: `nexolab`;
- dashboard title: `NEXOLAB · Platform Operations`.

The dashboard is versioned and not editable through the normal UI workflow.

## Metrics contract

### Platform readiness

- `up{job="telemetry-service"}`;
- `nexolab_telemetry_mqtt_connected`;
- `nexolab_telemetry_database_ready`;
- `nexolab:platform_dependency_ready`.

### Ingestion and durability

- `nexolab_telemetry_received_total`;
- `nexolab_telemetry_accepted_total`;
- `nexolab_telemetry_persisted_total`;
- `nexolab_telemetry_duplicate_total`;
- `nexolab_telemetry_rejected_total`;
- `nexolab_telemetry_persistence_failure_total`;
- `nexolab_telemetry_database_retry_total`;
- `nexolab_telemetry_dead_letter_persisted_total`.

### Capacity and latency

- `nexolab_telemetry_queue_size`;
- `nexolab_telemetry_queue_capacity`;
- `nexolab:ingestion_queue_utilization_ratio`;
- `nexolab_telemetry_ingestion_lag_seconds`;
- `nexolab:persistence_freshness_age_seconds`.

### Streaming

- `nexolab_telemetry_websocket_clients`;
- `nexolab_telemetry_websocket_slow_consumer_total`;
- `nexolab_telemetry_websocket_send_timeout_total`.

### Release identity

- `nexolab_telemetry_build_info{version="..."} 1`.

The build metric uses one bounded `version` label. Do not add node IDs, event IDs, channels, users, error messages or other unbounded values as labels.

## Initial software SLO policy

These targets are software acceptance values. They are not claims about the final central host, storage, network or alert-delivery provider.

| Signal                         | Warning          | Critical           |
| ------------------------------ | ---------------- | ------------------ |
| Telemetry scrape availability  | policy trend     | down for 1 minute  |
| MQTT subscription              | —                | down for 2 minutes |
| PostgreSQL readiness           | —                | down for 2 minutes |
| Ingestion lag                  | above 30 seconds | above 120 seconds  |
| Queue utilization              | above 70%        | above 90%          |
| Dropped queue work             | —                | any increase       |
| Persistence failures           | any increase     | sustained increase |
| Dead-letter persistence        | any increase     | burst above policy |
| Verified backup age            | above 30 hours   | above 48 hours     |
| Restore rehearsal age          | above 35 days    | —                  |
| Backup destination utilization | —                | above 90%          |
| Alert audit sink               | —                | down for 2 minutes |

## Disaster-recovery metrics bridge

The DR scheduler or backup workflow publishes only status metrics. It must never expose bundle bytes, database dumps, object archives, passwords, keys or manifest contents.

Write metrics to a temporary file and atomically rename it:

```bash
set -Eeuo pipefail
TARGET=runtime/observability/disaster-recovery.prom
TMP="${TARGET}.tmp"
NOW="$(date +%s)"

cat > "$TMP" <<EOF
# HELP nexolab_dr_last_verified_backup_timestamp_seconds Unix timestamp of the newest verified encrypted backup.
# TYPE nexolab_dr_last_verified_backup_timestamp_seconds gauge
nexolab_dr_last_verified_backup_timestamp_seconds $NOW
# HELP nexolab_dr_last_bundle_verification_success Whether the newest bundle passed verification.
# TYPE nexolab_dr_last_bundle_verification_success gauge
nexolab_dr_last_bundle_verification_success 1
EOF

chmod 0600 "$TMP"
mv -f "$TMP" "$TARGET"
```

Required production signals are:

- newest verified backup timestamp;
- newest off-host copy timestamp;
- newest restore rehearsal timestamp;
- newest bundle verification status;
- backup and restore durations;
- backup destination free and capacity bytes.

## Alert lifecycle

Alertmanager groups by `alertname`, `service` and `severity`. A critical alert inhibits the corresponding warning alert for the same service and SLO. Resolved notifications are mandatory.

The internal audit sink records normalized alert batches at:

```text
/var/lib/nexolab-alerts/events.jsonl
```

Inspect local delivery evidence:

```bash
docker compose \
  --env-file infrastructure/compose/.env.observability.local \
  -f infrastructure/compose/compose.central.yaml \
  -f infrastructure/compose/compose.observability.yaml \
  exec -T observability-alert-sink \
  python -c 'import urllib.request; print(urllib.request.urlopen("http://127.0.0.1:8080/events").read().decode())'
```

The audit sink is not the final paging destination. Configure real receivers only through the approved secret system and retain the local receiver as delivery evidence.

## Configuration validation

Run the repository policy and unit tests:

```bash
python scripts/validate-observability.py
python -m pytest -q tests/test_observability_policy.py
```

Validate Prometheus:

```bash
docker run --rm \
  --entrypoint /bin/promtool \
  -v "$PWD/infrastructure/observability/prometheus:/etc/prometheus:ro" \
  prom/prometheus:v3.13.0 \
  check config /etc/prometheus/prometheus.yml
```

Validate Alertmanager:

```bash
docker run --rm \
  --entrypoint /bin/amtool \
  -v "$PWD/infrastructure/observability/alertmanager:/etc/alertmanager:ro" \
  prom/alertmanager:v0.32.1 \
  check-config /etc/alertmanager/alertmanager.yml
```

Run the complete software acceptance:

```bash
bash scripts/run-observability-acceptance.sh
```

The GitHub Actions Gate additionally opens Grafana in Chromium and captures readiness, disaster-recovery and alert-delivery screenshots.

## Incident triage

### Telemetry Service target down

1. Check `/health/live` and `/health/ready`.
2. Check PostgreSQL and MQTT container health separately.
3. Inspect Telemetry Service logs for the first failure, not only restart noise.
4. Preserve queue and database state before restarting during a PostgreSQL outage.
5. Verify the alert resolves after the target returns.

### MQTT disconnected

1. Verify broker health and TLS/authentication policy.
2. Check `mqtt_error` and subscription acknowledgement state.
3. Do not restart PostgreSQL for a broker-only incident.
4. Confirm Device Agent queues remain durable.

### PostgreSQL unavailable

1. Restore PostgreSQL before changing queue capacity.
2. Observe retries and queue utilization.
3. Avoid terminating Telemetry Service while uncommitted in-memory work is active.
4. Verify queue drain and duplicate handling after recovery.

### Queue pressure

1. Restore the persistence dependency first.
2. Confirm queue utilization is falling.
3. Investigate database latency, storage latency and ingestion rate.
4. Do not treat a larger queue as the root-cause fix.

### Alert delivery missing

1. Verify Prometheus alert state.
2. Verify Alertmanager readiness and route configuration.
3. Inspect the internal audit sink health and events.
4. Verify grouping and inhibition labels.
5. Test both firing and resolved delivery before closing the incident.

### Grafana dashboard unavailable

1. Verify Grafana health.
2. Verify datasource UID `nexolab-prometheus`.
3. Verify dashboard UID `nexolab-platform-overview`.
4. Check provisioning logs for rejected JSON or missing mounts.
5. Do not edit the provisioned dashboard in place; correct the versioned JSON and redeploy.

## Retention and capacity

Software defaults:

- Prometheus time retention: `15d`;
- Prometheus size limit: `8GB`;
- Alertmanager and Grafana use named local volumes;
- alert audit evidence remains local until a production retention policy is approved.

Actual values must be sized after measuring series count, scrape rate, disk performance and incident-review requirements on the central host.

## Upgrade and rollback

Before upgrading Prometheus, Alertmanager or Grafana:

1. review upstream release and security notes;
2. update the exact image tag;
3. run policy, `promtool`, `amtool`, runtime and Chromium Gates;
4. preserve the previous image digests and configuration commit;
5. verify dashboards and alert delivery before operator cutover.

Rollback restores the previous exact image tags and versioned configuration. Do not roll back Prometheus data directories or Grafana databases in place unless compatibility is confirmed. When compatibility is uncertain, start the previous release against a copied or fresh data volume.

## Actual-host Gate

The following remain deferred until central-host access is available:

- reverse proxy, production TLS and SSO;
- real alert destinations and escalation ownership;
- long-term metrics storage;
- host, container, disk, UPS and network exporters;
- real backup scheduler metrics;
- production retention and capacity sizing;
- off-host monitoring data storage;
- firewall and VLAN verification;
- delivery tests to responsible operators;
- signed operational acceptance.
