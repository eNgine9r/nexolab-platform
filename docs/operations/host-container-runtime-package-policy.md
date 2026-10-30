# NEXOLAB Raspberry Pi: Docker/containerd host-package update policy (#1421)

## Incident boundary

At 2026-10-29 16:38:36 EET, `nexolab-edge-01` rebooted. At 16:39:07, **before the APT transaction**, Docker logged missing/stale network sandboxes. At 16:43:39, APT recorded `packagekit role='update-packages'`, `Requested-By: nexolab (1000)`. PackageKit upgraded Docker Engine/CLI 29.7.1 → 29.9.2, `containerd.io` 2.2.6 → 2.4.2, Compose 5.4.0 → 5.6.1 and related Docker packages on the running site. At 16:44:26 Docker reported a shim bootstrap API mismatch; containerd restarted at 16:45:13 and Docker at 16:45:51. No later high-severity service logs were seen in the supplied interval; **this is not evidence that network connectivity recovered**. The protected Dashboard port remained refused and multiple containers had `Networks={}`.

The PackageKit in-place upgrade plausibly explains the transient shim error, **not the pre-upgrade orphaned sandboxes**. These remain separate P0 incidents: #1399 protected boot repair, #1409 physical-LAN/Docker CIDR overlap, #1400 object-storage reachability. APT `Requested-By` does not establish which person or desktop client initiated PackageKit.

## Read-only source guard

The standalone Python 3 script reads exactly two local inventories and prints sanitized JSON:

```bash
python3 scripts/verify-host-container-runtime-package-policy.py --check
```

It checks hold state and installed versions for `docker-ce`, `docker-ce-cli`, `containerd.io`, `docker-compose-plugin`, `docker-buildx-plugin`, `docker-ce-rootless-extras`.

- `guarded` (exit 0): all six packages are installed and held in APT.
- `unprotected` (exit 78): all six packages are fully installed but at least one lacks an APT hold.
- `blocked` (exit 78): missing, removed, unpacked or half-configured package, unreadable inventory, malformed or contradictory APT/dpkg hold state.

The audit now cross-checks the `dpkg-query` desired/state/error code
(`hi ` for a held fully installed package; `ii ` for an installed
unheld package) against `apt-mark showhold`. Version strings alone
are rejected as proof of installation. Duplicate/unknown packages,
missing status codes, unexpected version formatting and incomplete
inventories fail closed. Only the six allowlisted package identities,
their installed versions and hold bits appear in success output.
The script never claims exact release-version approval.

This check **does not** call `apt install`, `apt-mark hold`, PackageKit, `systemctl`, Docker or any remote network. It does not read application secrets, write a file or touch industrial hardware. The status is **not** proof of installed immutable package authority, successful PostgreSQL/SQLite backups, working MQTT, hardware readiness or network health. APT holds alone do not prevent an authorized privileged user from explicitly overriding them or running direct `dpkg`; they are one defense-in-depth control, not a complete update policy.

## Controlled adoption (not part of this source-only WP)

Before changing package holds or PackageKit policy on a live Pi, verify and retain: exact accepted Version Manager source/image digest inventory and immutable Compose hashes; versioned Docker/containerd binaries and APT availability; exact current package list; secured PostgreSQL, SQLite and object-storage backups **plus verified restoration**; persistent volume identities and rollback; no active operation lock; three hardware RS-485 workers; LAN/CIDR risk; and owner-approved maintenance window/rollback decision. Record any outstanding security updates separately rather than blindly disabling all system updates. Then use only a reviewed, checksum-pinned, owner-authorized procedure to apply narrowly-scoped package controls, and independently verify PackageKit does not replace held Docker packages.

Do **not** deploy this script as an enabled boot supervisor, turn it into an auto-remediation service, run `docker compose down`, remove volumes, downgrade Docker, restart containerd, override the physical/Docker CIDR safety gate, or re-enable legacy `nexolab-dashboard.service`. Successful source-only tests never authorize production activation.
