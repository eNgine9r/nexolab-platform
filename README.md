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

docs/
├── architecture.md
└── design-system.md
```

## Архітектурні принципи

- Server Components за замовчуванням; Client Components тільки для інтерактивності.
- Компоненти не залежать від конкретного backend API.
- Demo-дані ізольовані в `src/data/dashboard.ts` і надалі можуть бути замінені на API adapter.
- Критичні стани мають текстові та іконографічні індикатори, а не лише колір.
- UI адаптується від мобільного формату до широких операторських екранів.

## Наступні етапи

1. Підключити Supabase Auth і RBAC.
2. Додати REST/WebSocket adapter для live-телеметрії.
3. Реалізувати сторінки вузлів, сесій, обладнання та звітів.
4. Додати E2E-тести основних операторських сценаріїв.
5. Підключити Vercel Preview Deployments.

## Ліцензування

Ліцензію проєкту ще не визначено. До додавання `LICENSE` усі права зберігаються за власником репозиторію.
