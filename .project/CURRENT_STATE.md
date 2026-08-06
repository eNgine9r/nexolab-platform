# NEXOLAB Current State

Updated: 2026-08-06
Verified software baseline: `a8b2590c94a2fa67cd414f4b956f204e6b8f8540`
Active control Work Package: Issue #329 — open the engineering hardening sprint
Branch: `docs/329-open-engineering-hardening-sprint`
Next Ready Work Package: Issue #327 — revalidate the expiring cJSON vulnerability exception
Active epic: Issue #326 — Engineering governance, security exception lifecycle and toolchain hardening
Parallel blocked epic: Issue #282 — acquisition software complete; physical Raspberry Pi/RS-485 acceptance pending
Status confidence: high for merged software and disconnected runtime; current cJSON package/fix status is intentionally unverified until the exact image is rebuilt and rescanned.

## New independent software queue

The Product Owner requested continued software planning while physical acquisition acceptance remains blocked. The new ordered queue is:

1. **Issue #327** — revalidate the expiring `libcjson1/CVE-2026-67216` exception before 2026-08-15.
2. **Issue #300** — canonical ADR registry with legacy-link compatibility and integrity validation.
3. **Issue #328** — separate dependency update lanes and retire grouped major PRs.
4. **Issue #253** — jsdom 30 migration.
5. **Issue #254** — Playwright 1.62.x migration.
6. **Issue #252** — lint-staged 17 migration after the completed Node 22 baseline and browser-tooling stabilization.
7. **Issue #255** — TypeScript 6 transition.

Deferred or blocked:

- **Issue #257** — ESLint 10 remains blocked until a compatible Next.js and plugin graph is demonstrated.
- **Issue #256** — TypeScript 7 remains deferred until TypeScript 6 is complete and ecosystem support is available.

Exactly one Work Package is Ready: Issue #327.

## Security exception priority

Issue #295 / PR #296 introduced a narrow exception for `telemetry-service/libcjson1/CVE-2026-67216`, owned by `platform-security`, with a repository review date of 2026-08-15.

Issue #327 must not assume that the package is still vulnerable or already fixed. It must:

- rebuild the exact current telemetry-service image;
- generate current SBOM and vulnerability evidence;
- verify the exact package version and current primary-source package status;
- prefer package removal, a fixed supported package or tool isolation;
- renew only the exact package/CVE/image exception when no supported fix exists;
- keep global HIGH/CRITICAL policy fail-closed.

No acquisition, frontend, database, Modbus or hardware behavior belongs in this Work Package.

## Dependency PR disposition

- PR #271 is closed unmerged as superseded because it grouped unrelated major migrations and conflicted with the one-Issue/one-branch/one-focused-PR rule.
- PR #272 remains open and unselected. Its `lucide-react` update requires a separate focused compatibility and visual-regression decision; it is not implicitly approved by the new queue.

The supported Node runtime baseline remains Node `22.23.1`. Node type packages must not silently move to a newer runtime major through grouped automation.

## Acquisition and hardware boundary

Issue #289 software acceptance remains merged through PR #323. Its classification remains:

```text
software verified; hardware performance acceptance pending
```

The following Issues remain on the parallel hardware-blocked track:

- #289 — physical acquisition scale and request-envelope acceptance;
- #245 — actual standalone Raspberry Pi acceptance;
- #189 — physical reboot, power-loss and media restore;
- #200 — physical RS-485 topology and single-master proof;
- #201 — LE-01MP cumulative energy validation;
- #202 — extended XJP60D semantics validation.

Independent engineering-hardening work may continue without changing this classification. No hardware-blocked Issue is treated as completed or Ready without access.

## Guardrails

- one Issue, one branch and one focused Pull Request;
- no grouped major migration;
- no mandatory cloud, CDN, external API, remote font or paid runtime dependency;
- development tooling changes must not enter the disconnected production runtime;
- no Modbus or other hardware writes;
- no production/site cutover;
- no destructive database or persistent-volume action;
- no physical acceptance claim without controlled evidence.

## Next action

Complete Issue #329 as an exact four-file state-only PR. After merge, start Issue #327 from current `main`: inspect the exact exception, rebuild and rescan the current telemetry-service image, then decide removal, supported remediation or narrowly evidenced renewal before 2026-08-15.
