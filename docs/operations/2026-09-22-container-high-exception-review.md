# 2026-09-22 HIGH container exception review

Issue: #1108. Discovery source: `2524f9c0c15218cc56a0416ecc76cb46040fab79`.
Fresh no-cache Container Supply Chain run: `35704565417`.

## Result

The repaired post-expiry discovery path from #1106 produced fresh exact-head image evidence before applying the expired acceptance registry.

Fresh Trivy HIGH/CRITICAL findings:

- Device Agent: 21 HIGH, 0 CRITICAL
- Telegram Gateway: 21 HIGH, 0 CRITICAL
- Telemetry Service: 48 HIGH, 0 CRITICAL
- MQTT Dynamic Security: 0 HIGH, 0 CRITICAL
- total: 90 HIGH, 0 CRITICAL

The 90 fresh image/package/CVE tuples match the existing registry 1:1 by image, package and CVE. No registered tuple disappeared, no new HIGH tuple appeared, and no CRITICAL finding exists. Therefore no stale exception is retained and no new exception is introduced.

All retained decisions are renewed for seven days through **2026-09-29**. Each entry remains exact, owner-bound to `platform-security`, and retains its prior tuple-specific rationale as audit history.

## Current package/fix evidence

Fresh image versions remain:

- Expat `2.8.3-1~deb13u1`
- Python 3.13 `3.13.5-2+deb13u5`
- ncurses `6.5+20250216-2`
- util-linux `2.41.5-0+deb13u1`
- systemd libraries `257.13-1~deb13u1`
- acl `2.3.2-2`
- cJSON `1.7.18-3.1+deb13u1`

Debian Security Tracker was rechecked on 2026-09-22:

- Expat: Trixie 2.8.3 remains vulnerable for CVE-2026-66046, CVE-2026-76956 and CVE-2026-76957; 2.8.4 is available in forky/sid, not the current Trixie runtime contract.
- Python 3.13: Trixie 3.13.5 remains vulnerable/no-DSA for CVE-2026-15308, CVE-2026-7210 and CVE-2026-82049.
- ncurses: Trixie 6.5+20250216-2 remains vulnerable/no-DSA for CVE-2025-69720.
- util-linux: Trixie 2.41.5 remains marked vulnerable/no-DSA for CVE-2026-76642, CVE-2026-78408, CVE-2026-78409 and CVE-2026-78410; fixed packages are not in the current Trixie contract.
- systemd: Trixie 257.13 remains vulnerable/no-DSA for CVE-2026-16742.
- acl: Trixie 2.3.2 remains vulnerable/no-DSA for CVE-2026-54369; 2.4.0 is outside Trixie.
- cJSON: the retained cJSON CVEs remain open for Trixie 1.7.18, including CVE-2026-67215, CVE-2026-67216 and CVE-2026-87933.

Authoritative references:

- https://security-tracker.debian.org/tracker/source-package/expat
- https://security-tracker.debian.org/tracker/source-package/python3.13
- https://security-tracker.debian.org/tracker/source-package/ncurses
- https://security-tracker.debian.org/tracker/source-package/util-linux
- https://security-tracker.debian.org/tracker/source-package/systemd
- https://security-tracker.debian.org/tracker/source-package/acl
- https://security-tracker.debian.org/tracker/source-package/cjson
- https://access.redhat.com/security/cve/cve-2026-78409

### CVE-2026-78409 source disagreement

Debian/Trivy still classify Trixie util-linux 2.41.5 as vulnerable. Red Hat's current CNA statement says the detached-tree `X-mount.subdir` path was introduced in util-linux 2.42 and explicitly states v2.41 is not affected. NEXOLAB keeps the exact scanner tuple fail-closed while authoritative source data disagree; it is not treated as conclusively unaffected.

## Current runtime reachability

A new source sweep on current `main` found:

- no XML/pyexpat/ElementTree parser path in Device Agent or Telegram Gateway;
- no HTMLParser path in Device Agent or Telegram Gateway;
- no tarfile/archive extraction path in Device Agent or Telegram Gateway;
- no `infocmp`/terminfo execution path in the affected services;
- no application `nsenter`, `unshare`, `X-mount`, host `/etc/fstab`, mount-helper or ACL mutation path;
- no systemd-homed, `org.freedesktop.home1`, polkit or D-Bus application path in the affected runtime services;
- cJSON remains a transitive dependency through the required `mosquitto_ctrl` dynamic-security client. Repository code invokes a fixed authenticated dynsec command surface and contains no cJSON Utils `MergePatch`, `ApplyPatches`, or `cJSON_Compare` application path.

The only `json_extract` hits in the generic parser sweep are SQLite JSON functions in a database migration and are unrelated to XML/archive parsing.

## Renewal boundary

Every retained exception must be removed or re-reviewed immediately if any of these conditions becomes true before 2026-09-29:

1. the exact image/package/CVE tuple disappears from a fresh no-cache scan;
2. Debian Trixie or the controlled base image consumes a compatible fixed package;
3. runtime reachability changes;
4. severity becomes CRITICAL;
5. the current source disagreement for CVE-2026-78409 converges;
6. 2026-09-29 is reached.

No wildcard, package-family, severity-wide or CRITICAL exception is introduced.

## Runtime safety

This review changes only security decision metadata, tests, documentation and project state. Production services, persistent data, Modbus polling, hardware configuration and site runtime are unchanged.
