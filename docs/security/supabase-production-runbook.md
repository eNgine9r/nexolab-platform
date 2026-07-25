# Supabase Auth production runbook

## Scope

This runbook connects Supabase Auth to the provider-neutral NEXOLAB JWT, organization RBAC and immutable audit implementation. Raspberry Pi, Modbus and RS-485 access are not required.

## Security boundary

- Supabase authenticates the user and issues the access token.
- FastAPI verifies the JWT signature, issuer, audience, expiry and subject.
- PostgreSQL memberships and role assignments determine authorization.
- Browser role claims, actor identifiers and organization names are not trusted.
- The verified JWT subject is stored as the actor for protected mutations.
- User access tokens, service-role keys and private signing keys must never use a `NEXT_PUBLIC_` variable.

## Backend configuration

Copy `infrastructure/compose/.env.central.example` to the controlled central environment and configure:

```dotenv
AUTH_MODE=jwt
AUTH_DEFAULT_ORGANIZATION_ID=<nexolab-organization-uuid>
AUTH_JWT_PUBLIC_KEY=
AUTH_JWT_JWKS_URL=<trusted-supabase-jwks-url>
AUTH_JWT_ALGORITHM=RS256
AUTH_JWT_ISSUER=<expected-supabase-issuer>
AUTH_JWT_AUDIENCE=<expected-api-audience>
AUTH_JWT_PROVIDER=supabase
```

Use one verification source:

1. `AUTH_JWT_JWKS_URL` for normal key rotation; or
2. `AUTH_JWT_PUBLIC_KEY` for an explicitly managed static public key.

Do not configure a private signing key in the telemetry service.

Restart the central stack after changing authentication configuration:

```bash
cd infrastructure/compose
docker compose --env-file .env.central -f compose.central.yaml up -d --build
curl -fsS http://127.0.0.1:8082/health/ready
```

## Frontend configuration

Configure the production Next.js environment:

```dotenv
NEXT_PUBLIC_NEXOLAB_DATA_MODE=live
NEXT_PUBLIC_NEXOLAB_API_BASE_URL=https://<trusted-api-host>
NEXT_PUBLIC_NEXOLAB_WEBSOCKET_URL=wss://<trusted-api-host>/ws/telemetry
NEXT_PUBLIC_NEXOLAB_ORGANIZATION_ID=<nexolab-organization-uuid>
NEXT_PUBLIC_NEXOLAB_AUTH_PROVIDER=supabase
NEXT_PUBLIC_SUPABASE_URL=https://<project-ref>.supabase.co
NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=<publishable-key>
```

The publishable key is intended for browser initialization. The Supabase service-role key is a server secret and must not be exposed to Next.js client code.

## Organization bootstrap

Before the first user signs in:

1. create the NEXOLAB organization row;
2. sign in once so the verified identity can be resolved;
3. create an organization membership for that identity;
4. assign the minimum required role;
5. verify the resulting permissions through `GET /api/v1/auth/session`.

Initial administrator assignment must be performed through a controlled database migration or another already-authorized administrator. Do not implement a public self-promotion endpoint.

## Role model

| Role | Primary access |
| --- | --- |
| `administrator` | Memberships, configuration and all protected operations |
| `laboratory_manager` | Sessions, layouts, publication, reports and audit review |
| `engineer` | Layout editing, publication and session operations |
| `operator` | Live operation, draft editing and alert acknowledgement |
| `viewer` | Read-only dashboard, telemetry and reports |
| `auditor` | Read-only evidence, reports and immutable audit history |

Permissions are evaluated inside one organization. Membership in one laboratory does not grant access to another laboratory.

## Acceptance checks

Run the isolated security Gate:

```bash
bash scripts/run-security-browser-acceptance.sh
```

The Gate proves:

- missing tokens return `401`;
- organization mismatch returns `403`;
- Viewer remains read-only;
- Operator cannot publish;
- Engineer can publish an equipment layout;
- browser-supplied actor values are ignored;
- the verified JWT subject is written to the audit event;
- Administrator can change membership roles;
- audit rows reject `UPDATE` and `DELETE`;
- Playwright traces, screenshots and PostgreSQL evidence are retained on failure.

## Key rotation

1. publish the new verification key through the identity provider JWKS;
2. keep the previous key available during the token overlap window;
3. verify login and `/api/v1/auth/session` with a newly issued token;
4. verify an existing non-expired token where policy permits;
5. remove the old key only after the maximum token lifetime has elapsed;
6. record the rotation in the operational change log.

## Incident response

When authentication or authorization fails unexpectedly:

1. confirm the API health endpoint;
2. inspect issuer, audience, algorithm and JWKS reachability;
3. confirm the user's identity and active organization membership;
4. inspect role assignments and the immutable audit trail;
5. revoke the affected Supabase session when compromise is suspected;
6. rotate exposed credentials;
7. never disable backend authorization as a production workaround.
