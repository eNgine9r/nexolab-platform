# NEXOLAB Current State

Updated: 2026-08-02  
Verified main baseline: `ab3c95809dc349a6b45c079ad4614758173a1e0e`  
Active Work Package: Issue #205 / PR #234 — upgrade GitHub Actions runtime dependencies with full compatibility evidence  
Status confidence: high for repository state, formatting baseline, GitHub-hosted CI, linux/amd64 disconnected-container evidence and encrypted software recovery; partial for ARM64 actual-host, Raspberry Pi, reboot, power-loss and hardware acceptance.

## Profile

- Project type: `LOCAL_LAN`
- Development internet: allowed
- Runtime internet: not required
- Mandatory paid runtime services: prohibited
- Device transport: read-only Modbus RTU and MQTT QoS 1
- No Modbus write, hardware write or production/site cutover is authorized.

## Completed reliability and maintenance baseline

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
- PR #225–#229 — controlled formatting of the exact 46-file historical inventory.
- PR #233 — permanent repository-wide Prettier `3.9.6` zero-difference CI gate, merge `e1e0e2311d1818157e3326ae9ca67adbf24813d5`.

Issues #185 and #230 are closed completed. The historical formatting backlog is zero.

## Issue #189 remaining boundary

The software-only recovery portion is verified and merged. Issue #189 remains open only for controlled actual-host evidence:

- central-host reboot;
- Raspberry Pi reboot;
- edge power interruption and SQLite outbox recovery;
- physical power-loss behavior;
- actual disk-full/disk-loss behavior;
- operator-owned physical-media restore.

These outcomes must not be inferred from container evidence.

## Issue #205 / PR #234 outcome in progress

The Work Package upgrades all supported GitHub Actions runtime majors in one controlled branch rather than merging overlapping Dependabot PRs independently.

Target matrix:

- `actions/checkout@v4` → `@v6`;
- `actions/setup-node@v4` → `@v6`;
- `actions/setup-python@v5` → `@v7`;
- `actions/upload-artifact@v4` → `@v7`;
- `actions/download-artifact@v4` → `@v8`;
- Docker QEMU, Buildx and login actions `@v3` → `@v4`;
- `docker/metadata-action@v5` → `@v6`;
- `docker/build-push-action@v6` → `@v7`.

Compatibility and hardening decisions:

- all 36 permanent checkout steps explicitly set `persist-credentials: false`;
- all 16 setup-node steps explicitly set `package-manager-cache: false` to preserve prior no-cache behavior unless a workflow already has an explicit npm cache input;
- no `pull_request_target`, `workflow_run` or self-hosted runner was introduced;
- workflow permissions, triggers, paths, conditions, secrets references, runner labels and action inputs remain otherwise unchanged;
- the pinned Trivy action SHA remains unchanged;
- no npm, Python or container dependency was upgraded.

Read-only and transformation evidence:

- inventory run `30752317242`, artifact `8834828551`;
- input compatibility run `30752487637`, artifact `8834884979`;
- verified transformed artifact run `30753198442`, artifact `8835111194`;
- clean implementation commit `ceafcb718071396c43b4e06cbc5d9ea1f12f8fbd` is one parent from exact main `ab3c95809dc349a6b45c079ad4614758173a1e0e` and changes exactly 26 permanent workflow files;
- all temporary inventory/apply/artifact workflows are absent from final branch history and diff.

Initial compatibility sweep on equivalent implementation head `617051a6c14195d13383872dd1c58cdac3417e2d`:

- 26 of 26 permanent workflows completed GREEN;
- CI, all browser acceptance suites, telemetry, secure broker/fleet, RS-485, disaster recovery, observability, capacity, container supply-chain and Offline Bundle passed;
- Container Supply Chain successfully uploaded per-image artifacts, downloaded and merged them with `download-artifact@v8`, then uploaded aggregate evidence;
- Offline Bundle built the linux/amd64 archive, removed local runtime images, blocked container egress, loaded the archive, started with pull disabled and preserved named-volume data through update/rollback;
- Offline Bundle run `30754351605`, artifact `8835562629`, digest `sha256:ccff0304ac8d3b2fe3e0378add5896990e18409b92b1598f41949d8627dc3990`.

The same 26-workflow sweep must repeat on the final state-updated head before merge.

## Open Pull Requests

- #234 — controlled GitHub Actions runtime compatibility Work Package.
- #217–#221 — Dependabot PRs superseded by #234; close only after #234 merges.

Duplicate Issue #235 was closed because Issue #205 already owns the overlapping workflow scope.

## Open risks and blockers

- Existing React test warnings about unwrapped `act(...)`, non-boolean DOM attributes and duplicate keys remain outside Issue #205; suites are GREEN.
- Issue #189 physical recovery evidence remains unverified.
- Hardware Issues #200–#202 remain blocked pending controlled read-only physical evidence.
- Complete `linux/arm64` offline archive/load/start/update/rollback execution on an actual Raspberry Pi 5 remains unverified.

## Next Ready Work Package

After PR #234 reaches final exact-head GREEN and merges, close superseded Dependabot PRs #217–#221 and mark Issue #205 done. Then start Issue #203: review production dependency updates as a separate application-dependency Work Package. Issue #204 remains queued for major frontend migration planning.
