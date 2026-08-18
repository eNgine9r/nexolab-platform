# NEXOLAB MCP Server

Production-oriented, read-only Model Context Protocol gateway for NEXOLAB telemetry and edge-node data.

## Why this service exists

The MCP service is an adapter, not a second NEXOLAB backend. It calls the existing NEXOLAB Nodes and Telemetry HTTP APIs and exposes a deliberately small, bounded tool surface to MCP clients.

It does **not** call the OpenAI API and does not require an `OPENAI_API_KEY`.

## Architecture

```text
MCP client
   |
   | Streamable HTTP /mcp
   v
NEXOLAB MCP (Node.js, read-only)
   |                |
   | GET only       | GET only
   v                v
Telemetry API     Nodes API
   |                |
   +------ NEXOLAB runtime ------+
```

The MCP process has no shell tool, no arbitrary URL-fetch tool, no SQL tool, and no write endpoint.

## Exposed tools

| Tool | Purpose |
| --- | --- |
| `nexolab_get_system_health` | Telemetry ingestion/readiness status |
| `nexolab_list_nodes` | List configured edge nodes |
| `nexolab_get_node_status` | Operational state + most recent health/status |
| `nexolab_get_latest_telemetry` | Latest samples with bounded filters |
| `nexolab_get_telemetry_history` | Bounded historical telemetry interval |
| `nexolab_get_active_alarms` | Latest low/high alarm samples |

Every tool is annotated `readOnlyHint: true`, `destructiveHint: false`, `idempotentHint: true`, and `openWorldHint: false`.

## Requirements

- Raspberry Pi OS / Linux, Windows, or another OS supported by Node.js.
- Node.js matching the NEXOLAB project engine requirement (Node 22.22.1+ in the 22.x line, or Node 24.x).
- npm 10+.
- Reachable NEXOLAB Telemetry and Nodes APIs.
- A backend Bearer credential if those APIs require authentication.

## 1. Install dependencies

From the repository root:

```bash
cd services/nexolab-mcp
npm install
```

Before deployment, keep the generated `package-lock.json` in version control so production installs can use `npm ci`.

## 2. Configure the service

Copy the example file:

```bash
cp .env.example .env
chmod 600 .env
```

Minimum local configuration:

```dotenv
NEXOLAB_MCP_HOST=127.0.0.1
NEXOLAB_MCP_PORT=8787
NEXOLAB_TELEMETRY_API_URL=http://127.0.0.1:8100
NEXOLAB_NODES_API_URL=http://127.0.0.1:8100
```

If the backend APIs are protected:

```dotenv
NEXOLAB_BACKEND_BEARER_TOKEN=<dedicated-read-only-backend-token>
```

Use a dedicated least-privilege credential. Do not permanently copy a personal browser session token into production configuration.

Generate a separate token for access to the MCP endpoint:

```bash
openssl rand -hex 32
```

Put the output in:

```dotenv
NEXOLAB_MCP_BEARER_TOKEN=<generated-secret>
```

Never commit `.env` or the real token.

## 3. Validate before running

```bash
npm run typecheck
npm test
npm run build
```

All three commands must pass before deployment.

## 4. Run locally

Load `.env` into the shell and start the compiled service:

```bash
set -a
. ./.env
set +a
npm start
```

Expected log includes:

```text
{"service":"nexolab-mcp","event":"server_started",...}
```

Check liveness:

```bash
curl http://127.0.0.1:8787/healthz
```

Expected response:

```json
{"status":"ok","service":"nexolab-mcp","version":"0.1.0"}
```

`/healthz` is process liveness. NEXOLAB backend readiness is intentionally exposed through the `nexolab_get_system_health` MCP tool.

## 5. Test with the official MCP Inspector

Run the Inspector:

```bash
npx @modelcontextprotocol/inspector
```

Select **Streamable HTTP** and use:

```text
http://127.0.0.1:8787/mcp
```

