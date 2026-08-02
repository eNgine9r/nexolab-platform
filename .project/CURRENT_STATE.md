# NEXOLAB Current State

Updated: 2026-08-02  
Verified main baseline: `f54cd7b6f6db580f3931a40889f5b4e33af3cc30`  
Active Work Package: Issue #191 / PR #192 — inventory and partition historical Prettier debt  
Status confidence: high for repository state, current Prettier inventory, linux/amd64 CI, encrypted software recovery and disconnected-container evidence; partial for ARM64 actual-host, Raspberry Pi, reboot, power-loss and hardware acceptance.

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
- PR #224 — encrypted local-auth disaster-recovery extension, merged as `f54cd7b6f6db580f3931a40889f5b4e33af3cc30`.

## Issue #189 remaining boundary

The software-only recovery portion is verified and merged. Issue #189 remains open only for controlled actual-host evidence:

- central-host reboot;
- Raspberry Pi reboot;
- edge power interruption and SQLite outbox recovery;
- physical power-loss behavior;
- actual disk-full/disk-loss behavior;
- operator-owned physical-media restore.

These outcomes must not be inferred from container evidence.

## Issue #191 Prettier inventory outcome

PR #192 was rebuilt on current `main` instead of relying on its stale July baseline.

Read-only workflow run `30742515790` checked out exact `main` SHA `f54cd7b6f6db580f3931a40889f5b4e33af3cc30` and executed Prettier `3.9.6` with:

```text
npm exec prettier -- --list-different .
```

Verified result:

- exact historical debt: **46 files**;
- line endings: **46 LF**, 0 CRLF, 0 mixed, 0 lone CR;
- extension distribution: 3 Markdown, 1 MJS, 21 TypeScript and 21 TSX;
- generated/vendor candidates: 0;
- new `.prettierignore` exclusions justified: 0;
- evidence artifact ID: `8831767220`;
- artifact digest: `sha256:5d55e49b403eca21dbfa798a360574d383fe3c4f4e27abacc77626aefb4569e7`.

The prior 48-file inventory is stale. These two files are now Prettier-clean and were removed from the backlog:

- `src/components/dashboard/dashboard-shell.tsx`;
- `src/lib/telemetry/websocket-client.ts`.

Current focused groups:

- Issue #193 — documentation: 3 files;
- Issue #194 — E2E/root tooling: 6 files;
- Issue #195 — telemetry/dashboard frontend: 10 files;
- Issue #196 — refrigeration domain/repositories: 10 files;
- Issue #197 — refrigeration UI: 17 files, depends on #196.

The durable exact path inventory is `docs/maintenance/prettier-baseline.md`. The temporary inventory workflow is removed before final review. No runtime/source file is reformatted in Issue #191.

## Open Pull Requests

- #192 — refreshed controlled Prettier inventory and project-state finalization.
- #217–#221 — queued Dependabot workflow-runtime updates; separate maintenance scope.

## Next Ready Work Package

After PR #192 reaches final exact-head GREEN and is merged, start Issue #193: format only the three inventoried documentation files. Do not combine formatting groups or product changes. Hardware Issues #200–#202 remain blocked pending read-only physical evidence.
