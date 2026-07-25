# Central-host Tailscale TLS acceptance

## Scope

This procedure deploys the NEXOLAB dashboard and the central refrigeration-layout backend on one controlled Linux host while exposing only three HTTPS endpoints inside the tailnet:

```text
operator browser
  ├─ https://<node>.ts.net       → Tailscale Serve → 127.0.0.1:3000 dashboard
  ├─ https://<node>.ts.net:8443  → Tailscale Serve → 127.0.0.1:8082 REST + WSS
  └─ https://<node>.ts.net:9443  → Tailscale Serve → 127.0.0.1:9000 MinIO signed objects
```

PostgreSQL remains Docker-network-only. MinIO anonymous access remains disabled. The API trusts `Tailscale-User-Login` only when `OPERATOR_IDENTITY_MODE=tailscale_serve` and the host binding remains `127.0.0.1`.

Tailscale Serve is intentionally used instead of Funnel. The application must remain private to the tailnet.

## Security invariants

- `CENTRAL_BIND_ADDRESS=127.0.0.1`;
- no PostgreSQL host port;
- exact dashboard origin in `CORS_ALLOWED_ORIGINS`;
- separate dashboard and API origins so browser CORS is exercised;
- API `ETag` is exposed to the browser;
- signed object URLs use the external HTTPS storage origin;
- operator audit identity comes from Tailscale Serve headers, not `actor_id` or `X-Actor-Id` supplied by JavaScript;
- requests without `Tailscale-User-Login` receive `401 operator_identity_required` for upload and publish mutations;
- `tailscale funnel` is not configured;
- rollback never removes Docker volumes.

Tailscale documents that Serve removes incoming identity-header values before injecting trusted `Tailscale-User-*` headers. It also recommends keeping a backend that trusts these headers on localhost. See:

- <https://tailscale.com/docs/features/tailscale-serve>
- <https://tailscale.com/docs/reference/tailscale-cli/serve>
- <https://tailscale.com/docs/features/access-control/grants>

## 1. Tailnet boundary

Assign the central host a service tag such as `tag:nexolab-central`. Grant only the operator group access to the three Serve ports:

```jsonc
{
  "groups": {
    "group:nexolab-operators": ["operator@example.com"]
  },
  "tagOwners": {
    "tag:nexolab-central": ["autogroup:admin"]
  },
  "grants": [
    {
      "src": ["group:nexolab-operators"],
      "dst": ["tag:nexolab-central"],
      "ip": ["tcp:443", "tcp:8443", "tcp:9443"]
    }
  ]
}
```

Do not grant operator workstations access to ports `3000`, `8082`, `9000`, `9001` or `5432`. Those ports are not meant to be reachable through the tailnet interface.

Enable MagicDNS and HTTPS certificates in the tailnet. Confirm the central host name:

```bash
tailscale status --json \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))'
```

## 2. Central environment

```bash
cd ~/nexolab-platform/infrastructure/compose
cp .env.central.example .env.central
chmod 600 .env.central
```

Replace all example values. The following values must describe the same central node:

```dotenv
CENTRAL_BIND_ADDRESS=127.0.0.1
TAILSCALE_NODE_FQDN=nexolab-central.<tailnet>.ts.net
TAILSCALE_DASHBOARD_HTTPS_PORT=443
TAILSCALE_API_HTTPS_PORT=8443
TAILSCALE_STORAGE_HTTPS_PORT=9443

NEXT_PUBLIC_NEXOLAB_API_BASE_URL=https://nexolab-central.<tailnet>.ts.net:8443
NEXT_PUBLIC_NEXOLAB_WEBSOCKET_URL=wss://nexolab-central.<tailnet>.ts.net:8443/api/v1/telemetry/live
OBJECT_STORAGE_PUBLIC_ENDPOINT_URL=https://nexolab-central.<tailnet>.ts.net:9443
CORS_ALLOWED_ORIGINS=https://nexolab-central.<tailnet>.ts.net
OPERATOR_IDENTITY_MODE=tailscale_serve
```

`NEXT_PUBLIC_*` values are embedded when the dashboard image is built. A URL change therefore requires rebuilding the dashboard image.

Keep `NEXT_PUBLIC_NEXOLAB_ACCEPTANCE_EQUIPMENT_ENABLED=false` for normal operation. Change it to `true` only for the controlled acceptance window, rebuild the dashboard, execute the gate, then return it to `false` and rebuild again.

## 3. Validate before deployment

```bash
cd ~/nexolab-platform/infrastructure/compose

docker compose \
  --env-file .env.central \
  -f compose.central.yaml \
  -f compose.central-dashboard.yaml \
  config --quiet

bash -n tailscale-serve-central.sh
bash -n collect-remote-acceptance-evidence.sh
```

