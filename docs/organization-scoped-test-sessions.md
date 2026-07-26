# Organization-scoped production test sessions

Sprint 12 starts by closing the multi-tenant boundary around the existing NEXOLAB session lifecycle.

## Existing capability

The platform already supports draft, ready, running, paused, completed, cancelled and archived states; idempotent lifecycle commands; production channel bindings; versioned limits; configuration snapshots; stages; notes; audit records; and telemetry attribution.

## Required production boundary

Every session and every child resource must belong to one organization. The authenticated organization selected by the verified user session is authoritative for all list, read, create, patch, transition, stage, note, audit, configuration and telemetry operations.

A foreign session identifier must not reveal whether the session exists. Browser-provided roles and actor identifiers are untrusted. Audit actors come from the verified backend principal.

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

The migration itself has no persistent server default. Repository creation will be changed to pass the authorized principal organization explicitly before the temporary model compatibility default is removed.

## Acceptance

A controlled browser Gate will prove anonymous denial, Viewer read-only behavior, Engineer lifecycle operations, immutable completed sessions, telemetry attribution, idempotent replay, verified audit actors and cross-organization non-disclosure using real Next.js, FastAPI, PostgreSQL and MQTT.
