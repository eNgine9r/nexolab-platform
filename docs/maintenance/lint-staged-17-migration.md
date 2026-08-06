# lint-staged 17 migration

Updated: 2026-08-06
Issue: #252
Profile: `LOCAL_LAN`

## Decision

Upgrade the development-only pre-commit tool from:

```text
lint-staged 16.4.0
```

to:

```text
lint-staged 17.3.0
```

The version is declared as `^17.3.0` and resolved exactly in `package-lock.json`.

## Upstream compatibility review

Primary references:

- https://github.com/lint-staged/lint-staged/blob/main/MIGRATION.md
- https://github.com/lint-staged/lint-staged/releases/tag/v17.3.0

The v17 migration boundary requires:

- Node `22.22.1` or newer;
- Git `2.32.0` or newer;
- an explicit `yaml` dependency only when configuration is stored as YAML.

NEXOLAB already uses:

```text
Developer and GitHub Actions Node: 22.23.1
Package engine: >=22.22.1 <23 || >=24 <25
Configuration source: package.json
Husky hook: npx lint-staged
```

No YAML lint-staged configuration exists, so no optional YAML package is added.

## Preserved production configuration

The migration does not alter file globs or task order:

```json
{
  "*.{js,jsx,ts,tsx,mjs,cjs}": ["eslint --fix", "prettier --write"],
  "*.{json,md,mdx,css,yml,yaml}": ["prettier --write"]
}
```

The JavaScript and TypeScript path continues to run ESLint before Prettier. The Husky hook remains unchanged:

```text
npx lint-staged
```

## Durable integration harness

`scripts/tests/lint-staged-v17.mjs` creates disposable Git repositories and verifies:

1. the actual repository ESLint → Prettier configuration formats and stages a TypeScript file;
2. a partially staged file hides unstaged content from the task and restores it after success;
3. a task that modifies a file and exits non-zero restores the original index and unstaged worktree diff;
4. an empty staged-file set exits successfully without mutation;
5. Node and Git satisfy the v17 floors;
6. the manifest version, globs, command order and Husky hook remain exact.

The harness operates only in temporary directories. It does not mutate the developer's active index, stash or working tree.

The full repository `npm test` command includes this harness so future CI runs retain the migration acceptance boundary.

## Verified preparation evidence

Preparation workflow run `31096023579` regenerated the lockfile under the exact repository Node baseline and completed successfully.

```json
{
  "git": "git version 2.54.0",
  "lintStaged": "17.3.0",
  "node": "22.23.1",
  "verified": ["production-eslint-prettier-order", "partial-stage-success", "failure-rollback", "empty-stage"]
}
```

The same run completed repository formatting, lint, typecheck, the full test suite and production build before publishing the permanent files.

The focused preparation artifact was recorded with SHA-256:

```text
0265ae89f4c56827171350b6d0dfef79b225048e72e5f9b80f103a828d0b910b
```

## Lockfile graph audit

The lockfile resolves `lint-staged 17.3.0` and updates its direct development-only graph to:

- `picomatch ^4.0.5`;
- `string-argv ^0.3.2`;
- `tinyexec ^1.2.4`.

The v16-only CLI rendering and YAML graph is removed, including `commander`, `listr2` and the mandatory transitive `yaml` entry previously pulled by lint-staged. This matches the v17 package contract because NEXOLAB stores configuration in `package.json`.

No production dependency is changed. The focused comparison against the verified `main` baseline contains exactly four permanent files.

## Runtime and offline impact

- lint-staged remains a development-only dependency;
- no production dependency is added or changed;
- no application source, API, database or acquisition behavior changes;
- no CDN, remote font, cloud API or paid runtime service is introduced;
- no Modbus or hardware path changes;
- the production `npm prune --omit=dev` closure must remain unchanged;
- Offline Bundle disconnected startup and update/rollback evidence remains a required merge gate.

## Rollback

Restore the previous manifest and lockfile pair:

```text
lint-staged ^16.4.0
resolved lint-staged 16.4.0 graph
```

Then remove the v17-specific integration harness and this document, restore the previous `npm test` command, and rerun:

```text
format → lint → typecheck → tests → production build → Offline Bundle
```

Rollback requires no database migration, volume deletion, hardware action or production cutover.
