# Live Dashboard canonical channel inventory

Updated: 2026-08-06
Issue: #355
Pull Request: #358
Implementation evidence head: `a0b4c2c9af064ea5e50ac0b53ae77092935446fd`
Profile: `LOCAL_LAN`

## Product defect removed

The Live Dashboard editor previously derived its selectable channel catalog from paginated `/api/v1/telemetry/latest` responses. That coupled editor discovery to telemetry-history volume, excluded active channels without samples and allowed a long-running PostgreSQL database to exceed the existing 8-second client timeout.

The editor now reads one organization-scoped canonical catalog endpoint:

```text
GET /api/v1/live-dashboards/channel-inventory?limit=500&offset=0
```

The endpoint is independent of telemetry-history pagination. It returns deterministic catalog pages and optionally attaches one latest sample through the existing full-identity index.

## Canonical eligibility

Inventory visibility and Live Dashboard save validation use the same eligibility boundary:

- authenticated principal organization matches the channel organization;
- measurement channel status is `active`;
- measurement device status is `active`;
- measurement bus status is `active`;
- climate chamber status is `active`;
- central node state is not `revoked`.

The endpoint requires `dashboard.read`. Cross-organization, inactive and revoked-node channels are excluded. Save validation continues to reject stale or unknown channel references.

## Response and pagination contract

- maximum page size: `500`;
- maximum offset: `10,000`;
- deterministic order: node, equipment, channel, metric, channel reference;
- no-sample channels remain present with:
  - `latest: null`;
  - `quality: unknown`;
  - `alarm: null`;
- no quality, alarm or telemetry value is fabricated;
- the frontend fails closed if pagination does not advance or exceeds the bounded 10,000-channel window.

## Latest metadata lookup

Latest metadata is optional and uses the complete telemetry identity:

```text
node_id + equipment_id + channel_id + metric
```

The correlated lookup orders by `captured_at DESC, event_id DESC` and uses the existing PostgreSQL index:

```text
ix_telemetry_latest_lookup
```

The catalog is the driving relation. Telemetry history is never the source of channel discovery.

## PostgreSQL evidence

Exact query-plan evidence was captured in the Telemetry Service workflow on implementation head `a0b4c2c9af064ea5e50ac0b53ae77092935446fd`.

Fixture and results:

| Evidence | Result |
| --- | ---: |
| Canonical catalog channels | 2 |
| Telemetry fixture rows | 50,003 |
| `EXPLAIN ANALYZE` execution | 0.363 ms |
| Complete repository call | 13.085 ms |
| Client timeout boundary | 8,000 ms |
| Latest lookup index | `ix_telemetry_latest_lookup` |

The fixture contained 50,000 unrelated telemetry samples, three samples for one eligible catalog channel and one eligible catalog channel with no sample. The latest sampled channel returned the newest value and alarm; the no-sample channel remained visible.

This proves the software query path is bounded on PostgreSQL and does not approach the existing client timeout under the acceptance fixture. It does not replace physical Raspberry Pi timing evidence.

## Browser evidence

Authenticated Dashboard Acceptance workflow run `31088731853` passed on the exact implementation head.

Artifact:

```text
authenticated-dashboard-acceptance-31088731853-1
sha256:08b093534b08e52efb684af4f9b088fe1e263c9e7e8bcedc5ff216498c69ae7e
```

The editor evidence recorded:

- one GET for the Dashboard library;
- one GET for `/api/v1/live-dashboards/channel-inventory`;
- zero `/api/v1/telemetry/*` requests while opening and using the editor catalog;
- zero Device Agent, discovery or configuration mutations;
- a canonical channel with no telemetry sample displayed as unknown quality and no alarm;
- the no-sample channel was added successfully and selection changed to `1 / 64`.

Permanent artifact files include:

- `live-dashboard-no-sample-editor.png`;
- `live-dashboard-inventory-summary.json`;
- `live-dashboard-summary.json`.

The no-sample editor screenshot SHA-256 is:

```text
35971ef0b9881b2d383b14783b209447e15f2552290cfb65626f6bed6dc4b528
```

## Selected-series behavior preserved

Opening a saved Dashboard still uses only its selected channel identity:

```text
GET /api/v1/telemetry/latest?channel_id=106-03&metric=temperature.probe&limit=1&offset=0
GET /api/v1/telemetry/history?channel_id=106-03&metric=temperature.probe&...
```

Browser evidence confirmed:

- only selected-series latest/history requests;
- WebSocket maximum active connections per page: `1`;
- zero acquisition/configuration mutations;
- persisted Dashboard remained available after Telemetry Service restart.

Display refresh and time-window settings remain presentation/read-model concerns and do not change acquisition scheduler or Modbus cadence.

## Runtime and offline impact

- no new dependency or external service;
- no CDN, remote font, telemetry vendor or cloud API;
- no schema migration;
- no telemetry-history deletion or truncation;
- no acquisition registry, scheduler or physical polling change;
- no Modbus write or hardware action;
- Offline Auth and Offline Bundle remain required merge gates.

## Rollback

Rollback is code-only:

1. restore the previous frontend inventory hook and adapter path;
2. remove the channel-inventory API route, schemas and query module;
3. restore the previous frontend inventory types and client surface;
4. rerun CI, Telemetry Service, Authenticated Dashboard Acceptance and Offline Bundle.

No database rollback or data mutation is required because Issue #355 adds no migration.

## Completion classification

```text
software verified; Raspberry Pi runtime latency acceptance pending
```

Physical acceptance requires retesting the affected Raspberry Pi LOCAL_LAN runtime with its real long-running database. Until that evidence is captured, no claim of Raspberry Pi latency acceptance is made.
