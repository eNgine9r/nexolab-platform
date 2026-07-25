# NEXOLAB authentication, RBAC and audit architecture

## Boundary

This production scope is intentionally independent of Raspberry Pi, Modbus, RS-485 and the actual laboratory network. It is implemented and validated through GitHub Actions, PostgreSQL integration tests and browser E2E tests.

## Identity sources

The backend accepts a provider-neutral authenticated principal derived from a verified OIDC/JWT token. Supabase Auth can be the first provider, but authorization code must not depend on Supabase-specific user metadata.

Browser-supplied actor identifiers are never trusted. Edge/service credentials remain separate from user credentials.

## Organization boundary

Every protected resource belongs to an organization. Authorization requires both:

1. membership in the resource organization;
2. the permission required for the operation.

Organization mismatch is denied before role evaluation. Cross-organization access is never inferred from a global role claim.

## Roles

| Role                 | Intended responsibility                                         |
| -------------------- | --------------------------------------------------------------- |
| `administrator`      | Memberships, roles, configuration and all operations            |
| `laboratory_manager` | Equipment, sessions, publication, approvals and audit review    |
| `engineer`           | Equipment layouts, sessions, publication and operational review |
| `operator`           | Live operation, draft editing and alert acknowledgement         |
| `viewer`             | Read-only dashboard, telemetry and reports                      |
| `auditor`            | Read-only evidence, reports, telemetry and audit history        |

The policy is deny-by-default. A user may hold multiple roles; effective permissions are the union of those roles inside one organization.

## Critical protected actions

- refrigeration image upload;
- layout draft save;
- layout publish;
- layout revision restore;
- test-session creation and configuration;
- test-session state transition;
- alert acknowledgement;
- membership and role changes;
- report approval.

The frontend may hide unavailable controls, but the backend remains authoritative and must return `401` or `403` when the caller is not authorized.

## Audit event contract

Critical mutations write an append-only event in the same database transaction as the domain mutation.

```json
{
  "event_id": "uuid",
  "organization_id": "org-lab-1",
  "actor_subject": "oidc-subject",
  "actor_email": "operator@example.com",
  "action": "layout.publish",
  "entity_type": "refrigeration_layout",
  "entity_id": "showcase-106-01",
  "before": { "draft_version": 4 },
  "after": { "draft_version": 4, "revision_number": 1 },
  "reason": "Approved equipment sensor placement",
  "request_id": "uuid",
  "source_ip": "redacted-or-bounded",
  "user_agent": "bounded string",
  "occurred_at": "2026-07-25T15:00:00Z"
}
```

Database triggers must reject `UPDATE` and `DELETE` on audit events for the application role. Sensitive tokens, authorization headers, signed object URLs and secrets must never be stored in audit payloads.

## Delivery slices

1. Pure authorization domain and permission matrix.
2. PostgreSQL organizations, memberships, roles and immutable audit events.
3. Verified token adapter and FastAPI authorization dependencies.
4. Protection of refrigeration and session APIs.
5. Frontend authenticated-session and access-denied UI.
6. PostgreSQL integration and browser E2E authorization gate.

## Operational runbook

Production Supabase/JWKS configuration, organization bootstrap, key rotation and incident response are documented in [Supabase Auth production runbook](supabase-production-runbook.md).

The controlled browser Gate is defined in `.github/workflows/security-browser-acceptance.yml` and executes `scripts/run-security-browser-acceptance.sh` against isolated PostgreSQL, MinIO, FastAPI and Next.js services.

## Acceptance evidence

The final pull request must include successful CI evidence for:

- role matrix unit tests;
- token validation tests;
- cross-organization denial;
- protected endpoint `401` and `403` behavior;
- same-transaction audit creation;
- audit immutability;
- frontend role-aware controls;
- browser tests for viewer, operator, engineer, auditor and administrator.
