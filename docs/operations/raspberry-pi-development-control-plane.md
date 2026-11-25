# Raspberry Pi development control plane (PC-independent workflow)

Issue: #1706. Host: `nexolab-edge-01` (Raspberry Pi 5, ARM64, 4 GiB RAM).

This runbook describes how NEXOLAB source development runs directly on the Raspberry Pi under an isolated, non-privileged account, so that a Windows PC is no longer required. It is a **development** workflow only. It does not install, deploy or activate anything on the production stack.

## Boundary

Production monitoring has absolute priority over development.

- The production stack (Device Agent, telemetry service, PostgreSQL, MQTT, dashboard, gateways) keeps running under its own accounts and does not depend on the development account, Claude Code, GitHub or the internet.
- The development account cannot read production configuration or secrets, cannot use Docker, serial or GPIO devices, and cannot gain privileges. These boundaries are enforced by the OS, not by agent instructions.
- Heavy builds, browser suites, Docker integration tests and ARM64 artifact generation run in GitHub Actions, never locally.
- Release, site activation, production database migration, backup gates and any hardware or Modbus operation stay owner-only, exactly as before (#1428, #1699, #1606 and the release runbooks are unchanged).

## Account and isolation

| Property        | Value                                                                                                                         |
| --------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| Account         | `nexolab-dev` (uid 1001), groups `nexolab-dev`, `users` only                                                                  |
| Home            | `/home/nexolab-dev`, mode `0700`, `UMask=0077`                                                                                |
| Workspace       | `/home/nexolab-dev/nexolab-platform`, a fresh clone of `eNgine9r/nexolab-platform` tracking `main`                            |
| Excluded groups | `sudo`, `docker`, `dialout`, `gpio` and any other hardware group                                                              |
| Privilege       | `NoNewPrivileges=yes` (sudo is refused)                                                                                       |
| Filesystem      | `ProtectSystem=strict`, writable only `/home/nexolab-dev`, `PrivateTmp=yes`, `PrivateDevices=yes`                             |
| Hidden paths    | `/home/nexolab`, `/etc/nexolab`, `/var/lib/nexolab`, `/var/lib/docker`, `/run/docker.sock`, `/run/containerd/containerd.sock` |

The existing production deployment checkout and the older Commander checkout belong to the operator account and are neither reused nor reset.

### Resource limits

Limits are set on `user-1001.slice` (persistent drop-ins created with `systemctl set-property`):

| Limit           | Value    | Effect                                                        |
| --------------- | -------- | ------------------------------------------------------------- |
| `MemoryHigh`    | 768 MiB  | reclaim/throttle above this                                   |
| `MemoryMax`     | 1280 MiB | hard cap; the kernel kills inside the slice, never production |
| `MemorySwapMax` | 512 MiB  | bounded swap use                                              |
| `CPUQuota`      | 100 %    | at most one of four cores                                     |
| `TasksMax`      | 128      | bounded process count; avoid parallel local test fan-out      |

Disk: the host must keep **at least 20 GiB free** on `/`. Development stops before that reserve is consumed.

## Session model

The development session is one persistent tmux server started by the owner as a transient systemd unit, so every process inside it inherits the sandbox and the slice limits:

```bash
# Owner (operator account with sudo). Starts the sandboxed session.
sudo systemd-run --unit=nexolab-dev-session --slice=user-1001.slice \
  --uid=nexolab-dev --gid=nexolab-dev \
  --working-directory=/home/nexolab-dev/nexolab-platform \
  --setenv=HOME=/home/nexolab-dev \
  -p Type=oneshot -p RemainAfterExit=yes \
  -p NoNewPrivileges=yes -p PrivateDevices=yes -p PrivateTmp=yes \
  -p ProtectSystem=strict -p ReadWritePaths=/home/nexolab-dev -p UMask=0077 \
  -p InaccessiblePaths="-/home/nexolab -/etc/nexolab -/var/lib/nexolab -/var/lib/docker -/run/docker.sock -/run/containerd/containerd.sock" \
  /usr/bin/tmux -S /home/nexolab-dev/nexolab.sock new-session -d -s nexolab /bin/bash
```

This transient unit survives client disconnect and the PC being switched off, but **not a host reboot** (confirmed by the unexpected reboot on 2026-11-23). It remains the manual fallback.

### Persistent session after reboot (#1710)

`docs/operations/dev-session/` holds an owner-installed persistent version with the **same sandbox** plus service-level copies of the slice limits (`MemoryHigh=768M`, `MemoryMax=1280M`, `MemorySwapMax=512M`, `CPUQuota=100%`, `CPUWeight=20`, `IOWeight=20`, `TasksMax=128`):

| File                           | Installed as                               | Role                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| ------------------------------ | ------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `nexolab-dev-session.service`  | `/etc/systemd/system/`                     | sandboxed tmux server for `nexolab-dev`; not enabled directly                                                                                                                                                                                                                                                                                                                                                                                                                   |
| `nexolab-dev-session.timer`    | `/etc/systemd/system/`                     | starts the service 5 minutes after boot, so production starts first                                                                                                                                                                                                                                                                                                                                                                                                             |
| `nexolab-dev-session-start.sh` | `/usr/local/lib/nexolab-dev/` (root-owned) | first tmux window: waits up to 15 minutes for telemetry readiness on internal endpoints (`127.0.0.1:8082`, then the #1733 compatibility address; never a DHCP address), then keeps re-checking every 60 s for up to 12 hours and resumes once ready (the guard is never bypassed), checks free disk (≥ 20 GiB) and host `MemAvailable` (≥ 900 MiB), writes `~/.local/state/nexolab-dev/last-recovery-snapshot.txt`, optionally resumes Claude, then leaves an interactive shell |

Automatic Claude resume is **opt-in**: only when `~/.config/nexolab-dev/auto-resume` exists and all gates pass does the script run `claude --continue --permission-mode auto` with a recovery prompt (recover from repository state, checkpoints, branches, PRs and Issues; no production change; no reboot). If Claude exits, the session falls back to a shell; there is no restart loop. If a gate fails, Claude is not started and the reason is logged in `~/.local/state/nexolab-dev/session-start.log`.

Install (owner, operator account with sudo; run from a checkout of `main`):

```bash
sudo install -d -o root -g root -m 0755 /usr/local/lib/nexolab-dev
sudo install -o root -g root -m 0755 docs/operations/dev-session/nexolab-dev-session-start.sh /usr/local/lib/nexolab-dev/
sudo install -o root -g root -m 0644 docs/operations/dev-session/nexolab-dev-session.service docs/operations/dev-session/nexolab-dev-session.timer /etc/systemd/system/
sudo systemd-analyze verify /etc/systemd/system/nexolab-dev-session.service /etc/systemd/system/nexolab-dev-session.timer
sudo systemctl daemon-reload
sudo systemctl enable nexolab-dev-session.timer
# Optional: allow automatic Claude resume after reboot.
sudo -u nexolab-dev install -d -m 0700 /home/nexolab-dev/.config/nexolab-dev
sudo -u nexolab-dev touch /home/nexolab-dev/.config/nexolab-dev/auto-resume
```

While a transient session is running, a unit with the same name cannot be loaded. Switch over at a convenient moment (this ends the current tmux session; commit or push work first):

```bash
sudo systemctl stop nexolab-dev-session.service   # transient unit
sudo systemctl daemon-reload
sudo systemctl start nexolab-dev-session.service  # persistent unit, same sandbox
```

Verify after the switch and after the next reboot: `systemctl status nexolab-dev-session.service nexolab-dev-session.timer`, `cat /proc/<claude pid>/cgroup` shows `user-1001.slice/nexolab-dev-session.service`, and `~/.local/state/nexolab-dev/session-start.log` shows the gate result. Do **not** reboot only to test this; use the next planned or unplanned restart.

Disable or roll back: `sudo systemctl disable --now nexolab-dev-session.timer`; remove the opt-in flag to stop automatic resume; delete the two unit files and `/usr/local/lib/nexolab-dev/`, then `sudo systemctl daemon-reload`. Production is not affected.

> Always work inside this tmux server. A shell opened with plain `sudo -u nexolab-dev` runs in the operator's cgroup, outside the sandbox and the slice limits. Never start Claude Code from such a shell.

## Operator procedures

### Connect

1. SSH to the Pi over the existing private path (LAN or Tailscale). No new public port is opened.
2. Attach to the session:

   ```bash
   sudo -u nexolab-dev tmux -S /home/nexolab-dev/nexolab.sock attach -t nexolab
   ```

3. Alternatively, use the official Claude Code Remote Control / claude.ai/code connection started from inside the tmux session. It uses the Claude service, not an inbound port.

### Disconnect

Detach with `Ctrl-b d`, or simply close the SSH client or browser. The session and any running agent continue. The PC can be switched off.

### Stop development

```bash
sudo systemctl stop nexolab-dev-session.service
```

This terminates the tmux server and every process in it. It does not touch production services. Uncommitted work stays in the workspace on disk; the repository checkpoint (`.project/LAST_CHECKPOINT.json`) and GitHub hold the recoverable state.

### Recover after disconnect, crash or reboot

1. Check whether the session exists: `systemctl status nexolab-dev-session.service`.
2. If absent after a reboot and the persistent timer is installed, wait for it (5 minutes after boot) and read `~/.local/state/nexolab-dev/session-start.log`. Otherwise run the resource gate below and start the session with `sudo systemctl start nexolab-dev-session.service` (persistent) or the `systemd-run` command above (transient fallback).
3. In the workspace: `git status`, `git fetch`, then read `.project/CURRENT_STATE.md`, `.project/LAST_CHECKPOINT.json` and open PRs before continuing. Do not infer state from chat history.

Execution is never uninterrupted across provider usage limits or host restarts; work resumes from the repository checkpoint.

## Resource and safety gates

Run before starting or resuming development, and stop development if any gate fails:

```bash
df -BG /                                                     # Avail must stay >= 20G
cat /sys/fs/cgroup/user.slice/user-1001.slice/memory.current # compare with memory.high (768 MiB)
free -m                                                      # host-wide available memory and swap
```

Read-only production health (GET only, no credentials):

```bash
curl -s http://127.0.0.1:8081/health          # Device Agent: status ok, mqtt_connected true, queue_size 0
curl -s http://127.0.0.1:8082/health/ready || curl -s http://172.18.48.66:8082/health/ready # telemetry (loopback after #1734; compatibility alias until then): database/mqtt ready, low ingestion_lag_seconds
```

Stop development immediately, and record the reason in `.project/BLOCKERS.md`, when:

- free disk on `/` approaches 20 GiB;
- host available memory is low enough to push production into swap;
- Device Agent or telemetry readiness degrades while development is running;
- any task would require production secrets, Docker, serial devices, privileges or a site action.

## Autonomous engineering model (Product Owner, 2026-11-25)

The development agent works continuously: it picks the next independent Ready Work Package, fixes ordinary implementation and CI failures itself, and keeps working while CI runs or owner approval is pending. Pending owner actions are recorded in `.project/BLOCKERS.md` and `.project/LAST_CHECKPOINT.json`, so the next session can resume them after an unexpected reboot.

Privileged reach is limited to the [Operator Broker](operator-broker/README.md) (#1758). Through it the agent can use fixed, audited diagnostics: systemd, journal, Docker metadata, network and Wi-Fi, power, storage. It can also recover two already-installed NEXOLAB units, and only when they are down. It never gets sudo, a shell, the Docker socket or the ability to change privileged code.

The owner is asked only for:

- a physical action;
- authentication;
- a destructive or backup-sensitive operation;
- an unresolved architectural decision;
- the exact approval of a production change: cutover, release activation, network or credential change, reboot.

Each such request comes fully prepared: preflight, checksum-pinned command, automatic rollback, and one approval line.

## What runs where

| Work                                                                                                                      | Location                           |
| ------------------------------------------------------------------------------------------------------------------------- | ---------------------------------- |
| git, `gh`, issue/PR/CI management                                                                                         | Pi, development account            |
| Project-state validation (`scripts/validate-project-state.py`), small Python checks                                       | Pi, development account            |
| Prettier check of changed files (user-local Node 22.23.1 in `~/.local/node`, Prettier 3.9.9 in `~/.local/tools/prettier`) | Pi, development account            |
| Next.js builds, `npm ci`, frontend unit and browser tests                                                                 | GitHub Actions                     |
| Docker image builds, Compose and integration tests, supply-chain scans                                                    | GitHub Actions                     |
| ARM64 offline bundles and release artifacts                                                                               | GitHub Actions                     |
| Release, site activation, production migration, backup and restore evidence                                               | Owner only, separate authorization |

Every change goes through a feature branch and a Pull Request; direct pushes to `main` are forbidden. A PR may merge only with an exact-head GREEN NEXOLAB Merge Gate and passing project-state integrity, under the authorization recorded in `AGENTS.md`.

## Credentials

- Claude Code (native ARM64 binary in `~/.local/bin/claude`) and the GitHub CLI are authenticated by the owner directly in the development account. No credential was copied from the operator account.
- Tokens are never printed into chat, logs, issues, PRs or evidence. Verify access with `gh auth status`, which masks the token.
- Git commits use the GitHub noreply identity configured in the workspace (`git config user.email`).

## Handoff and rollback

The previous Windows PC workflow remains a valid fallback; nothing in it was removed.

To roll back the Pi control plane (owner):

1. `sudo systemctl stop nexolab-dev-session.service`.
2. Revoke the development account's GitHub OAuth authorization and Claude login from the respective account settings.
3. Optionally remove the slice drop-ins (`/etc/systemd/system.control/user-1001.slice.d/`) and the account. Deleting the account home is an owner decision; push or archive any unmerged branches first.

Production is not affected by any of these steps.

## Verification record (2026-11-23, read-only)

Run from inside the sandboxed session on `main` `c20e6555`:

| Check                           | Result                                                                                                    |
| ------------------------------- | --------------------------------------------------------------------------------------------------------- |
| Account and groups              | `nexolab-dev` uid 1001; groups `nexolab-dev`, `users`                                                     |
| sudo                            | refused (`no new privileges`)                                                                             |
| Docker socket                   | not accessible                                                                                            |
| `/home/nexolab`, `/etc/nexolab` | not readable (contents not read)                                                                          |
| Serial devices                  | none visible (`/dev/serial/by-id` absent)                                                                 |
| Slice limits                    | `memory.high` 768 MiB, `memory.max` 1280 MiB, `memory.swap.max` 512 MiB, `cpu.max` 1 core, `pids.max` 128 |
| Disk                            | 24 GiB available on `/` (reserve 20 GiB)                                                                  |
| Claude Code                     | 2.1.323, native ELF aarch64                                                                               |
| GitHub                          | `gh` authenticated as the repository owner; token masked                                                  |
| Workspace                       | clean, tracking `origin/main`                                                                             |
| Device Agent `/health`          | `ok`, `mqtt_connected: true`, queue 0, `device_mode: modbus`                                              |
| Telemetry `/health/ready`       | `ready`; database and MQTT ready; ingestion lag about 0.18 s                                              |

Not verified by the agent and left to the owner:

- session continuity with the PC switched off (requires the owner to switch it off and reconnect);
- reboot recovery (requires a separately approved reboot test);
- before/after comparison of production container identities (the development account has no Docker access by design, so only health endpoints were compared).

### Local format check

The repository Prettier config loads `prettier-plugin-tailwindcss`, which is not installed in the tools prefix. It only sorts Tailwind classes, so for Markdown, JSON and YAML use a copy of the config without `plugins`:

```bash
export PATH="$HOME/.local/node/bin:$PATH"
python3 -c "import json;c=json.load(open('.prettierrc.json'));c.pop('plugins');json.dump(c,open('/tmp/prettierrc.json','w'))"
~/.local/tools/prettier/node_modules/.bin/prettier --config /tmp/prettierrc.json --check <changed files>
```

TypeScript and TSX formatting is left to CI.
