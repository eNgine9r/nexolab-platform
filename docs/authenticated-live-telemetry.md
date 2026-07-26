# Authenticated live telemetry

The production dashboard uses the verified user session introduced by the NEXOLAB RBAC gate for both REST and WebSocket telemetry.

## Dashboard session gate

Live telemetry is disabled until `/api/v1/auth/session` returns a verified identity and at least one organization membership. The dashboard distinguishes loading, unauthenticated, forbidden and request-failure states instead of starting anonymous data requests.

The selected organization must exist in the returned membership list. Switching organizations clears the current telemetry store and reconnects REST and WebSocket clients with the new organization boundary. Data from the previous organization is hidden immediately while the new scope is loading. Logout clears the in-memory credentials before returning the operator to `/login`.

## REST

Every `/api/v1/telemetry/latest` and `/api/v1/telemetry/history` request carries:

- `Authorization: Bearer <access token>`;
- `X-Organization-ID: <selected membership>`.

The backend resolves the JWT subject against PostgreSQL memberships and requires `telemetry.read`.

## WebSocket handshake

Bearer tokens are never placed in the WebSocket URL or query string. After the TLS WebSocket opens, the browser sends one authentication message before any replay or live subscription is registered:

```json
{
  "type": "authenticate",
  "access_token": "<short-lived user JWT>",
  "organization_id": "<selected organization UUID>"
}
```

The server verifies the JWT, membership and `telemetry.read` permission. A successful session receives:

```json
{
  "type": "authenticated",
  "subject": "verified-oidc-subject",
  "organization_id": "<selected organization UUID>"
}
```

Only then does the server register the bounded client queue and perform resume replay. Policy violations close with WebSocket code `1008` and are not retried automatically. Transport failures still use bounded reconnect backoff, and each reconnect obtains refreshed credentials from Supabase Auth.

## Security properties

- bearer tokens are absent from URLs, server access logs and acceptance evidence;
- browser roles are ignored;
- organization selection is checked against PostgreSQL membership;
- cross-organization subscriptions are denied before replay;
- no telemetry client is registered before authentication succeeds;
- development mode remains compatible with unauthenticated local tests when `AUTH_MODE=disabled`.

## Authenticated history

The temperature panel queries `/api/v1/telemetry/history` independently from the latest snapshot and WebSocket connection. Operators can select 1-hour, 6-hour and 24-hour windows. Each dashboard request is bounded to 1,000 records. History errors have their own retry state and do not downgrade a fresh live connection. Changing the range or organization aborts the previous request before starting the replacement query.

History and latest records are deduplicated by immutable event ID before rendering. Only valid production temperature channels are plotted; sensor and communication errors remain available in current-state cards but are not rendered as numeric curve points.

## Required public frontend variables

```dotenv
NEXT_PUBLIC_NEXOLAB_DATA_MODE=live
NEXT_PUBLIC_NEXOLAB_API_BASE_URL=https://api.example.test
NEXT_PUBLIC_NEXOLAB_WEBSOCKET_URL=wss://api.example.test/api/v1/telemetry/live
NEXT_PUBLIC_NEXOLAB_ORGANIZATION_ID=<organization UUID>
NEXT_PUBLIC_SUPABASE_URL=https://<project>.supabase.co
NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY=<publishable key>
```

Service-role keys, JWT signing secrets and private keys must never use the `NEXT_PUBLIC_` prefix.
