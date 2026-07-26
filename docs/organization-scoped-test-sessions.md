# Organization-scoped production test sessions

Sprint 12 starts by closing the multi-tenant boundary around the existing NEXOLAB session lifecycle.

## Existing capability

The platform already supports draft, ready, running, paused, completed, cancelled and archived states; idempotent lifecycle commands; production channel bindings; versioned limits; configuration snapshots; stages; notes; audit records; and telemetry attribution.

## Required production boundary

Every session and every child resource must belong to one organization. The authenticated organization selected by the verified user session is authoritative for all list, read, create, patch, transition, stage, note, audit, configuration and telemetry operations.

A foreign session identifier must not reveal whether the session exists. Browser-provided roles and actor identifiers are untrusted. Audit actors come from the verified backend principal.

## Frontend transport

The Session API client must reuse the Sprint 11 runtime credential provider and attach:

- `Authorization: Bearer <access token>`;
- `X-Organization-ID: <selected organization>`.

Changing organizations invalidates the complete session workspace and starts a new organization-scoped load. Logout removes all session access immediately.

## Database migration

The migration will:

1. add `organization_id` to `test_sessions`;
2. backfill existing rows to the configured default organization;
3. make the column non-null;
4. replace global session-number uniqueness with organization-scoped uniqueness;
5. add organization-first list and lookup indexes.

## Acceptance

A controlled browser Gate will prove anonymous denial, Viewer read-only behavior, Engineer lifecycle operations, immutable completed sessions, telemetry attribution, idempotent replay, verified audit actors and cross-organization non-disclosure using real Next.js, FastAPI, PostgreSQL and MQTT.
