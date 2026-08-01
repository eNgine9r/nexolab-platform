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

| ID    | Area                                 | Status                            | Required action                                                                                                                                  |
| ----- | ------------------------------------ | --------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| N-008 | MQTT-to-PostgreSQL durability        | Review — #198 / PR #207           | Targeted gates are green; rerun aggregate Container Supply Chain after #208 merges, then complete final review/merge                             |
| N-026 | Device Agent supply-chain provenance | In progress — #208 / PR #209      | Merge fresh-base and versioned-cache policy only after Container Supply Chain proves Device Agent, SBOM, Trivy and aggregate manifests are green |
| N-027 | Stale vulnerability evidence         | Classified, remediation in review | Do not add unused `pyasn1` or a vulnerability waiver; preserve diagnostic evidence showing the package is absent from the current runtime/rootfs |
| N-028 | Temporary diagnostics                | Resolved in branch                | The diagnostic workflow was removed through a Git tree commit; verify it is absent from the final changed-file list                              |

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
