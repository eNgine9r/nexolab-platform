# NEXOLAB external HTTPS — separated staging candidate (NO-GO / NOT DEPLOYED)

**Safety classification: source-only preparation.** This change does not enable
Tailscale Funnel on NEXOLAB, create or modify a public route, start an identity
provider, modify any network interface, restart services, or touch controllers.

## Verified deployed baseline — 2026-10-08

- Real Raspberry Pi `nexolab-edge-01` currently runs source
  `d00a83bfc83fb120777c721b5e46fa50ae455c7d` in `lan` mode,
  dashboard `http://172.18.48.66:3000`, Telemetry API
  `http://172.18.48.66:8082`.
- Current installation preserves `AUTH_MODE=jwt` and local operator login.
- `btc-radar` (NEXUS control plane) reaches NEXOLAB dashboard through Tailscale
  on TCP/3000; TCP/8082 is NOT reachable at the NEXOLAB Tailscale address.
- Browser JavaScript is compiled with LAN `http://` and `ws://` origins.
  Thus merely sharing port 3000 over HTTPS does not provide functional API/WS.
- Existing `btc-radar.tail...ts.net` hostname hosts NEXUS, OAuth, Mini App,
  Autopilot, and other routes. DO NOT replace its root or publish NEXOLAB
  under `/nexolab` with an unmodified Next.js build: the app uses root
  routes, server handlers, and generated `/_next/` assets.
- Production Modbus/RS-485 path remains **read-only**. An external dashboard
  does NOT authorize Modbus FC05/FC06/FC15/FC16, relay actuation, compressor
  writes or controller setpoint changes. Existing application-level
  acquisition/layout/session controls require backend role enforcement.
- The private object store currently issues signed URLs containing a LAN
  address/port. Full external refrigeration photo support is **NOT ready**:
  S3 port 9000 MUST NOT be publicly opened.

## Chosen architecture (subject to audit and separate cutover approval)

Use a **dedicated Tailscale-managed HTTPS hostname** for NEXOLAB. This needs
no purchased domain. BTC Radar remains the NEXUS/Commander control plane,
not an unauthenticated internet relay for lab hardware.

```text
External browser (corporate IT approval required)
  |
  v
Dedicated HTTPS origin via Tailscale Funnel on NEXOLAB (NOT ENABLED)
  |
  v
127.0.0.1:18790  NGINX gateway candidate (NOT STARTED)
  |-- oauth2-proxy 127.0.0.1:4180   -> OIDC named-user MFA (NOT CONFIGURED)
  |-- /api/v1/*                     -> private Telemetry Service LAN :8082
  |-- /api/device-agent/* and web   -> isolated Next.js candidate 127.0.0.1:3100
                                       -> Device Agent loopback only
```

Every application request (including API/WS) requires the independent
OIDC/MFA gateway _and_ NEXOLAB's signed JWT and server-side RBAC. OIDC
must have named identities, MFA, time-limited sessions and session
revocation. No "bypass", anonymous health path or wildcard origin.
The identity provider must be selected, configured and audited; the
NGINX example fails closed without it.

The NGINX template intentionally has a placeholder private API IP and an
example hostname. It cannot be used without explicit staging substitution
and validation. Never publish or deploy this template as-is.

## Separate frontend artifact for external staging

Do not rebuild or overwrite the active LAN dashboard. Only an isolated
Next.js candidate may be built, verified and run on `127.0.0.1:3100`.
Relevant build-time variables for the externally staged artifact:

```dotenv
NEXT_PUBLIC_NEXOLAB_DATA_MODE=live
NEXT_PUBLIC_NEXOLAB_API_BASE_URL=https://nexolab-edge-01.example.ts.net
NEXT_PUBLIC_NEXOLAB_WEBSOCKET_URL=wss://nexolab-edge-01.example.ts.net/api/v1/telemetry/live
NEXT_PUBLIC_NEXOLAB_AUTH_PROVIDER=local
NEXT_PUBLIC_NEXOLAB_EXTERNAL_HTTPS_STAGE=true
```

**Server-only runtime environment** for that candidate:

```dotenv
NEXOLAB_EXTERNAL_HTTPS_STAGE=true
NEXOLAB_SERVER_API_BASE_URL=http://REPLACE_WITH_APPROVED_PRIVATE_API_IP:8082
NEXOLAB_DEVICE_AGENT_BASE_URL=http://127.0.0.1:8081
NEXOLAB_EQUIPMENT_IMAGE_AUTHENTICATED_URLS=true
```

