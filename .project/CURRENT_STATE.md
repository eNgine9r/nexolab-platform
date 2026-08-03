# NEXOLAB Current State

Updated: 2026-08-03
Verified main baseline: `83b161ca7e26580c46789e76a7bbdc0d5e434c21`
Active Work Package: Issue #242 — optional Supabase dependency compatibility
Status confidence: high for dependency, adapter and local software checks; container-based offline acceptance awaits GitHub CI because Docker is unavailable on this host.

## Issue #242 outcome

- `@supabase/supabase-js` moved from resolved `2.110.8` to the current stable `2.112.0` patch/minor line.
- Its five direct Supabase packages (`auth-js`, `functions-js`, `postgrest-js`, `realtime-js` and `storage-js`) moved together to `2.112.0`; `phoenix 0.4.5`, `iceberg-js` and `tslib 2.8.1` did not change.
- The upstream release is compatible with the repository's Node `>=22` contract and contains incremental auth, PostgREST, storage and opt-in tracing changes without a documented breaking adapter change.
- GitHub's published repository-advisory endpoint reported no Supabase JS advisories at review time.
- The only SDK import remains `src/features/security/supabase-auth.ts`. Client creation is browser-only and requires both public configuration values.
- Regression coverage proves missing configuration creates no client and performs no fetch, while `local` remains the primary provider even if Supabase values are invalid.
- No runtime code, auth architecture, UI, schema, Compose, hardware code, secrets or unrelated dependencies changed.

## Verification

Passed locally on Node `22.23.2`:

- targeted Supabase and local-auth Vitest coverage;
- repository Prettier check;
- ESLint;
- strict TypeScript;
- complete Vitest suite;
- Next.js production build.

Security Browser, Offline Auth, Authenticated Dashboard, disconnected Offline Bundle and update/rollback volume preservation are pending on GitHub CI because this execution host has no Docker executable.

## Open risks and next action

- Review the exact PR head, confirm required CI and offline workflows are GREEN, confirm no unrelated lockfile movement or unresolved review thread, then merge Issue #242.
- Actual Raspberry Pi acceptance for Issue #245 remains separate and must not be marked hardware verified.
- After #242, Issue #243 is the next dependency Work Package.
