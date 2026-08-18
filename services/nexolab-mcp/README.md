# NEXOLAB MCP Server

Read-only Model Context Protocol gateway for NEXOLAB telemetry and edge-node data.

The service is intentionally a thin adapter over the existing NEXOLAB HTTP APIs. It does **not** call the OpenAI API, does not require `OPENAI_API_KEY`, does not connect directly to the database, and exposes no shell or arbitrary network tool.

## Architecture

```text
MCP client
    |
    | Streamable HTTP /mcp
    v
NEXOLAB MCP
    | GET only
    +--------------------+
    |                    |
    v                    v
Telemetry API         Nodes API
    |                    |
    +------ NEXOLAB -----+
```

## MCP tool surface

| Tool | Purpose |
| --- | --- |
| `nexolab_get_system_health` | Read telemetry service readiness |
| `nexolab_list_nodes` | List configured edge nodes |
| `nexolab_get_node_status` | Read operational state and latest health/status |
| `nexolab_get_latest_telemetry` | Read current telemetry with filters |
| `nexolab_get_telemetry_history` | Read a bounded historical interval |
| `nexolab_get_active_alarms` | Read current low/high telemetry alarms |

Every tool is annotated as read-only, non-destructive and idempotent. v0.1 deliberately has no start/stop, setpoint, Modbus-write, node-lifecycle, credential-rotation, SQL, filesystem or reboot tool.

## Runtime requirements

- Node.js compatible with the main NEXOLAB project (`>=22.22.1 <23` or `>=24 <25`).
- npm 10+.
- Reachable NEXOLAB Telemetry API.
- Reachable Nodes API, if it is served separately.
- A dedicated backend Bearer credential when the NEXOLAB APIs require authentication.

## 1. Install

```bash
cd services/nexolab-mcp
npm install
```

`npm install` creates `package-lock.json`. Commit the lockfile before production deployment; after that, deploy with `npm ci`.

## 2. Configure

```bash
cp .env.example .env
chmod 600 .env
```

The Telemetry API URL is **required**. Use the real base URL from the deployment. The NEXOLAB frontend currently obtains this from `NEXT_PUBLIC_NEXOLAB_API_BASE_URL`; use the corresponding server-reachable URL here.

Example:

```dotenv
NEXOLAB_MCP_HOST=127.0.0.1
NEXOLAB_MCP_PORT=8787

NEXOLAB_TELEMETRY_API_URL=http://127.0.0.1:<actual-port>
# Optional: omit when Nodes API uses the same base URL.
NEXOLAB_NODES_API_URL=

# Set when backend endpoints require authentication.
NEXOLAB_BACKEND_BEARER_TOKEN=

# Strongly recommended. Mandatory when MCP binds outside loopback.
NEXOLAB_MCP_BEARER_TOKEN=

NEXOLAB_MCP_ALLOWED_HOSTS=
NEXOLAB_MCP_ALLOWED_ORIGINS=

NEXOLAB_MCP_REQUEST_TIMEOUT_MS=8000
NEXOLAB_MCP_MAX_LATEST_ITEMS=200
NEXOLAB_MCP_MAX_HISTORY_ITEMS=500
NEXOLAB_MCP_MAX_HISTORY_HOURS=744
```

Generate the MCP access secret with:

```bash
openssl rand -hex 32
```

Put the result in `NEXOLAB_MCP_BEARER_TOKEN`. Never commit the real token or `.env`.

### Backend credential rule

`NEXOLAB_BACKEND_BEARER_TOKEN` is for MCP -> NEXOLAB API calls. In production, use a dedicated least-privilege identity that can only read the required APIs. Do not permanently reuse a personal browser/session token.

## 3. Validate locally

Run all gates before deployment:

```bash
npm run typecheck
npm test
npm run build
```

Then load the environment and run the compiled server:

```bash
set -a
. ./.env
set +a
npm start
```

Liveness check:

```bash
curl http://127.0.0.1:8787/healthz
```

Expected response:

```json
{"status":"ok","service":"nexolab-mcp","version":"0.1.0"}
```

`/healthz` verifies the MCP process. Backend/ingestion readiness is read through the `nexolab_get_system_health` MCP tool.

## 4. Verify with MCP Inspector

Run the official Inspector:

```bash
npx @modelcontextprotocol/inspector
```

Choose **Streamable HTTP** and connect to:

```text
http://127.0.0.1:8787/mcp
```

When `NEXOLAB_MCP_BEARER_TOKEN` is configured, send:

```text
Authorization: Bearer <token>
```

CLI smoke test:

```bash
npx @modelcontextprotocol/inspector --cli \
  http://127.0.0.1:8787/mcp \
  --transport http \
  --method tools/list \
  --header "Authorization: Bearer <token>"
```

Verify that exactly the six documented tools are present. Then call, in order:

1. `nexolab_get_system_health`
2. `nexolab_list_nodes`
3. `nexolab_get_latest_telemetry` with a known metric
4. `nexolab_get_telemetry_history` for a short interval
5. `nexolab_get_active_alarms`

Do not deploy if an unexpected write-capable tool appears.

