# NEXOLAB: external browser access readiness (DRAFT, NO DEPLOYMENT)

Status: **NOT APPROVED / NOT EXPOSED**. This is a source-only implementation proposal.
Owner approval is required again for any Cloudflare DNS, Tunnel, Access, certificate, service,
runtime, frontend build, LAN policy or controller change. Corporate IT approval is separately
required before accessing the application from a managed company device.

## Verified read-only baseline — 2026-10-08

- NEXUS Commander reported `nexolab-edge-01` online.
- Approved LAN deployment evidence under `runtime/deployments/20261008T092219Z`
  records `DEPLOYMENT PASSED`, source `d00a83bfc83fb120777c721b5e46fa50ae455c7d`,
  `auth_mode=jwt` and `local_auth_overlay=true`.
- The build embeds an HTTP API origin on the trusted LAN; it is NOT usable as-is across
  an external HTTPS origin. The frontend also embeds a WebSocket origin.
- The local operator auth runbook documents short-lived JWTs, refresh-token rotation,
  account lockout, revocation, organization membership and role checks.
- The deployed acceptance evidence records an unauthenticated auth-session request
  rejected with HTTP 401. This is not an exhaustive external penetration test.
- The codebase documents **no Modbus writes** on production serial paths. Remote web
  publication does not authorize new register writes, relay actuation, setpoint changes
  or safety bypasses.
- The object-storage public URL in the current architecture uses an internal service
  endpoint. Equipment imagery/download workflows require a separate bounded design
  and acceptance; do not publicly expose the S3/object-storage port.
- No live request was sent to a controller, no production configuration was changed,
  and no new network endpoint was published in this readiness work.

## Decision: NO-GO for production public access until every gate passes

