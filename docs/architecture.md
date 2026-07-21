# Архітектура frontend

## Межі поточного milestone

Dashboard працює на статичних типізованих даних. Це дозволяє стабілізувати дизайн-систему і компонентні контракти до підключення реального backend.

## Шари

```text
App Router
  ↓
Dashboard shell
  ↓
Feature panels
  ↓
Typed view models
  ↓
Future API / WebSocket adapter
```

## Майбутня інтеграція

Рекомендовано додати:

- `src/lib/api` — REST client;
- `src/lib/realtime` — WebSocket/Supabase Realtime adapter;
- `src/lib/auth` — session і RBAC;
- `src/features/*` — feature-oriented модулі;
- runtime validation через Zod перед передачею даних у UI.

## Телеметрія

Frontend не повинен напряму опитувати промислові прилади. Дані проходять через edge/gateway backend, який виконує нормалізацію, timestamp alignment, quality flags та контроль доступу.
