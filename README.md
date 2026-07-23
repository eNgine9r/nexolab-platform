# NEXOLAB Platform

**NEXOLAB** — industrial IoT-платформа для лабораторного моніторингу, холодильного обладнання та smart locker infrastructure.

Поточний production slice замикає реальний маршрут:

```text
XJP60D 106-03, 106-04 + LE-01MP 200–203
                  ↓
        edge-01 Device Agent
                  ↓ MQTT QoS 1
        Central Telemetry Service
                  ↓
              PostgreSQL
                  ↓
       REST latest/history + WebSocket
                  ↓
          NEXOLAB Dashboard
```

Повний цикл містить **34 telemetry records**. Edge-вузол працює offline-first: Modbus polling і локальна SQLite outbox не залежать від доступності central backend або dashboard.

## Технології

- Next.js 16 App Router
- React 19
- TypeScript
- Tailwind CSS 4
- FastAPI
- PostgreSQL 16
- Eclipse Mosquitto
- SQLAlchemy + Alembic
- Docker Compose
- Vitest + Testing Library
- Pytest
- ESLint + Prettier
- GitHub Actions + Dependabot

## Frontend quick start

```bash
nvm use
npm install
npm run dev
```

Відкрийте `http://localhost:3000`.

### Demo mode

```dotenv
NEXT_PUBLIC_NEXOLAB_DATA_MODE=demo
```

### Live mode

```dotenv
NEXT_PUBLIC_NEXOLAB_DATA_MODE=live
NEXT_PUBLIC_NEXOLAB_API_BASE_URL=http://<trusted-central-host>:8082
NEXT_PUBLIC_NEXOLAB_WEBSOCKET_URL=ws://<trusted-central-host>:8082/api/v1/telemetry/live
```

Live mode має явні `connecting`, `live`, `reconnecting`, `stale`, `offline` та `error` states і ніколи не підміняє недоступний backend demo-даними.

## M3 deployment and operations

Canonical operator entry point:

[`docs/operations/m3-operator-runbook.md`](docs/operations/m3-operator-runbook.md)

Supporting procedures:

- controlled central deployment: [`docs/operations/central-deployment.md`](docs/operations/central-deployment.md);
- edge-to-dashboard cutover and rollback: [`docs/operations/m3-cutover-validation.md`](docs/operations/m3-cutover-validation.md);
- backend incidents, retention, backup and restore: [`docs/operations/telemetry-backend-runbook.md`](docs/operations/telemetry-backend-runbook.md);
- acceptance evidence template: [`docs/operations/m3-validation-evidence-template.md`](docs/operations/m3-validation-evidence-template.md).

Read-only status bundle:

```bash
cd infrastructure/compose
bash m3-status.sh .env.central
```

Controlled cutover on `edge-01`:

```bash
bash m3-cutover.sh .env.edge-central
```

The cutover recreates only local Mosquitto with an outgoing persistent bridge. It proves that the `device-agent` container and `DEVICE_MODE=modbus` remain unchanged.

## Edge-контур Raspberry Pi

Edge stack includes:

- XJP60D and LE-01MP read-only Modbus drivers;
- sequential combined polling;
- local SQLite offline queue;
- MQTT QoS 1 publishing;
- health and readiness endpoints;
- Docker Compose hardware override;
- Ansible provisioning;
- `linux/arm64` image delivery.

Production hardware launch:

```bash
cd infrastructure/compose

docker compose \
  --env-file .env.edge \
  -f compose.edge.yaml \
  -f compose.hardware.yaml \
  up -d device-agent

curl -fsS http://127.0.0.1:8081/health \
  | python3 -m json.tool
```

The serial adapter must use a stable `/dev/serial/by-id/...` path. No production path permits Modbus writes.

Full Edge instructions: [`docs/edge-bootstrap.md`](docs/edge-bootstrap.md).

## RS-485 discovery

The read-only scanner enumerates baud rate, parity, stop bits and unit IDs, validates CRC and standard Device Identification, and records evidence without write functions.

```bash
python tools/rs485_discovery/scan_rs485.py \
  --port /dev/serial/by-id/<adapter> \
  --quick \
  --deep \
  --progress
```

Instructions and safety constraints: [`tools/rs485_discovery/README.md`](tools/rs485_discovery/README.md).

## Quality gates

Frontend:

```bash
npm run format:check
npm run lint
npm run typecheck
npm test
npm run build
```

Telemetry Service:

```bash
cd services/telemetry-service
python -m pip install -r requirements-dev.txt
python -m compileall -q app tests migrations
python -m pytest -q
```

Deployment contracts are additionally validated in GitHub Actions through shell syntax checks, Python compilation and `docker compose config --quiet`.

## Repository structure

```text
src/
├── app/                       # Next.js App Router and global UI
├── components/dashboard/      # Operational dashboard components
├── data/                      # Isolated demo-only data
├── hooks/                     # Live dashboard state integration
└── lib/telemetry/             # Typed REST/WebSocket adapter and state model

services/
├── device-agent/              # Modbus, SQLite outbox, MQTT and health
└── telemetry-service/         # Ingestion, PostgreSQL, REST, WebSocket and metrics

infrastructure/
├── compose/                   # Edge, central, bridge, validation and rollback profiles
├── observability/             # Prometheus alert rules
└── ansible/                   # Raspberry Pi provisioning

tools/
└── rs485_discovery/           # Read-only Modbus discovery and profiling

docs/
├── adr/                       # Architecture decisions
├── operations/                # Deployment, incidents, cutover and evidence
├── architecture.md
├── design-system.md
└── edge-bootstrap.md
```

## Архітектурні принципи

- Offline-first acquisition: edge polling does not depend on cloud or central services.
- Server Components by default; Client Components only where interaction is required.
- Explicit `demo` and `live` runtime modes.
- Stable typed REST/WebSocket contract with runtime payload validation.
- Newest `captured_at` wins; repeated `event_id` values are deduplicated.
- Stale records are never presented as live.
- Critical states include text and icon indicators, not color alone.
- PostgreSQL migrations complete before application readiness.
- Central PostgreSQL is not published to the host.
- Persistent volumes survive container recreation and rollback.
- MQTT, PostgreSQL, backend and WebSocket failures are diagnosed independently.
- No operational script uses `docker compose down -v`.
- No discovery, deployment or dashboard procedure performs Modbus writes.

## Current milestone boundary

Repository implementation is complete for:

- controlled central deployment contract;
- typed frontend telemetry adapter;
- live operational dashboard state;
- reversible edge-to-central MQTT cutover;
- operator runbooks and evidence tooling.

M3 operational acceptance still requires execution on real `edge-01` and the controlled central host, including outage, persistence, backup/restore and rollback evidence.

## Ліцензування

Ліцензію проєкту ще не визначено. До додавання `LICENSE` усі права зберігаються за власником репозиторію.
