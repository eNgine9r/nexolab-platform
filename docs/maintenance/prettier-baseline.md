# NEXOLAB Prettier baseline inventory

## Baseline

- Repository: `eNgine9r/nexolab-platform`
- Base `main`: `f54cd7b6f6db580f3931a40889f5b4e33af3cc30`
- Inventory workflow source head: `c03a147c0b81c67b18d5c7669e83aec837a28ec2`
- Prettier: `3.9.6`
- Exact command: `npm exec prettier -- --list-different .`
- Workflow run: `30742515790`
- Evidence artifact: `8831767220`
- Artifact digest: `sha256:5d55e49b403eca21dbfa798a360574d383fe3c4f4e27abacc77626aefb4569e7`
- Files reported: **46**

The workflow executed from PR #192 but checked out the exact merged `main` SHA above. The temporary workflow was not part of the inspected worktree and is removed before the final PR diff.

## Findings

- The repository-wide historical Prettier debt is 46 files on the verified baseline.
- All 46 reported files use LF line endings.
- No CRLF, mixed-line-ending or lone-CR file was reported.
- Extension distribution: 3 Markdown, 1 MJS, 21 TypeScript and 21 TSX files.
- Top-level distribution: 3 `docs`, 4 `e2e`, 2 root configuration files and 37 `src` files.
- All reported paths are maintained source, test, configuration or documentation files.
- No generated, vendored or externally managed file appears in the inventory.
- No new `.prettierignore` entry is justified.

The prior inventory on `8371ee59e76e64963405706be79fc4a909f9fac9` reported 48 files. The refreshed baseline no longer reports:

- `src/components/dashboard/dashboard-shell.tsx`;
- `src/lib/telemetry/websocket-client.ts`.

Those files became Prettier-clean through later focused product/reliability work and are removed from the formatting backlog rather than reformatted again.

## Review groups

### Documentation — Issue #193

Count: 3

- `docs/operations/capacity-release-gate.md`
- `docs/operations/observability.md`
- `docs/rs485/evidence-standard.md`

### E2E and root tooling configuration — Issue #194

Count: 6

- `e2e/nodes.production.e2e.ts`
- `e2e/observability.production.e2e.ts`
- `e2e/refrigeration-layout.production.e2e.ts`
- `e2e/security-rbac.production.e2e.ts`
- `eslint.config.mjs`
- `playwright.observability.config.ts`

### Telemetry and dashboard frontend — Issue #195

Count: 10

- `src/app/api/device-agent/xjp60d/route.ts`
- `src/components/dashboard/sensor-management-dialog.tsx`
- `src/components/dashboard/telemetry-status-bar.tsx`
- `src/components/dashboard/temperature-chart.test.tsx`
- `src/components/dashboard/temperature-chart.tsx`
- `src/hooks/use-dashboard-telemetry.ts`
- `src/hooks/use-xjp60d-sensor-management.ts`
- `src/lib/telemetry/dashboard-state.ts`
- `src/lib/telemetry/temperature-channel.test.ts`
- `src/lib/telemetry/temperature-channel.ts`

### Refrigeration domain and repositories — Issue #196

Count: 10

- `src/features/refrigeration/climate-catalog-repository.test.ts`
- `src/features/refrigeration/climate-catalog-repository.ts`
- `src/features/refrigeration/equipment-copy.ts`
- `src/features/refrigeration/equipment-lifecycle-repository.ts`
- `src/features/refrigeration/equipment-repository-runtime.ts`
- `src/features/refrigeration/equipment-repository.ts`
- `src/features/refrigeration/layout-draft-storage.test.ts`
- `src/features/refrigeration/sensor-configuration.ts`
- `src/features/refrigeration/sensor-placement-management.test.ts`
- `src/features/refrigeration/sensor-placement-management.ts`

### Refrigeration UI components — Issue #197

Count: 17

- `src/components/refrigeration/camera-scoped-image-canvas.tsx`
- `src/components/refrigeration/camera-scoped-layout-editor-implementation.tsx`
- `src/components/refrigeration/equipment-lifecycle-panel.tsx`
- `src/components/refrigeration/refrigeration-catalog-screen.test.tsx`
- `src/components/refrigeration/refrigeration-catalog-screen.tsx`
- `src/components/refrigeration/refrigeration-detail-screen.test.tsx`
- `src/components/refrigeration/refrigeration-detail-screen.tsx`
- `src/components/refrigeration/refrigeration-equipment-dialogs.tsx`
- `src/components/refrigeration/refrigeration-icon-button.tsx`
- `src/components/refrigeration/refrigeration-image-canvas.tsx`
- `src/components/refrigeration/refrigeration-layout-editor.test.tsx`
- `src/components/refrigeration/refrigeration-layout-editor.tsx`
- `src/components/refrigeration/refrigeration-layout-lifecycle-panel.tsx`
- `src/components/refrigeration/refrigeration-layout-workspace.tsx`
- `src/components/refrigeration/security-aware-layout-workspace.tsx`
- `src/components/refrigeration/sensor-placement-manager.test.tsx`
- `src/components/refrigeration/sensor-placement-manager.tsx`

Issue #197 depends on #196 so domain/repository formatting is reviewed before the larger UI group. Issues #193, #194 and #195 are otherwise independent and must still proceed one focused branch/PR at a time.

## Formatting policy

Each child Work Package must:

1. run Prettier only on its exact file list;
2. preserve runtime behavior and user-visible content;
3. review the diff for changed strings, numbers, conditions, identifiers and contracts;
4. run targeted tests plus standard CI;
5. contain no refactoring, dependency upgrade or product fix;
6. update project state and checkpoint independently.

No child PR may use `prettier --write .`.

## Repository-wide gate

Changed-file formatting remains mandatory immediately.

Repository-wide `npm run format:check` becomes mandatory again only after Issues #193, #194, #195, #196 and #197 are merged and a fresh inventory returns zero files. Parent Issue #185 closes only after that final zero-difference run and green standard CI.
