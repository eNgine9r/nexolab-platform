# GitHub Actions runtime inventory

Issue: #235  
Parent: #205  
Baseline: `e1e0e2311d1818157e3326ae9ca67adbf24813d5`

## Purpose

Inventory every `actions/checkout` and `actions/setup-node` use before changing action major versions. The upgrade must preserve least privilege, trusted/untrusted checkout boundaries, explicit refs, credential persistence, fetch depth and cache behavior.

## Initial repository search

Current `main` contains widespread `actions/checkout@v4` usage across CI, browser acceptance, RS-485 evidence, supply-chain, observability, disaster-recovery, offline-auth, MQTT and fleet workflows. `actions/setup-node@v4` is used by CI and Node-based browser/acceptance workflows.

## Required classification

For every workflow, record:

- trigger type: `push`, `pull_request`, `pull_request_target`, `workflow_run`, `workflow_dispatch`, schedule or release;
- top-level and job-level permissions;
- checkout ref and repository;
- `persist-credentials` behavior;
- `fetch-depth` behavior;
- whether untrusted pull-request code can execute with elevated context;
- setup-node version source and cache settings;
- representative verification gate after upgrade.

## Security rules

- Never execute untrusted pull-request code with write tokens or repository secrets.
- Keep `pull_request_target` and `workflow_run` checkout behavior fail-closed.
- Do not broaden `GITHUB_TOKEN` permissions.
- Preserve explicit refs and detached exact-source checkouts used by evidence and packaging workflows.
- Preserve deterministic npm cache and lockfile installation behavior.

## Rollback

Rollback is a focused revert of the action-major update commit, restoring the previous `actions/checkout@v4` and `actions/setup-node@v4` references without changing product code or workflow logic.
