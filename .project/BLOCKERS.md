# NEXOLAB Blockers

Updated: 2026-08-04

## Issue #265 — Equipment Layouts catalog

No product, repository-access, architecture or hardware blocker prevents implementation from starting in PR #266.

Verified repository basis:

- PR #264 merged into `main` as `249a271b4d67dc87c8fa28b81a76027274b07e28`;
- Issue #265 contains the complete product outcome, acceptance criteria, scope, out-of-scope boundaries and verification plan;
- branch `feat/265-equipment-layouts-catalog` exists from the exact post-merge main head;
- draft PR #266 is the single focused Pull Request for the Work Package;
- the existing equipment repository provides organization-scoped inventory;
- the existing layout repository provides draft, active publication, immutable history and signed image metadata;
- the existing refrigeration detail route remains the canonical editor and mutation surface.

The initial implementation must not introduce a duplicate editor, new persistence model or dependency migration.

## Soft risks to manage inside Issue #265

- Per-equipment draft/publication requests can become an N+1 pattern. Use bounded concurrency, cancellation and partial-result preservation before considering a new backend endpoint.
- Signed image URLs can expire or fail independently. Keep image failures local to the affected preview/card and expose retry without collapsing the catalog.
- Draft and publication versions represent different lifecycle concepts. Derive layout state explicitly and cover the version comparison with focused tests.
- Retired equipment is read-only and must not expose mutation affordances through the catalog.
- Live mode must fail explicitly and never silently substitute demo fixtures.

These are implementation risks, not blockers. A narrow read-only summary endpoint may be considered only if measured evidence proves the current contracts insufficient; no database migration is authorized by default.

## Product-page priority

Issue #265 is the active page-completion Work Package. After it merges, the next queued route is `/equipment`.

Deferred toolchain Issues #252–#257 remain out of the page-completion sequence unless a security, support or concrete product blocker appears.

## Smart Lockers blocker

The `/lockers` page remains blocked until a concrete locker inventory, read-only protocol and operator workflow are defined. Do not invent production device behavior or present demo controls as completed functionality.

## Hard blockers

Stop before:

- destructive database or persistent-volume operations;
- restore over production data without isolated proof and explicit approval;
- production/site cutover without explicit approval;
- Modbus or unsafe hardware writes;
- secret exposure or unauthorized key rotation;
- unresolved materially different product or architecture decisions;
- any operation that cannot preserve local laboratory data.

## Hardware and operational risks

- **#245:** software merged; actual standalone Raspberry Pi acceptance pending.
- **#189:** software recovery evidence verified; physical reboot, power-loss and media restore pending controlled access.
- **N-037:** Sharp compatibility override remains monitored.
- **N-023:** node health durability is not claimed equal to telemetry process-restart durability.
- **N-024:** rollback must preserve named volumes and spool compatibility.
- **N-025:** actual-host spool capacity evidence remains required.
- **N-032:** actual Raspberry Pi ARM64 archive/load/start/update/rollback remains unverified.
- **#200:** physical RS-485 topology hardware-blocked.
- **#201:** cumulative LE-01MP energy hardware-blocked.
- **#202:** extended XJP60D semantics hardware-blocked.

## Next Ready action

Implement the Issue #265 catalog domain loader and status derivation first, add focused unit tests, then wire the authenticated `/equipment-layouts` screen and read-only preview in PR #266.
