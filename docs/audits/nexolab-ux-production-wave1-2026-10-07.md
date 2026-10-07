# NEXOLAB Production UX Audit — Wave 1

Дата: 2026-10-07  
Parent: #1191  
Work Package: #1294  
Середовище: `nexolab-edge-01`, LOCAL_LAN  
Deployed product source: `75d9c75f8d1901d6b639ec711bf3784e22ed0642`  
Frontend build ID: `Up0mYuGscMzOz00Qyyacp`

## Мета

Перевірити фактично встановлений операторський шлях для найчастішого сценарію моніторингу: вхід, спільна навігація, Огляд, вибір датчиків, Live, мобільне представлення та базова клавіатурна доступність. Аудит read-only щодо production API/hardware; login і локальний display-only вибір каналів дозволені.

## Межі доказів

Chromium запускався на Raspberry поза Commander service cgroup з обмеженням `pids.max=32`. Перевірено ширини 360, 390, 430 і 1440 CSS px. Для authenticated проходу одноразово використано наявний root-only service credential після явного погодження Product Owner. Credential не виводився у лог і не зберігався у Git. Сирі screenshots/traces/videos не створювалися.

Після завершення входу audit-run контролював мережеві методи: не зафіксовано жодного POST/PUT/PATCH/DELETE під час перевірки Overview/Live. Перемикання першого Live checkbox змінило лише browser display/selection state. Modbus write, hardware write, service restart/cutover та production-data mutation не виконувалися.

## Production health перед аудитом

| Перевірка | Результат |
| --- | --- |
| Dashboard `/login` | HTTP 200 |
| Auth session без токена | HTTP 401, очікувано |
| Device Agent `/health` | HTTP 200 |
| Chromium launch | PASS |
| Product code deployed vs current main | однаковий; після deployment у main змінювався лише `.project/**` state |

## Результати по ширинах

| Width | Login | Overview | Live | Horizontal overflow |
| ---: | ---: | ---: | ---: | --- |
| 360 | 2304 ms | 981 ms | 1062 ms | none |
| 390 | 1480 ms | 1072 ms | 1071 ms | none |
| 430 | 1364 ms | 1133 ms | 1066 ms | none |
| 1440 | 1615 ms | 1140 ms | 1078 ms | none |

Це single-pass observed timings, а не performance benchmark. Орієнтовна медіана: login 1.55 s, Overview 1.10 s, Live 1.07 s.

## Shared shell / navigation

PASS на всіх ширинах:

- 13 navigation links присутні;
- рівно один `aria-current="page"` на Overview і Live;
- активний href відповідає фактичному маршруту;
- logout доступний;
- Alerts shortcut доступний;
- горизонтального overflow немає.

Service account має одне membership, тому organization switcher не рендериться. Multi-organization switching цим Wave 1 не приймається і залишається окремим scenario evidence.

## Overview

PASS на 360 / 390 / 430 / 1440:

- 6 KPI cards рендеряться;
- control «Налаштувати датчики на графіку Огляду» доступний;
- dialog відкривається;
- фактично доступно 15 monitored sensor checkboxes;
- Escape закриває modal;
- після закриття фокус повертається на opener;
- background/modal flow не створює horizontal overflow.

Це production-підтвердження раніше code-closed UX-10/UX-11 для перевіреної частини сценарію. Повний Tab-cycle не вимірювався кожною клавішею у цьому Wave; Escape + focus return підтверджені.

## Live

PASS на 360 / 390 / 430 / 1440:

- `/live` відкриває primary monitoring workspace;
- primary chart видимий;
- «Обрати датчики / Змінити датчики» видимий;
- дія переводить keyboard focus у channel search;
- inventory table видима;
- фактично рендериться 219 channel rows;
- display-only checkbox selection змінюється коректно;
- horizontal overflow відсутній на mobile;
- після login не зафіксовано жодного mutating network request.

Це production-підтвердження code-closed UX-13/UX-14/UX-15 у межах перевіреного operator flow.

## Нові production findings

### UX-42 / #1295 — signed-out Alerts показує service failure замість auth gate

**Priority: P1. Reproduced.**

Без сесії `/` і `/live` коректно показують «Потрібен вхід до системи» та login link. `/alerts` натомість рендерить робочу сторінку «Тривоги та події» і повідомлення «Alerts API недоступний».

API при цьому залишається захищеним; це operator-facing auth-state defect, а не доведена backend authorization проблема. Source підтверджує, що Alerts route напряму рендерить workspace без canonical security gate.

Follow-up: #1295.

### UX-43 / #1296 — primary mobile topbar controls мають 40×40 px

**Priority: P2. Reproduced.**

На 360 / 390 / 430 px menu, Alerts і logout мають 40×40 CSS px. Для порівняння Live selection action має 44 px висоти. Source підтверджує, що Topbar використовує shared `.icon-button` з `2.5rem`.

Це не функціональна відмова; це mobile usability consistency finding. Follow-up має збільшити лише primary Topbar hit areas, не глобально всі icon buttons.

Follow-up: #1296.

## Signed-out truthfulness

- Overview: PASS — «Потрібен вхід до системи».
- Live: PASS — «Потрібен вхід до системи».
- Alerts: FAIL UX truthfulness — показує API failure; tracked as #1295.

## Security / mutation evidence

- credential output: none;
- credential persisted in repository: none;
- raw browser artifacts retained: none;
- unexpected mutating requests after login: 0;
- production data mutation: none observed/intended;
- Modbus/controller write: none;
- hardware write: none;
- production service restart/cutover: none.

## Wave 1 conclusion

Shared shell, Overview and Live are production-usable across tested desktop/mobile widths for the verified service-account flow. Previously implemented navigation, Overview dialog and Live selection improvements are now backed by actual deployed Chromium evidence.

Wave 1 does **not** close parent #1191: remaining pages, role-specific affordances, multi-membership switching, sessions/reports/schemes/settings and error/offline/recovery journeys still require later waves.

Next implementation priority from this wave:

1. #1295 — truthful Alerts authentication gate (P1).
2. #1296 — mobile Topbar primary touch targets (P2).
