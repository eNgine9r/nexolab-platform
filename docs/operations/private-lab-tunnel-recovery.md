# Private NEXOLAB access after Tailscale restart

Issue [#1567](https://github.com/eNgine9r/nexolab-platform/issues/1567) covers the private `http://lab.nexolab` browser path. On the Raspberry Pi, Tailscale provides the private address, `nexolab-lab-dns.service` resolves the domain, and `nexolab-lab-http.service` forwards it to the installed frontend on `127.0.0.1:3104`. The LAN dashboard and local telemetry have their own endpoints.

`Requires=tailscaled.service` and `After=tailscaled.service` already order startup and propagate explicit daemon stops and restarts. Starting Tailscale by itself previously left both services inactive. A `Wants` drop-in on the daemon pulls them in whenever it starts. The existing restart policy covers the interval between daemon start and availability of the address that the HTTP bridge binds.

The private inspection HTTPS address on port `8443` is a separate path. On 2026-11-16 it returned HTTP 502 from two tailnet hosts because its root handler pointed to unused staging port `3102`. Its credential exchange has a dedicated socket and identity policy. Review the compatible frontend and policy separately before changing that Serve handler. The public Funnel gateway serves the existing OAuth redirect. Its active user unit and the inactive historical Nginx unit both use port `18790`, so starting the historical unit risks a port conflict.

## Verification before activation

Run the fixture as an ordinary user with a systemd user session. It creates temporary units, compares the original stop/start behavior against the proposed configuration, and tests a delayed address and an explicit restart.

```bash
bash scripts/verify-raspberry-pi-private-lab-tailscale-lifecycle.sh
```

## Install from the Raspberry Pi console

Use the reviewed revision of this repository and an owner-approved site window. From the repository root, verify that both lab services are enabled and active and that the current tailnet client can resolve `lab.nexolab` and load `/login`. Use an independent console before testing loss of the live tunnel.

```bash
systemctl is-enabled nexolab-lab-dns.service
systemctl is-enabled nexolab-lab-http.service
systemctl is-active tailscaled.service
systemctl is-active nexolab-lab-dns.service
systemctl is-active nexolab-lab-http.service

sudo bash -euo pipefail -s <<'SH'
source=infrastructure/systemd/nexolab-lab-tailscale-lifecycle.conf
units=(nexolab-lab-dns.service nexolab-lab-http.service)
path=/etc/systemd/system/tailscaled.service.d/40-nexolab-lab.conf
for unit in "${units[@]}"; do
    systemctl is-active --quiet "$unit"
    systemctl show --property=Requires --value "$unit" | tr ' ' '\n' | grep -Fx tailscaled.service >/dev/null
done
systemctl is-active --quiet tailscaled.service
if [[ -e "$path" || -L "$path" ]]; then
    test -f "$path" && test ! -L "$path" && cmp -s -- "$source" "$path" || exit 1
else
    install -D -m 0644 -- "$source" "$path"
fi
systemctl daemon-reload
systemctl show tailscaled.service -p Wants
systemctl show "${units[@]}" -p Id -p ActiveState
SH
```

Confirm the displayed `Wants` contains both lab services. The install reloads systemd's configuration and leaves the running service processes in place. From the authorized client, verify DNS and `/login` again. After separate approval for a restart or network interruption, verify the URL and authenticated session after network return. Record elapsed recovery and verify LAN Dashboard and telemetry readiness during the exercise.

## Rollback

If this change introduced `/etc/systemd/system/tailscaled.service.d/40-nexolab-lab.conf`, remove that file and run `sudo systemctl daemon-reload`. The existing `multi-user.target` registrations handle normal boot.
