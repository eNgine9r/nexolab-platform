# NEXOLAB Current State

Updated: 2026-08-02  
Verified main baseline: `75fb9f2921053d39187bbf216057913be2c7fe43`  
Active Work Package: Issue #194 / PR #226 — format E2E tests and root tooling configuration  
Status confidence: high for repository state, formatting-only semantic evidence, current Prettier inventory, linux/amd64 CI, encrypted software recovery and disconnected-container evidence; partial for ARM64 actual-host, Raspberry Pi, reboot, power-loss and hardware acceptance.

## Profile

- Project type: `LOCAL_LAN`
- Development internet: allowed
- Runtime internet: not required
- Mandatory paid runtime services: prohibited
- Device transport: read-only Modbus RTU and MQTT QoS 1
- No Modbus write, hardware write or production/site cutover is authorized.

## Completed reliability baseline

- PR #184 — AI Development Operating Standard.
- PR #190 — verified architecture and offline boundary.
- PR #206 — stale tracker and Pull Request reconciliation.
- PR #207 — durable MQTT-to-PostgreSQL telemetry ingestion.
- PR #209 — Device Agent supply-chain hardening.
- PR #213 — dashboard security bootstrap diagnostics.
- PR #214 — live WebSocket lifecycle stabilization.
- PR #215 — verified offline installation/update bundle.
- PR #216 — fail-closed offline operator authentication.
- PR #223 — argument-safe disposable DR MinIO credential.
- PR #224 — encrypted local-auth disaster-recovery extension.
- PR #192 — exact 46-file historical Prettier inventory.
- PR #225 — three documentation files formatted without semantic changes, merged as `75fb9f2921053d39187bbf216057913be2c7fe43`.

## Issue #189 remaining boundary

The software-only recovery portion is verified and merged. Issue #189 remains open only for controlled actual-host evidence:

- central-host reboot;
- Raspberry Pi reboot;
- edge power interruption and SQLite outbox recovery;
- physical power-loss behavior;
- actual disk-full/disk-loss behavior;
- operator-owned physical-media restore.

These outcomes must not be inferred from container evidence.

## Formatting maintenance baseline

Issue #191 established an exact Prettier `3.9.6` debt inventory of 46 files on `main` SHA `f54cd7b6f6db580f3931a40889f5b4e33af3cc30`.

Completed child Work Package:

- Issue #193 — documentation: 3 files, merged through PR #225.

Remaining child Work Packages:

- Issue #194 — E2E/root tooling: 6 files;
- Issue #195 — telemetry/dashboard frontend: 10 files;
- Issue #196 — refrigeration domain/repositories: 10 files;
- Issue #197 — refrigeration UI: 17 files, depends on #196.

## Issue #194 outcome

PR #226 applies Prettier only to:

- `e2e/nodes.production.e2e.ts`;
- `e2e/observability.production.e2e.ts`;
- `e2e/refrigeration-layout.production.e2e.ts`;
- `e2e/security-rbac.production.e2e.ts`;
- `eslint.config.mjs`;
- `playwright.observability.config.ts`.

Verified evidence:

- Prettier version: `3.9.6`;
- generation workflow: `30743441993`;
- generation artifact: `8832069755`;
- artifact digest: `sha256:0b3816f36eb2d2e01605e55f17d0f2be08b2f976cff02397b1d02d29651370e1`;
- final allowlisted apply workflow: `30743671286`;
- semantic comparison: identical TypeScript AST fingerprints and exact comment-token sequences before and after formatting;
- ESLint flat configuration imported successfully;
- Playwright observability configuration generated a non-empty test list without executing production/site E2E;
- `git diff --check` passed;
- the temporary generation/write workflow was removed before final review.

Patch review confirms line wrapping, array/object layout and optional trailing-comma formatting only. No assertion, selector, timeout, URL, permission, environment variable, test value or configuration behavior changed.

No dependency, runtime, `.prettierignore`, production data, hardware or Modbus path changed. After these six files are merged, 37 paths remain in the recorded historical formatting backlog.

## Open Pull Requests

- #226 — formatting-only E2E/tooling Work Package; project-state finalization and exact-head CI are in progress.
- #217–#221 — queued Dependabot workflow-runtime updates; separate maintenance scope.

## Next Ready Work Package

After PR #226 reaches final exact-head GREEN and is merged, start Issue #195: format only the ten inventoried telemetry/dashboard frontend files. Do not combine formatting groups or product changes. Hardware Issues #200–#202 remain blocked pending read-only physical evidence.
