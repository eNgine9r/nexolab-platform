# NEXOLAB authentication, RBAC and platform audit

## Scope

This contract protects the central REST and WebSocket APIs without changing Raspberry Pi, Modbus, RS-485, MQTT acquisition or edge deployment.

Production mode is fail-closed:

```dotenv
AUTH_MODE=jwt
AUTH_JWT_SECRET=<at-least-32-random-bytes>
AUTH_JWT_ISSUER=https://auth.example.internal
AUTH_JWT_AUDIENCE=nexolab-api
AUTH_AUTO_PROVISION_MEMBERSHIPS=false
```

`AUTH_MODE=disabled` exists only for isolated demo and automated compatibility tests. It resolves a development administrator and must not be used for a production central service.

## Access-token contract

The central service accepts externally issued compact JWT access tokens signed with HS256. Required claims:

| Claim | Requirement |
| --- | --- |
| `iss` | Exact match with `AUTH_JWT_ISSUER` |
| `aud` | Contains `AUTH_JWT_AUDIENCE` |
| `sub` | Stable external identity subject |
| `org_id` | Active NEXOLAB organization identifier |
| `role` | `admin`, `operator` or `viewer` during first provisioning |
| `exp` | Future Unix timestamp |

Optional validated claims are `iat`, `nbf`, `jti`, `email` and `name`.

The token role is not trusted after membership provisioning. The effective role is read from `organization_memberships`. Changing an operator's privileges therefore does not require accepting a new role claim from the browser.

Raw bearer tokens are never written to platform audit events.

## Roles and permissions

| Permission | Viewer | Operator | Admin |
| --- | :---: | :---: | :---: |
| `telemetry.read` | ✓ | ✓ | ✓ |
| `sessions.read` | ✓ | ✓ | ✓ |
| `sessions.write` | — | ✓ | ✓ |
| `layouts.read` | ✓ | ✓ | ✓ |
| `layouts.write` | — | ✓ | ✓ |
| `layouts.publish` | — | — | ✓ |
| `audit.read` | — | — | ✓ |

Frontend controls are disabled according to the effective session, but backend permission checks remain authoritative.

## HTTP authentication

Browser and API requests use:

```http
Authorization: Bearer <access-token>
```

Public endpoints:

```http
GET /
GET /health/live
GET /health/ready
OPTIONS *
```

Application endpoints return typed failures:

```json
{
  "detail": {
    "code": "authentication_required",
    "message": "authentication is required",
    "request_id": "..."
  }
}
```

A missing or invalid token returns `401` and `WWW-Authenticate: Bearer`. Insufficient permission returns `403` with the required permission. Cross-organization direct resource access returns an organization-scoped `404` to avoid resource enumeration.

Every protected response contains `X-Request-ID`; CORS exposes both `ETag` and `X-Request-ID`.

## Browser token boundary

The current provider-neutral frontend reads the access token from session storage:

```text
nexolab.access_token
```

The token is not stored in local storage, cookies, source control or public Next.js environment variables. A future external identity-provider callback must write the short-lived token into this session boundary and reload the session state.

Provider-specific login, password storage, password reset and MFA are outside this slice.

## WebSocket authentication

Browser WebSocket APIs cannot set an `Authorization` header. The client therefore requests two subprotocols:

```text
nexolab.v1
nexolab.jwt.<access-token>
```

The server validates the token before accepting the connection and selects only `nexolab.v1`. Missing or invalid authentication closes the handshake with code `4401`; insufficient permission uses `4403`.

Non-browser clients may continue to send `Authorization: Bearer ...` during the WebSocket upgrade.

Reverse proxies and access logs must redact `Sec-WebSocket-Protocol` because it can contain the short-lived token.

## Persistence

Migration `20260725_0008` adds:

- `organizations`;
- `auth_identities`;
- `organization_memberships`;
- `resource_organization_bindings`;
- `platform_audit_events`.

Equipment and direct session resources are bound to one organization. The first authorized write, or the controlled draft bootstrap read, creates the binding. Existing production resources should be pre-bound during rollout before enabling untrusted organizations.

## Platform audit

Protected mutations and denied authorization attempts append `platform_audit_events` containing:

- organization;
- trusted identity subject and effective role;
- normalized HTTP action;
- outcome: `success`, `failed` or `denied`;
- resource type and identifier;
- request ID;
- bounded metadata without credentials;
- UTC timestamp.

Audit events are append-only:

- ORM update and delete hooks reject mutation;
- SQLite test schemas receive update/delete triggers;
- PostgreSQL migration installs a trigger rejecting `UPDATE` and `DELETE`.

Admins query organization-scoped events through:

```http
GET /api/v1/audit/events
```

Filters: `action`, `outcome`, `resource_type`, `resource_id`, `limit`, `offset`.

## Session endpoint

```http
GET /api/v1/auth/session
```

Response:

```json
{
  "subject": "operator-42",
  "organization_id": "laboratory-a",
  "role": "operator",
  "permissions": [
    "layouts.read",
    "layouts.write",
    "sessions.read",
    "sessions.write",
    "telemetry.read"
  ],
  "email": "operator@example.com",
  "display_name": "Operator One",
  "provider": "jwt"
}
```

## Controlled rollout sequence

1. Apply migration `20260725_0008`.
2. Create organizations, identities and memberships through a controlled administrative procedure.
3. Pre-bind existing resources to their organizations.
4. Configure issuer, audience and a random secret of at least 32 bytes.
5. Set `AUTH_AUTO_PROVISION_MEMBERSHIPS=false`.
6. Deploy backend with `AUTH_MODE=jwt`.
7. Configure the external identity provider to issue the required claims.
8. Validate viewer, operator and admin acceptance scenarios.
9. Confirm audit events contain no bearer-token material.

Rollback may set the previously validated application image, but database tables and immutable audit records must be preserved. Do not drop migration `20260725_0008` as an operational rollback.