If `NEXOLAB_MCP_BEARER_TOKEN` is set, add the HTTP header:

```text
Authorization: Bearer <your-token>
```

CLI smoke test:

```bash
npx @modelcontextprotocol/inspector --cli \
  http://127.0.0.1:8787/mcp \
  --transport http \
  --method tools/list \
  --header "Authorization: Bearer <your-token>"
```

Then test at least these calls:

1. `nexolab_get_system_health`
2. `nexolab_list_nodes`
3. `nexolab_get_latest_telemetry` with `metric=temperature`
4. `nexolab_get_telemetry_history` for a short known interval
5. `nexolab_get_active_alarms`

Do not deploy if the tool list contains any unexpected write-capable tool.

## 6. Raspberry Pi production deployment with systemd

The recommended production layout is:

```text
/opt/nexolab/nexolab-platform/services/nexolab-mcp
/etc/nexolab/nexolab-mcp.env
/etc/systemd/system/nexolab-mcp.service
```

Create the configuration directory:

```bash
sudo install -d -m 0750 -o root -g nexolab /etc/nexolab
sudo install -m 0640 -o root -g nexolab .env /etc/nexolab/nexolab-mcp.env
```

Build the service:

```bash
cd /opt/nexolab/nexolab-platform/services/nexolab-mcp
npm ci
npm run typecheck
npm test
npm run build
```

Install the unit:

```bash
sudo cp deploy/nexolab-mcp.service /etc/systemd/system/nexolab-mcp.service
sudo systemctl daemon-reload
sudo systemctl enable --now nexolab-mcp
```

Inspect status and logs:

```bash
systemctl status nexolab-mcp --no-pager
journalctl -u nexolab-mcp -n 100 --no-pager
```

Verify locally:

```bash
curl http://127.0.0.1:8787/healthz
```

The supplied unit uses `NoNewPrivileges`, `ProtectSystem=strict`, `ProtectHome`, `PrivateTmp`, `PrivateDevices`, and other systemd hardening because the MCP gateway does not need local filesystem or device access.

## 7. Network exposure

### Recommended: keep MCP on loopback

Keep:

```dotenv
NEXOLAB_MCP_HOST=127.0.0.1
```

Then expose it only through a trusted tunnel or reverse proxy. This keeps the raw MCP listener unreachable from the LAN/Internet.

### Direct LAN/public bind

Direct exposure is deliberately fail-closed. If you set:

```dotenv
NEXOLAB_MCP_HOST=0.0.0.0
```

you must also set both a Bearer token and explicit allowed hosts:

```dotenv
NEXOLAB_MCP_BEARER_TOKEN=<strong-random-secret>
NEXOLAB_MCP_ALLOWED_HOSTS=mcp.example.com
```

TLS must terminate before traffic reaches the public Internet. Do not expose plain HTTP externally.

For a browser-facing deployment, configure an explicit Origin allow-list as well:

```dotenv
NEXOLAB_MCP_ALLOWED_ORIGINS=chatgpt.com
```

For a proper multi-user ChatGPT deployment, prefer standards-based OAuth in front of the MCP resource server rather than sharing one static Bearer token.

## 8. ChatGPT connection status as of 2026-08-18

The server itself is standards-compliant MCP and can be built/tested now without OpenAI API usage.

At the time this document was written, direct custom-MCP access in ChatGPT depends on the ChatGPT plan and Developer Mode availability. A Plus account should therefore use the local MCP Inspector for validation today; do not redesign the NEXOLAB server around a temporary product-plan limitation.

When custom MCP is available for the account/workspace:

1. Keep the MCP server on `127.0.0.1` if using OpenAI Secure MCP Tunnel, or expose it through a properly authenticated HTTPS endpoint.
2. In ChatGPT web, enable Developer Mode where the plan/workspace supports it.
3. Create a custom app/MCP connection.
4. Enter the remote `/mcp` endpoint.
5. Configure the supported authentication mechanism.
6. Run **Scan Tools**.
7. Confirm that exactly the six intended read-only NEXOLAB tools appear.
8. Test health and one narrow telemetry query before broader use.

