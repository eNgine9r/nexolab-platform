# M3 validation evidence

> Copy this file for each controlled acceptance run. Use UTC timestamps. Do not include passwords, `.env` contents, tokens, private keys or unrestricted network addresses.

## Run identity

| Field | Value |
| --- | --- |
| Validation ID | `M3-YYYYMMDD-NN` |
| Date | `YYYY-MM-DD` |
| Start UTC | `YYYY-MM-DDTHH:MM:SSZ` |
| Completion UTC | `YYYY-MM-DDTHH:MM:SSZ` |
| Operator | `<name>` |
| Reviewer | `<name>` |
| Repository revision | `<git rev-parse HEAD>` |
| Central host role | `<hostname / asset ID>` |
| Edge host role | `edge-01` |
| Dashboard host role | `<hostname / deployment ID>` |

## Approved production scope

- [ ] node is `edge-01`;
- [ ] XJP60D channels are `106-03`, `106-04`;
- [ ] LE-01MP units are `200`, `201`, `202`, `203`;
- [ ] expected latest series count is 34;
- [ ] MQTT topic is `nexolab/telemetry`;
- [ ] Modbus operations remain read-only;
- [ ] stable adapter path uses `/dev/serial/by-id/...`.

## Network boundary

| Item | Evidence |
| --- | --- |
| Central bind address classification | `loopback / trusted LAN / IoT VLAN / VPN` |
| Central MQTT port | `1884` |
| Central API port | `8082` |
| PostgreSQL published to host | `No` |
| Public port forwarding | `No` |
| CORS dashboard origin | `<origin without credentials>` |

Security confirmation:

- [ ] no `0.0.0.0` binding on an untrusted network;
- [ ] anonymous MQTT remains inside the approved pilot boundary;
- [ ] no secret values are present in this evidence document.

## Pre-deployment state

### Repository

```text
<paste git status --short>
<paste git rev-parse HEAD>
```

- [ ] working tree was clean;
- [ ] revision matched the approved release/commit.

### Edge health before cutover

Evidence file: `<runtime/evidence/.../edge-health-before.json>`

| Check | Result |
| --- | --- |
| Health HTTP status | `<200>` |
| Device mode | `<modbus>` |
| Last error | `<null / value>` |
| Queue depth | `<value>` |
| Device Agent container ID | `<container ID>` |

### Central readiness before cutover

Evidence file: `<runtime/evidence/.../central-ready-before.json>`

| Check | Result |
| --- | --- |
| `status` | `<ready>` |
| `database` | `<ready>` |
| `mqtt` | `<ready>` |
| Migration exit code | `<0>` |
| PostgreSQL volume | `<present>` |
| MQTT volume | `<present>` |

## Cutover execution

Command:

```bash
bash m3-cutover.sh .env.edge-central
```

Evidence directory: `<runtime/evidence/m3-cutover-...>`

| Check | Result |
| --- | --- |
| Cutover script exit code | `<0>` |
| Start UTC | `<timestamp>` |
| Completion UTC | `<timestamp>` |
| Device Agent container ID before | `<ID>` |
| Device Agent container ID after | `<ID>` |
| Container ID preserved | `<true>` |
| Modbus mode preserved | `<true>` |
| Edge broker recovered | `<true>` |
| Bridge connection observed | `<true / evidence>` |

## Telemetry validation

Evidence file: `<telemetry-validation.json>`

### Latest REST

| Check | Expected | Actual |
| --- | ---: | ---: |
| Production unique series | 34 | `<value>` |
| XJP60D `106-03` present | yes | `<yes/no>` |
| XJP60D `106-04` present | yes | `<yes/no>` |
| LE-01MP 200 series | 8 | `<value>` |
| LE-01MP 201 series | 8 | `<value>` |
| LE-01MP 202 series | 8 | `<value>` |
| LE-01MP 203 series | 8 | `<value>` |
| Oldest sample age | `≤ configured limit` | `<seconds>` |

Quality counts:

```json
<paste quality_counts>
```

Alarm counts:

```json
<paste alarm_counts>
```

- [ ] valid records contain numeric values;
- [ ] error records may contain `value=null` without fabricated data;
- [ ] units match the physical metrics;
- [ ] timestamps are timezone-aware UTC;
- [ ] future-dated records are not presented as live.

### History REST

| Check | Result |
| --- | --- |
| Recent history HTTP status | `<200>` |
| Recent history count | `<value>` |
| Earliest captured UTC | `<timestamp>` |
| Latest captured UTC | `<timestamp>` |

### WebSocket

| Check | Result |
| --- | --- |
| Handshake | `<passed>` |
| Newly committed event ID | `<event_id>` |
| Event captured UTC | `<timestamp>` |
| Equipment | `<equipment_id>` |
| Channel | `<channel_id>` |
| Metric | `<metric>` |
| Quality | `<quality>` |
| Alarm | `<alarm/null>` |

