# NEXOLAB #1447 — exact-image container security revalidation

> **2026-11-06 reconciliation:** All counts and proposed exceptions below describe historical image reviews. The current branch retains the main-branch registry unchanged: 48 entries, expired 2026-10-20; no new or renewed exception is approved. The latest separate #1529 candidate scan reports 5 CRITICAL and 83 HIGH amd64 image/package/CVE tuples before this remediation; it does not establish installed ARM64 exposure. Fresh builds and policy review are required. The owner requested an update; the bounded residual-risk decision described below remains a separate, as-yet-unmade decision.

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

A policy regression in this Work Package also rejects any exceptional HIGH with a non-empty Trivy `FixedVersion`; a newly available patch must be investigated rather than silently overridden by the previous exception. This is enforced by an isolated unit test and exact-head CI.

## 2026-11-04 technical review for the Product Owner

This section supersedes the historical count of 49 remaining findings. The owner authorized technical review/preparation; no specific risk waiver or production/site cutover was given. Repository CODEOWNERS identifies `@eNgine9r`; `platform-security` in the exception registry is a logical role string, not proof of a separate human reviewer.

### Evidence and limits

Downloaded all five image artifact ZIPs from exact-head run `41076486729`, source `0b50d7df348ea4234607a84ce4c692ee0c66ff59`, verified the source and all 15 CycloneDX/SPDX/raw-report digests against their manifests, then rescanned the immutable CycloneDX package inventories with checksum-pinned Trivy **0.70.0** and vulnerability DB updated **2026-11-04 07:16:25 UTC**. This is a current vulnerability lookup against previously built **linux/amd64** images, not a new image build, binary reachability proof, ARM64 acceptance or installed-site scan. Exact source/image/SBOM/rescan/DB hashes and all 50 exact HIGH tuples are in [the machine-readable review](security-container-review-20261104.json).

| Existing candidate image | HIGH | CRITICAL |
| ------------------------ | ---: | -------: |
| telemetry-service        |   50 |        0 |
| device-agent             |    0 |        0 |
| mqtt-dynamic-security    |    0 |        0 |
| telegram-gateway         |    0 |        0 |
| object-storage           |    0 |        0 |

Candidate SBOMs confirm Pillow **13.0.0**, msgpack **1.2.3**, and Go stdlib **1.27.3**. These remediate the known five Pillow CRITICAL and fixed-version msgpack/Go findings. Native Debian residual findings remain; they have not disappeared because of a policy exception.

The 50 package/CVE tuples represent **14 unique CVEs**. All 14 match the current official [Debian tracker JSON](https://security-tracker.debian.org/tracker/data/json), whose Trixie entries remain `open`; no current rescan HIGH reports a fixed version. The prior 49 exact tuples still match the existing short-lived registry; only `telemetry-service / libsqlite3-0 / CVE-2026-119373` is new. Running the existing candidate's unchanged evaluator against the current report **fails**, blocking this SQLite tuple. No new exception or expiry extension has been written.

### Reachability and residual risk

The new [SQLite advisory](https://security-tracker.debian.org/tracker/CVE-2026-119373) describes heap corruption requiring FTS5 `detail=none` data, attacker-controlled negative rowids and a prefix MATCH query. Debian Trixie `3.46.1-7+deb13u2` remains vulnerable; the reported fixed Debian package is in unstable, not Trixie. Telemetry actively uses SQLite for its MQTT spool and export staging; source paths use ordinary tables and bound values/BLOBs (`app/durable_spool.py:98,297-325`; `app/energy_export/source.py:136-156,225-230`). Scoped source search found no FTS5, virtual-table creation, arbitrary SQL scripts, extension loading or foreign database attachment. This narrows the observed trigger path but does not prove safety against a replaced database, transitive native use or an unverified site configuration.

The existing [libwebsockets advisory](https://security-tracker.debian.org/tracker/CVE-2026-95114) remains a native JSON-parser denial-of-service risk. The telemetry image installs Mosquitto for `mosquitto_ctrl`, while its default process is Uvicorn; broker admin launches a native command. No claim that all native parser entry points are unreachable is justified without actual image linkage/process/listener evidence. Other existing per-CVE reachability rationales remain conditional; current scanner/tracker agreement establishes package status, not exploit impossibility.

Two omitted packaging tests were actually run and failed because they still required msgpack **1.2.1** and Go **1.27.2**. Their assertions now require the already-remediated exact versions/checksums, and the Telemetry workflow explicitly executes both files and triggers on edits to them. Focused policy, packaging and PNG/msgpack codec checks: **67 PASS**. Full final-head CI remains required.

### Concrete decision and recommendation

Recommend allowing continued source development and isolated compatibility/hardware preparation. A source-only risk decision could provisionally retain exactly these **50 named HIGH package/CVE tuples through 2026-11-06**, after a fresh final-source build/scan confirms no further changes. This requires a specific Product Owner risk decision; the current authorization to prepare this review does not grant it. The current 49-entry registry is unchanged and intentionally fails on the 50th finding.

The proposed bounds are: zero CRITICAL; no accepted finding with a reported fixed version; exact image/package/CVE identities only; no wildcard or automatic renewal; remove/review an entry immediately on compatible fix or exposure change; fresh final ARM64 and runtime evidence still required. Final policy/CI must pass before any source merge. Production/site installation also retains the separate backup/restore, rollback, LAN/IPAM and real-device gates, and requires its own explicit cutover authorization.

Until that concrete risk decision and fresh verification exist, **do not merge or deploy** this candidate. This assessment grants no security exception, production approval, hardware write or update signal.
