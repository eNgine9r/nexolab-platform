# jsdom 30 migration evidence

## Scope

Issue #253 updates only the direct `jsdom` development dependency and its deterministic npm lockfile closure. Vitest, Testing Library, React, TypeScript, Playwright and production dependencies are unchanged.

## Runtime compatibility

- Repository Node baseline: `22.23.1`.
- Installed jsdom: `30.0.0`.
- jsdom engine requirement: `{"node": "^22.22.2 || ^24.15.0 || >=26.0.0"}`.
- Installation and the focused DOM contract ran on the exact repository Node baseline.

## Observable test-environment contract

`src/test/jsdom-environment.test.ts` locks the behavior NEXOLAB relies on:

- URL and history resolution against the configured test origin;
- local/session storage isolation;
- focus and active-element semantics;
- form submission, successful controls and cancellation;
- bubbling, custom-event detail and cancellation;
- layout-independent DOM behavior;
- no implicit external-resource fetch when DOM elements are attached.

No custom resource loader, script execution option or hidden network fixture was added.

## Deterministic lockfile changes

| Package                                           | Before   | After    |
| ------------------------------------------------- | -------- | -------- |
| `@asamuzakjp/css-color`                           | `5.1.11` | `6.0.5`  |
| `@asamuzakjp/css-color/node_modules/lru-cache`    | `absent` | `11.5.2` |
| `@asamuzakjp/dom-selector`                        | `7.1.1`  | `8.3.2`  |
| `@asamuzakjp/dom-selector/node_modules/lru-cache` | `absent` | `11.5.2` |
| `@asamuzakjp/generational-cache`                  | `1.0.1`  | `absent` |
| `@asamuzakjp/nwsapi`                              | `2.3.9`  | `absent` |
| `jsdom`                                           | `29.1.1` | `30.0.0` |
| `jsdom/node_modules/whatwg-url`                   | `absent` | `17.1.0` |
| `undici`                                          | `7.29.0` | `8.10.0` |

## Runtime and offline impact

`jsdom` remains a development-only dependency. No production dependency, container runtime contract, offline bundle manifest or application source import changes. The production build must remain byte-closure independent of jsdom.

## Rollback

Revert the focused Issue #253 squash merge, or restore the previous `package.json` and `package-lock.json` from the parent commit, run `npm install --no-audit`, then run the dependency-policy validator, full test suite and production build. No database, persistent-volume or hardware rollback is involved.