Inspect resolved host bindings:

```bash
docker compose \
  --env-file .env.central \
  -f compose.central.yaml \
  -f compose.central-dashboard.yaml \
  config \
  | sed -n '/ports:/,/volumes:/p'
```

Every published application port must start with `127.0.0.1:`. PostgreSQL must have no `ports` section.

## 4. Deploy and configure Tailscale Serve

```bash
cd ~/nexolab-platform/infrastructure/compose
sudo bash tailscale-serve-central.sh apply .env.central
```

The script:

1. validates the exact FQDN and URL relationships;
2. rejects any non-loopback central binding;
3. builds and starts PostgreSQL, MinIO, telemetry service and dashboard;
4. resets only the existing Serve configuration on this node;
5. creates HTTPS listeners on ports `443`, `8443` and `9443`;
6. verifies local dashboard, API and MinIO readiness.

Review state:

```bash
sudo bash tailscale-serve-central.sh status .env.central
tailscale serve status --json | python3 -m json.tool
```

## 5. Operator workstation acceptance

The gate must be run from a real user-owned workstation logged in to the tailnet. Tagged nodes do not receive Tailscale user identity headers.

```bash
cd ~/nexolab-platform/infrastructure/compose
cp .env.remote-acceptance.example .env.remote-acceptance
chmod 600 .env.remote-acceptance
```

Fill in the real origins and the expected Tailscale login. On the central host, temporarily set:

```dotenv
NEXT_PUBLIC_NEXOLAB_ACCEPTANCE_EQUIPMENT_ENABLED=true
```

Rebuild the dashboard profile:

```bash
cd ~/nexolab-platform/infrastructure/compose
docker compose \
  --env-file .env.central \
  -f compose.central.yaml \
  -f compose.central-dashboard.yaml \
  up -d --build --wait dashboard
```

Run from the operator workstation:

```bash
cd ~/nexolab-platform
bash scripts/run-refrigeration-remote-acceptance.sh \
  infrastructure/compose/.env.remote-acceptance
```

The runner requires valid TLS and does not allow `ignoreHTTPSErrors`. It checks:

- dashboard, API and storage certificate validation;
- exact allowed CORS origin;
- absence of CORS permission for `https://untrusted.invalid`;
- exposed `ETag` and initial draft `v1`;
- real `/api/v1/operator/session` identity;
- WSS connection;
- external HTTPS MinIO signed URL and `HTTP 200 image/png`;
- 48-position save and immutable `r1` publication;
- trusted `published_by` value;
- two-context stale-writer recovery;
- final draft `v5`.

The generated equipment identifier starts with `acceptance-`. Record it from the runner output.

## 6. Central-host evidence

On the central host, collect SQL, MinIO and Serve evidence for the exact generated equipment id:

```bash
cd ~/nexolab-platform/infrastructure/compose
bash collect-remote-acceptance-evidence.sh \
  .env.central \
  acceptance-YYYYMMDDTHHMMSSZ-PID
```

Expected evidence:

- one draft at `v5` with 48 placements;
- one immutable revision `r1` sourced from `v3` with 48 placements;
- `published_by` and image `created_by` equal the real Tailscale login;
- private MinIO bucket and stored PNG object;
- only loopback host publications;
- three Tailscale Serve HTTPS routes.

Do not attach `.env.central`, MinIO credentials, PostgreSQL credentials or full signed URL query values.

## 7. Close the acceptance window

Return the dashboard build flag to normal:

```dotenv
NEXT_PUBLIC_NEXOLAB_ACCEPTANCE_EQUIPMENT_ENABLED=false
```

Rebuild only the dashboard:

```bash
docker compose \
  --env-file .env.central \
  -f compose.central.yaml \
  -f compose.central-dashboard.yaml \
  up -d --build --wait dashboard
```

The acceptance database rows and object may be retained as auditable evidence or removed later through a separately reviewed maintenance procedure. The current production API intentionally provides no destructive layout endpoint.

## 8. Rollback

Remove remote exposure without touching containers or data:

```bash
sudo bash tailscale-serve-central.sh reset .env.central
```

Roll back the dashboard image:

```bash
# Set NEXOLAB_DASHBOARD_IMAGE to a previously validated immutable tag.
docker compose \
  --env-file .env.central \
  -f compose.central.yaml \
  -f compose.central-dashboard.yaml \
  up -d --no-deps dashboard
```

Stop application containers while preserving volumes:

```bash
docker compose \
  --env-file .env.central \
  -f compose.central.yaml \
  -f compose.central-dashboard.yaml \
  down --remove-orphans
```

Never use `down -v` for rollback.
