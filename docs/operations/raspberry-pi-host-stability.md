# Raspberry Pi host stability

Issue: #1037

Target: `nexolab-edge-01`

Profile: `LOCAL_LAN`

## Product outcome

Keep the 4 GiB Raspberry Pi responsive for monitoring and remote administration while development verification is running. Production acquisition, PostgreSQL, MQTT and the dashboard remain the priority; optional inspection tooling must not permanently consume the host's limited RAM/CPU/I/O budget.

## 2026-09-15 retained incident evidence

The repeated disconnects were host-wide stalls, not an isolated Remote Desktop Commander failure. During a heavy local Telemetry Service pytest/PostgreSQL run, the same retained boot journal recorded Docker health-check timeouts, containerd event deadlines, Tailscale DNS/control timeouts, Raspberry Pi Connect API timeouts, NetworkManager dispatcher timeouts and Desktop Commander heartbeat/connect timeouts.

The host did **not** show an OOM kill, thermal throttling or NIC hardware errors. `vcgencmd get_throttled=0x0`, temperature was about 49 C, SSD free space was ample, and `eth0` remained 1 Gbps full-duplex with zero error counters.

The avoidable load was significant: `nexolab-browser.service` and `nexolab-opera-inspection.service` were both enabled permanently, while a second legacy `tmux`/`npx @wonderwhy-er/desktop-commander@latest remote` stack duplicated the repository-managed Remote Desktop Commander. Together with full local pytest/PostgreSQL verification this exhausted practical host headroom and starved network/container control paths.
## Memory and swap policy

Raspberry Pi OS is intentionally using `rpi-swap` in `zram+file` mode. `/dev/zram0` is the active 2 GiB swap device; `/var/swap` is attached through `/dev/loop0` as zram backing/writeback storage. It is **not** a missing second swap device and must not be activated independently with `swapon /var/swap`.

The kernel command line currently contains `cgroup_disable=memory`, so Docker/systemd memory-controller limits are not available on this boot configuration. #1037 therefore stabilizes the host by removing unnecessary always-on development processes and by preventing heavyweight verification from competing with production, rather than pretending that per-container memory caps are enforced.

Before cleanup, the host showed roughly 2.5 GiB RAM used, ~1.4 GiB available and ~734 MiB swap used. After the two optional inspection services were disabled/stopped and the legacy duplicate Desktop Commander tmux stack was removed, the host showed roughly 1.7 GiB RAM used, ~2.2 GiB available and ~188 MiB swap used while all 12 NEXOLAB production containers remained healthy.

## Operational policy

`nexolab-browser.service` and `nexolab-opera-inspection.service` are on-demand tools. Keep them disabled when no UI inspection is actively running. Start only the one required for the current task, then stop it after acceptance evidence is captured.

Only `nexolab-remote-desktop-commander.service` owns the managed Desktop Commander identity. Do not run `npx @wonderwhy-er/desktop-commander@latest remote`, do not recreate the legacy `remote-desktop` tmux session, and do not run a second remote process alongside the managed service.

Full repository, full Telemetry Service PostgreSQL, browser-matrix and other heavyweight CI-equivalent suites must run in GitHub Actions. On the production 4 GiB edge host use targeted tests, touched-file checks and bounded runtime probes only.

Use the repository guard before and after development work:

```bash
./scripts/stabilize-raspberry-pi-development-host.sh --check
./scripts/stabilize-raspberry-pi-development-host.sh --apply
```
`--apply` performs only reversible user-level maintenance: it disables/stops the two optional inspection services, removes the legacy `remote-desktop` tmux session if present, and ensures the repository-managed Remote Desktop Commander service is enabled and running. It does not touch production containers, swap, networking, Modbus, hardware or persistent product data.

The verifier fails closed when host headroom is below its default thresholds (1 GiB `MemAvailable`, 512 MiB `SwapFree`, 10% root free), when `eth0` is down/erroring, when Tailscale or the managed remote service is unavailable, when optional inspection services are persistently active, or when an unmanaged Desktop Commander process/tmux session exists.

## Watchdog decision

The one-minute hardware watchdog remains enabled in #1037. The retained incident proves resource starvation and unclean resets, but it does not prove a defective watchdog policy by itself. The least-risk correction is to remove the known competing development load first. If an unexpected reboot recurs after this stabilization under a bounded workload, capture the persistent journal again and handle any watchdog-timeout change as a separate privileged maintenance step. No watchdog disablement is authorized by this Work Package.

The managed Remote Desktop Commander unit receives elevated relative CPU and I/O weights (`CPUWeight=200`, `IOWeight=200`) so the administration channel receives more scheduler share during contention. This does not reserve memory and does not change the production application runtime.

## Safety boundary

No reboot is required for the user-level stabilization. No Modbus/controller write, hardware write, production data deletion, Docker named-volume deletion, network-address change or site cutover belongs to #1037. The production runtime must remain healthy before and after every host-maintenance action.
