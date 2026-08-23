# NEXOLAB Blockers

Updated: 2026-08-23

## Active Issue #663

Issue #663 has **no implementation hard blocker**.

The required authenticated dashboard browser suite already exists and is GREEN for the accepted #415 head. The remaining work is deterministic PR path routing plus focused policy regression coverage. No Raspberry Pi deployment, browser stack rerun on the Pi, Modbus action or production cutover is required.

## Issue #200 — physical RS-485 topology

Passive Raspberry Pi evidence confirms only one CP2104 adapter and one current `rs485-main` production bus. Full #200 acceptance remains blocked on physical topology inspection and/or the intended second isolated adapter.

Still unknown or unaccepted:

- physical KK1/KK2 cable topology;
- termination, biasing, shielding and grounding observations;
- electrical duplicate Unit IDs;
- physical presence/absence of Unit ID 115;
- two-adapter simultaneous isolation/polling and reboot-stable mapping.

Draft PR #659 preserves the passive evidence and must not be merged as Issue #200 completion.

## Issue #444 — LOCAL_LAN user administration validation

The deployed API currently exposes `/api/v1/admin/users`; a read-only unauthenticated probe returned the expected profile/organization guard rather than route-not-found. Full acceptance still requires an authorized administrator identity and creation/authentication of a local test user. Do not cross the credential/security mutation boundary without the required access/approval.

## Issue #245 — standalone offline Raspberry Pi validation

Final acceptance requires controlled standalone deployment, Ethernet/Wi-Fi isolation, no default route, reboot, observation, Telemetry Service restart and another reboot. This is a production/network cutover boundary and is not authorized by the active chart Work Package.

## Issue #201 — LE-01MP cumulative energy

Software and normal-operation hardware semantics are accepted. The remaining acceptance item is an explicitly approved restart/power-cycle observation for reset/rollover/discontinuity behavior. An historical unplanned hard reset must not be reclassified as approved evidence.

## Issue #202 — XJP60D portability

Representative KK1/KK2 physical evidence, Unit 115 resolution and extended semantics still require real hardware actions/evidence. Unconfirmed fields remain unmapped.

## Issue #585 — W2 / Unit 201 handback

Blocked until the Product Owner confirms the temporary external RS-485 owner has released W2 and approves any required physical handback/reconnection.

## Issue #189 — recovery acceptance

Controlled actual-host/off-host/edge recovery and approved power-loss evidence remain outstanding. No destructive restore over production and no named-volume deletion are authorized.

## Issue #646 — main branch protection

Repository-side change-impact CI and `NEXOLAB Merge Gate` are implemented. GitHub branch/rules settings remain a soft access blocker; normal work continues through focused PRs and exact-head GREEN verification.

## Security maintenance — CVE-2026-14456

Four exact reviewed HIGH/no-fix exceptions expire on **2026-08-30**. Owner: `platform-security`.

Remove them earlier if a supported Debian Trixie fix is available, the exact finding disappears, QUIC/HTTP3 server reachability changes, or severity becomes Critical. Critical exceptions remain forbidden.

## Safety boundaries

No blocker may be bypassed by Modbus/controller write, hardware write, production/site cutover, persistent-data deletion, named-volume deletion, secret exposure or mandatory cloud dependency.
