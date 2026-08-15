# Issue #461 — TelemetryPointSelector verification checkpoint

Updated: 2026-08-15

## Scope boundary

Issue #461 adds the reusable hierarchical `TelemetryPointSelector` primitive only. It does not migrate a product route or alter backend, persistence, telemetry acquisition, scheduler, device registry, Modbus, hardware, dependency, or cloud-runtime behavior.

The selector consumes explicit organization-scoped `TelemetryPointDescriptor` metadata and produces canonical leaf keys compatible with the existing Live telemetry identity:

```text
node_id | equipment_id | channel_id | metric | unit
```

Laboratory, zone and equipment-type metadata are never inferred from telemetry strings.

## Implementation verification

Targeted implementation workflow `31890013361` verified implementation head `3463f4d6504240ccc0e62e925d4c7980dc924b0d`:

- touched-file Prettier: PASS;
- scoped ESLint: PASS;
- hierarchy and component regressions: 10/10 PASS;
- TypeScript typecheck: PASS.

The regressions cover deterministic hierarchy construction, canonical identity compatibility, organization scoping, mixed parent state, atomic branch selection limits, bounded search, hidden committed-selection preservation, visible-render limits, explicit metadata validation, Confirm/Cancel behavior, search, keyboard navigation and ARIA semantics.

## First production exact-head cycle

PR #464 first ran repository gates on head `e0e5dab11043f66c9c5cf3605db57ed75c955f60`.

Results:

- CI `31890288268`: PASS — formatting, lint, typecheck, full tests and production build;
- Refrigeration Browser Acceptance `31890288231`: PASS;
- Acquisition Scale Acceptance `31890288241`: PASS for both software matrices;
- Authenticated Dashboard Acceptance `31890288244`: 14/15 PASS;
- Offline Bundle `31890288246`: cancelled by a newer branch push after build/transfer/egress steps and therefore is not completion evidence.

The single Authenticated Dashboard failure was isolated to the new browser harness. The product selector and all 14 pre-existing production scenarios passed. Playwright transformed a React element imported directly into the E2E module into its internal `__pw_type` representation before `react-dom/server` received it.

## Browser harness correction

The browser proof now renders the actual selector source through an isolated plain Node subprocess outside Playwright's module transform. The subprocess:

1. transpiles the actual hierarchy and selector TypeScript/TSX source with the repository TypeScript dependency;
2. builds the real hierarchy from the representative descriptor inventory;
3. server-renders the real `TelemetryPointSelector` with React and `react-dom/server`;
4. returns markup plus hierarchy node/leaf counts;
5. removes its temporary directory.

Temporary correction workflow `31890655882` completed GREEN: patch application, Prettier, scoped E2E ESLint, TypeScript typecheck, helper removal and publication all passed. The resulting clean product/test/docs head is `198d1c5394d918e999207d90097dc5f49df0e6cd`.

The browser scenario then evaluates that real selector markup with the production Next.js stylesheet set and checks:

- nested ARIA tree semantics;
- mixed equipment-parent selection state;
- representative energy and temperature points;
- no document-level horizontal overflow at 360, 1440 and 1920 px;
- zero selector-owned WebSocket openings;
- zero telemetry-history, Device Agent control or non-GET API requests.

## Evidence classification

The first CI/Refrigeration/software-scale results are useful diagnostic evidence but are not final merge evidence after the browser-harness correction. A new user-authored exact PR head must repeat the required CI, Authenticated Dashboard, Refrigeration Browser, disconnected Offline Bundle and applicable software-scale gates.

Issue #289 remains the independent physical Raspberry Pi/RS-485 hardware-performance lane. No software workflow result in Issue #461 is classified as hardware acceptance.

## Safety and offline boundary

Issue #461 performs none of the following:

- Modbus write;
- hardware write or actuator control;
- controller configuration change;
- polling/scheduler change;
- acquisition-registry mutation;
- dependency upgrade;
- persistent-data or volume deletion;
- production/site cutover;
- secret, billing or DNS change;
- mandatory public-cloud, CDN, remote-font or external API dependency.

Final completion remains blocked on a fully GREEN exact-head PR verification cycle and project-state reconciliation.