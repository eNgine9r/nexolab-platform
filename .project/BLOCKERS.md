# NEXOLAB Blockers

Updated: 2026-08-22

## Current Work Package boundary — Issue #648

Issue #648 — **Prove Issue #646 state-only fast lane after CI merge** — is active in branch `chore/648-prove-state-fast-lane`.

Its diff is intentionally restricted to the four canonical `.project` state files. No product/runtime, dependency, migration, deployment, hardware or Modbus behavior is in scope.

The purpose of #648 is to prove the new state-only CI path introduced by Issue #646 / PR #647:

- `Change impact` must classify the exact diff as `state_only`;
- `State integrity` must pass;
- `Quality and build` must be skipped;
- Node setup, `npm ci`, repository-wide lint/Vitest and Next production build must not run;
- `NEXOLAB Merge Gate` must pass from the state-only lane;
- no external product/runtime workflow should be required by the exact four-file state diff.

## Issue #646 — repository implementation complete, settings acceptance pending

PR #647 merged GREEN into `main` as `19c053e0f197a4ccd925af19a6c40881ec56d348`.

Exact implementation evidence:

- final PR head `623a72a0fdec8b8ddb15c5a7e145d0ba60a6a135`;
- Core CI `32567703388`: PASS;
- Telemetry service `32567703424`: PASS;
- `NEXOLAB Merge Gate`: PASS after waiting for the external exact-head workflow;
- deterministic `npm ci`, formatting, lint, typecheck, tests and production build: PASS.

The only remaining #646 acceptance after #648 is repository branch protection.

GitHub currently reports `main` as `protected: false` and required status-check enforcement off. The connected GitHub tool surface does not expose a branch-protection/rules mutation action. This is a **soft access blocker** for the repository-settings acceptance criterion only. It must not block independent Ready Sprint work after the fast-lane proof is complete.

Do not report technical branch protection as complete before settings are actually changed and verified.

## Security maintenance — CVE-2026-14456 deadline

Issue #598 is closed, but its four exact temporary `CVE-2026-14456` exceptions remain active in `security/vulnerability-exceptions.json` and expire on **2026-08-26**.

Owner: `platform-security`.

Required maintenance action: re-check Debian/fixed-package availability and remove the exceptions immediately when a fixed package becomes available, or review before 2026-08-26. If the exceptions expire unchanged, the Container Supply Chain policy gate is expected to fail closed. Any introduction of a QUIC/HTTP3 listener also invalidates the current reachability justification.

## Independent product and validation lanes

- #618 — Saved Dashboard CSV browser-download reliability remains independent.
- #607 — dual RS-485 KK1/KK2 software isolation remains queued before #589; physical bus cutover is not approved.
- #589 — blocked until #607 establishes the dual-bus architecture.
- #590 — blocked on #589 persisted cadence/capacity contract.
- #585 — blocked until the Product Owner confirms physical W2 / Unit 201 handback and explicitly approves any required physical action.
- #444 — `status:needs-validation`, priority critical: LOCAL_LAN user-administration API acceptance remains open.
- #245 — `status:needs-validation`, priority critical: actual standalone loopback-only Raspberry Pi acceptance remains open.
- #200 — physical RS-485 topology and safe polling envelope remain hardware-unverified beyond retained evidence.
- #201 — approved LE-01MP restart/power-cycle evidence remains pending.
- #202 — representative KK1/KK2 XJP60D portability and Unit ID 115 presence/absence remain hardware-unverified.
- #189 — backup/restore/rollback/power-loss recovery remains blocked on controlled actual-host evidence.

## Non-blocking maintenance

- #615 tracks the authenticated-dashboard generated Compose project-name defect; explicit lowercase overrides remain the local workaround.
- Production remains deployed from `6e387485b68fb862d9f82ae7f6000b1f5b672764` until a separately authorized deployment/cutover.

## Safety boundaries

No Modbus/controller write, hardware write, product persistent-data deletion, Docker named-volume deletion, secret/billing/DNS mutation, production/site cutover or mandatory cloud runtime dependency is authorized by Issue #648.
