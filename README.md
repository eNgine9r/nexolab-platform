# NEXOLAB Platform

**NEXOLAB** — вебінтерфейс industrial IoT-платформи для лабораторного моніторингу, холодильного обладнання та smart locker infrastructure.

Поточний milestone реалізує адаптивну стартову сторінку операційного центру: KPI, edge-вузли, live-телеметрію, активні випробування, тривоги, схему лабораторії та камери.

## Технології

- Next.js 16 App Router
- React 19
- TypeScript
- Tailwind CSS 4
- Lucide icons
- Vitest + Testing Library
- ESLint + Prettier
- Husky + lint-staged + Commitlint
- GitHub Actions + Dependabot

## Швидкий старт

```bash
nvm use
npm install
npm run dev
```

Відкрийте `http://localhost:3000`.

## Edge-контур Raspberry Pi

Перший вертикальний зріз Edge-платформи включає:

- симулятор телеметрії;
- локальну SQLite offline-чергу;
- MQTT broker;
- health endpoint;
- Docker Compose для development і Raspberry Pi;
- Ansible provisioning;
- складання `linux/arm64` image у GitHub Actions.

Локальний запуск:

```bash
cp infrastructure/compose/.env.edge.example infrastructure/compose/.env
cd infrastructure/compose
docker compose -f compose.edge.yaml -f compose.dev.yaml up --build
curl http://127.0.0.1:8081/health
```

Повна інструкція: [`docs/edge-bootstrap.md`](docs/edge-bootstrap.md).

## RS-485 discovery

Для пошуку Modbus RTU пристроїв із невідомими параметрами додано read-only сканер. Він перебирає baud rate, parity, stop bits і unit ID, пробує стандартну ідентифікацію `43/14`, формує fingerprint і записує локальний JSON-реєстр.

```bash
python tools/rs485_discovery/scan_rs485.py \
  --port /dev/serial/by-id/<adapter> \
  --quick \
  --deep \
  --progress
```

Інструкція та обмеження: [`tools/rs485_discovery/README.md`](tools/rs485_discovery/README.md).

## Перевірки якості

```bash
npm run format:check
npm run lint
npm run typecheck
npm test
npm run build
```

## Структура

```text
src/
├── app/                  # App Router, metadata, global styles
├── components/dashboard # Компоненти стартового dashboard
├── data/                 # Типізовані demo-дані
└── test/                 # Налаштування тестів

services/
└── device-agent/         # Edge-збір, offline queue, MQTT і health

infrastructure/
├── compose/              # Development та production Edge stack
└── ansible/              # Provisioning Raspberry Pi

tools/
└── rs485_discovery/      # Read-only пошук Modbus RTU endpoints

docs/
├── architecture.md
├── design-system.md
└── edge-bootstrap.md
```

## Архітектурні принципи

- Server Components за замовчуванням; Client Components тільки для інтерактивності.
- Компоненти не залежать від конкретного backend API.
- Demo-дані ізольовані в `src/data/dashboard.ts` і надалі можуть бути замінені на API adapter.
- Критичні стани мають текстові та іконографічні індикатори, а не лише колір.
- UI адаптується від мобільного формату до широких операторських екранів.
- Edge-вузол продовжує збір без хмари та догружає локальну чергу після відновлення MQTT.
- Production images мають версіонуватися; тег `edge` використовується лише як канал початкової інтеграції.
- Діагностика RS-485 не виконує записів у регістри та не змінює налаштування приладів.

## Наступні етапи

1. Просканувати поточну RS-485 шину та підтвердити знайдені endpoints.
2. Додати перевірені профілі регістрів LE-01MP і Dixell XJP60D.
3. Підключити Modbus RTU adapter до Device Agent через `/dev/serial/by-id/...`.
4. Підключити Supabase Auth і RBAC.
5. Додати REST/WebSocket adapter для live-телеметрії.
6. Реалізувати сторінки вузлів, сесій, обладнання та звітів.
7. Додати E2E-тести основних операторських сценаріїв.
8. Підключити Vercel Preview Deployments.

## Ліцензування

Ліцензію проєкту ще не визначено. До додавання `LICENSE` усі права зберігаються за власником репозиторію.
