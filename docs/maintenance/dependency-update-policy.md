# NEXOLAB Dependency Update Policy

Updated: 2026-09-25

## Purpose

Dependency updates must remain reviewable, reversible and compatible with the `LOCAL_LAN` offline-runtime profile. Automation may reduce routine maintenance work, but it must not combine unrelated migrations or silently change the supported runtime boundary.

## Update lanes

### Production runtime

Production runtime updates are individual Pull Requests.

They are not grouped because each update can affect the browser bundle, server runtime, authentication, rendering, offline closure or operator-visible behavior. Every production dependency PR requires:

- a focused compatibility review;
- repository formatting, lint, typecheck, tests and production build;
- relevant browser/runtime acceptance;
- offline dependency review;
- rollback instructions;
- confirmation that no mandatory cloud, CDN, remote font, telemetry or paid runtime service was introduced.

Earlier `lucide-react` PRs #272/#341 established the ungrouped production-dependency lane. Their historical state does not authorize later package updates; every current production dependency candidate must be evaluated from its own exact head and current `main`.

### Development patch/minor

Development patch and minor updates may be grouped only when they share one verification surface:

| Group | Packages | Verification surface |
| --- | --- | --- |
| `development-test-patch-minor` | Testing Library, jsdom, Vitest and the Vite React test plugin | unit, browser and test-runtime compatibility |
| `development-quality-patch-minor` | Commitlint, ESLint, Husky, lint-staged and Prettier | repository quality gates and commit hooks |
| `development-build-patch-minor` | Tailwind CSS and its PostCSS adapter | CSS compilation and production build |
| `development-react-types-patch-minor` | React and React DOM type packages | TypeScript and React component contracts |

`@types/node` and `typescript` remain individual even for patch/minor updates because they define repository-wide compiler and runtime assumptions.

### Migration-grade minor updates

A SemVer-minor update can still be a repository migration when the package is pre-2.0, changes browser binaries, modifies test execution semantics or has a dedicated compatibility Work Package.

Playwright 1.62 was intentionally handled as a migration-grade browser/evidence update in completed Issue #254. Future browser-revision migrations remain subject to the same focused review rather than being mixed into unrelated development groups.

PR #339 demonstrated why this rule is required: it combined a migration-grade Playwright update with an unrelated Vite plugin patch and was closed unmerged.

### Major migrations

Major version updates are disabled in Dependabot version-update automation.

Every major migration requires one dedicated Issue, one feature branch, one focused Pull Request, an explicit rollback plan and the full verification surface declared by that Issue. Dependabot must not group, automatically merge or silently introduce major versions.

Current migration mapping after the 2026-09-25 reconciliation:

| Migration | Dedicated Issue | Status |
| --- | ---: | --- |
| Node 22 baseline / Node 22 types | #251 | completed |
| lint-staged 17 | #252 | completed |
| jsdom 30 | #253 | completed |
| @playwright/test 1.62.x | #254 | completed |
| TypeScript 6 | #255 | completed |
| TypeScript 7 | #256 | deferred pending supported TS7 parser/toolchain integration |
| ESLint 10 | #257 | blocked pending an official compatible Next/import-plugin graph |

The completed migrations above are independent accepted baselines. The open #256/#257 issues are future compatibility-gated migrations and are not permission to bypass peer/support constraints.

## Node runtime boundary

The active repository developer/CI runtime baseline is Node `22.23.1`, with the declared supported range `>=22.22.1 <23 || >=24 <25`. `@types/node` remains on major 22 while Node 22 is the active exact CI/developer baseline.

Dependabot therefore retains:

- a global SemVer-major ignore rule;
- an explicit `@types/node >=23` guard while the active runtime line remains Node 22;
- focused treatment for browser/tool migrations that change execution semantics.

Moving to another Node major requires a dedicated runtime migration Issue that updates `.nvmrc`, package engine constraints, CI images, container/runtime evidence and `@types/node` together. A type-only major jump is not acceptable.

## Pull Request triage

### Superseded or grouped migration PR

Close without merge and explain which focused Issues replace it.

- PR #271 mixed Playwright, Node types, ESLint, jsdom, lint-staged and TypeScript migrations and was superseded by Issues #252–#257.
- PR #339 mixed migration-grade Playwright with an unrelated Vite plugin patch and was superseded by completed Issue #254 plus a separate routine patch path.

### Stale PR

Rebase or recreate only after confirming its Issue is still Ready and its requested version remains current. Do not revive a PR whose dependency version or migration plan has been superseded.

### Conflicting or non-mergeable PR

Do not patch unrelated conflicts into the dependency PR. Recreate it from current `main` or open a focused prerequisite Issue.

### Security update

Security remediation may be expedited, but it still requires exact package/vulnerability evidence, bounded exceptions when no fix exists, supply-chain checks and a rollback path. Security urgency does not permit unrelated dependency bundling.

## Required checks

At minimum:

- dependency-policy validator and negative fixtures;
- formatting, lint, typecheck, full tests and production build;
- affected browser/API/runtime acceptance;
- supply-chain review when production closure changes;
- offline bundle review and, when dependency closure changes, a full disconnected startup/update/rollback run;
- confirmation that persistent data and volumes survive rollback.

## Rollback

A dependency PR must be reversible by reverting its focused commit or squash merge. Rollback documentation must identify:

- the previous manifest and lockfile state;
- any generated artifacts or browser binaries that must be restored;
- whether container images require rebuild;
- the exact verification command after rollback.

No dependency PR may require destructive database or persistent-volume operations.

## Automation ownership

- Owner: NEXOLAB engineering / platform maintenance.
- Cadence: npm weekly on Monday at 04:00 Europe/Kyiv; GitHub Actions monthly.
- Automatic major merge: prohibited.
- Dependency version or lockfile changes in policy-only Work Packages: prohibited.

## Parent governance status

The executable migration sequence tracked by Issue #204 is complete through TypeScript 6. Issue #256 and Issue #257 intentionally remain independent compatibility-gated follow-ups. Their existence does not require the completed migration parent to remain active, and neither may start until its own acceptance prerequisites are current and evidenced.