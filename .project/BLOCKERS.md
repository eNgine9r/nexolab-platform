# NEXOLAB Blockers

Updated: 2026-08-05

## Issue #269 — operator-safe Settings workspace

PR #270 was squash-merged into `main` as `5aa2252a6c20874dcc3d975c19fee441d20600a8` after current-head, mergeability, four-GREEN-check and clean-review audits. Issue #269 has no remaining software blocker.

## Issue #273 — operator-safe local Cameras workspace

No repository-access or architecture blocker prevents the truthful software slice from starting.

Verified repository boundary:

- `/cameras` is a placeholder;
- Overview contains six hardcoded illustrative scenes labelled `LIVE`;
- no camera inventory API or persisted camera table exists;
- no ONVIF discovery, snapshot proxy or RTSP/WebRTC/HLS browser gateway exists;
- no verified physical camera inventory exists in repository state.

The Ready slice is constrained to:

- typed browser-safe camera inventory;
- sanitized endpoint metadata;
- explicit unconfigured, configured-unverified, online, offline, unavailable and invalid states;
- removal of fabricated `LIVE` evidence from Overview;
- authenticated read-only `/cameras` workspace and canonical navigation;
- zero mutation controls and no unsupported media claims.

## Residual risks, not blockers

- A real `online` state cannot be claimed without a real read-only observation source.
- Browser clients cannot consume raw RTSP safely; no direct RTSP playback may be implied.
- Camera credentials must remain outside client-visible variables, UI, logs and screenshots.
- Physical cameras, ONVIF, RTSP, NVR and LAN/VPN access remain unverified.
- `/lockers` remains blocked pending concrete inventory and read-only protocol scope.
- Deferred toolchain Issues #252–#257 remain outside the page-completion sequence unless a concrete blocker appears.

## Explicitly unsupported and out of scope for Issue #273

- camera CRUD or database migration;
- ONVIF discovery;
- RTSP-to-WebRTC/HLS transcoding;
- recording, archive, playback timeline or retention;
- PTZ, microphone or speaker control;
- camera firmware/configuration writes;
- credentials or secret rotation;
- cloud video hosting;
- physical camera acceptance;
- doors, locks, Smart Lockers or unrelated pages;
- dependency upgrades and unrelated refactors;
- production/site cutover.

## Smart Lockers blocker

The `/lockers` page remains blocked until a concrete locker inventory, read-only protocol and operator workflow are defined. Do not invent production behavior or present demo controls as completed functionality.

## Hard blockers

Stop before:

- destructive database or persistent-volume operations;
- production/site cutover without explicit approval;
- Modbus, camera or other unsafe hardware writes;
- credential exposure or unauthorized secret rotation;
- materially different product or architecture choices;
- any operation that cannot preserve local laboratory data.

## Hardware and operational risks

- **#245:** software merged; actual standalone Raspberry Pi acceptance pending.
- **#189:** software recovery evidence verified; physical reboot, power-loss and media restore pending.
- **N-037:** Sharp compatibility override remains monitored.
- **N-023:** node health durability is not claimed equal to telemetry process-restart durability.
- **N-024:** rollback must preserve named volumes and spool compatibility.
- **N-025:** actual-host spool capacity evidence remains required.
- **N-032:** actual Raspberry Pi ARM64 archive/load/start/update/rollback remains unverified.
- **#200:** physical RS-485 topology hardware-blocked.
- **#201:** cumulative LE-01MP energy hardware-blocked.
- **#202:** extended XJP60D semantics hardware-blocked.

## Next Ready action

Open a focused draft Pull Request for Issue #273, implement the typed truthful camera domain and tests, then integrate `/cameras` and remove fabricated Overview `LIVE` evidence.
