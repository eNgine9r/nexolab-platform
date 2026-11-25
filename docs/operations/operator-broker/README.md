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

## Operations (v1.0.0)

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

Approved deployment or network operations (Wi-Fi profile change, Stage 2/3 activation) are added later as separate reviewed handlers. Each one needs a new pinned broker release, installed by the owner, and an approval per run.

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
bash install-operator-broker.sh status
bash install-operator-broker.sh uninstall   # keeps audit log and reports as evidence
```

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
