# NEXOLAB Current State

Updated: 2026-08-03
Verified main baseline: `83b161ca7e26580c46789e76a7bbdc0d5e434c21`
Active Work Package: Issue #242 / PR #248 — optional Supabase dependency compatibility
Status confidence: high for dependency scope, adapter behavior, local software checks and exact-head GitHub acceptance workflows.

## Issue #242 outcome

- `@supabase/supabase-js` moved from resolved `2.110.8` to `2.112.0`.
- Its five direct Supabase packages (`auth-js`, `functions-js`, `postgrest-js`, `realtime-js` and `storage-js`) moved together to `2.112.0`; `phoenix 0.4.5`, `iceberg-js 0.8.1` and `tslib 2.8.1` did not change.
- The only SDK import remains `src/features/security/supabase-auth.ts`.
- Client creation remains browser-only and requires both public Supabase configuration values.
- Regression coverage proves missing configuration creates no client and performs no fetch.
- Regression coverage proves `local` authentication remains primary and fail-closed even when invalid Supabase values are present.
- No authentication architecture, UI, schema, Compose, telemetry, hardware, Lucide, Sharp, Next.js, React, secrets or production configuration changed.

## Checks actually completed

Local checks on Node `22.23.2`:

- targeted Supabase and local-auth Vitest coverage;
- `npm run format:check`;
- `npm run lint`;
- `npm run typecheck`;
- `npm test`;
- `npm run build`.

Exact-head GitHub workflows for `73cf19b2e7191a38290b3dc99fa211bdaf038878` are GREEN:

- CI `30800858215`;
- Security Browser Acceptance `30800857389`;
- Offline Auth Acceptance `30800857575`;
- Authenticated Dashboard Acceptance `30800857397`;
- Offline Bundle `30800858287`;
- Refrigeration Browser Acceptance `30800857965`;
- Nodes Browser Acceptance `30800857446`;
- Alerts Browser Acceptance `30800858049`;
- Test Sessions Browser Acceptance `30800857431`;
- Reports Browser Acceptance `30800857402`;
- Rendered Reports Browser Acceptance `30800857520`.

The disconnected Offline Bundle workflow includes image load/start with blocked container egress and update/rollback volume-preservation evidence.

## Runtime, offline and hardware evidence

- Supabase remains optional and unconfigured LOCAL_LAN operation performs no Supabase request.
- Local authentication remains the primary runtime path.
- No mandatory cloud, CDN, remote font, analytics or paid runtime dependency was introduced.
- No hardware operation was in scope or performed.
- Actual Raspberry Pi acceptance for Issue #245 remains separate and must not be marked hardware verified.

## Review and next action

- PR #248 head is mergeable and exact-head workflows are GREEN.
- Project state now records completed CI rather than the obsolete `pending_pr_ci` state.
- Resolve the state-review thread, merge PR #248 with expected head `73cf19b2e7191a38290b3dc99fa211bdaf038878`, then begin Issue #243.
- The resulting merge SHA must be recorded in the next state checkpoint because it does not exist until GitHub completes the merge.
