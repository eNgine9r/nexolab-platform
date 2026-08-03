# NEXOLAB Current State

Updated: 2026-08-03
Verified main baseline: `cc865098e7d1ffa81313c34c32672276c8bc51a9`
Active Work Package: Issue #203 — close focused production dependency maintenance
Status confidence: high for repository state, dependency decisions, exact-head quality gates and disconnected runtime evidence; physical Raspberry Pi acceptance remains separate and pending.

## Production dependency maintenance outcome

Parent Issue #203 has completed all focused compatibility groups:

- Issue #239 / PR #240 — Next.js and React security patch line, merged as `3623be1f2778ea283200e6a5d2278c5f1326c434`.
- Issue #241 / PR #244 — transitive `sharp 0.35.3` compatibility control, merged as `2c00812aed7bc107f191a50e2e0745cb9c091bbd`.
- Issue #242 / PR #248 — optional Supabase SDK updated to resolved `2.112.0` with local authentication remaining primary and offline-safe, merged as `33224e148c733e50896fe68c13c53130e0a7afac`.
- Issue #243 / PR #249 — Lucide resolved `1.26.0` retained with regression coverage for Energy semantics and icon-button accessibility, merged as `cc865098e7d1ffa81313c34c32672276c8bc51a9`.

## Acceptance evidence

- Every compatibility group used a separate Issue, branch and focused Pull Request.
- Framework and security updates were handled before optional cloud and icon-library work.
- Lockfile movement was reviewed per group.
- Supabase remains optional; missing configuration creates no client or network request.
- LOCAL_LAN local authentication remains primary and fail-closed.
- Lucide `1.27.0` was not adopted because it changes the used `Zap` operator icon without a security or runtime requirement.
- The Lucide regression test fixes `Zap → Енергомоніторинг → /energy` and the accessible refrigeration icon-button contract.
- No mandatory CDN, external telemetry, cloud API, online license or paid runtime dependency was introduced.
- Exact-head formatting, ESLint, strict TypeScript, Vitest and production builds passed for each merged group.
- Relevant browser acceptances passed where affected.
- Disconnected Offline Bundle startup and update/rollback volume-preservation evidence passed on the final Supabase and Lucide heads.

## Remaining dependency risks

- The temporary `sharp 0.35.3` override must be reassessed when Next.js publishes a supported patched optional range.
- Playwright `1.55.0` remains a development-tool concern under Issue #204; it is not a mandatory runtime dependency.
- Major TypeScript, ESLint, jsdom, lint-staged and Playwright migrations remain explicitly outside Issue #203.

## Runtime and hardware status

```text
software dependency maintenance verified; no hardware operation performed
```

Actual Raspberry Pi evidence remains pending for Issue #245 and recovery Issue #189. Issues #200–#202 remain blocked on controlled read-only physical evidence. No Modbus or hardware write was performed.

## Next Ready Work Package

Issue #204 — plan and split major frontend toolchain migrations into focused compatibility Work Packages. First action: build the compatibility matrix and migration order before changing any package.
