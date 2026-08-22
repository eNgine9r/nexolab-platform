# NEXOLAB Current State

Updated: 2026-08-22

## Repository baseline

Repository `main` is `7bb2115ef739daf2406c71110162b6d68c713f95`, the GREEN state-only reconciliation merge of PR #642 after completion of Issue #606.

Issue #606 — **Add read-only LOCAL_LAN equipment discovery and adoption inbox** — is complete and closed `status:done`. Its final software source head `83abc9b4a0056a2709c33a627b203785eeefff79` passed 22/22 exact-head workflows before squash merge in PR #632. Hardware/LAN acceptance remains anchored to `804d0b44045a5099c59149c87b70cbf63ca047f8` with bounded TCP-connect-only evidence and application payload bytes `0`.

Production remains intentionally deployed from source `6e387485b68fb862d9f82ae7f6000b1f5b672764` using immutable frontend release `runtime/frontend-releases/6e387485b68fb862d9f82ae7f6000b1f5b672764-20260820T214127Z`, BUILD_ID `wb6SYt8RD2_XAcyPcyZP2`.

## Active Work Package — Issue #633

Issue #633 — **Stop isolated frontend candidate after successful Raspberry Pi deployment** — is active `status:in-progress` in branch `fix/633-frontend-candidate-cleanup` with PR #643.

Latest software refinement before this state checkpoint is `0436c0a663d9d7416a487cb61a69626cf1f786dd`.

Implemented behavior:

- isolated frontend candidate starts in its own session/process group;
- a parent/child startup gate prevents the candidate from executing `setsid` or Next.js until the parent has published the exact background PID;
- the child stops waiting if the deployment parent disappears before gate release;
- after gate release, PGID publication occurs only after `ps` confirms the tracked PID is the isolated group leader;
- cleanup re-checks an unpublished PID for an already-established exact process group before exact-PID fallback;
- established candidate groups use bounded TERM → KILL cleanup;
- both exact-PID and process-group cleanup verify that the candidate is no longer live before invoking Bash `wait`, so a process stuck in uninterruptible I/O cannot create an indefinite deployment hang after the bounded TERM/KILL windows;
- Bash `wait` is not globally overridden; normal shell wait semantics remain unchanged outside the candidate cleanup path;
- zombie-only group members are classified as terminated rather than executable work;
- EXIT cleanup failures are surfaced while preserving the original deployment failure code;
- candidate port `3100` is verified free before backend/activation work proceeds;
- the candidate-cleanup regression module is executed by the standalone runtime CI entry point and asserts that no live candidate reaches `wait`;
- broad `pkill`/process-name matching is not introduced and production Dashboard process semantics are unchanged.

Verification status:

- initial exact-head `87afc1116bbb393c748d9bd666cbcbc1da959969` Core CI run `32514504593`: PASS;
- exact-head `08884615decb4d55a9c4faabaea26d32d5e6a650` Core CI run `32517056093`: PASS;
- exact-head `a7d91af104474c0fec604767a818bd9cfb6a27dd` Core CI run `32519957941`: PASS;
- exact-head `b3420a3be7b1b7b3060d484ca30c0aa4fa4c21ee` Core CI run `32521673945`: PASS;
- exact-head state checkpoint `c28736864d91f521a02101a3d2ca7e8448dea3f1` Core CI run `32523415155`: PASS;
- exact-head `7bf2604c4b823cc4f3643c230dc58b16624384c3` Core CI run `32563481255`: PASS;
- fresh code review on `7bf2604c...` identified an unnecessary global Bash `wait` override in the liveness helper; `0436c0a6...` removes that global semantic change while preserving the structural liveness guards already regression-tested in the deployment cleanup;
- final exact-head CI and fresh review on the new state-checkpoint head remain the merge gates;
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

- #598 follow-up — four temporary `CVE-2026-14456` exceptions expire **2026-08-26**;
- #444 — `status:needs-validation`, priority critical: LOCAL_LAN user-administration API acceptance;
- #245 — `status:needs-validation`, priority critical: standalone loopback-only Raspberry Pi acceptance;
- #200 — hardware-validation lane: physical RS-485 topology, stable adapter paths, Unit IDs, termination/biasing, latency and safe polling envelope remain unverified beyond retained narrow pilot evidence;
- #201 — `status:needs-validation`, priority high: approved LE-01MP restart/power-cycle boundary;
- #202 — hardware-validation lane: extended XJP60D portability, KK2 representative evidence, and actual Unit ID 115 presence/absence remain unverified;
- #189 — `status:blocked`, priority high: actual-host backup/restore/rollback/power-loss recovery evidence.

## Safety boundaries

`LOCAL_LAN`, offline-first runtime and read-only industrial boundaries remain unchanged. No Modbus/controller write, hardware write, production/site cutover, persistent-data deletion, Docker named-volume deletion, secret/billing/DNS mutation or mandatory cloud runtime dependency is authorized.
