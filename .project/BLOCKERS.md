# NEXOLAB Blockers

Updated: 2026-08-01

## Hard blockers

No hard blocker prevents completion of Issue #186.

Stop before:

- destructive database or persistent-volume operation;
- production/site cutover without explicit approval;
- Modbus or other unsafe hardware write;
- secret exposure or key rotation without the required authority;
- missing mandatory credentials/device access for the scoped acceptance;
- unresolved materially different product architecture choice;
- inability to preserve local laboratory data.

## Resolved source-of-truth blockers

| ID    | Area                     | Result                                                                                       |
| ----- | ------------------------ | -------------------------------------------------------------------------------------------- |
| N-001 | Architecture/roadmap     | PR #190 established the verified LOCAL_LAN architecture, offline and recovery boundaries     |
| N-002 | Legacy Pull Requests     | #53, #109, #111 and #175 are closed with focused replacement Issues or owning outcomes       |
| N-003 | Dependency Pull Requests | #159, #160, #1 and #2 are closed; #203–#205 own focused compatibility work                   |
| N-004 | M4 tracker               | #74 matches closed #82 and is closed with a scoped completion boundary                       |
| N-005 | Refrigeration foundation | #94 is closed because later `main` contains and surpasses the photo-backed layout foundation |
| N-006 | Historical M1 tracker    | #11–#15/#18 are closed as superseded; #17 and #200–#202 preserve the unverified residuals    |
| N-007 | Open PR classification   | PR #192 is the only open PR and has an explicit draft/rebase/finalization action             |

## Open soft blockers and risks

| ID    | Area                          | Status                    | Required action                                                                                                                                              |
| ----- | ----------------------------- | ------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| N-008 | MQTT-to-PostgreSQL durability | Confirmed — #198          | Implement durable local central staging/replay before claiming end-to-end persistence across PostgreSQL outage and Telemetry Service restart                 |
| N-009 | Live WebSocket lifecycle      | Queued — #199             | Implement from current `main`; PR #175 is reference-only; keep catalog behavior out of scope                                                                 |
| N-010 | Offline installation          | Queued — #187             | Build and prove a checksummed local OCI installation/update bundle on a clean disconnected host                                                              |
| N-011 | Offline authentication        | Queued — #188             | Select and prove a fail-closed local operator identity and RBAC lifecycle                                                                                    |
| N-012 | Recovery and power loss       | Blocked — #189            | Extend PR #144 software DR with #198 durability, actual-host scheduling, off-host copies, edge restart/rollback and approved power-loss evidence             |
| N-013 | Formatting baseline           | Draft — #185/#191/PR #192 | Rebase or recreate after #186 merge, update project state, rerun inventory if material, require green CI; do not mix source formatting into the inventory PR |
| N-014 | Physical RS-485 topology      | Hardware blocked — #200   | Inventory actual buses, stable adapter paths, Unit IDs, termination/biasing, latency and safe polling envelope using read-only evidence                      |
| N-015 | LE-01MP cumulative energy     | Hardware blocked — #201   | Confirm register layout, scale, unit, rollover and display correlation; otherwise keep excluded                                                              |
| N-016 | Extended XJP60D semantics     | Hardware blocked — #202   | Confirm portability, Unit ID `115` reality, status distinctions, setpoint and I/O semantics; leave unverified fields unmapped                                |
| N-017 | Versioned device profiles     | Blocked — #17             | Consolidate profiles only after #200–#202 evidence; schema must reject write operations                                                                      |
| N-018 | Optional Tailscale acceptance | Blocked — #108            | Requires #188 decision plus controlled central host and operator workstation; local LAN runtime remains independent                                          |
| N-019 | Production dependency updates | Queued maintenance — #203 | Split framework/security, optional Supabase and icon updates into focused compatibility PRs                                                                  |
| N-020 | Major frontend toolchain      | Queued maintenance — #204 | Plan TypeScript/ESLint/jsdom/lint-staged/Playwright migrations separately                                                                                    |
| N-021 | GitHub Actions v7             | Queued maintenance — #205 | Audit workflow triggers, checkout security, permissions, runner/runtime and representative workflow compatibility before upgrade                             |

Soft blockers do not justify assumed completion. A task may start only when its predecessor is `done`; `review` does not authorize successor work in the same branch.
