# NEXOLAB Blockers

Updated: 2026-08-22

## Issue #589 — no software hard blocker

Issue #589 is active in `feat/589-persisted-acquisition-cadence`.

The implementation is repository-side and can be verified without Raspberry Pi access, Modbus writes, hardware writes, site cutover, secrets, billing/DNS changes or an external runtime service.

The Remote Desktop connector still reports `nexolab-edge-01` offline. This is a **soft hardware-evidence blocker** only. Do not claim the selected cadence is physically accepted for KK1/KK2 until the real Raspberry Pi and adapters are reachable and read-only site evidence is collected.

Issue #589 does not authorize wiring changes, adapter installation, controller configuration changes or Modbus writes.

The software capacity model is intentionally conservative: it uses timeout fallback until sufficient physical latency samples exist, retains a 25% utilization safety margin, never counts cooldown as capacity credit and rejects unsafe activation/cadence changes before persistence.

## Issue #607 — software completed, hardware evidence pending

Dual RS-485 isolation was accepted through PR #653 and merged into the accepted source baseline.

Physical two-adapter verification remains unavailable while the Raspberry Pi connector is offline. This does not block #589 software development, but real simultaneous KK1/KK2 polling, reboot-stable adapter mapping and disconnect-isolation acceptance remain unverified.

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

The separate `CVE-2026-67215` prerequisite was handled through Issue #654 and merged before the #607 accepted baseline; it is not part of #589.

## Product and validation dependencies

- #590 — blocked on completion of #589 persisted cadence/capacity API.
- #585 — blocked until explicit physical W2 / Unit 201 handback approval.
- #444 — LOCAL_LAN user-administration API acceptance remains `needs_validation`.
- #245 — standalone loopback-only Raspberry Pi acceptance remains `needs_validation`.
- #200 — physical RS-485 topology and safe polling envelope remain hardware-unverified beyond retained evidence.
- #201 — LE-01MP restart/power-cycle evidence remains pending.
- #202 — XJP60D KK1/KK2 portability and Unit ID 115 presence/absence remain hardware-unverified.
- #189 — controlled backup/restore/rollback/power-loss recovery evidence remains outstanding.

## Safety boundaries

No Modbus/controller write, hardware write, product persistent-data deletion, Docker named-volume deletion, secret/billing/DNS mutation, production/site cutover or mandatory cloud runtime dependency is authorized by Issue #589.
