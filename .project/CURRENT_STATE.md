# NEXOLAB Current State

Updated: 2026-08-22

## Repository baseline

Repository `main` is `6d223415deebf1a44bb52ba4fcaa3c5db9b03697`, the GREEN squash merge of PR #643 for Issue #633.

Issue #633 — **Stop isolated frontend candidate after successful Raspberry Pi deployment** — is complete and closed `status:done`.

Final Issue #633 evidence:

- PR #643 final head: `5d1f1f82ad555b68cab8ce9205283cf939d3be09`;
- merge SHA: `6d223415deebf1a44bb52ba4fcaa3c5db9b03697`;
- exact-head Core CI run `32564575388`: PASS, including standalone Raspberry Pi runtime contracts, formatting, lint, typecheck, tests and production build;
- all existing P1/P2 inline review threads: resolved;
- requested fresh Codex automated review could not run because the code-review usage limit was reached; Team Lead fresh review of the exact final diff found no remaining merge-blocking finding;
- candidate cleanup uses exact PID/process-group ownership, startup gating, PGID handshake, bounded TERM → KILL escalation, zombie-aware liveness and liveness checks before Bash `wait`;
- Bash built-in `wait` is not globally overridden;
- production Dashboard process matching or port/bind semantics were not broadened.

Real Raspberry Pi post-deployment verification for the merged #633 behavior remains **hardware/runtime unverified** because `nexolab-edge-01` is offline. This is not software acceptance evidence and is not represented as such.

Production remains intentionally deployed from source `6e387485b68fb862d9f82ae7f6000b1f5b672764` using immutable frontend release `runtime/frontend-releases/6e387485b68fb862d9f82ae7f6000b1f5b672764-20260820T214127Z`, BUILD_ID `wb6SYt8RD2_XAcyPcyZP2`. No #633 deployment/site cutover was performed.

## Current planning boundary

There is **no active product Work Package** while Issue #644 performs the state-only post-merge reconciliation. The next product Work Package must be selected only by a fresh GitHub Ready audit after #644 merges.

Known unresolved lanes that must remain visible during that audit:

- #618 — independent Saved Dashboard CSV browser-download reliability lane;
- #607 — dual RS-485 KK1/KK2 software architecture prerequisite before #589;
- #589 — blocked on #607;
- #590 — blocked on #589;
- #585 — blocked pending explicit physical W2 / Unit 201 handback confirmation;
- #444 — `status:needs-validation`, priority critical: LOCAL_LAN user-administration API acceptance;
- #245 — `status:needs-validation`, priority critical: standalone loopback-only Raspberry Pi acceptance;
- #200 — hardware-validation lane: physical RS-485 topology, stable adapter paths, Unit IDs, termination/biasing, latency and safe polling envelope;
- #201 — `status:needs-validation`: LE-01MP restart/power-cycle evidence;
- #202 — hardware-validation lane: XJP60D portability, representative KK2 evidence and Unit ID 115 presence/absence;
- #189 — `status:blocked`: actual-host backup/restore/rollback/power-loss recovery evidence.

Security maintenance remains time-bounded: Issue #598 follow-up tracks four temporary `CVE-2026-14456` exceptions that expire **2026-08-26** and must be removed earlier if a fixed Debian package becomes available or the reachability assumptions change.

## Safety boundaries

`LOCAL_LAN`, offline-first runtime and read-only industrial boundaries remain unchanged. No Modbus/controller write, hardware write, production/site cutover, persistent-data deletion, Docker named-volume deletion, secret/billing/DNS mutation or mandatory cloud runtime dependency is authorized.
