# NEXOLAB Current State

Updated: 2026-08-05
Verified main baseline: `5aa2252a6c20874dcc3d975c19fee441d20600a8`
Active Work Package: Issue #273 — operator-safe local Cameras workspace
Branch: `feat/273-local-cameras-workspace`
Pull Request: #274 — draft Work Package
Parent Product Epic: Issue #260 — complete all NEXOLAB operator pages
Status confidence: high for merged Settings software, authenticated browser and disconnected-runtime evidence; physical Raspberry Pi, RS-485 and camera hardware remain explicitly unverified.

## Product route status

Implemented on merged `main`:

- `/` — Overview dashboard;
- `/nodes` — Nodes;
- `/sessions` — Test sessions;
- `/refrigeration` — Refrigeration equipment and canonical mutation workflows;
- `/alerts` — Alerts;
- `/reports` — Reports;
- `/energy` — verified LE-01MP Energy Monitoring;
- `/live` — verified universal telemetry explorer;
- `/equipment-layouts` — verified cross-asset catalog and read-only published-layout preview;
- `/equipment` — authenticated organization-wide Equipment and metrology registry;
- `/settings` — authenticated operator-safe organization context, sanitized runtime diagnostics and browser-local presentation preferences, merged through PR #270.

Remaining placeholder routes on merged `main`:

- `/cameras` — active Issue #273 / draft PR #274;
- `/lockers` — blocked pending concrete inventory and read-only protocol scope.

Optional toolchain migrations #252–#257 remain deferred unless they become a security, support or concrete product-delivery blocker.

## Issue #269 merged outcome

PR #270 was squash-merged as `5aa2252a6c20874dcc3d975c19fee441d20600a8` after the final audit confirmed:

- state head `9e6894c6c8011bc4fa906ec1137b6f4336a0f5a8` remained current and mergeable;
- all four state-head checks were GREEN;
- source/state diff was focused to 15 files;
- inline review threads and submitted reviews were zero;
- no dependency, lockfile, backend schema, Modbus or hardware-write change.

## Active Issue #273 boundary

Repository inventory confirms:

- `/cameras` is a pure placeholder;
- the Overview camera panel contains six hardcoded illustrative scenes labelled `LIVE`;
- no camera inventory API or persisted camera table exists;
- no ONVIF discovery, snapshot proxy or RTSP/WebRTC/HLS browser gateway exists;
- no physical camera inventory is verified in repository state.

PR #274 will therefore deliver a truthful local-first read-only workspace:

- typed camera inventory and sanitized endpoint metadata;
- explicit unconfigured, configured-unverified, online, offline, unavailable and invalid states;
- removal of fabricated `LIVE` evidence from Overview;
- authenticated `/cameras` shell with deterministic search and bounded filters;
- zero camera mutation controls, credentials or unsupported media claims.

## Runtime, offline and hardware evidence

```text
Settings software verified and merged; disconnected runtime verified; physical Raspberry Pi, RS-485, camera, ONVIF, RTSP and NVR evidence unverified
```

No camera configuration write, credential rotation, PTZ, recording, door/lock action or production/site cutover is permitted in Issue #273.

## Next action

Implement the typed truthful camera domain and focused tests first, then integrate `/cameras` and replace the fabricated Overview `LIVE` panel in PR #274.
