# NEXOLAB Blockers

Updated: 2026-08-01

## Hard blockers

No hard blocker prevents completion of Issue #208.

Stop before:

- destructive database or persistent-volume operation;
- production/site cutover without explicit approval;
- Modbus or other unsafe hardware write;
- secret exposure or unauthorized key rotation;
- an unresolved materially different product/security decision;
- inability to preserve local laboratory data.

## Active blockers and risks

| ID    | Area                               | Status                  | Required action                                                                                                    |
| ----- | ---------------------------------- | ----------------------- | ------------------------------------------------------------------------------------------------------------------ |
| N-008 | MQTT-to-PostgreSQL durability      | Review — #198 / PR #207 | Update from `main` after #209 merges, rerun aggregate Container Supply Chain, then complete final review and merge |
| N-026 | Device Agent supply-chain evidence | Review — #208 / PR #209 | Final CI and complete Supply Chain matrix are green; keep checks green through ready transition and squash merge   |
| N-027 | Historical `pyasn1` scanner result | Resolved in branch      | Wrong target and sequential SBOM contamination are ruled out; do not add an unused dependency or waiver            |
| N-028 | Stale Expat exception decisions    | Resolved in branch      | Five no-longer-active `libexpat1` exceptions were removed; strict stale-exception enforcement remains enabled      |
| N-029 | Temporary supply-chain diagnostics | Resolved in branch      | Diagnostic workflow is absent from the final nine-file diff                                                        |

## Other open soft blockers

| ID    | Area                          | Status                    | Required action                                                                                                       |
| ----- | ----------------------------- | ------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| N-009 | Live WebSocket lifecycle      | Queued — #199             | Start only after #198 merges                                                                                          |
| N-010 | Offline installation          | Queued — #187             | Build and prove a checksummed local OCI bundle on a clean disconnected host                                           |
| N-011 | Offline authentication        | Queued — #188             | Prove fail-closed local operator identity and RBAC                                                                    |
| N-012 | Recovery and power loss       | Blocked — #189            | Extend software DR with actual-host scheduling, spool/edge recovery, rollback and approved power-loss evidence        |
| N-013 | Formatting baseline           | Draft — #185/#191/PR #192 | Keep separate from security and durability changes                                                                    |
| N-014 | Physical RS-485 topology      | Hardware blocked — #200   | Inventory actual buses, stable adapter paths, Unit IDs, termination/biasing and safe polling using read-only evidence |
| N-015 | LE-01MP cumulative energy     | Hardware blocked — #201   | Confirm register layout, scale, unit, rollover and display correlation                                                |
| N-016 | Extended XJP60D semantics     | Hardware blocked — #202   | Confirm portability, status distinctions, setpoint and I/O semantics without writes                                   |
| N-017 | Versioned device profiles     | Blocked — #17             | Consolidate only after #200–#202 evidence                                                                             |
| N-018 | Optional Tailscale acceptance | Blocked — #108            | Requires offline-auth decision plus controlled central host and workstation                                           |
| N-019 | Production dependency updates | Queued maintenance — #203 | Split framework/security and optional integration updates into focused PRs                                            |
| N-020 | Major frontend toolchain      | Queued maintenance — #204 | Plan major migrations separately                                                                                      |
| N-021 | GitHub Actions v7             | Queued maintenance — #205 | Audit triggers, permissions, runtime and representative workflow compatibility before upgrade                         |

Missing actual-host or hardware evidence remains unverified. A green scanner result does not authorize image publication or site deployment.
