# NEXOLAB Current State

Updated: 2026-08-02  
Verified main baseline: `cb8f4b21d24c00f1d6a501b69ed8af4db55f353e`  
Active Work Package: Issue #195 / PR #227 — format telemetry and dashboard frontend files  
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

Issue #191 established an exact Prettier `3.9.6` debt inventory of 46 files.

Completed child Work Packages:

- Issue #193 / PR #225 — 3 documentation files, merged as `75fb9f2921053d39187bbf216057913be2c7fe43`;
- Issue #194 / PR #226 — 6 E2E/root tooling files, merged as `cb8f4b21d24c00f1d6a501b69ed8af4db55f353e`.

## Issue #195 outcome

PR #227 applies Prettier `3.9.6` only to the ten paths listed in Issue #195.

Verified evidence:

- generation workflow: `30744141325`;
- generation artifact: `8832300630`;
- artifact digest: `sha256:9e5cae5c725074b5d62cd3d8190096fa1d0e4d2339eec544ef4d86f05544375e`;
- canonical semantic apply workflow: `30747460492`;
- source AST structure, non-TSX runtime AST, JSX text slots and exact comment tokens are identical before and after formatting;
- targeted tests for `temperature-chart.test.tsx` and `temperature-channel.test.ts` passed;
- patch review confirms wrapping and layout changes only;
- clean feature history was reconstructed from baseline `cb8f4b21d24c00f1d6a501b69ed8af4db55f353e` using the verified artifact;
- final PR diff contains exactly the ten allowlisted source files before mandatory project-state updates;
- the temporary generation/write workflow is absent from the final diff.

No endpoint, string, close code, timeout, state transition, assertion, public contract, dependency, runtime, deployment, hardware or Modbus behavior changed.

After Issue #195, 27 paths remain in the historical formatting backlog.

## Open Pull Requests

- #227 — formatting-only telemetry/dashboard Work Package; project-state finalization and exact-head CI are in progress.
- #217–#221 — queued Dependabot workflow-runtime updates; separate maintenance scope.

## Next Ready Work Package

After PR #227 reaches final exact-head GREEN and is merged, start Issue #196: format only the ten inventoried refrigeration domain/repository files. Issue #197 remains blocked until #196 is merged. Hardware Issues #200–#202 remain blocked pending read-only physical evidence.
