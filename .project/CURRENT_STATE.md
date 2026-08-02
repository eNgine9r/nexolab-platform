# NEXOLAB Current State

Updated: 2026-08-02  
Verified main baseline: `16f1c04616541e7d2391a13eb9eb6b8fb955567c`  
Active Work Package: Issue #193 / PR #225 — format the three historical documentation files  
Status confidence: high for repository state, formatting-only evidence, current Prettier inventory, linux/amd64 CI, encrypted software recovery and disconnected-container evidence; partial for ARM64 actual-host, Raspberry Pi, reboot, power-loss and hardware acceptance.

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
- PR #192 — exact 46-file historical Prettier inventory, merged as `16f1c04616541e7d2391a13eb9eb6b8fb955567c`.

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

The formatting sequence remains split into focused Work Packages:

- Issue #193 — documentation: 3 files;
- Issue #194 — E2E/root tooling: 6 files;
- Issue #195 — telemetry/dashboard frontend: 10 files;
- Issue #196 — refrigeration domain/repositories: 10 files;
- Issue #197 — refrigeration UI: 17 files, depends on #196.

## Issue #193 outcome

PR #225 applies Prettier only to:

- `docs/operations/capacity-release-gate.md`;
- `docs/operations/observability.md`;
- `docs/rs485/evidence-standard.md`.

Verified evidence:

- Prettier version: `3.9.6`;
- generation workflow: `30742929245`;
- evidence artifact: `8831904927`;
- artifact digest: `sha256:e19ea8a75f6f8c96656a403f1f2638b4af79071384a72504696926e1d4dfd543`;
- formatted file digests:
  - capacity release Gate: `fa3bdc6acd8f82314aab93bd55b806859c1099cd330b81809b244306623e41a0`;
  - observability runbook: `1105f999807c3acd95d190461d164f487b5c2fab987acfec516fcc37e9bb09c2`;
  - RS-485 evidence standard: `f8ec6f1fcdba25f36daf0bdf929509de91a1bee7e3bca34d93884e94b21fa251`.

Patch review confirms only Markdown table alignment changed. No wording, number, threshold, image tag, command, path, contract or safety statement changed. The temporary generation/write workflow was removed before final review.

No runtime, source, configuration, dependency, `.prettierignore`, production data, hardware or Modbus path changed. After these three files are merged, 43 paths remain in the recorded historical formatting backlog.

## Open Pull Requests

- #225 — formatting-only documentation Work Package; project-state finalization and exact-head CI are in progress.
- #217–#221 — queued Dependabot workflow-runtime updates; separate maintenance scope.

## Next Ready Work Package

After PR #225 reaches final exact-head GREEN and is merged, start Issue #194: format only the six inventoried E2E/root tooling files. Do not combine formatting groups or product changes. Hardware Issues #200–#202 remain blocked pending read-only physical evidence.
