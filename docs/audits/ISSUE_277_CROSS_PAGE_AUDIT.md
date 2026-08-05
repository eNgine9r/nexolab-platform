# Issue #277 — Cross-page operator consistency audit

Baseline: `68c443ff9e8aeff2cdb1384ecdb90daf85baceba`
Profile: `LOCAL_LAN`
Audit date: 2026-08-05

## Audited routes

- `/`
- `/nodes`
- `/sessions`
- `/refrigeration`
- `/alerts`
- `/reports`
- `/energy`
- `/live`
- `/equipment-layouts`
- `/equipment`
- `/settings`
- `/cameras`

`/lockers` is explicitly excluded and remains blocked pending a concrete inventory, read-only protocol and operator workflow.

## Route inventory result

All audited routes use the authenticated NEXOLAB shell or an explicit security gate. No audited route uses `PlatformPlaceholderScreen`. The shared `Sidebar` and `Topbar` are reused across the implemented route screens. Existing route-specific loading, empty, stale, offline, forbidden and error behavior remains owned by the corresponding route domain and is not broadened by this Work Package.

## Bounded defect list

### D-277-01 — Fabricated global service and cloud status in Sidebar

- **Routes:** every route rendering the shared `Sidebar`.
- **Evidence:** `src/components/dashboard/sidebar.tsx` always renders `Усі сервіси в нормі`, `Локальна мережа Online` and `Хмарна синхронізація Synced` without reading health, network or cloud state.
- **Impact:** operators receive unsupported production claims; the cloud claim also conflicts with the optional-cloud LOCAL_LAN architecture.
- **Expected behavior:** the shared shell must not claim service, LAN or cloud health without a verified observation source. It may show a neutral LOCAL_LAN profile boundary and direct operators to route-specific diagnostics.
- **Priority:** critical truthfulness defect.
- **Shared:** yes.

### D-277-02 — Sidebar can expose two active navigation items

- **Routes:** every route rendering the shared `Sidebar`.
- **Evidence:** active state is computed as `routeActive || activeItem === label`. Route screens pass a fixed `activeItem`; the Overview additionally mutates `activeItem` before navigation. A stale caller value can therefore mark a second item active alongside `usePathname()`.
- **Impact:** active-route feedback can contradict the browser URL and confuse keyboard/screen-reader navigation context.
- **Expected behavior:** `usePathname()` is the single source of truth for the active navigation item. Callers only control mobile close behavior.
- **Priority:** high navigation consistency defect.
- **Shared:** yes.

### D-277-03 — Overview panel actions look interactive but do not navigate

- **Route:** `/`.
- **Evidence:** `PanelAction` renders a `<button>` with no `onClick`; actions labelled `Всі вузли`, `Всі тривоги`, `Всі сесії`, `Лабораторія 1` and `Всі камери` do nothing.
- **Impact:** visible controls fail silently and are inconsistent with canonical Sidebar navigation.
- **Expected behavior:** actions with canonical destinations are links to the relevant route. The unsupported `Лабораторія 1` action is removed instead of inventing a destination.
- **Priority:** high operator interaction defect.
- **Shared:** no; Overview-only correction.

## Explicitly not selected for implementation

- visual redesign or design-system rewrite;
- route-specific feature additions;
- new backend health aggregation;
- cloud synchronization implementation;
- Smart Lockers work;
- dependency or toolchain migrations;
- camera media, ONVIF, RTSP or hardware acceptance;
- Modbus, camera, locker or other hardware writes;
- production/site cutover.

## Permitted implementation files

- `src/components/dashboard/sidebar.tsx`
- `src/components/dashboard/sidebar.test.tsx`
- `src/components/dashboard/dashboard-shell.tsx`
- focused dashboard tests or authenticated browser acceptance only when required by the three defects;
- `.project/**` for the final checkpoint.

## Verification plan

1. focused Sidebar tests for route-derived active state and neutral LOCAL_LAN status;
2. focused DashboardShell test or production browser assertion for canonical Overview links;
3. repository formatting;
4. lint;
5. typecheck;
6. tests;
7. production build;
8. directly affected authenticated dashboard browser acceptance;
9. focused diff, review and state checkpoint audit.
