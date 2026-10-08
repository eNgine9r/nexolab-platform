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

The NGINX template intentionally has a placeholder private API IP. The
Tailscale hostname has been read from the live device but no public route exists. It cannot be used without explicit staging substitution
and validation. Never publish or deploy this template as-is.

## Google identity and MFA — approved choice, not activated

**Selected external identity:** personal Google Account with the owner-approved
single email address. Store that address only in the protected on-device
`/etc/nexolab-external/allowed-emails.txt`, not this public repository.
The file MUST contain exactly one address. `--authenticated-emails-file`
is a named-user authorization boundary. Do NOT configure
`email_domains = ["*"]`, `trusted_ips`, unauthenticated routes, or
`skip_jwt_bearer_tokens`. A Google login by someone else (including a
different Gmail user) must be denied. Local NEXOLAB JWT and RBAC remain enabled.

Inert candidate: `infrastructure/external-access/oauth2-proxy-google.example.cfg`.
It accepts Google identity on loopback `127.0.0.1:4180`, has a dedicated
`__Host-` session cookie (Secure, HttpOnly, SameSite=Lax, 2h expire,
15m refresh), strict exact redirect URL and trusted NGINX proxy address.
There are no Google credentials, email addresses or cryptographic keys in Git.

**Critical: OAuth Google login is NOT independently a proof that MFA was
required or freshly performed.** The OAuth2 Proxy `google` provider
does not provide a dedicated Google MFA-enforcement control here. Before
go-live the owner must confirm 2-Step Verification or a passkey on the
approved Google Account, test an interactive reauthentication, and the
security reviewer must accept the residual risk or deploy an IdP that can
enforce and verify MFA for each privileged session. Never label the mere
presence of `provider = "google"` as "MFA confirmed".

### Operator-only Google Cloud setup — operator-reported complete; verification pending

1. Check the Google Account at
   https://myaccount.google.com/security: configure 2-Step Verification
   with a passkey/security key if possible. Do NOT share backup codes.
2. In https://console.cloud.google.com/auth/ create/select a Google Cloud
   project, configure the Google Auth Platform branding and set the audience
   to External/Testing with the approved user as a test user. The OAuth scopes
   are `openid email profile` only — no Gmail, Drive or other scopes.
3. Create an OAuth client **Web application**. Allowed redirect URI must
   exactly match:
   `https://nexolab-edge-01.tail7f9b04.ts.net/oauth2/callback`.
   The hostname is confirmed through the live Pi's Tailscale DNS; however,
   _no Funnel route is enabled_. Google OAuth domain restrictions may reject
   a `.ts.net` host under Google's domain ownership/verification rules.
   If so, stop and obtain an owned/approved domain. Do not work around the
   ownership policy by substituting another party's redirect URL.
4. Provision the Google `client_id`, `client_secret`, strong random
   `cookie_secret` as a private root/operator-owned service environment
   outside Git. Never paste secrets into PRs, the chat or command logs.
5. Provision `allowed-emails.txt` with exactly one approved address,
   restrictive file permissions and audited operator access. Validate the
   template first (without identity secrets):

   ```bash
   python3 scripts/inspection/nexolab_google_oauth_gate.py \
     --config infrastructure/external-access/oauth2-proxy-google.example.cfg \
     --expected-origin https://nexolab-edge-01.tail7f9b04.ts.net
   python3 -m unittest discover -s tests -p test_nexolab_google_oauth_gate.py
   ```

6. Before any real publication: review NGINX `auth_request`, signed cookie
   rotation, wrong-identity rejection, Google OAuth callback state/CSRF,
   logout/session revocation, expired cookie, API 401 vs browser redirects,
   WebSocket upgrades and rate limits in a disconnected staging fixture.
7. Obtain owner go-live approval **again**, in addition to explicit company
   IT permission for the destination and network. Only then may a dedicated
   Funnel route be created; preserve existing NEXUS/BTC routes.

### Local-only credentials provisioning — operator-completed; NOT activated

The operator reports that Google 2-Step Verification is enabled, a new
Web OAuth client was created after revoking the compromised original,
the dedicated callback URL was saved and the approved account was added
to **Test users**. These are user-reported settings, not independently
verified through the Google Cloud control plane. The owner has now run
the local provisioning wizard and its root-only `--check` successfully:
`PASS: local files present with private permissions; credentials NOT verified
with Google`. The actual Google credentials remain in private files on
NEXOLAB and are never sent to Commander, chat or GitHub.

An interactive, fail-closed provisioning script is prepared in
`scripts/operations/nexolab_google_oauth_private_provision.py` and copied
(without any credentials) to the Pi's isolated workspace at:

```text
/home/nexolab/commander-workspaces/nexolab-external-stage/google-oauth-private-provision.py
```

