#!/usr/bin/env bash
set -euo pipefail

# Use throwaway user units to exercise systemd's actual job handling on the Pi.
: "${XDG_RUNTIME_DIR:?Run from a systemd user session}"
repo=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
unit_dir="$XDG_RUNTIME_DIR/systemd/user"
mkdir -p -- "$unit_dir"
fixture=$(mktemp -d "$XDG_RUNTIME_DIR/nexolab-lifecycle.XXXXXXXX")
prefix=${fixture##*/}
tunnel="$prefix-tunnel.service"
dns="$prefix-dns.service"
http="$prefix-http.service"
wants="$unit_dir/$tunnel.wants"
services=("$tunnel" "$dns" "$http")
bus=(systemctl --user)

cleanup() {
    "${bus[@]}" stop "${services[@]}" >/dev/null 2>&1 || true
    for unit in "${services[@]}"; do
        rm -f -- "$unit_dir/$unit" "$unit_dir/$unit.d/40-tailscale-lifecycle.conf" "$wants/$unit"
        rmdir -- "$unit_dir/$unit.d" 2>/dev/null || true
    done
    rmdir -- "$wants" 2>/dev/null || true
    rm -f -- "$fixture/address-ready"
    rmdir -- "$fixture"
    "${bus[@]}" daemon-reload
}
trap cleanup EXIT

cat >"$unit_dir/$tunnel" <<'EOF'
[Service]
Type=exec
ExecStart=/usr/bin/sleep infinity
EOF
for unit in "$dns" "$http"; do
    {
        printf '[Unit]\nRequires=%s\nAfter=%s\n' "$tunnel" "$tunnel"
        printf '[Service]\nType=exec\nExecStart=/usr/bin/sleep infinity\nRestart=on-failure\nRestartSec=1s\n'
        if [[ "$unit" == "$http" ]]; then
            printf 'ExecStartPre=/usr/bin/test -f %s/address-ready\n' "$fixture"
        fi
    } >"$unit_dir/$unit"
done

wait_active() {
    local unit=$1
    for ((attempt = 0; attempt < 80; attempt++)); do
        if "${bus[@]}" is-active --quiet "$unit"; then
            return
        fi
        sleep 0.1
    done
    "${bus[@]}" status --no-pager "$unit" >&2
    return 1
}

touch "$fixture/address-ready"
"${bus[@]}" daemon-reload
"${bus[@]}" start "$dns" "$http"
wait_active "$dns"
wait_active "$http"
"${bus[@]}" stop "$tunnel"
"${bus[@]}" start "$tunnel"
test "$("${bus[@]}" is-active "$dns" || true)" = inactive
test "$("${bus[@]}" is-active "$http" || true)" = inactive
printf 'BASELINE_STOP_START_LEAVES_DNS_AND_HTTP_INACTIVE\n'
"${bus[@]}" stop "$tunnel"

mkdir -- "$wants"
for unit in "$dns" "$http"; do
    mkdir -- "$unit_dir/$unit.d"
    sed "s/tailscaled\.service/$tunnel/g" \
        "$repo/infrastructure/systemd/nexolab-lab-tailscale-lifecycle.conf" \
        >"$unit_dir/$unit.d/40-tailscale-lifecycle.conf"
    ln -s -- "../$unit" "$wants/$unit"
done
"${bus[@]}" daemon-reload
rm -- "$fixture/address-ready"
"${bus[@]}" start "$tunnel"
wait_active "$dns"
for ((attempt = 0; attempt < 30; attempt++)); do
    [[ $("${bus[@]}" show --property=NRestarts --value "$http") -gt 0 ]] && break
    sleep 0.1
done
test "$("${bus[@]}" show --property=NRestarts --value "$http")" -gt 0
touch "$fixture/address-ready"
wait_active "$http"
printf 'FIXED_START_RECOVERS_AFTER_ADDRESS_IS_READY\n'

"${bus[@]}" stop "$tunnel"
test "$("${bus[@]}" is-active "$dns" || true)" = inactive
test "$("${bus[@]}" is-active "$http" || true)" = inactive
"${bus[@]}" start "$tunnel"
wait_active "$dns"
wait_active "$http"
printf 'FIXED_STOP_START_RESTORES_DNS_AND_HTTP\n'

dns_invocation=$("${bus[@]}" show --property=InvocationID --value "$dns")
http_invocation=$("${bus[@]}" show --property=InvocationID --value "$http")
"${bus[@]}" restart "$tunnel"
wait_active "$dns"
wait_active "$http"
test "$dns_invocation" != "$("${bus[@]}" show --property=InvocationID --value "$dns")"
test "$http_invocation" != "$("${bus[@]}" show --property=InvocationID --value "$http")"
printf 'FIXED_RESTART_RESTARTS_BOTH_DEPENDENTS\n'
