# NEXOLAB — Production UX Wave 2: Випробування → Звіти

Дата: 2026-10-08  
Parent: #1191  
Work Package: #1300  
Профіль: `LOCAL_LAN`  
Статус доказів: **anonymous + authenticated route-level Chromium PASS; розширена operator acceptance частково непідтверджена**

## Межі аудиту

Read-only Chromium запущено на `nexolab-edge-01` поза Commander process-limit cgroup. Відкрито наявний NEXOLAB frontend через `http://127.0.0.1:3000`. Під час anonymous проходу credential не використовувався. Для authenticated проходу root-only service credential використано одноразово після окремого погодження Product Owner; ім’я користувача, пароль, токени й production-показники не виводилися у звіт або Git, screenshots/traces/videos не зберігалися. Остання прийнята в durable project state deployed product source: `75d9c75f8d1901d6b639ec711bf3784e22ed0642`; повторної перевірки deployed manifest у межах цього проходу не було.

Аудит складається з **двох окремих проходів** на 360 / 390 / 430 / 1440 CSS px: anonymous перевірка `/sessions`, `/sessions/new`, `/reports` та authenticated read-only перевірка списків, wizard surface, першої доступної картки випробування й наявного звіту. Відкриття існуючих маршрутів не дорівнює підтвердженню всіх дій, даних і прав ролей.

## Реальний Chromium evidence: anonymous gate

| Width | Route           | HTTP | Auth gate | Safe returnTo | Horizontal overflow | Час, мс |
| ----: | --------------- | ---: | --------- | ------------- | ------------------: | ------: |
|   360 | `/sessions`     |  200 | PASS      | PASS          |                0 px |    1081 |
|   360 | `/sessions/new` |  200 | PASS      | PASS          |                0 px |     910 |
|   360 | `/reports`      |  200 | PASS      | PASS          |                0 px |     895 |
|   390 | `/sessions`     |  200 | PASS      | PASS          |                0 px |    1016 |
|   390 | `/sessions/new` |  200 | PASS      | PASS          |                0 px |     913 |
|   390 | `/reports`      |  200 | PASS      | PASS          |                0 px |     908 |
|   430 | `/sessions`     |  200 | PASS      | PASS          |                0 px |     996 |
|   430 | `/sessions/new` |  200 | PASS      | PASS          |                0 px |     906 |
|   430 | `/reports`      |  200 | PASS      | PASS          |                0 px |     901 |
|  1440 | `/sessions`     |  200 | PASS      | PASS          |                0 px |     982 |
|  1440 | `/sessions/new` |  200 | PASS      | PASS          |                0 px |     944 |
|  1440 | `/reports`      |  200 | PASS      | PASS          |                0 px |     904 |

Час — один single-pass замір для DOMContentLoaded + 800 мс очікування, включає фіксовану затримку; це **не показник реального часу завантаження для користувачів** і не performance SLA. HTTP 200 тут означає доставку frontend-сторінки; правильний результат без сесії — видимий security gate, а не відкрита production інформація.

Підсумок: **12/12** правильно показали «Потрібен вхід до системи»; **12/12** мали безпечний `/login` з `returnTo`, що збігається з локальним запитаним маршрутом; **12/12** не мали горизонтального overflow. Під час усіх 12 переходів network observer зафіксував **0 HTTP-запитів методами, відмінними від GET/HEAD/OPTIONS**. Жодної дії створення сесії, генерації звіту або зміни даних не виконувалося.

## Actual-host Chromium evidence: authenticated read-only journey

Одноразовий авторизований запуск успішно завершився (`status=completed`, `authenticated=true`). На кожній ширині відкрито **п’ять** маршрутів/поверхонь: `/sessions`, `/sessions/new`, `/reports`, деталі існуючого випробування та деталі існуючого звіту. Ідентифікатори, назви, персональні дані, стан конкретного виробу та результати вимірювань у evidence не записувалися.

| CSS width | Список випробувань | Створення (лише огляд) | Список звітів | Існуюча картка | Існуючий звіт | Overflow |
| --------: | ------------------ | ---------------------- | ------------- | -------------- | ------------- | -------: |
|       360 | HTTP 200           | HTTP 200               | HTTP 200      | HTTP 200       | HTTP 200      |     0 px |
|       390 | HTTP 200           | HTTP 200               | HTTP 200      | HTTP 200       | HTTP 200      |     0 px |
|       430 | HTTP 200           | HTTP 200               | HTTP 200      | HTTP 200       | HTTP 200      |     0 px |
|      1440 | HTTP 200           | HTTP 200               | HTTP 200      | HTTP 200       | HTTP 200      |     0 px |

