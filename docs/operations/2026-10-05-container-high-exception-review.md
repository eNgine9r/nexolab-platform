# 2026-10-05 container HIGH exception revalidation

Issue: #1277

## Trigger

The bounded container HIGH exception registry expired on 2026-10-02. On 2026-10-05, PR #1275 exact-head Container Supply Chain run `37294551286` correctly failed closed at policy validation with `exceptions[0] expired on 2026-10-02`. Evidence collection still completed before policy, as required by the post-expiry discovery contract.

## Fresh evidence baseline

Discovery source: `56b4d41250dc6390506052356e498eedfe90faba`.

- Device Agent: 26 HIGH / 0 CRITICAL.
- Telegram Gateway: 26 HIGH / 0 CRITICAL.
- Telemetry Service: 48 HIGH / 0 CRITICAL.
- MQTT Dynamic Security: 0 HIGH / 0 CRITICAL.
- VersityGW Object Storage: 0 HIGH / 0 CRITICAL.
- Fresh exact HIGH tuple count: 100.
- Registry exact tuple count: 100.
- Fresh and registry tuple sets match 1:1.
- Stale registry tuples: 0.
- Unmatched fresh tuples: 0.
- Fresh HIGH findings with a non-empty Trivy `FixedVersion`: 0.
- Exact tuple-set SHA-256: `ca05a899e5684acd7d8bcec2bfcf8c4c012c4d0fdc29f6ac0613ba777ddfcdc2`.

The revalidation does not add, widen or generalize any exception. CRITICAL findings remain unexceptable.

## Current Debian status

Rechecked on 2026-10-05 against Debian Security Tracker:

- ncurses Trixie `6.5+20250216-2` remains vulnerable/no-DSA for `CVE-2025-69720`; fixed versions are in newer suites.
- Expat Trixie `2.8.3-1~deb13u1` remains vulnerable for the retained `CVE-2026-66046`, `CVE-2026-76956`, `CVE-2026-76957` and `CVE-2026-93990`; compatible Trixie fixed packages are not currently listed.
- Python 3.13 Trixie `3.13.5-2+deb13u5` remains vulnerable/no-DSA for retained Python findings including `CVE-2026-82049` and `CVE-2026-19553`; Debian currently lists no fixed unstable version for those two.
- util-linux Trixie `2.41.5-0+deb13u1` remains vulnerable/no-DSA for `CVE-2026-76642`, `CVE-2026-78408`, `CVE-2026-78409` and `CVE-2026-78410`.
- ACL Trixie `2.3.2-2` remains vulnerable/no-DSA for `CVE-2026-54369`; the 2.4.0 fix is outside Trixie.
- systemd Trixie `257.13-1~deb13u1` remains vulnerable/no-DSA for `CVE-2026-16742`; newer suites are fixed.
- cJSON Trixie `1.7.18-3.1+deb13u1` remains vulnerable for the retained cJSON findings. Debian still reports `CVE-2026-87933`, `CVE-2026-67215` and `CVE-2026-67216` as unfixed even in newer cJSON packages.

Authoritative references:

- https://security-tracker.debian.org/tracker/source-package/ncurses
- https://security-tracker.debian.org/tracker/source-package/expat
- https://security-tracker.debian.org/tracker/source-package/python3.13
- https://security-tracker.debian.org/tracker/source-package/util-linux
- https://security-tracker.debian.org/tracker/source-package/acl
- https://security-tracker.debian.org/tracker/source-package/systemd
- https://security-tracker.debian.org/tracker/source-package/cjson

## Current NEXOLAB runtime reachability

A current-source search of `main` at `57f1191dc4804c9f35a56aab00c32f640bcc421f` found no affected application path in the runtime services for:

- `html.parser.HTMLParser`;
- XML/pyexpat/ElementTree/SAX/minidom/lxml parsing in Device Agent or Telegram Gateway;
- tarfile/archive extraction in Device Agent or Telegram Gateway;
- `infocmp`/terminfo execution;
- ACL mutation APIs;
- cJSON Utils `MergePatch`, `ApplyPatches` or `cJSON_Compare`;
- `systemd-homed`, homectl, D-Bus or polkit application flows;
- `nsenter --join-cgroup`;
- mount/fstab/`X-mount` application flows.

Repository backup, deployment and RS-485 tooling does contain archive-handling code, but those paths are not part of the affected Device Agent/Telegram Gateway runtime images reviewed for the retained Python tarfile tuples.

Telemetry Service still reaches cJSON transitively through the required Debian `mosquitto_ctrl` client and the bounded authenticated `nexolab-dynsec-admin → mosquitto_ctrl dynsec <fixed operation>` contract. No arbitrary cJSON Utils patch/compare surface was found.

## Decision

Retain only the same 100 exact image/package/CVE HIGH decisions through **2026-10-12**, seven days from this review. No severity threshold is relaxed, no package-family or wildcard exception is introduced, and no CRITICAL exception path exists.

Each decision must be removed immediately if:

- the exact tuple disappears from a fresh scan;
- a compatible current base/Trixie fix becomes consumable;
- a non-empty scanner `FixedVersion` becomes available and can be consumed;
- affected runtime reachability appears;
- authoritative vulnerability status materially changes;
- severity becomes CRITICAL;
- 2026-10-12 is reached without another fresh review.

## Verification boundary

This document records discovery evidence. The #1277 exact-head candidate must independently rebuild/scan the controlled images and pass Container Supply Chain policy plus the routed Core/Merge Gate before merge. Discovery evidence alone is not merge acceptance.

## Safety

No production deployment or restart, persistent-data or named-volume mutation, severity-threshold relaxation, Modbus/controller write or hardware write is authorized by this review.
