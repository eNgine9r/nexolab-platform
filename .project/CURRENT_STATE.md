# NEXOLAB Current State

Updated: 2026-08-21

## Repository baseline

Repository `main` is `7bb2115ef739daf2406c71110162b6d68c713f95`, the GREEN state-only reconciliation merge of PR #642 after completion of Issue #606.

Issue #606 — **Add read-only LOCAL_LAN equipment discovery and adoption inbox** — is complete and closed `status:done`. Its final software source head `83abc9b4a0056a2709c33a627b203785eeefff79` passed 22/22 exact-head workflows before squash merge in PR #632. Hardware/LAN acceptance remains anchored to `804d0b44045a5099c59149c87b70cbf63ca047f8` with bounded TCP-connect-only evidence and application payload bytes `0`.

Production remains intentionally deployed from source `6e387485b68fb862d9f82ae7f6000b1f5b672764` using immutable frontend release `runtime/frontend-releases/6e387485b68fb862d9f82ae7f6000b1f5b672764-20260820T214127Z`, BUILD_ID `wb6SYt8RD2_XAcyPcyZP2`.

## Active Work Package — Issue #633

Issue #633 — **Stop isolated frontend candidate after successful Raspberry Pi deployment** — is active `status:in-progress` in branch `fix/633-frontend-candidate-cleanup` with PR #643.

Final software implementation boundary before this state checkpoint is `24390ea3fa490a90fb4aa964f17191e12af53b14`.

Implemented behavior:

- isolated frontend candidate starts in its own session/process group;
- a parent/child startup gate prevents the candidate from executing `setsid` or Next.js until the parent has published the exact background PID;
- the child also stops waiting if the deployment parent disappears before gate release, preventing an untracked candidate from escaping during the `$!` publication window;
- after gate release, the deployment publishes the PGID only after a `ps` handshake confirms the tracked PID is the isolated group leader;
- if cleanup runs before PGID publication, it re-checks the exact tracked PID: an already-established candidate group is terminated as a group; otherwise only the exact tracked PID is terminated;
- established candidate groups use bounded TERM → KILL cleanup;
- zombie-only group members are classified as terminated rather than executable work;
- EXIT cleanup failures are surfaced while preserving the original deployment failure code;
- candidate port `3100` is verified free before backend/activation work proceeds;
- the candidate-cleanup regression module is executed by the standalone runtime CI entry point;
- broad `pkill`/process-name matching is not introduced and production Dashboard process semantics are unchanged.

Verification status:

- initial exact-head `87afc1116bbb393c748d9bd666cbcbc1da959969` Core CI run `32514504593`: PASS;
- exact-head `08884615decb4d55a9c4faabaea26d32d5e6a650` Core CI run `32517056093`: PASS;
- exact-head `a7d91af104474c0fec604767a818bd9cfb6a27dd` Core CI run `32519957941`: PASS, including the cleanup regression suite through the standalone runtime contract;
- review findings through the handshake-window, fixture-isolation, EXIT-reporting and CI-coverage gaps are addressed in software through `24390ea3...`;
- this state checkpoint records the final software behavior; final exact-head CI and fresh review on the state-checkpoint head remain the merge gates;
- real Raspberry Pi post-deployment verification is **hardware/runtime unverified** because `nexolab-edge-01` is currently offline;
- no production deployment/site cutover has been authorized or performed by #633.

## Current planning boundary

Issue #633 is the single active Work Package. Do not select it again as Ready while PR #643 is in its final exact-head CI/review gate.

Known queue after #633:

- #618 — independent Saved Dashboard CSV browser-download reliability lane;
- #607 — queued dual RS-485 KK1/KK2 software architecture before #589;
- #589 — blocked on #607;
- #590 — blocked on #589;
- #585 — blocked pending explicit physical W2 / Unit 201 handback confirmation.

Required maintenance/evidence lanes remain explicit:

- #598 follow-up — four temporary `CVE-2026-14456` exceptions expire **2026-08-26**; remove earlier if Debian publishes a fixed package or QUIC runtime reachability changes;
- #444 — `status:needs-validation`, priority critical: LOCAL_LAN user-administration API acceptance;
- #245 — `status:needs-validation`, priority critical: standalone loopback-only Raspberry Pi acceptance;
- #200 — hardware-validation lane: physical RS-485 topology, stable adapter paths, Unit IDs, termination/biasing, latency and safe polling envelope remain unverified beyond retained narrow pilot evidence;
- #201 — `status:needs-validation`, priority high: approved LE-01MP restart/power-cycle boundary;
- #202 — hardware-validation lane: extended XJP60D portability, KK2 representative evidence, and actual Unit ID 115 presence/absence remain unverified;
- #189 — `status:blocked`, priority high: actual-host backup/restore/rollback/power-loss recovery evidence.

## Safety boundaries

`LOCAL_LAN`, offline-first runtime and read-only industrial boundaries remain unchanged. No Modbus/controller write, hardware write, production/site cutover, persistent-data deletion, Docker named-volume deletion, secret/billing/DNS mutation or mandatory cloud runtime dependency is authorized.