Only **from the Raspberry Pi's own trusted terminal or a private SSH
terminal** run the following when authorized to create private local
staging credentials. **Do not invoke this command using NEXUS Commander
or a chat tool**, because no Google secret may pass through orchestrator
commands, stdout, recorded logs or conversation history.

```bash
sudo python3 /home/nexolab/commander-workspaces/nexolab-external-stage/google-oauth-private-provision.py
sudo python3 /home/nexolab/commander-workspaces/nexolab-external-stage/google-oauth-private-provision.py --check
```

The first command asks for the Google Web Client ID and Client Secret
with hidden terminal input, then the operator-approved single email. It
generates its own 32-byte random cookie secret and creates files under
`/etc/nexolab-external`, mode 0700, files mode 0600. It refuses
overwrite/symlinks/non-interactive secret input and does not print them.
No service, NGINX, Funnel, firewall, Modbus, working dashboard or
production runtime is modified.

**Unprivileged secret delivery: code drafted and tested, NOT deployed.**
The root-only originals remain private. The separate inert systemd
template (`infrastructure/external-access/nexolab-google-oauth-stage.service.example`)
would use `DynamicUser=yes`, `LoadCredential` for the two original files,
and a 0700 `RuntimeDirectory`. The new
`scripts/operations/nexolab_google_oauth_private_exec.py` reads that
private credential copy; it creates ephemeral 0600 `client-secret` and
`cookie-secret` files and passes only their file **paths** to OAuth2 Proxy.
Secret values are never passed to the process environment, command line
or logs. The service is missing an install section and is not deployed,
started or enabled.

Eight focused credential-handoff tests passed on isolated synthetic
credentials. The real OAuth2 Proxy v7.15.5 `--config-test` also returned
`configuration is valid` when invoked through that synthetic file-handoff
mechanism on the Raspberry Pi; systemd `verify` of the inert unit completed
successfully. No production secret was accessed by these remote tests.
Live systemd user isolation, WebSocket gating, end-to-end sign-in/MFA
assurance and corporate IT permission remain **unverified**. Do not
weaken permissions or run the gateway as root.

The official OAuth2 Proxy **v7.15.5 Linux ARM64** release artifact was
downloaded into the isolated Pi workspace and SHA-256 verified. Its
`--config-test` reported `configuration is valid` using a synthetic
single-user list and synthetic credentials. No gateway was started.
Eleven standalone local credential-wizard tests passed, including unsafe
permissions, malformed terminal UTF-8, symlinks and duplicate writes. None of these isolated tests
validate the Google OAuth flow, MFA challenge or token/session revocation.

### Isolated NGINX route and OAuth fail-closed acceptance — 2026-10-08

The `scripts/inspection/nexolab_oauth_loopback_nginx_probe.py` source-only
probe was run on NEXOLAB's Raspberry Pi using a **locally unpacked Debian
NGINX 1.26.3 ARM64 binary**. It created ephemeral loopback ports,
a synthetic OAuth2 /auth identity server, a synthetic API and a synthetic
Next.js upstream. **No** real Google client ID/secret, local JWT, controller,
Telemetry API, S3, public domain request or Funnel was used. NGINX and the
mock servers were terminated at test completion.

The gateway template first exhibited an HTTPS termination bug: NGINX's
default absolute redirects could generate an `http://` Location when it
received plain HTTP from Tailscale's TLS terminator. Added
`absolute_redirect off;` to the candidate NGINX server to preserve
**relative** Google sign-in redirects; this does not relax OAuth or
backend JWT requirements.

**11 of 11** synthetic scenarios passed: anonymous browser 302 to a fixed
relative login destination, unauthorized REST 401, unauthorized device
route 401, unauthorized WebSocket 401, wrong-host 421, inaccessible internal
auth subrequest 404, authorized fake API/Next.js/device routes 200,
authorized fake WebSocket upgrade 101 and identity-server failure 500
(with no application backend forwarding). The real backend JWT/RBAC and
Google MFA were deliberately **not** simulated as passing: those remain
separate verification gates.

The probe is reproducible with any independently supplied trusted NGINX
binary and needs no root privileges:

```bash
python3 scripts/inspection/nexolab_oauth_loopback_nginx_probe.py \
  --nginx-binary /path/to/local/nginx \
  --template infrastructure/external-access/nginx-staging.example.conf
```

Do not direct the probe at the production NGINX listener or actual backends;
its port rewriting is purposely limited to synthetic loopback mocks.
This offline gate is a useful acceptance signal, **not** proof that a
Google login, corporate MFA requirements, IT approval or full external
NEXOLAB image upload/download path has passed.

### Additional real OAuth2 Proxy secret-format gate — 2026-10-08

