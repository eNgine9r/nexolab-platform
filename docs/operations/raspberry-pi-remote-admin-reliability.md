# Raspberry Pi remote-administration reliability

Issue: #988

Target: `nexolab-edge-01`

Profile: `LOCAL_LAN`

## Purpose

Keep the NEXOLAB host recoverably reachable when an optional remote channel restarts or the host reboots.
Remote administration is operational tooling only; PostgreSQL, MQTT, Device Agent and the dashboard must not depend on it.

The supported remote channels are independent:

- Raspberry Pi Connect: vendor-managed user service for shell/screen access;
- Remote Desktop Commander: NEXOLAB-managed user service for ChatGPT remote execution;
- Tailscale: independent network/tailnet transport used by approved NEXOLAB inspection surfaces.

A failure of one channel must not intentionally terminate another.

## 2026-09-10 incident findings

The observed outage was not only a dropped browser session. The host had booted at approximately `2026-09-10 11:05:46+03:00`, so the simultaneous loss of Raspberry Pi Connect, Remote Desktop Commander and tmux included a real host reboot.

Before this repair, `tmux` and Remote Desktop Commander had been launched from a Raspberry Pi Connect shell. Process/cgroup inspection showed those processes inside `rpi-connect.service`. Therefore restarting or removing that user-service cgroup could terminate the tmux server and Desktop Commander together. tmux alone was not a supervisor boundary.

Current hardware/runtime observations at diagnosis were non-failing: `vcgencmd get_throttled=0x0`, temperature about 49 C, SSD root `/dev/sda2`, boot `/dev/sda1`, JMicron `152d:0583` over UAS 5000M, and no current-boot UAS reset, USB disconnect, EXT4 error, OOM or thermal fault. The one-minute hardware watchdog remains enabled; no change is justified without retained failure evidence.

Raspberry Pi OS uses `rpi-swap` in `zram+file` mode. `/dev/zram0` is the active 2 GiB swap device and `/var/swap` is attached through `/dev/loop0` as the zram backing/writeback device. Do not add an independent `swapon /var/swap` action.

## Remote Desktop Commander service

Install from an exact repository checkout as the ordinary `nexolab` user:

```bash
./scripts/install-raspberry-pi-remote-admin.sh --defer-start
```

`--defer-start` stages the pinned package and enables the user unit without starting a second process that could share the persisted remote-device identity. After the legacy process is stopped, start the service with `systemctl --user start nexolab-remote-desktop-commander.service`.

The unit pins repository Node `22.23.1` and Desktop Commander `0.2.48`, uses `Restart=always`, and belongs to its own cgroup under `user@1000.service/app.slice`. It deliberately does not grant root privileges. Normal `sudo` policy remains available for separately authorized privileged operations.

Verify with:

```bash
systemctl --user is-enabled nexolab-remote-desktop-commander.service
systemctl --user is-active nexolab-remote-desktop-commander.service
systemctl --user show nexolab-remote-desktop-commander.service -p MainPID -p ControlGroup -p NRestarts
loginctl show-user nexolab -p Linger
```

## Persistent crash evidence

Raspberry Pi OS ships `/usr/lib/systemd/journald.conf.d/40-rpi-volatile-storage.conf`, which selects volatile journal storage. A hard reset therefore can erase the evidence needed to distinguish watchdog, OOM, USB/UAS, filesystem, power and kernel failures.

Install the bounded override as root:

```bash
sudo ./scripts/install-raspberry-pi-persistent-journal.sh
```

The NEXOLAB override selects persistent storage with a 256 MiB ceiling, keeps at least 2 GiB filesystem free, retains at most 14 days, and syncs at one-minute intervals. The installer restarts only `systemd-journald`, writes a marker, and requires that marker to be readable from `/var/log/journal` before reporting success.

After any unexpected reconnect or reboot, run:

```bash
./scripts/diagnose-raspberry-pi-remote-admin.sh
```

The diagnostic is read-only and includes current/previous boot signals, power/thermal/watchdog state, zram backing, service/cgroup identity, NetworkManager, Tailscale, Raspberry Pi Connect and SSD USB transport.

## Host acceptance evidence — 2026-09-10

The staged legacy handoff removed the `remote-desktop` tmux server and activated `nexolab-remote-desktop-commander.service` without running two remote processes concurrently. The service became enabled/active in its own cgroup.

A controlled Raspberry Pi Connect restart changed its PID from `1464` to `112684` while Desktop Commander remained PID `110871`, active, and `NRestarts=0`. This proves service/cgroup isolation.

A controlled `SIGKILL` of Desktop Commander changed its PID from `110871` to `115306`; systemd reported `NRestarts=1` and restored the remote channel automatically. A later unit-policy restart applied the final service template and restored the channel normally.

Persistent journald installation reported marker `nexolab-persistent-journal-20260910T091218Z` present in `/var/log/journal`; journal usage was 24 MiB after activation. NetworkManager, Tailscale, Raspberry Pi Connect, WayVNC and Desktop Commander were all active after the change.

The Product Owner explicitly authorized a controlled reboot on 2026-09-10. The pre-reboot boot ID `0f99f89c-c76c-447e-8723-ee4a8cdfff56` changed to `0bd4936d-49a5-4303-b197-24be581984da`. After reboot, `nexolab-remote-desktop-commander.service` returned automatically under linger in its own user-service cgroup with no tmux server and no legacy `npx @latest` remote process. Network startup initially caused three bounded Desktop Commander startup failures; `Restart=always` retried until the network was usable, restored the persisted session, and marked the device online without user action. Raspberry Pi Connect returned `enabled/active`, reported `Signed in: yes` and `Subscribed to events: yes`; Tailscale returned `Online=true`.

Persistent journal reboot proof passed: `journalctl --list-boots` retained the pre-reboot boot as `-1`, the marker `nexolab-persistent-journal-20260910T091218Z` remained readable there, and the previous-boot tail recorded the controlled `reboot.target`, filesystem/block sync and `Journal stopped` sequence. All 12 NEXOLAB containers returned healthy. Dashboard `/` and `/login` returned HTTP 200, Telemetry `/health/ready` returned HTTP 200 on its configured LAN binding, and Device Agent returned `status=ok`, `device_mode=modbus`, MQTT connected, queue depth `0`, `2/2` healthy bus workers and advancing samples (`293 → 327`). No Modbus/controller write was issued by this acceptance.

## Safety boundary

This reliability repair does not deploy NEXOLAB product code, change the deployed product-source authority, change Modbus polling, issue Modbus/controller writes, change SSD UAS policy, disable the watchdog, repair the rollback microSD, delete product data, or delete Docker named volumes. Heavy full-repository verification must not compete with the production 4 GiB Raspberry Pi runtime; use a detached verifier or GitHub CI instead.