Do not add write tools merely to make remote connectivity work. Connectivity and authorization are transport concerns; equipment control is a separate safety decision.

## 9. Configuration reference

| Variable | Default | Purpose |
| --- | --- | --- |
| `NEXOLAB_MCP_HOST` | `127.0.0.1` | MCP bind address |
| `NEXOLAB_MCP_PORT` | `8787` | MCP HTTP port |
| `NEXOLAB_TELEMETRY_API_URL` | `http://127.0.0.1:8100` | Telemetry service base URL |
| `NEXOLAB_NODES_API_URL` | telemetry URL | Nodes service base URL |
| `NEXOLAB_BACKEND_BEARER_TOKEN` | empty | Credential for MCP -> NEXOLAB APIs |
| `NEXOLAB_MCP_BEARER_TOKEN` | empty on loopback | Credential for client -> MCP |
| `NEXOLAB_MCP_ALLOWED_HOSTS` | loopback hostnames | DNS-rebinding/Host allow-list |
| `NEXOLAB_MCP_ALLOWED_ORIGINS` | Host allow-list | Browser Origin allow-list |
| `NEXOLAB_MCP_REQUEST_TIMEOUT_MS` | `8000` | Backend request timeout |
| `NEXOLAB_MCP_MAX_LATEST_ITEMS` | `200` | Max latest samples per tool call |
| `NEXOLAB_MCP_MAX_HISTORY_ITEMS` | `500` | Max history samples per tool call |
| `NEXOLAB_MCP_MAX_HISTORY_HOURS` | `744` | Max time span (31 days) |

## 10. Security rules for future development

Any future MCP tool must follow these rules unless a separate design/security review explicitly approves otherwise:

- Prefer NEXOLAB application APIs over direct database access.
- Never accept arbitrary SQL, shell commands, filesystem paths, or arbitrary URLs.
- Validate every argument with a strict schema and explicit size/range limits.
- Keep read and write tools separate.
- Mark read-only tools with MCP annotations.
- Treat text originating from devices, notes, labels, reports, or external services as untrusted data, not instructions.
- Never place secrets in tool results, logs, descriptions, or error messages.
- Use short backend timeouts and bounded response sizes.
- Use a dedicated least-privilege backend identity.
- Require explicit authorization for remote access.
- Keep an audit trail for any future state-changing action.
- For equipment control, add domain-level interlocks in NEXOLAB itself; never rely only on an LLM confirmation dialog.

## 11. Troubleshooting

### `401 unauthorized`

The MCP Bearer token is enabled but the client did not send the correct `Authorization` header.

### `403 forbidden`

Check `Host` and `Origin`. For a reverse proxy, either preserve an allow-listed public hostname and configure it in `NEXOLAB_MCP_ALLOWED_HOSTS`, or deliberately rewrite the upstream Host to the loopback host.

### `NEXOLAB API returned HTTP 401/403`

The MCP process can be reached, but its backend credential cannot read the NEXOLAB API. Configure a valid read-only `NEXOLAB_BACKEND_BEARER_TOKEN` or adjust the backend's service-auth mechanism.

### timeout

Confirm the Telemetry/Nodes API URL, service health, firewall rules, and `NEXOLAB_MCP_REQUEST_TIMEOUT_MS`.

### no telemetry

Call `nexolab_get_system_health`, then use `nexolab_get_latest_telemetry` without filters. Add one filter at a time after confirming the raw feed is available.

## Non-goals of v0.1

The initial release intentionally does not expose:

- start/stop tests;
- setpoint changes;
- Modbus writes;
- Raspberry Pi shell/reboot;
- node provisioning/suspension/revocation;
- credential rotation;
- arbitrary report/file retrieval;
- direct SQL access.

Those capabilities require separate write-path authorization, auditability, and equipment-safety controls.
