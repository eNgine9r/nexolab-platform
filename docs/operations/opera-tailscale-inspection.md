# Opera + Tailscale read-only inspection

## Purpose

This runbook records the host-local browser-inspection pattern accepted under Issue #730. It lets an authorized NEXOLAB maintainer inspect the LOCAL_LAN UI through Opera/Tailscale without storing a normal operator password in Git, browser automation, shell history or logs.

This is inspection tooling, not a production feature deployment. The normal dashboard, Device Agent, database, MQTT and hardware acquisition remain independent of this helper.

## Accepted topology

```text
approved tailnet workstation
        |
        | HTTPS + trusted Tailscale identity
        v
Tailscale Serve :8443 (tailnet only)
        |
        +-- / ----------------> 127.0.0.1:3100 inspection frontend
        |
        +-- /api -------------> central Telemetry Service /api

inspection frontend
        |
        +-- /inspection-login
                |
                +-- verify trusted Tailscale user + approved client address
                +-- server-side local-auth login for dedicated viewer account
                +-- establish normal short-lived browser local-auth session
                +-- redirect to /
```

The helper must never expose a Tailscale Funnel/public-internet route.

## Security boundary

The automatic identity is a dedicated local `viewer` account. Its accepted permission set is read-only:

- `dashboard.read`;
- `telemetry.read`;
- `alerts.read`;
- `reports.read`;
- `nodes.read`.

Do not use an administrator, laboratory-manager or engineer credential for automatic browser inspection.

Authentication is not disabled or bypassed. The helper calls the canonical NEXOLAB local-auth login endpoint and receives the same access/refresh session used by the normal frontend. Backend RBAC remains authoritative.

Privileged workflows such as user administration, equipment mutation, layout publication or other write operations require a separately authenticated operator with the required server-side permissions.

## Host-local files

Current host-local implementation is intentionally outside Git-tracked source under:

```text
/home/nexolab/runtime/inspection/opera-tailscale/
```

The dedicated credential is stored only in a host-owned secret directory. Required permissions:

```text
secret directory  0700
credential file   0600
```

Never print, copy, commit or attach the credential contents. Access and refresh tokens must not be written to logs or evidence files.

The current user service unit is:

```text
~/.config/systemd/user/nexolab-opera-inspection.service
```

It binds the inspection frontend only to `127.0.0.1:3100` and is configured to restart on failure.

## Device binding

Before credential exchange, `/inspection-login` must validate trusted values injected by Tailscale Serve:

- `Tailscale-User-Login` equals the approved tailnet identity;
- `X-Forwarded-For` resolves to the approved workstation tailnet address;
- `X-Forwarded-Proto` is `https`;
- `X-Forwarded-Host` is the expected private NEXOLAB inspection origin.

Do not trust browser-supplied identity headers outside Tailscale Serve. Do not weaken this check to “any tailnet user”.

A direct loopback request to `/inspection-login` without trusted proxy identity must return HTTP `403` before any local-auth credential exchange occurs.

## Normal inspection entry point

Use the private tailnet inspection origin and open:

```text
https://<nexolab-node>.<tailnet>.ts.net:8443/inspection-login
```

For an approved workstation, the route creates a normal short-lived viewer session and redirects to `/` automatically.

Successful acceptance requires the application shell to identify the dedicated inspection viewer and the dashboard to report both REST synchronization and an active WebSocket.

## Operational verification

On the Raspberry Pi, verify the user service without printing its environment secrets:

```bash
export XDG_RUNTIME_DIR=/run/user/$(id -u)
export DBUS_SESSION_BUS_ADDRESS=unix:path="$XDG_RUNTIME_DIR/bus"

systemctl --user is-enabled nexolab-opera-inspection.service
systemctl --user is-active nexolab-opera-inspection.service
ss -ltnp '( sport = :3100 )'
```

Expected local bind:

```text
127.0.0.1:3100
```

Verify the frontend and fail-closed bootstrap locally:

```bash
curl --max-time 30 -sS -o /dev/null -w '%{http_code}\n' \
  http://127.0.0.1:3100/

curl --max-time 10 -sS -o /dev/null -w '%{http_code}\n' \
  http://127.0.0.1:3100/inspection-login
```

Expected results:

```text
root:             200
inspection-login: 403
```

Verify Tailscale Serve remains private and same-origin:

```bash
tailscale serve status
```

The accepted shape is one tailnet-only HTTPS origin whose root points to the loopback inspection frontend and whose `/api` path points to the existing central API.

## Restart verification

A host/user-session restart must not require re-entering the inspection password.

Controlled service restart:

```bash
export XDG_RUNTIME_DIR=/run/user/$(id -u)
export DBUS_SESSION_BUS_ADDRESS=unix:path="$XDG_RUNTIME_DIR/bus"

systemctl --user restart nexolab-opera-inspection.service
systemctl --user is-active nexolab-opera-inspection.service
```

After restart, open a fresh Opera tab through `/inspection-login`. Acceptance is GREEN only when the browser reaches the authenticated application shell with the dedicated viewer identity and live REST/WebSocket state.

## Revocation and rollback

To stop the inspection frontend without touching the production dashboard or persistent volumes:

```bash
export XDG_RUNTIME_DIR=/run/user/$(id -u)
export DBUS_SESSION_BUS_ADDRESS=unix:path="$XDG_RUNTIME_DIR/bus"

systemctl --user disable --now nexolab-opera-inspection.service
```

Revoke all refresh sessions for the dedicated inspection account through the repository local-auth administration tooling. Do not reset or reuse a normal operator password for this purpose.

If the Tailscale Serve route must be reverted, restore it through the controlled Tailscale Serve procedure. Do not use Funnel, wildcard CORS, disabled authentication or a public reverse proxy as a shortcut.

Rollback must not delete PostgreSQL data, named volumes, Device Agent state or hardware configuration.

## Evidence rules

Safe evidence may include:

- service `enabled/active` state;
- loopback listening address;
- Tailscale Serve topology without secrets;
- viewer role and effective permission names;
- HTTP status codes;
- browser shell identity label;
- REST/WebSocket readiness state.

Do not include:

- passwords;
- access or refresh tokens;
- private signing keys;
- cookies;
- full secret files;
- production telemetry payload dumps.

## Hardware and runtime classification

```text
Modbus write: none
hardware write: none
production feature cutover: none
persistent-data deletion: none
mandatory public runtime dependency: none
```

The helper is optional tooling. NEXOLAB core acquisition, persistence and LOCAL_LAN operation must continue to function without Opera, Tailscale or this inspection service.
