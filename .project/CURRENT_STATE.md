# NEXOLAB Current State

Updated: 2026-08-02  
Verified main baseline: `786f4568650f5a8bbb3efa5e22445d3f88b706b0`  
Active Work Package: Issue #230 / PR #233 — close the controlled Prettier baseline with a permanent repository-wide zero-difference gate  
Status confidence: high for repository state, formatting baseline, linux/amd64 CI, encrypted software recovery and disconnected-container evidence; partial for ARM64 actual-host, Raspberry Pi, reboot, power-loss and hardware acceptance.

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

## Controlled Prettier baseline

Issue #191 established an exact Prettier `3.9.6` historical debt inventory of 46 maintained files. The debt was cleared through focused formatting-only Work Packages:

- Issue #193 / PR #225 — 3 documentation files, merge `75fb9f2921053d39187bbf216057913be2c7fe43`;
- Issue #194 / PR #226 — 6 E2E/root tooling files, merge `cb8f4b21d24c00f1d6a501b69ed8af4db55f353e`;
- Issue #195 / PR #227 — 10 telemetry/dashboard files, merge `c5fa0fdcca6d86f54ba7430b5ca8efd7ffc39f8c`;
- Issue #196 / PR #228 — 10 refrigeration domain/repository files, merge `402df05d516af08f1d001e3b80bcb174c33197e0`;
- Issue #197 / PR #229 — 17 refrigeration UI files, merge `786f4568650f5a8bbb3efa5e22445d3f88b706b0`.

All 46 inventoried paths are complete. No generated/vendor path or new `.prettierignore` exclusion was introduced.

## Issue #230 outcome in progress

PR #233 replaces the temporary changed-file-only formatting check with the permanent repository-wide gate:

```text
npm run format:check
```

The workflow runs the command behind `set -euo pipefail` and preserves failure diagnostics through `tee`, so a failed Prettier command cannot be masked.

Initial exact-head evidence on `b978a1cdee95c6ab1f8e566b787e6ba7997ed8de`:

- CI run `30751629252` — GREEN;
- `prettier --check .` reported `All matched files use Prettier code style!`;
- ESLint passed;
- strict TypeScript typecheck passed;
- Vitest passed 39 files and 181 tests;
- Next.js production build passed.

The final PR head must repeat the same repository-wide check after baseline and project-state updates. Parent Issue #185 remains open until PR #233 reaches exact-head GREEN and merges.

## Open Pull Requests

- #233 — final controlled Prettier baseline closure gate.
- #217–#221 — queued Dependabot workflow-runtime updates; separate maintenance scope.

## Open risks and blockers

- Existing React test warnings about unwrapped `act(...)`, non-boolean DOM attributes and duplicate keys remain outside Issue #230; the suites still pass and no runtime source is changed here.
- Issue #189 physical recovery evidence remains unverified.
- Hardware Issues #200–#202 remain blocked pending controlled read-only physical evidence.
- Complete `linux/arm64` offline archive/load/start/update/rollback execution on an actual Raspberry Pi 5 remains unverified.

## Next Ready Work Package

After PR #233 reaches final exact-head GREEN and is merged, close Issue #230 and parent Issue #185, then select the next independent queued maintenance Work Package from Issues #203–#205. Hardware work remains blocked until physical access is available.
