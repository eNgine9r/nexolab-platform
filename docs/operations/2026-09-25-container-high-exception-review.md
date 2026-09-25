# 2026-09-25 container HIGH exception revalidation

Issue: #1156

## Fresh evidence baseline

- Source head: `a231169f0269a441fac4fc1f05da39097e4adfa3`.
- Container Supply Chain run: `36123964257`.
- Device Agent: 22 HIGH / 0 CRITICAL.
- Telemetry Service: 48 HIGH / 0 CRITICAL.
- Telegram Gateway: 22 HIGH / 0 CRITICAL.
- MQTT Dynamic Security: 0 HIGH / 0 CRITICAL.
- VersityGW object-storage: 0 HIGH / 0 CRITICAL.
- Fresh exact tuple count: 92.
- Registry exact tuple count: 92.
- Fresh and registry tuple-set SHA-256: `6f38696e08354c9ad505964ec4df82d61bca23b12f4af9e934158bc9be1d394e`.
- Stale registry tuples: 0.
- Unmatched fresh tuples: 0.
- Fresh HIGH findings with a non-empty Trivy `FixedVersion`: 0.

The repository-owned evaluator accepts all 92 fresh HIGH tuples only through exact image/package/CVE decisions. No CRITICAL decision exists.

## Current Debian and upstream status

Observed on 2026-09-25 from Debian Security Tracker and upstream/vendor references:

- ncurses Trixie `6.5+20250216-2` remains vulnerable to `CVE-2025-69720`; fixed versions are only in newer suites.
- Python 3.13 Trixie `3.13.5-2+deb13u5` remains vulnerable for the retained `CVE-2026-15308`, `CVE-2026-7210` and `CVE-2026-82049` families; fixes where available are not in the current Trixie package.
- Expat Trixie `2.8.3-1~deb13u1` remains vulnerable for `CVE-2026-66046`, `CVE-2026-76956`, `CVE-2026-76957` and `CVE-2026-93990`.
- ACL Trixie `2.3.2-2` remains vulnerable to `CVE-2026-54369`; the 2.4.0 fix is outside Trixie.
- util-linux Trixie `2.41.5-0+deb13u1` remains vulnerable for `CVE-2026-76642`, `CVE-2026-78408`, `CVE-2026-78409` and `CVE-2026-78410`; Debian marks these Trixie issues vulnerable/no-DSA.
- For `CVE-2026-78409`, Red Hat states the vulnerable `X-mount.subdir` detached-tree path begins in util-linux 2.42 and considers 2.41 not affected. Debian still marks Trixie 2.41.5 vulnerable. The disagreement remains explicit rather than being treated as a fix.
- systemd Trixie `257.13-1~deb13u1` remains vulnerable/no-DSA for `CVE-2026-16742`; the affected component is `systemd-homed`.
- cJSON Trixie `1.7.18-3.1+deb13u1` remains vulnerable for the retained cJSON families; current Debian tracker still has open cJSON issues and no compatible Trixie fixed package for these tuples.

Authoritative references used for this review:

- `https://security-tracker.debian.org/tracker/source-package/ncurses`
- `https://security-tracker.debian.org/tracker/source-package/python3.13`
- `https://security-tracker.debian.org/tracker/source-package/expat`
- `https://security-tracker.debian.org/tracker/source-package/acl`
- `https://security-tracker.debian.org/tracker/source-package/util-linux`
- `https://security-tracker.debian.org/tracker/source-package/systemd`
- `https://security-tracker.debian.org/tracker/source-package/cjson`
- `https://access.redhat.com/security/cve/cve-2026-78409`

## Current NEXOLAB runtime reachability

The current `main` source `36a9d2a2ab7c3f5aaa4cba3859d4d225834f543c` was searched across Device Agent, Telegram Gateway, Telemetry Service and relevant runtime Compose/object-storage surfaces.

No runtime source path was found for `html.parser.HTMLParser`, XML/pyexpat/ElementTree/SAX/minidom/lxml, tar archive extraction, `infocmp`/terminfo parsing, ACL mutation APIs, cJSON Utils `MergePatch`/`ApplyPatches`/`cJSON_Compare`, `systemd-homed`/D-Bus/polkit, `nsenter --join-cgroup`, or mount/fstab/X-mount operations.

Telemetry Service still installs Debian `mosquitto` only to obtain `mosquitto_ctrl`. NEXOLAB reaches it through the bounded authenticated `nexolab-dynsec-admin` command contract; no arbitrary cJSON document or arbitrary `mosquitto_ctrl` argument surface is exposed.

## Decision

Retain the same 92 exact image/package/CVE HIGH decisions through **2026-10-02**, seven days from the fresh evidence date. No tuple is added and no tuple is widened. The review does not change severity thresholds and does not create a CRITICAL exception path.

Every retained decision remains fail-closed and must be removed immediately if any of these conditions becomes true:

- the exact tuple disappears from a fresh scan;
- a compatible Trixie/base-image fix becomes consumable;
- runtime reachability changes so the affected path becomes available;
- scanner or authoritative package status materially changes;
- severity becomes CRITICAL;
- the 2026-10-02 review boundary is reached without fresh revalidation.

## Safety

No production service restart, deployment/cutover, persistent-data or named-volume mutation, vulnerability threshold relaxation, Modbus/controller write or hardware write is part of this review.