A deeper test used the *actual* isolated OAuth2 Proxy v7.15.5 binary
with **disposable synthetic credentials**, never the operator's private
OAuth files. The first startup failed because the drafted
`--cookie-secret-file` contained a 44-byte textual Base64 encoding.
OAuth2 Proxy's file option requires **raw 16/24/32-byte key material**,
unlike the Base64-compatible text option `--cookie-secret`.

The launcher now decodes the locally generated 32-byte cookie key from
the private environment's Base64 value and writes **exactly 32 raw bytes**
to its 0600 ephemeral systemd runtime file. Unit acceptance asserts
the decoded bytes and byte length, not the former 44-character string.
The disposable-real-proxy smoke-test fixture was corrected likewise.

Upstream reference:
https://oauth2-proxy.github.io/oauth2-proxy/configuration/overview/

**Verification boundary:** the earlier failed real-binary run confirmed
the defect, while the corrected path has *not yet completed an actual
real-binary round trip* on the Raspberry Pi. Unit tests and CI are
required; until the real-proxy startup/NGINX integration test passes,
`REAL_PROXY_COOKIE_HANDOFF=UNVERIFIED` and `GO_LIVE=DENIED`.
The experimental command-line probe is source-only and must never be
invoked with operator credentials or production upstreams.

### Current release verdict

`GOOGLE_OAUTH_CONFIG=DRAFT`,
`GOOGLE_OAUTH_CLIENT=USER_PROVISIONED_ROOT_ONLY_NOT_VALIDATED_WITH_GOOGLE`,
`GOOGLE_2SV=USER_REPORTED_ENABLED`,
`MFA_ENFORCEMENT=NOT_VERIFIED`,
`FUNNEL_EXTERNAL_ROUTE=DISABLED`,
`GO_LIVE=DENIED`.

References: [OAuth2 Proxy Google](https://oauth2-proxy.github.io/oauth2-proxy/configuration/providers/google/),
[OAuth2 Proxy NGINX](https://oauth2-proxy.github.io/oauth2-proxy/configuration/integrations/nginx/),
[Google OAuth for server-side apps](https://developers.google.com/identity/protocols/oauth2/web-server),
[Google OAuth policies](https://developers.google.com/identity/protocols/oauth2/policies),
[Google 2-Step Verification](https://support.google.com/accounts/answer/185839).

## Separate frontend artifact for external staging

Do not rebuild or overwrite the active LAN dashboard. Only an isolated
Next.js candidate may be built, verified and run on `127.0.0.1:3100`.
Relevant build-time variables for the externally staged artifact:

```dotenv
NEXT_PUBLIC_NEXOLAB_DATA_MODE=live
NEXT_PUBLIC_NEXOLAB_API_BASE_URL=https://nexolab-edge-01.tail7f9b04.ts.net
NEXT_PUBLIC_NEXOLAB_WEBSOCKET_URL=wss://nexolab-edge-01.tail7f9b04.ts.net/api/v1/telemetry/live
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

## Container vulnerability policy — independent release blocker (2026-10-08)

Fresh GitHub Container Supply Chain run
[37793481715](https://github.com/eNgine9r/nexolab-platform/actions/runs/37793481715)
correctly **rejected** four unapproved `HIGH` Trivy records for
`CVE-2026-19445` in the Device Agent distroless Debian 13 image:
`libpython3.13-minimal`, `libpython3.13-stdlib`,
`python3.13-minimal` and `python3.13-venv`, installed
`3.13.5-2+deb13u5`. The CI merge gate rejected the failed supply-chain
prerequisite; other independent functional pipelines passing does not lift
this release blocker.

- [Debian's source package tracker](https://security-tracker.debian.org/tracker/CVE-2026-19445)
  lists Debian 13 Python 3.13 as affected with **no distro fixed version**.
- The triggering condition is server-side `ssl.SSLContext.sni_callback`
  changing a socket's `SSLContext` without preserving the original context
  lifetime. TLS _clients_ are not affected by this particular bug.
- Inspected Device Agent `mqtt_tls.py`: it constructs outbound MQTT TLS
  **client** contexts with certificate validation. Repository code search
  found no `sni_callback` assignment in the Device Agent source. The
  current Device Agent API is an internal-only HTTP service on :8081, not
  an externally published TLS terminator.
- This is a **bounded source-level reachability observation, not a
  scanner waiver**. Dependency changes, library call paths or deployment
  changes can invalidate the observation. External NEXOLAB must never
  forward :8081 or device/serial buses to untrusted networks.
- Security owner must separately review the full reachable runtime and
  fresh CVE evidence. Prefer an upstream/distro patched image when
  available. Do not loosen Trivy thresholds, introduce blanket exceptions,
  substitute an unreviewed Python/runtime or mark CI green manually.
- Until a reviewed policy-compliant remediation or explicitly authorized
  bounded decision passes a fresh exact-head scan, **release remains NO-GO**.

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
