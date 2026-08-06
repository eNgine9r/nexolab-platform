# NEXOLAB Dependency Update Policy

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

PR #272 remains an independent unselected production dependency review. Issue #328 does not approve, merge or close it.

### Development patch/minor

Development patch and minor updates may be grouped only when they share one verification surface:

| Group                                 | Packages                                                                  | Verification surface                         |
| ------------------------------------- | ------------------------------------------------------------------------- | -------------------------------------------- |
| `development-test-patch-minor`        | Playwright, Testing Library, jsdom, Vitest and the Vite React test plugin | unit, browser and test-runtime compatibility |
| `development-quality-patch-minor`     | Commitlint, ESLint, Husky, lint-staged and Prettier                       | repository quality gates and commit hooks    |
| `development-build-patch-minor`       | Tailwind CSS and its PostCSS adapter                                      | CSS compilation and production build         |
| `development-react-types-patch-minor` | React and React DOM type packages                                         | TypeScript and React component contracts     |

`@types/node` and `typescript` remain individual even for patch/minor updates because they define repository-wide compiler and runtime assumptions.

### Major migrations

Major version updates are disabled in Dependabot version-update automation.

Every major migration requires one dedicated Issue, one feature branch, one focused Pull Request, an explicit rollback plan and the full verification surface declared by that Issue. Dependabot must not group, automatically merge or silently introduce major versions.

Current migration mapping:

| Migration               | Dedicated Issue | Status                                     |
| ----------------------- | --------------: | ------------------------------------------ |
| lint-staged 17          |            #252 | queued                                     |
| jsdom 30                |            #253 | queued                                     |
| @playwright/test 1.62.x |            #254 | queued                                     |
| TypeScript 6            |            #255 | queued                                     |
| TypeScript 7            |            #256 | deferred                                   |
| ESLint 10               |            #257 | blocked on compatible Next.js/plugin graph |

## Node runtime boundary

The active repository runtime baseline is Node 22 from `.nvmrc`. `@types/node` must remain on major 22 while that runtime boundary is active.

Dependabot therefore has:

- a global SemVer-major ignore rule;
- an explicit `@types/node >=23` guard.

Moving to Node 24, Node 26 or another major requires a dedicated runtime migration Issue that updates `.nvmrc`, package engine constraints, CI images, container/runtime evidence and `@types/node` together. A type-only jump is not acceptable.

## Pull Request triage

### Superseded or grouped major PR

Close without merge and explain which focused Issues replace it. PR #271 is the reference example: it mixed Playwright, Node types, ESLint, jsdom, lint-staged and TypeScript major migrations and was superseded by Issues #252–#257.

### Stale PR

Rebase or recreate only after confirming its Issue is still Ready and its scope remains focused. Do not revive a PR whose dependency version or migration plan has been superseded.

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
