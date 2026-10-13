# 2026-10-13 container security prerequisite review

Issue #1369 restores shared gates blocking Energy export #1363 / PR #1368.
It changes build/policy metadata, contracts and state; it does not install images.

## Fresh discovery

Container Supply Chain run `38475307833` rebuilt and scanned all controlled
images at `cd62d2f8e8cbcc16505ec4e6a7ea6a8eb7fd5c29` on 2026-10-13.
Policy correctly failed closed on the previous 2026-10-12 expiry.
Downloaded reports match their manifest digests and source SHA.

| Image                 | HIGH | CRITICAL | Trivy report SHA-256                                               |
| --------------------- | ---: | -------: | ------------------------------------------------------------------ |
| Telemetry Service     |   48 |        0 | `f42fdd99126152f5a13cd31f30bacee234931632a0d63490a44fdd7e56a04627` |
| Device Agent          |    0 |        0 | `70fb928361539ef9d77a783ee7a0c9826ab131f9db8e126b7de233ab8f5c0834` |
| Telegram Gateway      |    0 |        0 | `9d215a8388709b96973b96f7218b8e3aff33a0d28c363ed553c4c334293450d3` |
| MQTT Dynamic Security |    0 |        0 | `9e71002dc1380c1a3c21bb70ad8cb2f04ab2d232db0b8ca4820ea9fd6c1af755` |
| Object Storage        |    4 |        0 | `67476dd190b167f6ec6be71b9106ea131479e36560447a2fe0d66c4a5a5a5b3b` |

Telemetry's 48 exact image/package/CVE tuples match the existing registry 1:1:
zero stale or unmatched entries, no HIGH with a nonempty `FixedVersion`.
Sorted compact-JSON tuple-set SHA-256:
`3a0f6834d30d647b97692b2cf016f1a8ecb2e30af8067a39505a33daa634765e`.
There are no remaining Device Agent or Telegram Gateway HIGH exceptions.

## Telemetry decisions

Current Debian Trixie status was rechecked on 2026-10-13:

| Source package | Trixie version       | Retained findings                                                                            |
| -------------- | -------------------- | -------------------------------------------------------------------------------------------- |
| ncurses        | `6.5+20250216-2`     | `CVE-2025-69720`; newer suites fixed                                                         |
| util-linux     | `2.41.5-0+deb13u1`   | `CVE-2026-76642`, `78408`, `78409`, `78410`; newer suites fixed                              |
| acl            | `2.3.2-2`            | `CVE-2026-54369`; newer suites fixed                                                         |
| systemd        | `257.13-1~deb13u1`   | `CVE-2026-16742`; newer suites fixed                                                         |
| cjson          | `1.7.18-3.1+deb13u1` | `CVE-2026-16554`, `29036`, `67215`, `67216`, `87933`; current newer suites remain vulnerable |

Authoritative current sources:
[ncurses](https://security-tracker.debian.org/tracker/source-package/ncurses),
[util-linux](https://security-tracker.debian.org/tracker/source-package/util-linux),
[acl](https://security-tracker.debian.org/tracker/source-package/acl),
[systemd](https://security-tracker.debian.org/tracker/source-package/systemd),
[cjson](https://security-tracker.debian.org/tracker/source-package/cjson).

The current Telemetry runtime and Energy candidate source have no infocmp or
terminfo execution, ACL mutation, homectl/systemd-homed/D-Bus/polkit flow,
nsenter/join-cgroup, mount/fstab/X-mount or cJSON Utils patch/compare interface.
The required `mosquitto_ctrl` client remains confined to the fixed authenticated
`nexolab-dynsec-admin` operations. The original tuple-specific rationale, including
the 64-bit cJSON condition and library dependency review, is preserved.
The image runs as UID 10001; Compose's local service, secret, mount and endpoint
contracts are unchanged. Export adds private scalar SQLite staging and XLSX
writing, not a new affected system-library input path.

Retain only these same 48 HIGH decisions through **2026-10-20**, seven days from
this review. New review wording supersedes historical expiry wording without
removing historical rationale. Remove immediately when a compatible fix is
available, the exact tuple disappears, affected reachability/mitigation changes,
authoritative guidance changes or severity becomes CRITICAL. New source review
and fresh exact-head policy/scan acceptance are mandatory.

## Fixed Object Storage findings

The discovery image contains four new HIGH tuples:

| Package          | CVE              | Compatible fix         |
| ---------------- | ---------------- | ---------------------- |
| stdlib           | `CVE-2026-78667` | Go `1.27.2` / `1.26.9` |
| stdlib           | `CVE-2026-78669` | Go `1.27.2` / `1.26.9` |
| stdlib           | `CVE-2026-97031` | Go `1.27.2` / `1.26.9` |
| golang.org/x/net | `CVE-2026-78669` | `v0.60.0`              |

These receive **no exception**. The build preserves VersityGW v1.8.0 source commit
`fd04bc1df2656298577b82667a4195c77f8c7563` and recompiles with Go 1.27.2 and
x/net v0.60.0, checksum-verifying the SDK, verifying Go modules and checking
resulting binary build metadata. Target amd64/arm64, version, entrypoint, scratch
runtime and `posix /data` contract remain explicit. Build access to GitHub/Go is
development-only; no downloader or required internet enters the finished image.

Go's [release history](https://go.dev/doc/devel/release#go1.27.2) records the fixed
security release on 2026-10-08. SDK checksums come from the official
[Go image recipe](https://github.com/docker-library/golang/blob/master/1.27/bookworm/Dockerfile).
Actual replacement-image scans and isolated S3/report regression evidence must
prove the result; source edits alone do not establish vulnerability removal.

## Verification and safety boundary

Local policy validation and 61 focused policy/image/manifest contract tests pass.
Exact-head CI builds, fresh scans, full routed checks and review are pending.
An actual Pi isolated-build preflight was denied while creating a new home
directory (`read-only filesystem`), before any file, builder or runtime change.
Native build/export performance acceptance is unverified until a writable
isolated validation environment is available; do not substitute x86/QEMU proof.

Production C296, existing volumes, acquisition, device configuration, backup and
rollback/update gates are unchanged. No site cutover, service restart, data or
evidence deletion, Modbus or other hardware write is part of this Work Package.
