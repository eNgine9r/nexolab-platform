# NEXOLAB Current State

Updated: 2026-08-15

## Canonical product/runtime baseline

Current product/runtime `main` is
`d69b11aed67812fbae65c1a63b49803a93f317d0`.

That baseline includes Issue #457 / PR #460 — graph-first Live Data composition —
squash-merged from final exact verified head
`56ad319c355bdd1725021d5862beed3b1f3ccf6d`.

Final #457 software/browser/offline verification:

- CI `31883658826`: PASS;
- Authenticated Dashboard Acceptance `31883658924`: 14/14 PASS;
- Refrigeration Browser Acceptance `31883658836`: PASS;
- disconnected Offline Bundle `31883658920`: PASS.

Classification remains **software/browser/offline verified; Raspberry Pi operator
acceptance pending**. Physical Raspberry Pi completion is not claimed.

## State-only reconciliation — Issue #462

Issue #462 reconciles `.project/**` after #457 / PR #460 merged. It changes no
product/runtime code and records the GitHub facts above plus the newly Ready next
software Work Package.

## Next Ready software Work Package — Issue #461

Issue #461 — **Add reusable hierarchical TelemetryPointSelector** — is open,
assigned and `status:ready`. Its dependency on #457 is resolved.

The Work Package is intentionally limited to a reusable hierarchy/read-model and
selector primitive. Live Dashboard migration and other route integrations remain
separate follow-up work under Epic #450.

## Independent hardware lane — Issue #289

Issue #289 remains open and `status:in-progress` for controlled Raspberry Pi/
RS-485 acquisition-scale and truthful-state acceptance. Software, browser and
offline evidence from #457 does not satisfy that physical hardware matrix.

Other previously classified physical evidence remains separate, including KK2 /
Unit 115 field retest, refrigeration perceived-latency acceptance and version-
management Raspberry Pi acceptance.

## Safety boundary

LOCAL_LAN and offline-first requirements remain unchanged. No Modbus/hardware
write, controller configuration, scheduler/polling change, acquisition-registry
mutation, dependency upgrade, persistent-data deletion, production/site cutover,
secret/billing/DNS change or mandatory public-cloud runtime change is authorized
by this reconciliation.
