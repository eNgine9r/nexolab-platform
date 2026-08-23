# NEXOLAB Current State

Updated: 2026-08-23

## Current Sprint

`CHART-RELIABILITY-1` is active under Epic #450 — canonical chart interaction and reliability.

Active Work Package: Issue #415 — **Add left-button drag panning to canonical NEXOLAB charts** on branch `feat/415-canonical-left-drag-pan`.

The prior `ENGINEERING-HARDENING-1` queue was exhausted with no independent `status:ready` item. Product Owner continuation on 2026-08-23 selected the recommended Chart reliability / operator UX direction rather than silently unblocking hardware/validation work.

## Durable baselines

Accepted product source: `286a219611f95413b5580d8099a7c5665416d1ad`.

Deployed product source: `6e387485b68fb862d9f82ae7f6000b1f5b672764`.

The Raspberry Pi Git checkout is synchronized with current GitHub `main`, but the running Dashboard remains pinned to the immutable deployed release above. Repository synchronization is not a deployment or cutover.

## Issue #415 architecture boundary

Current installed ECharts already provides primary-button drag panning through `dataZoom.inside` / `RoamController`: middle/right mousedown is rejected, primary drag emits `pan`, and ECharts owns `grab`/`grabbing` cursor behavior.

NEXOLAB must not duplicate that pan implementation. The focused integration change is to:

- make the native `moveOnMouseMove` / wheel behavior explicit in the canonical adapter contract;
- freeze NEXOLAB Exact Inspector callbacks while the primary-button native pan is active;
- resume normal cursor inspection after release, including a lost-mouseup recovery path;
- verify the same renderer host/canvas remains mounted;
- verify zoom/pan/reset does not request a new history window or mutate acquisition state.

No route-local pan implementation is permitted.

## Recently completed security maintenance

Issue #660 / PR #661 is merged. Four exact OpenSSL QUIC `CVE-2026-14456` HIGH/no-fix exceptions remain reviewed only through **2026-08-30**.

Final exact-head Container Supply Chain run `32626324921` was GREEN. Remove the decisions earlier if a supported fixed Debian Trixie package appears, the exact findings disappear, QUIC reachability changes, or severity becomes Critical.

## Raspberry Pi and RS-485 boundary

The Remote Desktop/Raspberry Pi connector is online. Passive Issue #200 evidence confirms only one CP2104 RS-485 adapter is currently enumerated and the running Device Agent uses one `rs485-main` bus. Draft PR #659 remains intentionally unmerged because physical dual-bus/topology acceptance is incomplete.

Do not start a second Modbus master/scanner while the production Device Agent owns the bus. No Modbus write is permitted.

## Validation boundaries retained outside the active Sprint

- #444 — local-admin route is mounted in the current deployed runtime; full acceptance still needs an authorized administrator identity and local-user create/auth verification.
- #245 — standalone loopback acceptance still requires an explicitly approved network-isolation/reboot/cutover exercise.
- #200 — physical topology, second adapter, Unit 115 reality and electrical observations remain hardware-unverified.
- #201 — approved restart/power-cycle discontinuity evidence remains pending.
- #202 — representative KK1/KK2 and Unit 115 physical evidence remains pending.
- #585 — W2 / Unit 201 physical handback still requires Product Owner confirmation/approval.
- #189 — controlled actual-host recovery/power-loss evidence remains outstanding.
- #646 — repository branch protection/rules remain a soft settings-access blocker.

## Runtime and offline boundary

Issue #415 is presentation-only. It must not change telemetry acquisition, persistence, polling cadence, WebSocket topology, offline operation, authentication, database schema, deployment or device configuration.

Core NEXOLAB runtime remains LOCAL_LAN/offline-first with no mandatory public internet, paid service, CDN, remote font or external runtime API.

## Safety boundaries

No Modbus/controller write, hardware write, product persistent-data deletion, Docker named-volume deletion, secret/billing/DNS mutation or production/site cutover is authorized by Issue #415.
