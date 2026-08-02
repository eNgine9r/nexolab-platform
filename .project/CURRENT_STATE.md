# NEXOLAB Current State

Updated: 2026-08-02  
Verified main baseline: `402df05d516af08f1d001e3b80bcb174c33197e0`  
Active Work Package: Issue #197 / PR #229 — format refrigeration UI component files  
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
- Issue #195 / PR #227 — 10 telemetry/dashboard files, merged as `c5fa0fdcca6d86f54ba7430b5ca8efd7ffc39f8c`;
- Issue #196 / PR #228 — 10 refrigeration domain/repository files, merged as `402df05d516af08f1d001e3b80bcb174c33197e0`.

## Issue #197 outcome

PR #229 applies Prettier `3.9.6` only to the 17 refrigeration UI/component paths listed in Issue #197.

Verified evidence:

- initial fail-closed semantic workflow: `30749791642`;
- diagnostic workflow: `30749858956`;
- diagnostic artifact: `8834080073`;
- diagnostic digest: `sha256:85967a8a6039585559511bccc86c1d053e2e51432ddff17faf1030693ae0f727`;
- verified semantic workflow: `30749965825`;
- verified artifact: `8834113947`;
- verified artifact digest: `sha256:b79c4aa42a7a6bbeec9de6f0f45a228794ce46e8c6ac22c8610839c6731c822f`;
- staging workflow: `30750064883`;
- TSX structural AST, JSX text slots, direct `className` utility-token sets and exact comment sequences are identical before and after formatting;
- four targeted catalog/detail/layout/sensor-placement UI test files passed;
- patch review confirms reflow plus canonical Tailwind utility ordering only;
- ARIA labels, visible strings, icons, coordinates, event handlers, conditions and assertions are unchanged;
- clean commit `35fc2d51c5b6d1c794c81cc1488e97a73043e683` was created directly from baseline `402df05d516af08f1d001e3b80bcb174c33197e0` using the 17 verified blob SHA values;
- final source diff contains exactly the 17 allowlisted files before mandatory project-state updates;
- all temporary diagnostic/evidence/staging workflows are absent from the final branch history and diff.

No product redesign, defect fix, refactor, dependency, runtime, deployment, hardware or Modbus behavior changed.

After Issue #197, zero paths remain in the historical 46-file Prettier backlog.

## Open Pull Requests

- #229 — formatting-only refrigeration UI Work Package; project-state finalization and exact-head CI are in progress.
- #217–#221 — queued Dependabot workflow-runtime updates; separate maintenance scope.

## Next Ready Work Package

After PR #229 reaches final exact-head GREEN and is merged, execute a repository-wide locked Prettier zero-difference verification, update project state and close parent Issue #185. Hardware Issues #200–#202 remain blocked pending read-only physical evidence.
