# Organization-scoped production test sessions

Sprint 12 starts by closing the multi-tenant boundary around the existing NEXOLAB session lifecycle.

## Existing capability

The platform already supports draft, ready, running, paused, completed, cancelled and archived states; idempotent lifecycle commands; production channel bindings; versioned limits; configuration snapshots; stages; notes; audit records; and telemetry attribution.

## Required production boundary

Every session and every child resource belongs to one organization. The authenticated organization selected by the verified user session is authoritative for all list, read, create, patch, transition, stage, note, audit, configuration and telemetry operations.

A foreign session identifier does not reveal whether the session exists. Browser-provided roles and actor identifiers are untrusted. Audit actors come from the verified backend principal.

Repository instances are scoped with `for_organization(...)`. The scope is applied to session creation, number conflicts, idempotent create replay, list/get/patch/lifecycle operations, child-resource ownership checks and session telemetry existence checks. The same session number and create idempotency key may be used independently in different organizations.

## Frontend transport

The Session API client reuses the Sprint 11 runtime credential provider and attaches:

- `Authorization: Bearer <access token>`;
- `X-Organization-ID: <selected organization>`.

Credentials are resolved for every request instead of being frozen when the client is created. Token refresh and organization switching therefore apply to existing list, wizard and workspace clients without rebuilding application state manually.

Changing organizations invalidates the complete session workspace and starts a new organization-scoped load. Logout removes all session access immediately.

## Database migration

Migration `20260726_0009`:

1. adds `organization_id` to `test_sessions`;
2. backfills existing rows to the default organization created by the RBAC migration;
3. makes organization ownership non-null and adds a restrictive organization foreign key;
4. replaces global session-number uniqueness with `organization_id + session_number` uniqueness;
5. adds organization-first state and node indexes.

The migration and model have no persistent organization default. Every new session receives organization ownership explicitly from the scoped repository selected by the authorized principal.

## Create idempotency namespace

Create-command keys remain client-generated, but their persisted lookup key is a SHA-256 namespace of the verified organization ID and normalized client key. This preserves deterministic replay while preventing a key used in one organization from blocking another organization.

## Delivery hygiene

Generated Python bytecode and temporary mutation workflows are excluded from the production branch. Organization regressions are validated through normal frontend and telemetry-service pipelines before the dedicated browser Gate is allowed to merge.

## Acceptance

Repository and API integration tests verify organization-scoped create replay, duplicate session numbers across organizations, isolated lists, foreign-ID non-disclosure, verified JWT actor attribution and ownership checks before configuration or telemetry queries.

The controlled browser Gate proves anonymous denial, Viewer read-only behavior, Engineer lifecycle operations, immutable completed sessions, telemetry attribution and idempotent replay using real Next.js, FastAPI, PostgreSQL and MQTT. Its engineering principal also receives the independent Auditor role so the Gate validates permission union without expanding the production Engineer role.
