# NEXOLAB Current State

Updated: 2026-08-02  
Verified main baseline: `c5fa0fdcca6d86f54ba7430b5ca8efd7ffc39f8c`  
Active Work Package: Issue #196 / PR #228 — format refrigeration domain and repository files  
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
- Issue #194 / PR #226 — 6 E2E/root tooling files, merged as `cb8f4b21d24c00f1d6a501b69ed8af4db55f353e`;
- Issue #195 / PR #227 — 10 telemetry/dashboard files, merged as `c5fa0fdcca6d86f54ba7430b5ca8efd7ffc39f8c`.

## Issue #196 outcome

PR #228 applies Prettier `3.9.6` only to the ten refrigeration domain/repository paths listed in Issue #196.

Verified evidence:

- generation workflow: `30748758550`;
- generation artifact: `8833742334`;
- artifact digest: `sha256:7b0a538fec903beb1e2440422a7abbcbcf7cea1a48103e74d894259e0690e56f`;
- verified staging workflow: `30748882865`;
- source AST, transpiled runtime AST and exact comment-token sequences are identical before and after formatting;
- targeted tests passed for climate catalog repository, layout draft storage and sensor placement management;
- patch review confirms line wrapping and layout changes only;
- query paths, methods, request bodies, `If-Match`, audit headers, ETag/version handling, validation predicates, identifiers, error strings and assertions are unchanged;
- clean commit `24eb015513f28780fcf1d1ee919ef1db41908e72` was created directly from baseline `c5fa0fdcca6d86f54ba7430b5ca8efd7ffc39f8c` using the ten verified blob SHA values;
- final source diff contains exactly the ten allowlisted files before mandatory project-state updates;
- the temporary generation/write workflow is absent from the final branch history and diff.

No schema, migration, dependency, UI, runtime, deployment, hardware or Modbus behavior changed.

After Issue #196, 17 paths remain in the historical formatting backlog, all assigned to Issue #197.

## Open Pull Requests

- #228 — formatting-only refrigeration domain/repository Work Package; project-state finalization and exact-head CI are in progress.
- #217–#221 — queued Dependabot workflow-runtime updates; separate maintenance scope.

## Next Ready Work Package

After PR #228 reaches final exact-head GREEN and is merged, start Issue #197: format only the 17 inventoried refrigeration UI component files. Hardware Issues #200–#202 remain blocked pending read-only physical evidence.
