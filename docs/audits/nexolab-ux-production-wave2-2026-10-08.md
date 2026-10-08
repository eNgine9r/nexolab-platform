# NEXOLAB — Production UX Wave 2: Випробування → Звіти

Дата: 2026-10-08  
Parent: #1191  
Work Package: #1300  
Профіль: `LOCAL_LAN`  
Статус доказів: **частково перевірено, authenticated journey pending**

## Межі аудиту

Read-only Chromium запущено на `nexolab-edge-01` поза Commander process-limit cgroup. Відкрито наявний NEXOLAB frontend через `http://127.0.0.1:3000`. Ніяких credentials, access tokens, production-вимірювань або browser traces не зчитано чи збережено. Остання прийнята в durable project state deployed product source: `75d9c75f8d1901d6b639ec711bf3784e22ed0642`; повторної перевірки deployed manifest у межах цього проходу не було.

Аудит перевіряв **лише анонімні сторінки** на 360 / 390 / 430 / 1440 CSS px. Відвідано `/sessions`, `/sessions/new`, `/reports`. Після входу список випробувань, реальну картку, звіти, ролі та кнопки не перевіряли. Відсутність цих доказів не означає, що функції завершені чи зламані.

## Реальний Chromium evidence: anonymous gate

| Width | Route | HTTP | Auth gate | Safe returnTo | Horizontal overflow | Час, мс |
| ---: | --- | ---: | --- | --- | ---: | ---: |
| 360 | `/sessions` | 200 | PASS | PASS | 0 px | 1081 |
| 360 | `/sessions/new` | 200 | PASS | PASS | 0 px | 910 |
| 360 | `/reports` | 200 | PASS | PASS | 0 px | 895 |
| 390 | `/sessions` | 200 | PASS | PASS | 0 px | 1016 |
| 390 | `/sessions/new` | 200 | PASS | PASS | 0 px | 913 |
| 390 | `/reports` | 200 | PASS | PASS | 0 px | 908 |
| 430 | `/sessions` | 200 | PASS | PASS | 0 px | 996 |
| 430 | `/sessions/new` | 200 | PASS | PASS | 0 px | 906 |
| 430 | `/reports` | 200 | PASS | PASS | 0 px | 901 |
| 1440 | `/sessions` | 200 | PASS | PASS | 0 px | 982 |
| 1440 | `/sessions/new` | 200 | PASS | PASS | 0 px | 944 |
| 1440 | `/reports` | 200 | PASS | PASS | 0 px | 904 |

Час — один single-pass замір для DOMContentLoaded + 800 мс очікування, включає фіксовану затримку; це **не показник реального часу завантаження для користувачів** і не performance SLA. HTTP 200 тут означає доставку frontend-сторінки; правильний результат без сесії — видимий security gate, а не відкрита production інформація.

Підсумок: **12/12** правильно показали «Потрібен вхід до системи»; **12/12** мали безпечний `/login` з `returnTo`, що збігається з локальним запитаним маршрутом; **12/12** не мали горизонтального overflow. Під час усіх 12 переходів network observer зафіксував **0 HTTP-запитів методами, відмінними від GET/HEAD/OPTIONS**. Жодної дії створення сесії, генерації звіту або зміни даних не виконувалося.

## Source review (не production acceptance)

Оглянуті актуальні `main` файли:
- `src/app/sessions/page.tsx`, `src/app/sessions/new/page.tsx`, `src/app/sessions/[sessionId]/page.tsx`;
- `src/app/reports/page.tsx`, `src/app/reports/[reportId]/page.tsx`;
- `src/components/sessions/sessions-list-screen.tsx`, `session-wizard.tsx`, `session-workspace.tsx`;
- `src/components/reports/reports-screen.tsx`, `report-output-screen.tsx`.

Джерела підтверджують окремі list/wizard/detail та reports list/detail компоненти; SessionWorkspace має report action, ReportsScreen використовує security state. Це **не** доказ, що створення/перехід/доступ працюють у встановленій production-сесії. Нова функціональна несправність у межах безсекретного проходу **не відтворена**.

## Pending acceptance / обмеження

- **UNVERIFIED**: авторизований список випробувань і реальна існуюча картка, пошук/фільтри, збереження контексту, клавіатура.
- **UNVERIFIED**: існуючі report list/detail, зрозумілі operator labels, зв'язок сесія → готовий звіт.
- **UNVERIFIED**: 360/390/430/1440 mobile cards і діалоги в authenticated state, реальна role permission boundary.
- **UNVERIFIED**: error/stale/offline поведінка, з якою неможливо експериментувати без окремо ізольованого сценарію.
- **UNVERIFIED**: реальна наявність безпечних existing session/report records для read-only огляду.

Для production authenticated проходу потрібна **нова явна одноразова авторизація** на використання root-only service credential; попередній дозвіл #1294 уже використаний. Секрет не можна зберігати в repo, логах чи нових browser traces. Якщо в обліковому записі немає придатних existing records, потрібно зафіксувати `unverified_missing_fixture`, а не створювати/змінювати production-сесії.

## Safety

- API/production data mutations: не виконувалися у виміряному anonymous проході;
- Modbus/controller writes: none;
- hardware writes: none;
- service restart або cutover: none;
- credential read: none;
- demo/fallback за production evidence: не видавався.

## Наступний крок

Отримати явну авторизацію для окремого **read-only** authenticated Wave 2, після чого доповнити цей звіт фактичними session/report та mobile/keyboard доказами. #1300 залишається відкритим до виконання цих AC.