The new `getServerTelemetryApiBaseUrl()` helper ensures that the
server-side `/api/device-agent/*` RBAC/session checks do not accidentally
hairpin through the public Funnel/identity gateway. It retains the
accepted legacy LAN fallback when the external-stage flag is absent.
An explicitly configured server-only URL is validated to be HTTP,
private IPv4/loopback, port 8082 and no userinfo, path, query or fragment.

**Do not put a private server URL into a `NEXT_PUBLIC_` environment
variable.** That would make the private address visible to browsers
and could make app API calls bypass or fail at the public gateway.

## Authenticated private equipment image delivery — source candidate

The new `GET /api/v1/equipment/{equipment_id}/images/{image_id}/content`
Telemetry API endpoint requires `dashboard.read`, validates the selected
organization and equipment ownership, enforces the image size cap, verifies
SHA-256 integrity and returns image bytes with `Cache-Control: private, no-store`.
It never serves an arbitrary user-supplied URL or publicly exposes S3 port 9000.

With the server-only `NEXOLAB_EQUIPMENT_IMAGE_AUTHENTICATED_URLS=true` flag,
image metadata contains only the authenticated relative API path, not a
presigned internal S3 URL. The production LAN mode keeps the prior behavior.

With `NEXT_PUBLIC_NEXOLAB_EXTERNAL_HTTPS_STAGE=true`, the layout views,
camera-scoped view, equipment history thumbnails and revision preview fetch
images using the existing JWT-aware `createAuthenticatedFetch` and display
short-lived, browser-local blob URLs. The private S3 signed URL is never used
by these staged UI components. The currently deployed LAN build preserves
its existing signed-URL behavior.

This is **source preparation**, not an acceptance verdict. Staged E2E
must verify image upload/download, 401/403, cross-organization denial,
revocation, large/corrupt object handling, blob URL revocation and every
refrigeration image surface before production exposure.

## Read-only staging policy gate

```bash
python3 scripts/inspection/nexolab_external_https_gate.py \
  --manifest infrastructure/external-access/manifest.example.json
python3 -m unittest discover -s tests -p test_nexolab_external_https_gate.py
```

Expected: `PASS` for the source-only stage profile, but
`PUBLICATION=BLOCKED` while the public route remains disabled and
live MFA, CORS, frontend, API/WS and equipment-photo checks are pending.

The gate rejects non-HTTPS browser/API origins, non-WSS telemetry,
origin mismatch, token-bearing query strings, exposed S3 port,
wide-open WAN listener, missing local JWT/RBAC/MFA, active public route,
and enabled Modbus writes.

## Additional hard gates before a production full-feature rollout

1. Confirm that corporate IT permits connecting to the site from managed
   browsers. Never evade managed-device policy.
2. Verify a separately deployed OIDC/MFA gateway end-to-end:
   logged-out user, wrong identity, correct identity + MFA, revoked user,
   expired session, CSRF request and WebSocket handshake. Confirm
   every API and Next.js route is gated before hitting a backend.
3. Run CVE re-audit against currently deployed dependency versions and
   resolve or obtain documented, time-bounded exception for HIGH issues.
4. Authenticate all API/WS endpoints using NEXOLAB local JWT and organization
   membership; verify real 401/403 and append-only audits on writes.
5. Validate the separate frontend artifact (not the active LAN build).
   Inspect browser network: no `http://172.18...`, private IP,
   direct port 8082, `ws://`, localhost or mixed-content requests.
6. Solve private equipment image delivery with a _bounded, authenticated_
   same-origin object proxy or equivalent server-side image handler.
   Revalidate signed URLs and upload limits. Port 9000 stays private.
7. Verify control action allowlists, reconfirmations, ownership and audit
   in isolated fixtures. **No live physical Modbus writes.**
8. Verify proxy upgrades WebSocket without disclosing tokens in URLs or logs;
   verify token expiration, forced revocation, reconnect and gateway outage.
9. Check resource envelope of Raspberry Pi 5 (4 GB), latency and NEXUS/BTC
   isolation. Preserve rollback and 24h LAN telemetry continuity.
10. Obtain explicit owner approval for production public route and separate
    corporate IT permission. Only then can a controlled, reversible
    publication be scheduled.

## Rollback boundary

Disconnect the _new dedicated NEXOLAB public route_ only; do not reset
Tailscale Funnel on BTC Radar or touch its existing MCP/OAuth paths.
Terminate the external gateway, identity service and the isolated
dashboard candidate. Keep the active LAN release, databases, storage
volumes, serial buses and Modbus settings intact.

Nothing in this PR authorizes deploying or publishing real lab data.
