# NEXOLAB Current State

Updated: 2026-08-02
Verified main baseline: `36b63cd6aba96c0fcb0e7f8649496e0207840cf3`
Active Work Package: Issue #239 / PR #240 — patch the Next.js 16.2 and React 19.2 security line
Parent maintenance track: Issue #203 — focused production dependency updates
Status confidence: high for repository state, deterministic lockfile generation, GitHub-hosted CI, browser acceptance and linux/amd64 disconnected runtime; partial for actual Raspberry Pi, ARM64 host, reboot, power-loss and physical hardware acceptance.

## Profile

- Project type: `LOCAL_LAN`.
- Development internet is allowed; core runtime internet and paid cloud services are not required.
- Local PostgreSQL, MQTT, edge SQLite, logs, backup and restore remain first-class.
- No Modbus write, hardware write or production/site cutover is authorized.

## Completed maintenance baseline

- PR #184 — AI Development Operating Standard.
- PR #190 — verified architecture and offline boundary.
- PR #206 — tracker and Pull Request reconciliation.
- PR #207 — durable MQTT-to-PostgreSQL ingestion.
- PR #209 — Device Agent supply-chain hardening.
- PR #213 — dashboard security diagnostics.
- PR #214 — WebSocket lifecycle stabilization.
- PR #215 — offline installation/update bundle.
- PR #216 — offline operator authentication.
- PR #224 — encrypted local-auth disaster recovery.
- PR #225–#229 and #233 — controlled Prettier baseline.
- PR #234 — GitHub Actions runtime compatibility.
- PR #238 / Issue #237 — argument-safe DR credentials, merged as `36b63cd6aba96c0fcb0e7f8649496e0207840cf3`.

## Issue #239 / PR #240 outcome

The framework security group is isolated from Supabase, Lucide and major toolchain migrations.

Direct changes:

- `next`: `16.2.10` → `16.2.12`;
- `eslint-config-next`: `16.2.10` → `16.2.12`;
- `react`: `19.2.4` → `19.2.8`;
- `react-dom`: `19.2.4` → `19.2.8`.

Deterministic package evidence:

- generation/audit run `30762557284` — GREEN;
- artifact `8837927439`, digest `sha256:79caeea78bfb8a4b1e212a2a31abd9d4259113966cfc11fe930c11de023eebfd`;
- `package.json` SHA-256 `70b43835bd19f3c0f405430680494651a18f8b32d54ac4c69bafaf3d350d5556`;
- `package-lock.json` SHA-256 `cc3746f2e95fc449350bd2e92d65754f1b9b8e9acb2f12b1a08cb41572d813d7`;
- Supabase remains resolved at `2.110.8`;
- Lucide remains resolved at `1.26.0`.

Audit classification:

- all direct Next.js advisories affecting `<16.2.11` are removed;
- remaining production risk: transitive `sharp 0.34.5`, advisory range `<0.35.0`;
- Next.js `16.2.12` constrains optional `sharp` to `^0.34.5`, so forcing `0.35.x` is excluded from this PR;
- Playwright `1.55.0` is a dev-tool advisory and remains isolated under the toolchain track.

Verified implementation head `814fc1d46003c2b786e5bb73723b654ce5e3fffe`:

- exactly `package.json` and `package-lock.json` changed;
- CI `30764056361` — formatting, lint, typecheck, 181 tests and production build GREEN;
- Security Browser `30764056348` — GREEN, artifact `8838386715`, digest `sha256:0904ac5269fbb49aee58096be97236b258d615aba74ae96f828ab02491295692`;
- Authenticated Dashboard `30764056342` — GREEN, artifact `8838388043`, digest `sha256:6674f3a2402ce008813ff193cca55dafc47cf55cc38dde942f1021f815b91b20`;
- Refrigeration Browser `30764056354` — GREEN, artifact `8838383301`, digest `sha256:e103e86fc620fcf8349ee76e86a03ece195601ac67e9907be8031cd8fd59fecb`;
- Offline Bundle `30764056351` — disconnected load/start and update/rollback volume preservation GREEN, artifact `8838464830`, digest `sha256:4fb9e27a84ecc42fea42a4f8269a5b6a464f51c4a1fb46d786560877a2272730`;
- reports, rendered reports, alerts, sessions, nodes and offline-auth workflows also completed GREEN.

## Open Pull Requests

- #240 — verified framework package/lock implementation; pending final exact-head CI after state update, review audit and merge.

## Open risks and blockers

- No hard blocker prevents completing PR #240.
- `sharp 0.34.5` requires a separate focused compatibility Work Package after merge.
- Playwright `1.55.0` remains outside Issue #239.
- Issue #189 actual-host recovery evidence remains unverified.
- Hardware Issues #200–#202 remain blocked pending controlled read-only evidence.
- Actual Raspberry Pi 5 ARM64 offline update/rollback remains unverified.
- Existing non-failing frontend test warnings are pre-existing and out of scope.

## Next Ready Work Package

Finish and merge PR #240 on exact-head GREEN. Then create a focused Issue for the transitive `sharp` risk. Continue parent Issue #203 with separate Supabase and Lucide compatibility groups; keep Issue #204 toolchain migrations isolated.
