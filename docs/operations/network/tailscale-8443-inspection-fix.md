# Tailscale `:8443` private inspection origin: 502 fix (#1784)

Status: **prepared, not applied**. This is a network change: the owner runs it after WP2c Stage 2 is executed (#1734).

## Finding (2026-11-26, read-only)

`tailscale serve status` on `nexolab-edge-01`:

```text
https://<node>.ts.net:8443 (tailnet only)
|-- /                 proxy http://127.0.0.1:3102                      <- nothing listens: 502
|-- /api              proxy http://172.18.48.66:8082/api               <- compatibility address (Stage 3 consumer)
|-- /inspection-login proxy unix:/run/nexolab-opera-inspection/login.sock
```

- `3102` is the protected-release **candidate** port. It is only live while a release runs.
- The originally accepted root target `127.0.0.1:3100` (`opera-tailscale-inspection.md`) is retired as well.
- Neither live frontend fits this origin. `3104` (`lab.nexolab`, source `08f1c8a4`) and `3105` (HTTPS UI, source `7db6e1a8`) both compile the Funnel origin `https://nexolab-edge-01.tail7f9b04.ts.net` and its `wss://` into the browser bundle. From `:8443`, their API and WebSocket calls would go cross-origin to the OAuth-gated Funnel, so the viewer session issued by `/inspection-login` would not apply.
- The `/api` mapping sends **all** `/api/*` paths to the Telemetry Service, so it would also shadow dashboard routes such as `/api/runtime-identity`.

## Fix

The compatible frontend is a **same-origin** build, which is the WP2c Stage 2 LAN dashboard. The Stage 1 LAN gateway (`127.0.0.1:80`) already serves it with the right split:

- `/api/v1/…` (HTTP and WebSocket) goes to the Telemetry API;
- everything else goes to the dashboard.

So both `/` and `/api` of `:8443` point at the gateway, and `/inspection-login` stays unchanged.

After Stage 3 the gateway's upstreams move to loopback. `:8443` then needs no further change and no longer depends on the compatibility address.

### Preconditions (read-only)

```bash
curl -s http://127.0.0.1:3000/api/runtime-identity 2>/dev/null || curl -s http://172.18.48.66:3000/api/runtime-identity
# must show the Stage 2 same-origin build (not build CWBsCWWebOZGHa5YyWp18)
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1/__nexolab_lan_gateway/health        # 200
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1/api/runtime-identity                  # 200 (dashboard)
systemctl is-active nexolab-opera-inspection-login.socket                                         # active
```

### Apply (owner, sudo)

```bash
B=/home/nexolab/runtime/inspection/opera-tailscale/serve-before-1784-$(date -u +%Y%m%dT%H%M%SZ).json
sudo tailscale serve get-config --all | sudo -u nexolab tee "$B" >/dev/null && sudo chmod 0600 "$B"
sudo tailscale serve --bg --yes --https=8443 --set-path=/    http://127.0.0.1:80
sudo tailscale serve --bg --yes --https=8443 --set-path=/api http://127.0.0.1:80/api
tailscale serve status
```

Expected `:8443` shape: `/` and `/api` go to `http://127.0.0.1:80`, and `/inspection-login` still goes to the Unix socket. `:443` (Funnel), `:8444` and `:8445` stay unchanged.

### Verify

From the Pi (the tailnet address with SNI) or from an authorized tailnet client:

```bash
H=<node>.ts.net
curl -s -o /dev/null -w '/ %{http_code}\n' --resolve $H:8443:100.113.204.81 https://$H:8443/
curl -s --resolve $H:8443:100.113.204.81 https://$H:8443/api/runtime-identity        # dashboard identity
curl -s -o /dev/null -w '/api/v1 %{http_code}\n' --resolve $H:8443:100.113.204.81 https://$H:8443/api/v1/telemetry/latest
# expect 400/401 from the Telemetry API (it needs a session and parameters), never 502
```

Then, in a browser on an approved tailnet workstation:

1. open `https://<node>.ts.net:8443/inspection-login`;
2. expect the read-only viewer session;
3. check that Live Data updates over `wss://<node>.ts.net:8443/api/v1/telemetry/live`;
4. log out.

### Rollback

Restore the saved configuration exactly:

```bash
sudo tailscale serve set-config --all "$B"
tailscale serve status
```

Alternatively, reset only the two handlers to their previous targets:

```bash
sudo tailscale serve --bg --yes --https=8443 --set-path=/    http://127.0.0.1:3102
sudo tailscale serve --bg --yes --https=8443 --set-path=/api http://172.18.48.66:8082/api
```

## Not changed

- Funnel `:443` (`127.0.0.1:18790`, Google OAuth gateway);
- `:8444` (LAN dashboard);
- `:8445` (Grafana);
- the `100.113.204.81:80` `lab.nexolab` listener;
- the inspection login helper and its identity policy.
