# NEXOLAB Operator Broker (#1758)

A root-owned local service that gives the isolated development account (uid 1001, `nexolab-dev`) a fixed set of audited operations, so routine diagnostics and permitted recovery no longer need a manual owner command. It extends the control plane in [`raspberry-pi-development-control-plane.md`](../raspberry-pi-development-control-plane.md) (#1706) without loosening its sandbox.

**Source merge is not installation.** The owner installs it once with the checksum-pinned procedure below.

## Trust model

| Property            | Implementation                                                                                                                                                                                                                                          |
| ------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Caller identity     | Unix socket `/run/nexolab-operator/broker.sock` (root:nexolab-dev 0660) plus kernel peer credentials (`SO_PEERCRED`) against `NEXOLAB_OPERATOR_ALLOWED_UIDS=1001`. Root is never a client                                                               |
| Operations          | Fixed IDs with typed schemas (enum, bounded integer, anchored name). Unknown fields, extra or mistyped arguments are rejected. Container names must also exist in `docker ps -a`                                                                        |
| Execution           | Fixed argv lists, no shell, clean environment, per-op timeout with process-group kill, 256 KiB output cap, at most 4 concurrent requests, one heavy diagnostic at a time                                                                                |
| Output              | Every string is redacted (private keys, JWTs, Tailscale/GitHub/GitLab tokens, URL credentials, bearer values, `password/psk/secret/token/...=value`). Wi-Fi profiles are read without secrets. Docker metadata uses fixed templates, never `Env`        |
| Replay              | Lowercase UUID4 `request_id`, single use (persisted through the audit log across restarts) and a ±120 s timestamp window                                                                                                                                |
| Audit               | Every request, accepted or rejected, is appended to `/var/log/nexolab-operator/audit.jsonl` as a SHA-256 hash chain (peer uid/pid, op, validated args, status, duration, output digest). The response carries the receipt `{seq, hash}`                 |
| Immutable code      | The broker refuses to start, and refuses every state-changing op, unless its own file, `/usr/local/lib/nexolab-operator/**` and the approvals directory are root-owned, not group/world-writable and not symlinked                                      |
| State changes       | `recover` ops: one at a time (in-process lock plus `flock`), only on a unit that is already down, never enable/disable. `approved` ops: a single-use, root-only, mode-0600 owner approval for the exact op and arguments with an expiry, consumed first |
| Sandbox             | `NoNewPrivileges`, `ProtectSystem=strict`, `ProtectHome=read-only`, the GitLab token directory inaccessible, `DevicePolicy=closed` (VideoCore mailbox only), capabilities `CAP_DAC_READ_SEARCH CAP_CHOWN CAP_FOWNER`, 256 MiB, 64 tasks, 50 % CPU       |
| Not possible at all | Generic exec, scripts or paths from the caller, Docker API proxy or `docker exec`, `prune`, volume operations, reboot, credential or network changes, Modbus, secret output, self-approval                                                              |

The development account cannot write the code, the units, the approvals or the audit log. It cannot run `approve`, which exits 77 unless it runs as root.

## Operations (v1.1.0)

| Op                                                      | Kind    | What it returns                                                                                                                                                            |
| ------------------------------------------------------- | ------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `broker.list`                                           | read    | Ops, kinds and argument schemas                                                                                                                                            |
| `system.summary`, `system.power`, `system.boots`        | read    | Uptime, memory, disk, temperature, throttling and undervoltage flags, failed units, time, boot list                                                                        |
| `logs.unit`, `logs.kernel`, `logs.system`               | read    | Journal of an allow-listed unit, or kernel/system lines of a fixed category (power, wifi, crash…)                                                                          |
| `service.status`, `service.list`                        | read    | State of allow-listed units and NEXOLAB timers                                                                                                                             |
| `docker.containers`, `docker.container`, `docker.logs`  | read    | NEXOLAB containers only (`nexolab-*`, Compose project `nexolab*` or none): identity, health, networks, ports, mounts; redacted logs                                        |
| `docker.networks`, `docker.images`, `docker.disk`       | read    | Networks and attachments, images with digests and in-use mapping, `docker system df`                                                                                       |
| `network.summary`, `wifi.diagnose`                      | read    | Addresses, routes, DNS, NM devices, listeners, DHCP; Wi-Fi profiles without secrets, scan, reasons                                                                         |
| `storage.summary`, `storage.inventory`                  | read    | Filesystems and journal usage; the pinned #1710 inventory as a sanitized excerpt (allow-listed sections, foreign workspaces masked). The raw report stays root-only (0600) |
| `service.recover unit=nexolab-lan-gateway.service`      | recover | Restart only if enabled and `failed`/`inactive`                                                                                                                            |
| `service.recover unit=nexolab-network-endpoint-repair…` | recover | Run the same idempotent #1748 repair its timer runs                                                                                                                        |

v1.1 adds:

| Op                             | Kind     | What it does                                                                                                                                                                                                      |
| ------------------------------ | -------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `system.reset-reason`          | read     | SoC reset status (`vcgencmd get_rsts`), PMIC and supply data from the firmware device tree, watchdog settings, boot list                                                                                          |
| `logs.boot-end`                | read     | Last lines of a previous boot. A clean shutdown sequence means a reboot was requested; an abrupt stop means power loss or a hang ended by the watchdog                                                            |
| `docker.service-model`         | read     | WP2c Phase 0: the effective NEXOLAB container and network model (images, ports, networks and aliases, mounts, restart policy, labels). Environment keys are listed, values only for non-secret configuration keys |
| `storage.cleanup-regenerable`  | approved | Build cache older than 7 days, untagged images used by no container (checked per image, never `-f`), journal vacuumed to 200 MB. Fails if the set of volumes changes                                              |
| `service.retire-legacy-https`  | approved | Stops, disables and masks the prepared-only legacy HTTPS pair that restart-loops. Verifies the live `:3105` UI identity is unchanged                                                                              |
| `service.restore-legacy-https` | approved | Exact undo of the above                                                                                                                                                                                           |

Log operations now keep the newest output when it exceeds the cap. Redaction never crosses a line.

### v1.2 (#1775)

| Op                            | Kind     | What it does                                                                                                                                                                                                                                                                                                                  |
| ----------------------------- | -------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `deploy.lan-frontend`         | approved | WP2c Stage 2 (#1734). `phase=prepare` (stage, offline build, preview on `127.0.0.1:3125`, check: production unchanged), `phase=execute` (switch with automatic verified rollback) or `phase=rollback`. Runs the **pinned** Stage 2 tool as the owner account `nexolab` (docker group, never root) in a bounded transient unit |
| `backup.health`               | read     | DR backup units and timer, presence (never contents) of `/etc/nexolab/dr-backup.json`, bundle names, sizes and modes, free space against the 20 GiB reserve                                                                                                                                                                   |
| `backup.start`                | approved | Starts the owner-installed `nexolab-dr-backup.service` once, like its timer. Refuses when the unit or its config is not installed, a run is active, or less than 28 GiB is free. Installing the unit and its keys stays an owner step (#1630)                                                                                 |
| `storage.cleanup-regenerable` | approved | New argument `build_cache=older-than-7d` (default) or `all-unused`. The approval binds it, so removing all unused build cache needs that exact approval                                                                                                                                                                       |

`service.retire-legacy-https` no longer tries `mask` on a unit whose file is a real file in `/etc/systemd/system` (the v1.1 site run returned exit 1 there). It reports what still pulls the unit in instead. On the site that is only the disabled legacy nginx unit.

**How `deploy.lan-frontend` binds what is deployed.**

- The approval fixes the phase, the artifact SHA-256 and the expected identity (`expect_current_source`, `expect_current_build`) of the dashboard being replaced.
- The agent places the artifact in `~nexolab-dev/operator-inbox/<sha256>.zip`. The broker opens it without following links and hashes it while copying into `/var/lib/nexolab-operator-deploy` (root:nexolab 0750; file 0640). Only that verified copy reaches the tool.
- Different bytes give `approval_mismatch`, and the tool is not run.
- A workspace already staged from another artifact is refused for `prepare` and `execute`. `execute` needs a prepared workspace.

### v1.3 (#1778)

| Op                      | Kind     | What it does                                                                                                                                                                                                                                                                                                                                                                                                                           |
| ----------------------- | -------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `storage.remove-images` | approved | Removes the exact images listed in `~nexolab-dev/operator-inbox/<manifest_sha256>.json` (`{"images": [{"ref", "id"}]}`, ≤ 60). The manifest bytes must match the approved hash. Per image: NEXOLAB refs only, `protected`/`recovery`/`rollback`/`baseline`/`-base:` names refused, tag must still resolve to the listed id, no container (even stopped) may use it. `docker image rm` without `-f`; the volume set must stay identical |
| `wifi.connect-test`     | approved | One bounded `nmcli connection up` of a Wi-Fi profile (`mac=permanent` or `random`). The MAC setting is changed in memory only (`--temporary`) and restored. A random-MAC test is always brought down afterwards. Refuses unless Ethernet holds the default route and `wlan0` is not connected; reports whether Ethernet still holds it                                                                                                 |
| `wifi.profile-remove`   | approved | Removes exactly one inactive Wi-Fi profile by name. Ethernet profiles and the active connection are refused. Irreversible (the owner re-creates the profile if needed)                                                                                                                                                                                                                                                                 |

Further handlers (Stage 3 backend recreation) come as separate reviewed releases, applied by the owner with `upgrade`, with an approval per run.

## Use (development account)

```bash
python3 docs/operations/operator-broker/nexolab-operator.py broker.list
python3 docs/operations/operator-broker/nexolab-operator.py system.power
python3 docs/operations/operator-broker/nexolab-operator.py logs.unit unit=nexolab-lan-gateway.service lines=50
python3 docs/operations/operator-broker/nexolab-operator.py logs.kernel filter=power boot=-1
python3 docs/operations/operator-broker/nexolab-operator.py docker.container name=<container>
```

Exit 0 means ok, 2 rejected and 3 unreachable (not installed or stopped). `--json` prints the raw response with the receipt.

## Owner installation (once)

The owner gets one command with the SHA-256 of `install-operator-broker.sh`. That script pins the broker, both units and the inventory handler. It copies them into a root-only staging directory, verifies them there, then installs:

- `/usr/local/lib/nexolab-operator/` (root, 0755);
- `/etc/systemd/system/nexolab-operator-broker.{socket,service}`;
- `/etc/nexolab-operator/approvals` (root, 0700);
- `/var/log/nexolab-operator` (root:nexolab-dev, 2750: audit receipts readable by the dev group);
- `/var/lib/nexolab-operator/reports` (root, 0700: raw inventory reports never reach the dev account).

It enables only the socket and then proves:

- the owner account, which is not in the socket group, is refused by the kernel at the socket file (`EACCES`);
- root is refused by the broker (`unauthorized_peer`);
- the development account, called inside a transient unit with the dev-session sandbox (`NoNewPrivileges`, `ProtectSystem=strict`, `PrivateDevices`, no Docker socket), can list operations and read `system.summary`;
- the audit chain verifies, and the socket, file modes and service sandbox match the final state.

Any failure removes everything it installed and verifies the removal (`ROLLBACK_VERIFIED`, otherwise `HARD_BLOCKER_ROLLBACK_INCOMPLETE`). The staging directory is always deleted.

CI (`operator-broker-install-acceptance.yml`) performs the real installation on a disposable runner with systemd, with an owner account outside the socket group. It also covers a tampered payload, a failure during installation, a foreign container that must stay invisible, a NEXOLAB container logging a secret, and uninstall. Production services, containers, networks and credentials are not touched.

```bash
bash install-operator-broker.sh upgrade <payload-dir>   # verify new pins, snapshot, replace; failure restores the previous version
bash install-operator-broker.sh rollback                # back to the version retained by the last upgrade (run again to roll forward)
bash install-operator-broker.sh status
bash install-operator-broker.sh uninstall   # keeps audit log and reports as evidence
```

**Upgrade with automatic rollback (v1.2).**

1. `upgrade` verifies the new pins first. A bad payload changes nothing.
2. It copies the installed code and units into `/var/lib/nexolab-operator/previous.pending` (root, 0700) with a SHA-256 manifest.
3. It installs the new version and runs the full acceptance on the real socket.
4. If any step fails, including a payload changed after the check, it verifies the snapshot manifest, reinstalls the previous version, runs the same acceptance and prints `OPERATOR_BROKER_UPGRADE_ROLLED_BACK version=<previous>` (exit 3).
5. Only if the previous version also fails does it fall back to verified removal (`ROLLBACK_VERIFIED` or `HARD_BLOCKER_ROLLBACK_INCOMPLETE`).
6. After a successful upgrade, `previous/` holds the replaced version for `rollback`.

CI installs the merged v1.1 from history and injects a failure after the v1.2 install (the test-only `NEXOLAB_OPERATOR_TEST_FAULT=after-install`, which can only cause a rollback). It proves the byte-identical v1.1 is back and accepted, then upgrades, rolls back and rolls forward.

Owner approval of a gated operation, when such an operation exists:

```bash
sudo python3 -I /usr/local/lib/nexolab-operator/nexolab-operator-broker.py approve --op <op> --arg key=value --ttl-minutes 30 --reason "<why>"
```

The printed `approval_id` is given to the agent, which passes it with `--approval`. It is valid once, for exactly those arguments.

## Verification

`tests/test_ci_operator_broker.py` runs the broker on a real Unix socket with real peer credentials. In its test mode (refused as root) it checks:

- an unauthorized peer, unknown and shell-like ops, extra, missing and mistyped arguments, injection and traversal values;
- replay and stale timestamps, oversized requests and redaction;
- timeout, output cap and concurrent mutation;
- approvals: missing, mismatched, expired, mode 0644 and 0622, symlinked, and the single-use path;
- tampering with the audit chain;
- refusal to start with a writable broker, install directory or handler, or a symlinked handler;
- the root-only `approve`, the unit hardening, `systemd-analyze verify`, and that the installer pins match the files.
