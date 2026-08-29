# Opera + Tailscale read-only inspection

## Purpose

This runbook defines the optional NEXOLAB browser-inspection path accepted under Issue #730. It gives an authorized maintainer one-click read-only UI access through private Tailscale HTTPS without storing a normal operator password in Git, browser automation, shell history, service arguments or logs.

The helper is presentation/maintenance tooling. Core LOCAL_LAN Dashboard, Device Agent, PostgreSQL, MQTT and hardware acquisition do not depend on it.

## Security model

The automatic identity is a dedicated local `viewer` account with only:

- `dashboard.read`;
- `telemetry.read`;
- `alerts.read`;
- `reports.read`;
- `nodes.read`.

Authentication and backend RBAC remain authoritative. Administrator, laboratory-manager and mutation workflows require a separate normal login.

## Accepted topology

```text
approved tailnet workstation
        |
        | HTTPS + Tailscale identity headers
        v
Tailscale Serve :8443 (tailnet only)
        |
        +-- / ----------------> 127.0.0.1:3100 inspection frontend
        |
        +-- /api -------------> existing Telemetry Service /api
        |
        +-- /inspection-login -> root-owned Unix socket 0600
                                      |
                                      +-> socket-activated helper
                                      +-> canonical local-auth login
                                      +-> short-lived viewer session
```

The credential-exchange route must **not** exist on TCP port `3100`. A local process must not be able to reach the login helper merely by forging proxy headers.

## Repository-owned implementation

The reconstructible, secret-free implementation is tracked under:

```text
scripts/inspection/opera_tailscale_login.py
scripts/inspection/opera-tailscale-config.example.json
scripts/inspection/systemd/nexolab-opera-inspection-login.socket
scripts/inspection/systemd/nexolab-opera-inspection-login.service
```

Policy tests live in:

```text
tests/test_opera_tailscale_inspection.py
```

Do not place workstation identity, tailnet account identity, passwords, tokens or the populated host config in Git. The example config contains placeholders only.

## Host-local files

Use the ignored host path:

```text
/home/nexolab/runtime/inspection/opera-tailscale/
```

Required secret/config permissions:

```text
secret directory   0700
credential file    0600
config file        0600
```

The Unix socket is created by the system socket unit at:

```text
/run/nexolab-opera-inspection/login.sock
```

It must be `0600 root:root`. The helper itself runs as the unprivileged `nexolab` user and receives the already-open listen socket from systemd.

## Install or recover the helper

From a checked-out accepted repository revision, copy the helper and unit templates into host-local/system locations. Keep the populated config and credential outside Git.

```bash
install -d -m 0700 /home/nexolab/runtime/inspection/opera-tailscale/helper
install -m 0755 scripts/inspection/opera_tailscale_login.py \
  /home/nexolab/runtime/inspection/opera-tailscale/helper/opera_tailscale_login.py

sudo install -m 0644 scripts/inspection/systemd/nexolab-opera-inspection-login.socket \
  /etc/systemd/system/nexolab-opera-inspection-login.socket
sudo install -m 0644 scripts/inspection/systemd/nexolab-opera-inspection-login.service \
  /etc/systemd/system/nexolab-opera-inspection-login.service
```

Create `/home/nexolab/runtime/inspection/opera-tailscale/config.json` from the repository example, replace placeholders locally, and set mode `0600`. Never paste its populated values into an Issue or PR.
Enable the socket after the host-local config and credential exist:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now nexolab-opera-inspection-login.socket
```

Verify:

```bash
systemctl is-enabled nexolab-opera-inspection-login.socket
systemctl is-active nexolab-opera-inspection-login.socket
stat -c '%a %U %G %n' /run/nexolab-opera-inspection/login.sock
```

Expected socket evidence:

```text
enabled
active
600 root root /run/nexolab-opera-inspection/login.sock
```

Do not start the helper as a standalone TCP listener.

## Tailscale Serve configuration

Before changing Serve, save the current configuration outside Git:

```bash
sudo tailscale serve get-config --all \
  /home/nexolab/runtime/inspection/opera-tailscale/serve-before.json
chmod 0600 /home/nexolab/runtime/inspection/opera-tailscale/serve-before.json
```

Add only the inspection-login path to the root-owned Unix socket:

```bash
sudo tailscale serve --bg --yes --https=8443 \
  --set-path=/inspection-login \
  unix:/run/nexolab-opera-inspection/login.sock
