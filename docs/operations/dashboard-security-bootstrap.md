# NEXOLAB dashboard security bootstrap diagnostics

## Purpose

Use this runbook when the live dashboard stops at `NEXOLAB Security Gate` before the application shell opens.

The session bootstrap path is:

```text
browser dashboard origin
        ↓
NEXT_PUBLIC_NEXOLAB_API_BASE_URL
        ↓
GET /api/v1/auth/session
        ↓
Telemetry Service authentication and organization membership
```

A blocked bootstrap does not by itself prove that the operator lacks permission. The browser may also be unable to reach the API, the exact browser origin may be absent from CORS, HTTPS may be calling an HTTP API, or the service may be unavailable.

Do not disable authentication or add wildcard CORS to bypass the gate.

## 1. Record the safe diagnostics shown by the gate

Record only:

- error code;
- Dashboard origin;
- Session API URL;
- HTTP status, when present.

Do not copy access tokens, cookies, passwords, private keys or production telemetry into an Issue or chat.

Stable bootstrap codes:

| Code                                        | Meaning                                                                                           |
| ------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| `AUTHENTICATION_REQUIRED`                   | API returned HTTP 401                                                                             |
| `ACCESS_DENIED`                             | API returned HTTP 403                                                                             |
| `SESSION_API_ERROR`                         | API returned another non-success HTTP status                                                      |
| `SESSION_REQUEST_TIMEOUT`                   | API did not finish within the bounded browser timeout                                             |
| `SESSION_MIXED_CONTENT`                     | HTTPS dashboard is configured to call an HTTP API                                                 |
| `SESSION_API_UNREACHABLE_OR_ORIGIN_BLOCKED` | Browser fetch failed; common causes are unreachable API, wrong host/port or CORS origin rejection |
| `INVALID_RESPONSE`                          | API response does not match the security-session contract                                         |
| `INVALID_CONFIGURATION`                     | Live dashboard runtime configuration is incomplete or invalid                                     |

## 2. Identify the addresses used by the browser

The value `127.0.0.1` always means the machine where the request is executed.

Therefore:

- a dashboard and Telemetry Service running on the same PC may both use `127.0.0.1`;
- a browser on a Windows PC cannot use `127.0.0.1:8082` to reach a Raspberry Pi or another central host;
- for a remote browser, use the explicit trusted LAN address of the central host in `NEXT_PUBLIC_NEXOLAB_API_BASE_URL` and `NEXT_PUBLIC_NEXOLAB_WEBSOCKET_URL`;
- do not use `0.0.0.0` as a browser destination.

Record the exact dashboard URL from the browser address bar. Its origin includes scheme, hostname and port, for example:

```text
http://192.168.1.20:3000
```

## 3. Check the API from Windows PowerShell

Replace the example API address with the `Session API` origin shown by the gate.

```powershell
$Api = "http://127.0.0.1:8082"

Invoke-RestMethod "$Api/health/ready" |
  ConvertTo-Json -Depth 8

Invoke-RestMethod "$Api/api/v1/auth/session" |
  ConvertTo-Json -Depth 8
```

For `AUTH_MODE=disabled`, the session response must contain:

```json
{
  "authenticated": true,
  "identity": {
    "provider": "disabled",
    "subject": "development-system"
  },
  "memberships": [
    {
      "organization_slug": "development",
      "roles": ["administrator"]
    }
  ]
}
```

A failure here is an API binding, service, firewall or network-route problem rather than a browser RBAC denial.

Inspect the listening port on the same Windows host when applicable:

```powershell
Get-NetTCPConnection -State Listen -LocalPort 8082 -ErrorAction SilentlyContinue
```

## 4. Check the API from Linux or Raspberry Pi

```bash
API="http://127.0.0.1:8082"

curl -fsS "$API/health/ready" | python3 -m json.tool
curl -fsS "$API/api/v1/auth/session" | python3 -m json.tool
```

For the central Compose profile:

```bash
cd ~/nexolab-platform/infrastructure/compose

docker compose \
  --env-file .env.central \
  -f compose.central.yaml \
  ps -a

docker compose \
  --env-file .env.central \
  -f compose.central.yaml \
  logs --since=15m --no-color telemetry-service
```

Do not recreate or delete persistent volumes during diagnosis.

## 5. Verify the exact CORS origin

CORS requires the exact dashboard origin. These values are different origins:

```text
http://localhost:3000
http://127.0.0.1:3000
http://192.168.1.20:3000
https://192.168.1.20:3000
```

PowerShell check:

```powershell
$Api = "http://127.0.0.1:8082"
$Origin = "http://localhost:3000" # replace with the exact browser origin

curl.exe -sS -D - -o NUL `
  -H "Origin: $Origin" `
  "$Api/api/v1/auth/session"
```

Linux check:

```bash
API="http://127.0.0.1:8082"
ORIGIN="http://localhost:3000" # replace with the exact browser origin

curl -sS -D - -o /dev/null \
  -H "Origin: $ORIGIN" \
  "$API/api/v1/auth/session"
```

Expected response header:

```text
Access-Control-Allow-Origin: <the exact browser origin>
```

Configure the central environment with a comma-separated allowlist, never `*`:

```text
CORS_ALLOWED_ORIGINS=http://127.0.0.1:3000,http://localhost:3000,http://192.168.1.20:3000
```

After editing `.env.central`, recreate only the Telemetry Service container with the controlled Compose profile:

```bash
cd ~/nexolab-platform/infrastructure/compose

docker compose \
  --env-file .env.central \
  -f compose.central.yaml \
  up -d --no-deps --force-recreate telemetry-service
```

Then repeat the session and CORS checks.

## 6. Verify frontend live configuration

Example for dashboard and API on the same PC:

```text
NEXT_PUBLIC_NEXOLAB_DATA_MODE=live
NEXT_PUBLIC_NEXOLAB_API_BASE_URL=http://127.0.0.1:8082
NEXT_PUBLIC_NEXOLAB_WEBSOCKET_URL=ws://127.0.0.1:8082/api/v1/telemetry/live
```

Example for a browser on another LAN machine:

```text
NEXT_PUBLIC_NEXOLAB_DATA_MODE=live
NEXT_PUBLIC_NEXOLAB_API_BASE_URL=http://192.168.1.50:8082
NEXT_PUBLIC_NEXOLAB_WEBSOCKET_URL=ws://192.168.1.50:8082/api/v1/telemetry/live
```

The central host must bind the API to that exact trusted LAN interface. Loopback binding cannot serve a remote browser.

`NEXT_PUBLIC_*` values are embedded into the Next.js client bundle. After changing them, restart the development server or rebuild/redeploy the frontend. A browser refresh alone is insufficient.

## 7. Mixed-content rule

An HTTPS dashboard must not call:

```text
http://...
ws://...
```

Use HTTPS/WSS for both endpoints, or access the controlled local dashboard over HTTP when that is the approved LOCAL_LAN configuration. Do not bypass browser mixed-content protection.

## 8. Acceptance record

Record:

- dashboard origin;
- API origin;
- `/health/ready` result;
- `/api/v1/auth/session` status and safe identity provider/role summary;
- CORS response header;
- resolved `CENTRAL_BIND_ADDRESS` and `CENTRAL_API_PORT`;
- confirmation that the frontend was restarted or rebuilt after public environment changes;
- final Security Gate code or successful dashboard opening.

The Work Package may claim software diagnostics and CI acceptance without actual-host evidence. The host-specific root cause remains unverified until these checks are run on the affected PC and central host.
