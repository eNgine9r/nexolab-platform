# NEXOLAB #1447 — exact-image container security revalidation

**Status:** source-only risk review. The seven-day exception registry is a narrow risk decision, **not** proof of vulnerability elimination or permission to merge/deploy. The production site, credentials, field buses and data volumes were not changed.

## Source-bound scan and fixes

Source head: `66c30bd496193e4ea334df9d80deac07aea0f772`, GitHub Actions `Container Supply Chain` run `41071197854` (linux/amd64 images).

- `telemetry-service`: before 73 HIGH / 5 CRITICAL, after 49 HIGH / 0 CRITICAL; Trivy JSON SHA-256 `176a86e51affe51805aecf4fc1987093705aacd5db500a1b16940c3c7e330fd5`.
- `object-storage`: before 1 HIGH / 0 CRITICAL, after 0 HIGH / 0 CRITICAL; Trivy JSON SHA-256 `717f4c3f8b52da68953aff3c62adac0e5a8fc7925529937dde93f73ddefc4675`.
- `device-agent`: 0 HIGH / 0 CRITICAL; Trivy JSON SHA-256 `95b6f5a7bf1bfdae50fa3f8873c5b65a9477895ce5de026f80a26dcc692feb83`.
- `telegram-gateway`: 0 HIGH / 0 CRITICAL; Trivy JSON SHA-256 `a3b238b6c59b366b61b7c1164880fe960451a4fbed8b906769e2a01a84750355`.
- `mqtt-dynamic-security`: 0 HIGH / 0 CRITICAL; Trivy JSON SHA-256 `34cb9f676015640fbb3e0024ae749120fc22a0f006f51859379ab25bfbd9b120`.

Fixed using **Pillow 13.0.0**, **msgpack 1.2.3**, and Object Storage **Go 1.27.3**. Go downloads checksums came from [official downloads](https://go.dev/dl/). This source-only security PR does not modify runtime networking, authentication, package installation or deployed storage.

## Exactly scoped residual findings

**49 distinct telemetry HIGH** findings remain. All have empty Trivy `FixedVersion`; none is CRITICAL. The 48 historical image/package/CVE tuples match the current scan exactly, and retain their existing individual issue-specific rationale and owner `platform-security`. Their previous expiry was 2026-10-20. A new 49th HIGH is `libwebsockets19t64 / CVE-2026-95114`. No exceptions exist for findings not in the current list.

Current Debian Trixie Security Tracker references: [util-linux](https://security-tracker.debian.org/tracker/source-package/util-linux), [ncurses](https://security-tracker.debian.org/tracker/source-package/ncurses), [acl](https://security-tracker.debian.org/tracker/source-package/acl), [cjson](https://security-tracker.debian.org/tracker/source-package/cjson), [systemd](https://security-tracker.debian.org/tracker/source-package/systemd), and [libwebsockets](https://security-tracker.debian.org/tracker/CVE-2026-95114). The latter describes a potentially remotely triggered LEJP JSON parsing denial of service; current Trixie has no fixed version. The telemetry runtime uses `mosquitto_ctrl` as an outbound broker-management CLI, while the actual Mosquitto broker resides in a different container. This narrows direct service exposure but **does not demonstrate absence of indirect native-library exploitability**.

The 49 bounded records expire on **2026-11-06**. They are **not** blanket version or severity waivers. Each exception is keyed by exact image/package/CVE, and the 48 existing reasons are preserved. A fixed package or new reachable path requires immediate removal or re-review. A fresh exact-head CI scan is required after this change; preserve automated fail-closed reconciliation and require security-owner review before merge.

## Open release gates

- Exact-head post-exception-policy Container Supply Chain GREEN with image hashes and matching vulnerability findings; no new HIGH or CRITICAL.
- Changed-source formatting, telemetry integration tests, offline bundle and independent policy regression checks.
- ARM64 cross-build/isolated use evidence and runtime installed package verification.
- Owner-approved protected production backups and restore, plus separate site change approval, before release.
- No hardware acceptance; no Modbus/hardware writes, broker ACL modifications or storage cutover.
