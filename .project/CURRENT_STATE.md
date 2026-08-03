# NEXOLAB Current State

Updated: 2026-08-03
Verified main baseline: `3623be1f2778ea283200e6a5d2278c5f1326c434`
Active Work Package: Issue #241 / PR #244 — resolve the transitive `sharp` production advisory
Parent maintenance track: Issue #203 — focused production dependency updates
Status confidence: high for repository state, dependency evidence, linux/amd64 native runtime, GitHub-hosted quality checks and lockfile ARM64 package metadata; partial for actual Raspberry Pi 5 execution, reboot, power-loss and physical hardware acceptance.

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
- PR #238 — argument-safe disaster-recovery credentials.
- PR #240 / Issue #239 — Next.js 16.2.12 and React 19.2.8 security patch line, merged as `3623be1f2778ea283200e6a5d2278c5f1326c434` after 11-of-11 exact-head GREEN workflows.

## Issue #241 / PR #244 candidate outcome

Baseline evidence proved the production path is `next@16.2.12 -> sharp@0.34.5`; NEXOLAB application source has no direct `sharp` import. GitHub advisory `GHSA-f88m-g3jw-g9cj` affects `sharp <0.35.0`, while the current Next.js 16.2 line still declares optional `sharp` as `^0.34.5`.

The smallest remediation candidate adds only:

- `overrides.sharp = 0.35.3` in `package.json`;
- the deterministic `package-lock.json` graph for `sharp 0.35.3` and libvips `8.18.3`.

Evidence:

- baseline run `30782736886`, artifact `8844227708`, digest `sha256:97a7780a9738776a1cd31fe8859eed5830695d438921e25843fc3be7b47c71ca`;
- candidate run `30785495411`, artifact `8845125944`, digest `sha256:a5d82492f62c95240df61e00992dc66f162cc0563ed860339a896b14e0f1ed81`;
- candidate `package.json` SHA-256 `370a941f8b8995b59fe6f8199c5a6b9e0ad1085f03d4a0f14e3f698ac5432e06`;
- candidate `package-lock.json` SHA-256 `302c4cd59a40dd4462e51d2eb251519929d80d9fb5d614b3dc409142477e5350`;
- `npm ls sharp --omit=dev` resolves only `sharp 0.35.3`;
- production audit has no `sharp` or `next` advisory entry;
- linux/x64 native SVG-to-PNG smoke passed with libvips `8.18.3`;
- linux/arm64 glibc and musl native packages are present with integrity metadata in the lockfile;
- repository-wide formatting, ESLint, strict typecheck, Vitest and production build passed in the candidate workflow.

Clean implementation head `f9594f517b5b9e8a8b94da53da4b36f5a5abec8b` contains exactly `package.json` and `package-lock.json`. Temporary evidence/publisher workflows are absent from its history and diff.

## Open Pull Requests

- #244 — verified `sharp 0.35.3` override candidate; 11-of-11 workflows and review audit are GREEN on `82c83d5357da62cdb30e9c1f692c750f74da773c`; pending merge.

## Open risks and blockers

- No hard blocker prevents completing PR #244.
- The override intentionally exceeds Next.js 16.2.12's declared `^0.34.5` range; compatibility is evidence-backed and must be removed or reassessed when Next.js publishes a supported patched range.
- Playwright `1.55.0` remains a separate dev-tool advisory under Issue #204.
- Actual Raspberry Pi 5 ARM64 execution remains unverified; only package/build metadata is verified.
- Issue #189 actual-host recovery evidence remains unverified.
- Hardware Issues #200–#202 remain blocked pending controlled read-only evidence.

## Next Ready Work Package

Merge PR #244 with expected exact head after the final state-only sweep. Then execute Issue #242 as a separate optional-Supabase/offline-auth compatibility review. Issue #243 remains queued independently for Lucide operator semantics.

## Issue #241 final verification sweep

Verification head `82c83d5357da62cdb30e9c1f692c750f74da773c` completed all 11 permanent workflows GREEN:

- CI `30786862301`;
- Security Browser `30786862321`, artifact `8845566996`;
- Authenticated Dashboard `30786862289`, artifact `8845567008`;
- Refrigeration Browser `30786862297`, artifact `8845563069`;
- Offline Auth `30786862303`, artifact `8845627973`;
- Offline Bundle `30786862331`, artifact `8845690195`;
- Nodes, Alerts, Test Sessions, Reports and Rendered Reports also GREEN.

Review audit: 0 review threads and 0 submitted reviews requiring action. The final state-only commit must repeat exact-head checks before merge.
