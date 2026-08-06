# NEXOLAB Current State

Updated: 2026-08-06
Verified software baseline: `20863d5e0242ff4248b208633e5e6ef58bb70adf`
Active control Work Package: Issue #332 — reconcile cJSON exception review and promote ADR registry
Branch: `docs/332-reconcile-cjson-review`
Next Ready Work Package: Issue #300 — canonical ADR registry, legacy-link compatibility and integrity validation
Active epic: Issue #326 — Engineering governance, security exception lifecycle and toolchain hardening
Parallel blocked epic: Issue #282 — acquisition software complete; physical Raspberry Pi/RS-485 acceptance pending
Status confidence: high for exact-image security evidence, merged software and disconnected runtime; physical hardware acceptance remains explicitly pending.

## Security exception review completed

Issue #327 / PR #331 was squash-merged as `20863d5e0242ff4248b208633e5e6ef58bb70adf` from exact verified head `d05e3e2405f55a7b8f5d3b722e1165924a4eaf9e`.

Completion classification:

```text
narrow exception renewed; fixed package unavailable; next review date recorded
```

Next mandatory review:

```text
2026-09-05
```

The exact renewed exception remains limited to:

```text
telemetry-service + libcjson1 + CVE-2026-67216
```

Exact telemetry-service evidence:

- image digest: `sha256:544eead98d548c84c938922deb2513b1428994271600fa027dd5895c9813b24d`;
- installed `libcjson1`: `1.7.18-3.1+deb13u1`;
- severity: HIGH;
- status: affected;
- fixed version: none;
- image tag, OCI revision and release manifest all bind to exact head `d05e3e2405f55a7b8f5d3b722e1165924a4eaf9e`.

The required Debian `mosquitto` package remains because it supplies `mosquitto_ctrl` for the authenticated local dynamic-security administration contract. The unused `mosquitto-clients` package and `mosquitto_pub/sub/rr` utilities were removed from telemetry-service.

Supply-chain policy now rejects:

- expired exceptions;
- wildcard image, package or vulnerability matches;
- duplicate exact exceptions;
- exception lifetimes longer than 45 days.

Every unapproved HIGH and every CRITICAL finding remains release-blocking.

## Exact-head verification for PR #331

All checks were GREEN:

- formatting, lint, typecheck, full tests and production build;
- Container Supply Chain exact image rebuild, OCI labels, CycloneDX/SPDX SBOMs, Trivy report and exception policy;
- Telemetry Service;
- Broker Control Acceptance;
- MQTT TLS Fleet Acceptance;
- Offline Auth Acceptance;
- Device Agent Fleet Acceptance;
- Capacity Release Gate;
- Disaster Recovery TLS Fleet;
- Disaster Recovery Browser;
- Offline Bundle clean-host transfer, blocked egress, disconnected startup, update/rollback and persistent-volume preservation.

Final product/security diff contained six permanent files. Temporary repair workflows were absent. No acquisition, frontend, database migration, secret rotation, Modbus write, hardware action or production cutover occurred.

## Ordered engineering-hardening queue

1. **Issue #300 — Ready:** canonical ADR registry with legacy-link compatibility and integrity validation.
2. **Issue #328 — queued:** separate dependency update lanes and retire grouped major PRs.
3. **Issue #253 — queued:** jsdom 30 migration.
4. **Issue #254 — queued:** Playwright 1.62.x migration.
5. **Issue #252 — queued:** lint-staged 17 migration.
6. **Issue #255 — queued:** TypeScript 6 transition.

Deferred or blocked:

- **Issue #257:** ESLint 10 remains blocked until a compatible Next.js/plugin graph is demonstrated.
- **Issue #256:** TypeScript 7 remains deferred until TypeScript 6 and ecosystem support are available.

PR #271 remains closed unmerged as a superseded grouped-major update. PR #272 remains independently open and unselected.

## Parallel acquisition and hardware boundary

Issue #289 remains:

```text
software verified; hardware performance acceptance pending
```

Hardware-dependent Issues #289, #245, #189, #200, #201 and #202 remain blocked by unavailable controlled Raspberry Pi/RS-485 access. Independent documentation and engineering-hardening work may continue without changing their classification.

## Guardrails

- one Issue, one branch and one focused Pull Request;
- preserve legacy links when reorganizing ADR governance;
- no dependency or runtime changes in Issue #300;
- no mandatory cloud, CDN, external API, remote font or paid runtime dependency;
- no Modbus or other hardware writes;
- no production/site cutover;
- no destructive database or persistent-volume action;
- no physical acceptance claim without controlled evidence.

## Next action

Complete Issue #332 as an exact four-file state-only PR. Then execute Issue #300 from current `main`: establish one authoritative ADR registry, preserve the legacy `docs/architecture/decisions/0001-*` path, add deterministic duplicate/broken-link/integrity checks, and avoid runtime or dependency changes.