## 5. Raspberry Pi deployment

Recommended layout:

```text
/opt/nexolab/nexolab-platform/services/nexolab-mcp
/etc/nexolab/nexolab-mcp.env
/etc/systemd/system/nexolab-mcp.service
```

If the repository currently lives elsewhere, either deploy/copy it under `/opt/nexolab/nexolab-platform` or edit `WorkingDirectory` and `ExecStart` in `deploy/nexolab-mcp.service` to match the real path.

Build:

```bash
cd /opt/nexolab/nexolab-platform/services/nexolab-mcp
npm ci
npm run typecheck
npm test
npm run build
```

Install the environment file:

```bash
sudo install -d -m 0750 -o root -g nexolab /etc/nexolab
sudo install -m 0640 -o root -g nexolab .env /etc/nexolab/nexolab-mcp.env
```

Install and start systemd service:

```bash
sudo cp deploy/nexolab-mcp.service /etc/systemd/system/nexolab-mcp.service
sudo systemctl daemon-reload
sudo systemctl enable --now nexolab-mcp
```

Check:

```bash
systemctl status nexolab-mcp --no-pager
journalctl -u nexolab-mcp -n 100 --no-pager
curl http://127.0.0.1:8787/healthz
```

The supplied systemd unit enables process hardening such as `NoNewPrivileges`, `ProtectSystem=strict`, `ProtectHome`, `PrivateTmp`, and `PrivateDevices` because this gateway does not need local device or filesystem access.

## 6. Network security

### Preferred deployment

Keep:

```dotenv
NEXOLAB_MCP_HOST=127.0.0.1
```

Expose the service only through a trusted tunnel or authenticated HTTPS reverse proxy. This keeps the raw MCP listener off the LAN/Internet.

### Non-loopback bind

The process refuses to start on a non-loopback address unless both conditions are met:

1. `NEXOLAB_MCP_BEARER_TOKEN` is configured.
2. `NEXOLAB_MCP_ALLOWED_HOSTS` is explicitly configured.

Example:

```dotenv
NEXOLAB_MCP_HOST=0.0.0.0
NEXOLAB_MCP_BEARER_TOKEN=<strong-random-secret>
NEXOLAB_MCP_ALLOWED_HOSTS=mcp.example.com
NEXOLAB_MCP_ALLOWED_ORIGINS=chatgpt.com
```

Use TLS for any external route. For a real multi-user ChatGPT integration, prefer OAuth/resource-server authorization over sharing a static token.

## 7. Resource limits

The MCP gateway deliberately limits context and backend load:

- latest telemetry: default maximum 200 items;
- history: default maximum 500 items;
- history interval: default maximum 744 hours (31 days);
- backend timeout: default 8 seconds;
- node listing: maximum 100 nodes per call.

All limits are validated server-side; the model cannot bypass them by crafting a larger request.

## 8. ChatGPT connection status (2026-08-18)

The MCP service can be built and validated now without any OpenAI API call or token billing.

Direct custom-MCP support inside ChatGPT depends on the current plan and Developer Mode availability. As of this document date, the public OpenAI documentation does not list Plus as a plan with direct custom MCP Developer Mode access. Use MCP Inspector for local validation on Plus. When the account/workspace supports custom MCP, point it to the remote `/mcp` endpoint and scan the tools; no NEXOLAB MCP redesign should be required.

ChatGPT cannot directly connect to `localhost`. For supported plans/workspaces, an on-premises/private MCP server should be reached through OpenAI Secure MCP Tunnel or another properly authenticated remote HTTPS route.

## 9. Future write tools

Do **not** simply add equipment-control methods beside these read tools. Any future write capability must have a separate review and should include:

- dedicated authorization scopes;
- explicit audit records;
- idempotency for repeatable commands;
- domain-level safety interlocks in NEXOLAB;
- clear destructive/write MCP annotations;
- strict target/value/range validation;
- no generic shell/SQL/Modbus-write escape hatch;
- confirmation where appropriate, without treating confirmation as the only safety barrier.

## 10. Troubleshooting

### `NEXOLAB_TELEMETRY_API_URL is required`

Set it to the actual server-reachable NEXOLAB Telemetry API base URL. Do not guess the port.

### `401 unauthorized` from `/mcp`

The client is missing or has the wrong `Authorization: Bearer ...` value.

### `403 forbidden` from `/mcp`

The request Host or Origin is outside the configured allow-list. Check reverse-proxy/tunnel Host forwarding and `NEXOLAB_MCP_ALLOWED_HOSTS` / `NEXOLAB_MCP_ALLOWED_ORIGINS`.

### `NEXOLAB API returned HTTP 401/403`

MCP itself is reachable, but its backend credential cannot read NEXOLAB. Fix `NEXOLAB_BACKEND_BEARER_TOKEN` or the backend service-auth policy.

### timeout

Check the API URLs, service status and firewall, then inspect `NEXOLAB_MCP_REQUEST_TIMEOUT_MS`.

### empty telemetry

Call `nexolab_get_system_health`, then call `nexolab_get_latest_telemetry` without filters. Add filters one by one only after confirming the raw feed is available.
