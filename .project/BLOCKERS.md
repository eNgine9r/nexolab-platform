# NEXOLAB Blockers

Updated: 2026-08-22

## Issue #590 — no software hard blocker

Issue #590 is active in `feat/590-settings-acquisition-cadence`.

The implementation is a Settings/control-plane integration over the completed #589 persisted cadence/capacity API. It can be verified repository-side without Raspberry Pi access, Modbus writes, hardware writes, site cutover, secrets, billing/DNS changes or an external runtime service.

The browser must use the authenticated Next.js proxy only. Direct browser access to the Device Agent, direct Modbus/driver access, force/bypass controls and per-logical-channel physical cadence controls remain prohibited.

The Remote Desktop connector still reports `nexolab-edge-01` offline. This is a **soft hardware-evidence blocker** only. The UI may expose server-authoritative 10/30/60/Custom cadence controls, but it must not claim that a selected interval is physically accepted on KK1/KK2 until read-only evidence from the real Pi and intended adapters exists.

## Issue #607 — software completed, hardware evidence pending

Dual RS-485 isolation was accepted through PR #653. Physical two-adapter verification remains unavailable while the Raspberry Pi connector is offline.

Repository evidence maps XJP60D KK2 to Unit IDs `101..115` and KK1 to `126..138`. LE-01MP Unit IDs `200..203` still have no repository-backed KK1/KK2 ownership and must not be guessed.

## Issue #646 — branch protection settings access

Repository-side change-impact CI, exact-head external-workflow aggregation and the stable merge gate are software-verified.

The retained observation still reports:

- `main` protected: false;
- required status checks: disabled.

The connected GitHub tool surface does not expose the required branch-protection/rules mutation. This remains a **soft access blocker** only. Do not represent technical branch protection as complete until the setting is actually changed and verified.

## Security maintenance — CVE-2026-14456

Issue #598 is closed, but four temporary `CVE-2026-14456` exceptions expire on **2026-08-26**.

Owner: `platform-security`.

Re-check fixed Debian package availability and remove the exceptions immediately when a fix becomes available, or review before expiry. Any change that makes QUIC/HTTP3 reachable invalidates the current reachability justification.

## Product and validation dependencies

- #585 — blocked until explicit physical W2 / Unit 201 handback approval.
- #444 — LOCAL_LAN user-administration API acceptance remains `needs_validation`.
- #245 — standalone loopback-only Raspberry Pi acceptance remains `needs_validation`.
- #200 — physical RS-485 topology and safe polling envelope remain hardware-unverified beyond retained evidence.
- #201 — LE-01MP restart/power-cycle evidence remains pending.
- #202 — XJP60D KK1/KK2 portability and Unit ID 115 presence/absence remain hardware-unverified.
- #189 — controlled backup/restore/rollback/power-loss recovery evidence remains outstanding.

## Safety boundaries

No Modbus/controller write, hardware write, product persistent-data deletion, Docker named-volume deletion, secret/billing/DNS mutation, production/site cutover or mandatory cloud runtime dependency is authorized by Issue #590.
