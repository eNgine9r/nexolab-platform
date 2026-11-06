# NEXOLAB #1466 — Original LOCAL_LAN Dashboard + Session access probe

## Product result

This small, offline-capable **read-only diagnostic** detects the failure
operator experienced on 3 November 2026: the dashboard's original LAN port
was closed, and a separate Next.js frontend presented
`SESSION_API_UNREACHABLE_OR_ORIGIN_BLOCKED` despite apparently healthy data
services.

It **does not** log in as the owner, use stored credentials, bypass
authentication, test WebSockets or assert that every RS-485 sensor is live.
It does not change Docker, systemd, IPAM, images, volumes, secrets, local
auth keys, site networking or hardware. It is not an automatic recovery
supervisor and is not installed or scheduled by this source-only Work Package.

## Operator command

From the checked-out NEXOLAB source on the Raspberry Pi:

    python3 -I -B infrastructure/offline/inspect-site-lan-access.py \
      --check --host 172.18.48.66

The host is illustrative of the actual verified local address on 3 November;
the command requires an explicit **literal RFC1918 or loopback IPv4**
address. It rejects external addresses, hostnames, domains, URLs, IPv6,
link-local addresses and ambiguous path/port forms. The probe only makes
four fixed-path HTTP GETs to that host on **port 3000 and port 8082**.
No redirects are followed; no DNS is used. No credentials, cookies, MQTT
messages, database query, Modbus write or hardware commands are transmitted.
Each bounded connection times out by default after three seconds; response
bodies are limited to 64 KiB.

The following five checks must pass together:

1. `GET / :3000` — HTTP 200, HTML and NEXOLAB identity.
2. `GET /login :3000` — HTTP 200, NEXOLAB HTML/password-form marker.
3. `GET /health/ready :8082` — HTTP 200, JSON status/database/mqtt each
   `ready`; this does **not** prove fresh persisted samples.
4. Unauthenticated `GET /api/v1/auth/session :8082` with exact
   `Origin: http://<IP>:3000` — HTTP 401, not 200 or a redirect. User
   passwords are never attempted.
5. The same session 401 carries **exactly one**
   `Access-Control-Allow-Origin` matching the request origin — no wildcard,
   wrong origin or duplicate headers.

Sample positive report:

    {"status":"LOCAL_LAN_AUTH_PATH_REACHABLE","read_only":true,"browser_login_verified":false,"live_telemetry_verified":false,"hardware_verified":false,"site_mutation":false}

The actual JSON also contains boolean results for the five checks. An
unreachable/misconfigured endpoint returns `status=BLOCKED` and **exit 78**,
with a fixed reason code; HTTP response bodies, credentials and network
errors are not echoed into output.

## Verification and activation

- Eighteen hermetic HTTP/negative tests, including real **isolated loopback
  HTTP** tests, verify 401 auth protection, precise CORS, no redirect
  following, invalid host and large-body refusal.
- The test is registered in the repository's existing Standalone Offline
  Runtime Contract and must pass on the exact GitHub PR HEAD.
- The live Raspberry smoke probe is **read-only**. Its result proves only
  the original LAN access chain **from the host running the probe**.
  Independent real browser sign-in by the owner, client-machine LAN access,
  authenticated WebSockets, valid current telemetry and physical equipment
  acceptance are separate steps.
- Future recurring collection, Prometheus metrics, authenticated UI
  acceptance and alert routing require a separate scoped Work Package with
  protected installation review; this PR adds no scheduler or automated
  network-repair action.
- Physical LAN ↔ Edge Docker CIDR overlap is still a separate #1409 issue;
  do not run network-repair `--execute` or rename Docker bridges to fix
  a probe error. Hardware USB/RS485 faults are separately tracked #1429.

The original NEXOLAB runtime should remain available offline with
no mandatory cloud, remote fonts, CDN, paid service or telemetry upload.