```

Do not use Funnel. The existing `/` and `/api` handlers must remain unchanged.
Verify the accepted handler shape:

```bash
tailscale serve status
```

Expected structure:

```text
/                 -> inspection frontend on 127.0.0.1:3100
/api              -> existing Telemetry Service API
/inspection-login -> unix:/run/nexolab-opera-inspection/login.sock
```

The helper accepts credential exchange only when both boundaries pass:

1. the Unix peer is root (`SO_PEERCRED`), proving the request came through the privileged proxy path rather than an ordinary local process;
2. Tailscale identity/source/HTTPS/host headers exactly match the approved host-local configuration.

Either failure returns `403` before the credential file is read.

## Negative security verification

The frontend TCP port must not expose the credential route:

```bash
curl --max-time 10 -sS -o /dev/null -w '%{http_code}\n' \
  http://127.0.0.1:3100/inspection-login
```

Expected: `404`.

An ordinary unprivileged local process must be unable to connect to the Unix socket because the socket is `0600 root:root`. Repository policy tests additionally verify exact identity matching, local-only redirects, socket peer credentials and root-only socket ownership.

Never weaken this into trusting browser-supplied `X-Forwarded-*` or `Tailscale-*` headers on a normal TCP listener.

## Positive browser verification

Open the private tailnet origin from the approved Opera workstation:

```text
https://<nexolab-node>.<tailnet>.ts.net:8443/inspection-login
```

Acceptance requires:

- automatic redirect into the normal authenticated NEXOLAB shell;
- dedicated viewer identity only;
- effective permissions remain read-only;
- REST snapshot synchronizes;
- WebSocket becomes active;
- ordinary `/login` remains available as the fallback if the helper is unavailable.

Do not collect cookies, access tokens or refresh tokens as evidence.

## Restart and persistence

The inspection frontend user service is enabled with `Linger=yes`; the privileged login socket is a system socket unit enabled under `sockets.target`.

Configuration evidence:

```bash
export XDG_RUNTIME_DIR=/run/user/$(id -u)
export DBUS_SESSION_BUS_ADDRESS=unix:path="$XDG_RUNTIME_DIR/bus"
systemctl --user is-enabled nexolab-opera-inspection.service
systemctl --user is-active nexolab-opera-inspection.service
loginctl show-user nexolab -p Linger -p State -p RuntimePath
systemctl is-enabled nexolab-opera-inspection-login.socket
systemctl is-active nexolab-opera-inspection-login.socket
```

A controlled service restart is accepted as service-level evidence. A full host reboot is **not** implied unless it was actually performed and recorded. If reboot evidence is unavailable, use the deterministic recovery commands below instead of claiming reboot acceptance.
Deterministic service recovery:

```bash
export XDG_RUNTIME_DIR=/run/user/$(id -u)
export DBUS_SESSION_BUS_ADDRESS=unix:path="$XDG_RUNTIME_DIR/bus"
systemctl --user restart nexolab-opera-inspection.service
sudo systemctl restart nexolab-opera-inspection-login.socket
```

Then verify both units, socket ownership and `tailscale serve status` before opening Opera.

## Revocation and rollback

To revoke browser bootstrap without touching production Dashboard/API/data:

```bash
sudo tailscale serve --https=8443 --set-path=/inspection-login off
sudo systemctl disable --now nexolab-opera-inspection-login.socket
```

Also stop/disable the user inspection frontend if the entire optional inspection path is being retired.
To restore the complete previously saved Serve configuration instead of editing handlers manually:

```bash
sudo tailscale serve set-config \
  /home/nexolab/runtime/inspection/opera-tailscale/serve-before.json \
  --all
```

Revoke/deactivate the dedicated inspection account and its refresh sessions with the existing local-auth administration tooling. Never reset or reuse a normal operator password for this purpose.

Rollback must not delete PostgreSQL data, named volumes, Device Agent state or hardware configuration.

## Evidence rules

Safe evidence may include service enabled/active state, Unix socket mode/owner, tailnet-only Serve handler topology, dedicated viewer role/permission names, HTTP status codes and browser REST/WebSocket readiness.

Never include passwords, populated host config identity values, access/refresh tokens, cookies, private keys or credential-file contents.

## Acceptance evidence boundary

Current accepted host evidence includes the private `:8443` Serve topology, read-only viewer role, service-level restart, `Linger=yes`, enabled system socket, `0600 root:root` Unix login socket, unprivileged local socket denial, HTTP `404` for `/inspection-login` on the normal frontend port, and HTTP `403` when the Raspberry Pi itself reaches the real tailnet `/inspection-login` route with a non-approved Tailscale identity.

A host reboot is not claimed by this runbook unless separately performed and recorded. The deterministic restart/recovery commands above satisfy the alternative restart criterion when reboot evidence is intentionally not collected.

## Runtime classification

```text
Modbus write: none
hardware write: none
production feature cutover: none
persistent-data deletion: none
public Funnel: none
mandatory public runtime dependency: none
```

The inspection path is optional. NEXOLAB core acquisition, persistence and LOCAL_LAN operation must remain functional when Opera, Tailscale or this helper are unavailable.
