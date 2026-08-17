# Isolated Work Package development with Git worktrees

NEXOLAB uses focused branches and pull requests. Git worktrees let several independent Work Packages exist at the same time without switching or stashing the main checkout.

This workflow adds no paid service and no runtime dependency. It uses Git, PowerShell, the existing repository verification script, and optionally GitHub CLI when it is already installed.

## Why use it

Use a separate worktree when:

- Codex or a developer is implementing a focused GitHub Issue while another task is already open locally;
- a review/fix needs to happen without disturbing the current checkout;
- multiple independent Work Packages may be active in parallel;
- you want to preserve one clean checkout of `main`.

Do not use worktrees to bypass the one-issue/one-focused-PR rule. Every worktree still owns one branch and one scoped outcome.

## Create a worktree

From the main NEXOLAB checkout:

```powershell
./scripts/new-work-package.ps1 -Issue 494 -DryRun
```

The dry run shows the planned branch and path without changing Git state.

Create it:

```powershell
./scripts/new-work-package.ps1 -Issue 494
```

If GitHub CLI is authenticated, the helper attempts to use the Issue title to build a readable branch/path name. Otherwise it falls back to a stable `work-package` name. You can always provide a title explicitly:

```powershell
./scripts/new-work-package.ps1 -Issue 494 -Title "device simulator fault scenarios"
```

To also install frontend dependencies in the new checkout:

```powershell
./scripts/new-work-package.ps1 -Issue 494 -InstallDependencies
```

By default the helper fetches `origin/main` first so a new branch starts from the latest remote baseline. Use `-NoFetch` only when intentionally working without network access.

## Safe defaults

The helper intentionally refuses to continue when:

- the target local branch already exists;
- the matching `origin/...` branch already exists;
- the target worktree directory already exists.

It never deletes, resets, force-checks-out, or reuses an existing worktree implicitly.

## Work inside the isolated checkout

Change directory to the path printed by the helper, then inspect the Issue and repository state before editing.

Run the smallest useful verification first. Examples:

```powershell
./scripts/verify-project.ps1 -Component Frontend -SkipBuild
./scripts/verify-project.ps1 -Component Telemetry
./scripts/verify-project.ps1 -Component DeviceAgent
```

Before publishing a focused PR, run the required broader verification for the Work Package. For a cross-cutting change:

```powershell
./scripts/verify-project.ps1 -Component All
```

Software verification does not replace real hardware, offline, backup/restore, or controlled-site acceptance evidence when those are required by the Work Package.

## Publish

From the isolated worktree:

```powershell
git status
git add <scoped-files>
git commit -m "<type>: <focused change>"
git push -u origin HEAD
```

If GitHub CLI is available:

```powershell
gh pr create --fill
```

Keep the PR focused on the Issue that owns the worktree.

## Remove after merge

Return to the main checkout first. Then remove the linked worktree using the exact path printed during creation:

```powershell
git worktree list
git worktree remove "<worktree-path>"
git branch -d "<branch-name>"
git worktree prune
```

Do not use force removal unless you have explicitly inspected and accepted the loss of uncommitted work.

## Default directory layout

For a main checkout such as:

```text
.../GitHub/nexolab-platform
```

the helper creates siblings under:

```text
.../GitHub/nexolab-worktrees/
```

Example:

```text
GitHub/
├─ nexolab-platform/                  # clean/main checkout
└─ nexolab-worktrees/
   ├─ 494-dev-productivity/
   ├─ 501-device-simulator/
   └─ 508-alert-recovery/
```

Each linked worktree shares the same Git repository history while keeping its own working files, index, and checked-out branch.