- [ ] WebSocket event was not already present in the initial REST snapshot;
- [ ] dashboard updated without full-page reload.

## Dashboard acceptance

Dashboard mode: `<live>`

- [ ] explicit `live` mode configured;
- [ ] API URL configured;
- [ ] WebSocket URL configured;
- [ ] state progressed from `connecting` to `live`;
- [ ] freshness timestamp matched committed telemetry;
- [ ] `edge-01` displayed as the production node;
- [ ] XJP60D values matched REST records;
- [ ] LE-01MP power matched REST records and unit normalization;
- [ ] quality errors remained visible;
- [ ] alarm states remained visible;
- [ ] no demo KPI or demo chart appeared during a live transport failure.

Screenshots or screen recording references:

```text
<artifact names / secure storage references>
```

## Incident drills

### Central MQTT outage

| Field | Evidence |
| --- | --- |
| Stop UTC | `<timestamp>` |
| Central readiness state | `<mqtt=not_ready>` |
| Database readiness | `<ready>` |
| Edge Modbus mode | `<modbus>` |
| Dashboard state | `<reconnecting/stale/offline>` |
| Demo fallback observed | `<no>` |
| Restore UTC | `<timestamp>` |
| Recovery validation evidence | `<path>` |

- [ ] local edge acquisition continued;
- [ ] bridge reconnect was observed;
- [ ] fresh telemetry resumed after recovery.

### PostgreSQL outage

| Field | Evidence |
| --- | --- |
| Stop UTC | `<timestamp>` |
| Central readiness state | `<database=not_ready>` |
| Queue size maximum | `<value>` |
| Database retry counter delta | `<value>` |
| Device Agent restarted | `<no>` |
| Restore UTC | `<timestamp>` |
| Database recovery counter delta | `<value>` |
| Queue drained | `<yes>` |

- [ ] Telemetry Service was not restarted while PostgreSQL was down;
- [ ] fresh 34-series validation passed after recovery.

### WebSocket/backend restart

| Field | Evidence |
| --- | --- |
| Restart UTC | `<timestamp>` |
| Dashboard state during restart | `<reconnecting>` |
| Resume cursor | `<captured_at>` |
| Duplicate UI series observed | `<no>` |
| Return to live UTC | `<timestamp>` |
| New event ID | `<event_id>` |

### Duplicate suppression

| Layer | Evidence |
| --- | --- |
| PostgreSQL duplicate `event_id` rejected/idempotent | `<test or observation>` |
| Frontend repeated `event_id` ignored | `<test or observation>` |
| UI series count before | `<value>` |
| UI series count after duplicate | `<same value>` |

## Restart persistence

History query interval:

```text
from=<UTC>
to=<UTC>
```

| Check | Before restart | After restart |
| --- | ---: | ---: |
| History count | `<value>` | `<value>` |
| Known event ID present | `<yes>` | `<yes>` |
| PostgreSQL volume ID | `<ID>` | `<same ID>` |

- [ ] historical records survived backend/PostgreSQL restart;
- [ ] no volume deletion occurred.

## Backup and restore drill

| Field | Evidence |
| --- | --- |
| Backup file | `<secure path>` |
| Backup UTC | `<timestamp>` |
| Backup size | `<bytes>` |
| Restore test database | `<name>` |
| Telemetry row count | `<value>` |
| Dead-letter row count | `<value>` |
| Restore result | `<passed>` |
| Test database removed | `<yes>` |

## Rollback

### Edge bridge rollback

Command:

```bash
bash m3-edge-rollback.sh .env.edge-central
```

Evidence directory: `<runtime/evidence/m3-rollback-...>`

- [ ] bridge override inactive;
- [ ] Device Agent container ID preserved;
- [ ] Modbus mode preserved;
- [ ] local edge broker healthy;
- [ ] no volumes deleted.

### Central stop

Command:

```bash
bash m3-central-stop.sh .env.central
```

Evidence directory: `<runtime/evidence/m3-central-stop-...>`

- [ ] central services stopped;
- [ ] `nexolab-central-postgres-data` present;
- [ ] `nexolab-central-mqtt-data` present;
- [ ] `down -v` was not used.

### Dashboard state after rollback

Selected mode: `<demo / live-offline>`

Reason:

```text
<operator decision>
```

- [ ] mode was changed explicitly;
- [ ] no silent fallback occurred.

## Deviations and known issues

| ID | Observation | Impact | Owner | Disposition |
| --- | --- | --- | --- | --- |
| `M3-D01` | `<description>` | `<impact>` | `<owner>` | `<accepted/fix/block>` |

## Final decision

- [ ] **Accepted** — all mandatory checks passed.
- [ ] **Accepted with documented limitations** — no safety/data-integrity blocker.
- [ ] **Rejected** — rollback completed; issue remains open.

Decision rationale:

```text
<summary>
```

Operator signature/date: `<name / UTC>`

Reviewer signature/date: `<name / UTC>`
