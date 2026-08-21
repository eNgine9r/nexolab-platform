# NEXOLAB Current State

Updated: 2026-08-21

## Repository baseline

Repository `main` is `dc2b130cbd0f9f6e84dcfec1dc8ee045b18ab8cc`, the GREEN squash merge of PR #632 for Issue #606.

Issue #606 — **Add read-only LOCAL_LAN equipment discovery and adoption inbox** — is complete and closed `status:done`.

Final software source head before squash merge: `83abc9b4a0056a2709c33a627b203785eeefff79`.

Final exact-head verification on `83abc9b4...` is **22/22 GREEN**, including:

- Core CI `32490226544`: PASS;
- Telemetry Service `32490226340`: PASS;
- Authenticated Dashboard Acceptance `32490226813`: PASS;
- Offline Bundle `32490226383`: PASS;
- Offline Auth Acceptance `32490226880`: PASS;
- Acquisition Scale Acceptance `32490226435`: PASS;
- Container Supply Chain `32490226447`: PASS;
- Observability `32490226480`: PASS;
- Capacity Release Gate `32490226536`: PASS;
- Device Agent Fleet Acceptance `32490226271`: PASS;
- all remaining browser, MQTT, disaster-recovery and reports workflows: PASS.

All final PR #632 P1/P2 review threads are resolved.

## Issue #606 product outcome

NEXOLAB now contains a bounded, read-only LOCAL_LAN equipment discovery workflow with persisted scan evidence, a review/adoption inbox, explicit administrative candidate actions, deterministic scope/change semantics, bounded cancellation and truthful scan metrics.

Discovery remains isolated from physical acquisition:

- only configured RFC1918/LOCAL_LAN CIDRs and allowed TCP ports are eligible;
- production discovery is TCP-connect-only;
- application payload bytes remain `0`;
- TCP 502 connect evidence is not a Modbus request;
- no automatic acquisition enrollment occurs;
- no Device Agent or AcquisitionRegistry mutation is performed by discovery;
- no credential guessing, unrestricted scanning, raw sockets or vulnerability scanning is introduced;
- no hardware write or site cutover is part of #606.

## Real Raspberry Pi / LOCAL_LAN evidence

Hardware/LAN acceptance is anchored to exact product head `804d0b44045a5099c59149c87b70cbf63ca047f8` and was Product Owner-authorized on 2026-08-21.

Evidence boundary:

- parent LAN: `172.18.48.0/21`;
- requested scope: five explicit /32 hosts;
- requested ports: TCP 502 and 8082;
- hosts considered: 5;
- probes/connect attempts: 10;
- application payload bytes: 0;
- responsive evidence: local NEXOLAB API `172.18.48.34:8082`;
- production containers healthy before and after;
- Raspberry Pi boot identity unchanged;
- baseline 10-second acquisition delta: physical requests `+74`, retries `+16`, bus busy `+7.615496 s`;
- discovery 10-second acquisition delta: physical requests `+64`, retries `+16`, bus busy `+7.067059 s`;
- no AcquisitionRegistry mutation, Modbus command, hardware write, credential attempt, deployment or site cutover occurred.

Post-acceptance software hardening through `83abc9b4...` changed only failure/cancellation/metrics handling. It did not broaden scan scope or add protocol payload, Modbus or hardware behavior, so the completed physical acceptance is not repeated.

## Production runtime boundary

Production remains intentionally deployed from source `6e387485b68fb862d9f82ae7f6000b1f5b672764` using immutable frontend release `runtime/frontend-releases/6e387485b68fb862d9f82ae7f6000b1f5b672764-20260820T214127Z`, BUILD_ID `wb6SYt8RD2_XAcyPcyZP2`.

The controlled 2026-08-21 LOCAL_LAN cutover is healthy. No #606 production deployment or cutover was performed by the #606 Work Package.

## Current planning boundary

There is **no active product Work Package** after completion of #606. Product Owner planning / Ready audit is the next decision point.

Known queue state:

- #633 — Ready/high: deterministically stop the isolated frontend candidate after successful Raspberry Pi deployment; **not started**;
- #618 — independent Saved Dashboard CSV browser-download reliability lane;
- #607 — queued dual RS-485 KK1/KK2 software architecture before #589;
- #589 — held behind #607;
- #590 — blocked on #589;
- #585 — blocked pending explicit physical W2 / Unit 201 handback confirmation.

Do not infer that #633 or any other item has been selected merely because it is Ready. The next Work Package will be chosen after the Product Owner reviews priorities.

## Safety boundaries

`LOCAL_LAN`, offline-first runtime and read-only industrial boundaries remain unchanged. No Modbus/controller write, hardware write, production/site cutover, persistent-data deletion, Docker named-volume deletion, secret/billing/DNS mutation or mandatory cloud runtime dependency is authorized.