У кожному з 20 виміряних відкриттів `authGate=false` після успішного входу. Списки мали видимі правильні заголовки; тест знаходив **4 посилання на існуючі випробування** в перевіреній вибірці на кожній ширині, а також `open-rendered-report` у списку звітів. Показ порожнього стану звітів не спостерігався. Route-level evidence не підтверджує правильність усіх значень у картках.

Окремі single-pass часи 20 відкриттів лежали в межах **999–2128 мс**; кожен включає фіксовані 900 мс очікування. Не інтерпретувати ці числа як SLA, повноцінні performance measurements або cold-start benchmark.

Після login браузерний audit блокував усі запити з методами, відмінними від GET/HEAD/OPTIONS: `blockedWrites=0` (жодної спроби write-запиту не зафіксовано). Жодних кнопок створення сесії, переходу lifecycle, формування версії звіту, завантаження артефакту чи змін налаштувань не натискали.

**Report entry nuance:** вибрана існуюча session-detail картка не показала селектор, який тест очікував для переходу у `/reports?session=...`. Це **не підтверджений UX-дефект**: source `SessionReportAction` приховує дію для станів, відмінних від `completed`/`archived`, і без `reports.read`. Тест не зафіксував стан вибраної сесії чи permission. Крім того, сам список звітів містив робоче посилання для відкриття існуючого звіту. Потрібна окрема conditional-role перевірка, без припущення про несправність.

## Source review (допоміжне підтвердження поведінки)

Оглянуті актуальні `main` файли:

- `src/app/sessions/page.tsx`, `src/app/sessions/new/page.tsx`, `src/app/sessions/[sessionId]/page.tsx`;
- `src/app/reports/page.tsx`, `src/app/reports/[reportId]/page.tsx`;
- `src/components/sessions/sessions-list-screen.tsx`, `session-wizard.tsx`, `session-workspace.tsx`;
- `src/components/reports/reports-screen.tsx`, `report-output-screen.tsx`.

Джерела підтверджують окремі list/wizard/detail та reports list/detail компоненти; SessionWorkspace має report action, ReportsScreen використовує security state. Це **не** доказ, що створення/перехід/доступ працюють у встановленій production-сесії. Нова функціональна несправність у межах безсекретного проходу **не відтворена**.

## Що залишилося неперевіреним

- **VERIFIED:** авторизовані списки випробувань і звітів та доступність існуючих session/report detail routes на чотирьох ширинах; відсутність overflow; безпечний browser-level read-only контур.
- **UNVERIFIED:** коректність фактичних даних у session/report detail, операторський пошук/фільтрація, повернення контексту, повний keyboard Tab/Shift+Tab/Escape/focus workflow, дії кнопок без зміни даних.
- **UNVERIFIED:** рольові permissions, умовна поява `SessionReportAction` на завершеній/архівній сесії та multi-organization switching. Перевірявся лише доступ наявного service account, без перемикання ролі.
- **UNVERIFIED:** error/stale/offline/recovery journeys без небезпечного втручання у стабільний runtime.

Ці залишкові перевірки не можна вважати PASS лише на підставі успішного HTTP 200. Повторне використання credential #1300 **не дозволене без нового погодження**. Додаткову role/keyboard перевірку слід планувати окремим вузьким Work Package або виконувати в уже авторизованому browser-контексті без експорту секретів.

## Safety

- Root-only service credential: використано **один раз** за погодженням; user/password/token не виведено й не збережено в evidence.
- Browser screenshots/traces/videos: не створювалися й не додавалися в репозиторій.
- Mutating API requests після входу: зафіксовано **0**, блокування у Chromium було активне.
- Створення/редагування session/report, report generation/export, changes to lifecycle: не виконувалися.
- Modbus/controller writes: none; hardware writes: none.
- Service restart, deployment або production cutover: none.
- Mock/demo/fallback не видавалися за production evidence.

## Наступний крок

Authenticated read-only route-level acceptance **виконана**. Залишкові keyboard, context-navigation та role/permission assertions не входили в автоматичний сценарій і повинні бути оформлені як окрема доказова частина; #1300/PR #1301 не можна закривати з формулюванням «повне operator UX acceptance», поки ці критерії явно не скориговані або не перевірені.