| Gate | Requirement | Current evidence |
| --- | --- | --- |
| Corporate policy | IT explicitly permits this destination and usage | Not verified |
| Identity | Named-user allowlist, phishing-resistant MFA preferred, short Access sessions | Not configured |
| Access coverage | One whole-host self-hosted Access app, NO bypass paths | Not configured |
| Tunnel origin protection | cloudflared validates Access JWT (team + audTag) | Template only |
| Direct origin bypass | No WAN router forwards; local proxy listens on loopback only | LAN/WAN verification pending |
| Application auth | JWT/local login remains enabled; server-side RBAC tested for every write route | Partial test evidence; endpoint matrix pending |
| API/WebSocket origin | New HTTPS/WSS frontend artifact, same public origin, local API proxy | Template only |
| Next.js operations | /api/device-agent/* and all write routes pass authorization and audit | Endpoint-level external acceptance pending |
| Image storage | No direct port 9000; authorized image download/upload workflow under HTTPS | Blocked pending design |
| CSRF/origin controls | Verify unsafe methods, Origin/Host and login flows through tunnel | Not verified |
| Rate limiting | Protect login, writes, uploads; test fail-closed and abuse response | Not verified |
| Session expiry | Access logout/expiry + app logout/revocation; WS reauthorization | Not verified externally |
| Supply chain | Recheck current CVEs and mitigations before any exposure | Prior HIGH findings need review |
| Monitoring/rollback | Signed audit, no tokens in logs, independent rollback of public route | Not verified |
| Hardware safety | Existing prohibition on Modbus writes respected; control changes individually approved | Hard gate |

## Proposed architecture

Browser -> HTTPS `nexolab.example.com` -> Cloudflare Access (named users + MFA)
-> Cloudflare Tunnel with *Protect with Access* -> NGINX bound to 127.0.0.1:17878
-> Next.js 127.0.0.1:3000 OR protected backend API 127.0.0.1:8082.

- One hostname for HTML, REST and `wss://.../api/v1/telemetry/live`. Keep
  `/api/device-agent/*` routed to Next.js and its server-side authorization.
- Cloudflare is an additional boundary, NOT a replacement for local JWT and RBAC.
- Cloudflare Tunnel is outbound-only: do not create WAN router port forwarding.
- All server-bound Next.js URLs must be audited for unintended internal-origin leaks.
- The current frontend cannot simply be reused because its embedded API/WebSocket URLs
  are HTTP/WS LAN destinations. Rebuild and validate a separate artifact using:
  `NEXT_PUBLIC_NEXOLAB_API_BASE_URL=https://nexolab.example.com`
  `NEXT_PUBLIC_NEXOLAB_WEBSOCKET_URL=wss://nexolab.example.com/api/v1/telemetry/live`
  `NEXT_PUBLIC_NEXOLAB_AUTH_PROVIDER=local`.
- These example URLs are placeholders, not registered hostnames.
- Do not change the approved LAN deployment simply to trial external access.
  First run on a separately isolated staging environment or approved canary.
- The `nginx.conf.example` and `cloudflared.example.yaml` templates must be
  reviewed against the current Cloudflare docs and the actual upstream route inventory.
- Do not route PostgreSQL, MQTT, S3, Grafana, Prometheus, device-agent port, SSH,
  Commander, or any other administrative service through this published hostname.

## No owned domain? Use a protected Quick Tunnel ONLY for disposable staging

Cloudflare added `cloudflared tunnel --url ... --allowed-mail ...` support for temporary
`*.trycloudflare.com` test links on 2026-10-02. This option requires neither an
owned domain nor a Cloudflare account, and requires an email one-time PIN before a
visitor can access the selected test origin. It is **not** equivalent to our proposed
named Tunnel with Cloudflare Access policies and validated application identity.

**Strict isolation requirement:** never target the active NEXOLAB Dashboard (:3000),
the LAN API (:8082), Device Agent, database, or any service backed by production
telemetry/hardware. Use ONLY an isolated local fixture that has no access to the
live controllers, no real user data, and no inherited production credentials.

Example syntax **for a disposable staging fixture only** (illustration, do not run
until the fixture is independently approved and created):

```bash
cloudflared tunnel --url http://127.0.0.1:18787 \
  --allowed-mail approved-tester@example.com
```

The disposable staging fixture is deliberately **not provided** by this PR:
port 18787 is a placeholder and must not fall through to live Raspberry services.
Access by the company-owned laptop requires IT approval regardless of the test URL.
Quick Tunnel provides no stable hostname or uptime guarantee; restart changes the URL.
For permanent full-functionality access, purchase/use a controlled domain and
complete all named-Tunnel, Access, application auth, and hardware safety gates.

Official reference: https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/

## Cloudflare Access provisioning — after approval only

1. Verify Cloudflare-controlled domain and required account access.
2. Obtain a corporate IT decision for company-managed endpoints. A public link must
   NOT be used to evade employer network policy or browser restrictions.
3. Create self-hosted Access application covering the ENTIRE host
   `nexolab.example.com` including `/api/v1/*`, `/api/device-agent/*` and
   WebSockets. Avoid more-specific apps that override the host policy.
4. Allow only named identities (not Everyone or a broad public email domain); enforce
   independent or IdP MFA; prefer phishing-resistant MFA for control operators.
   Set reasonably short application session lifetime; review privileged sessions.
5. No Bypass, public health path, anonymous preview, wildcard hostname or wildcard
   origin allowance. Deny unrecognized users; test another account is rejected.
6. Create a named tunnel, store its credential in root-only storage outside Git,
   configure `originRequest.access.required=true` with exact Access team and AUD,
   and use a final `http_status:404` ingress rule.
7. Create an Access-protected DNS published route only after all local and staged gates
   are proven. Keep the service stopped until explicit go-live approval.
8. Record account admins, break-glass revocation and trusted IT notification channel.
   Credentials and private access data belong in an operator secret store, not issues.

## Required staged acceptance (no production controller writes)

- Access unauthenticated request denied; permitted named user with MFA reaches
  application login; wrong organization/user denied; API REST and WS cannot be
  reached when Access denies the request.
- Local unauthenticated request to `/api/v1/auth/session` receives 401.
- Viewer read-only, operator/engineer/administrator permission matrix checked
  by direct endpoint calls (not just hidden buttons). Cross-organization 403.
- Revoke Cloudflare and local session separately; deny subsequent HTTP and WS access.
- Open Overview, Live, History, Reports, Alerts, Refrigeration, Settings and
  equipment-image upload/download on staging. Inspect network panel: no mixed
  content, no LAN/localhost URLs, valid WSS, no S3 public exposure.
- All available *application* control actions in staging require per-action RBAC,
  audit trail, a confirmation step for riskier actions and server-side validation.
  Under NO circumstances exercise Modbus writes or actual relay/compressor control
  without a separate hardware safety change approval and test plan.
- Verify negative test: missing/wrong Cloudflare Access JWT is rejected at
  cloudflared even if a route or DNS record is accidentally misconfigured.
- Load/timeout/reconnect tests; fail closed if Cloudflare Access or API is down.
- Verify source commit, rollback artifact and a switch-off procedure for tunnel/DNS
  that leaves LAN services and data untouched.

## Deployment and rollback boundary

This draft does NOT install, enable or start NGINX/cloudflared, create Cloudflare
objects, change firewall, rebuild the deployed dashboard or merge any branch.

Required explicit approvals in order:
1. Owner approves final audited and tested design, public hostname and access identities.
2. Corporate IT permits access from the managed workstation.
3. Owner separately approves a controlled cutover of the finished design.
4. After go-live, rotate/revoke on any incident and disable the public route without
   touching PostgreSQL volumes or Modbus buses.

Official design references:
- https://developers.cloudflare.com/tunnel/get-started/
- https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/self-hosted-public-app/
- https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/configure-tunnels/origin-parameters/
- https://developers.cloudflare.com/cloudflare-one/access-controls/policies/mfa-requirements/
