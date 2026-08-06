# Playwright 1.62 migration evidence

## Scope

Issue #254 updates only the direct `@playwright/test` development dependency and its deterministic npm lockfile closure. Product behavior, browser selectors, runtime dependencies, Node, jsdom, TypeScript, React and production code are unchanged.

## Runtime compatibility

- Repository Node baseline: `22.23.1`.
- Installed Playwright: `1.62.0`.
- Playwright package engine requirement: `{"node": ">=20"}`.
- Installation, config loading and test discovery ran on the exact repository Node baseline.

## Official compatibility review

- Playwright 1.57 changed the bundled Chromium distribution to Chrome for Testing.
- Playwright 1.58 removed `_react`, `_vue`, `:light` selectors and `browserType.launch({ devtools })`.
- The deterministic validator scans all Playwright configs and E2E TypeScript files for those removed APIs.
- No removed API was found, so no selector or product-test rewrite was required.

## Config and discovery preservation

- Configs compared: `13`.
- Discovered tests compared: `24`.
- Every config file hash, test title, test count and test-file count is identical before and after migration.

| Config                                    | Tests | Files | Config unchanged |
| ----------------------------------------- | ----: | ----: | :--------------: |
| `playwright.alerts.config.ts`             |     1 |     1 |       yes        |
| `playwright.broker-control.config.ts`     |     1 |     1 |       yes        |
| `playwright.dashboard.config.ts`          |     9 |     9 |       yes        |
| `playwright.device-agent-fleet.config.ts` |     1 |     1 |       yes        |
| `playwright.disaster-recovery.config.ts`  |     1 |     1 |       yes        |
| `playwright.local-auth.config.ts`         |     3 |     2 |       yes        |
| `playwright.nodes.config.ts`              |     1 |     1 |       yes        |
| `playwright.observability.config.ts`      |     1 |     1 |       yes        |
| `playwright.production.config.ts`         |     2 |     1 |       yes        |
| `playwright.rendered-reports.config.ts`   |     1 |     1 |       yes        |
| `playwright.reports.config.ts`            |     1 |     1 |       yes        |
| `playwright.security.config.ts`           |     1 |     1 |       yes        |
| `playwright.sessions.config.ts`           |     1 |     1 |       yes        |

## Deterministic lockfile changes

| Package            | Before   | After    |
| ------------------ | -------- | -------- |
| `@playwright/test` | `1.55.0` | `1.62.0` |
| `playwright`       | `1.55.0` | `1.62.0` |
| `playwright-core`  | `1.55.0` | `1.62.0` |

## Browser installation evidence

The exact branch installed Chromium with `npx playwright install --with-deps chromium`.

```text
Playwright version: 1.62.0
  Browsers:
    /home/runner/.cache/ms-playwright/chromium-1234
    /home/runner/.cache/ms-playwright/chromium_headless_shell-1234
    /home/runner/.cache/ms-playwright/ffmpeg-1011
  References:
    /home/runner/work/nexolab-platform/nexolab-platform/node_modules/playwright-core
```

Existing configs continue to retain screenshots, traces, videos, HTML reporters, result directories, timeouts and single-worker behavior because no config file changed.

## Runtime and offline impact

`@playwright/test` remains development-only. Browser binaries are CI/development artifacts and are not part of NEXOLAB production containers or the offline runtime bundle. No mandatory network request, CDN, telemetry service or production external API was added.

Repository-native Prettier was applied to the permanent migration artifacts before exact-head verification.

## Rollback

Revert the focused Issue #254 squash merge, or restore the previous `package.json` and `package-lock.json`, run `npm install --no-audit`, remove cached Playwright browsers with `npx playwright uninstall --all`, reinstall the prior Chromium revision with `npx playwright install --with-deps chromium`, then rerun CI, every browser acceptance workflow and Offline Bundle. No database, persistent-volume, Raspberry Pi or hardware rollback is involved.
