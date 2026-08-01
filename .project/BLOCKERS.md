# NEXOLAB Blockers

Updated: 2026-08-01

## Hard blockers

No hard blocker currently prevents software completion of Issue #198.

Stop before:

- destructive database or persistent-volume operation;
- production/site cutover without explicit approval;
- Modbus or other unsafe hardware write;
- secret exposure or unauthorized key rotation;
- missing mandatory credentials or access for a required acceptance gate;
- a materially different unresolved product architecture choice;
- inability to preserve local laboratory data.

## Resolved source-of-truth blockers

| ID    | Area                  | Result                                                                                      |
| ----- | --------------------- | ------------------------------------------------------------------------------------------- |
| N-001 | Architecture/roadmap  | PR #190 established the verified `LOCAL_LAN` architecture and offline/recovery boundaries   |
| N-002 | GitHub reconciliation | PR #206 merged as `bd286690`; stale PRs and trackers now have focused successors            |
| N-003 | Sprint sequencing     | Issue #198 is active in PR #207; formatting, dependency and hardware tracks remain separate |

## Active Work Package risks

| ID    | Area                          | Status                                          | Required action                                                                                                                                              |
| ----- | ----------------------------- | ----------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| N-008 | MQTT-to-PostgreSQL durability | In progress — #198 / PR #207                    | Complete latest-head CI/review and prove the local spool, manual ACK, restart replay, capacity visibility and named-volume contract                          |
| N-022 | Actual-host spool recovery    | Software prepared; host evidence pending — #189 | Prove container recreation, rollback with pending rows, disk-full response, backup/restore and controlled power interruption on the supported host           |
| N-023 | Node health/status durability | Explicitly out of #198                          | Current node health/status worker is not claimed to have the same process-restart durability; create a focused Issue only if required by operations evidence |
| N-024 | Rollback compatibility        | Open operational risk                           | Do not roll back to a pre-ADR-0008 image while pending or terminal spool records exist; preserve named volumes                                               |
| N-025 | Spool capacity policy         | Software thresholds implemented                 | Validate 70%/90% utilization and 15-minute backlog thresholds against actual-host capacity/throughput evidence; never auto-delete terminal/pending records   |

## Other open soft blockers and risks

| ID    | Area                          | Status                     | Required action                                                                                                                       |
| ----- | ----------------------------- | -------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| N-009 | Live WebSocket lifecycle      | Queued — #199              | Implement from post-#198 `main`; keep catalog behavior out of scope                                                                   |
| N-010 | Offline installation          | Queued — #187              | Build and prove a checksummed local OCI installation/update bundle on a clean disconnected host                                       |
| N-011 | Offline authentication        | Queued — #188              | Select and prove a fail-closed local operator identity and RBAC lifecycle                                                             |
| N-012 | Recovery and power loss       | Blocked — #189             | Extend PR #144 with ingestion spool, actual-host scheduling, off-host copies, edge restart/rollback and approved power-loss evidence  |
| N-013 | Formatting baseline           | Draft — #185/#191/PR #192  | Rebase or recreate from current `main`; never mix source formatting into #207                                                         |
| N-014 | Physical RS-485 topology      | Hardware blocked — #200    | Inventory actual buses, stable adapter paths, Unit IDs, termination/biasing, latency and safe polling using read-only evidence        |
| N-015 | LE-01MP cumulative energy     | Hardware blocked — #201    | Confirm register layout, scale, unit, rollover and display correlation                                                                |
| N-016 | Extended XJP60D semantics     | Hardware blocked — #202    | Confirm portability, Unit ID reality, status distinctions, setpoint and I/O semantics without writes                                  |
| N-017 | Versioned device profiles     | Blocked — #17              | Consolidate profiles only after #200–#202 evidence; schema must reject write operations                                               |
| N-018 | Optional Tailscale acceptance | Blocked — #108             | Requires #188 decision plus controlled central host and operator workstation                                                          |
| N-019 | Production dependency updates | Queued maintenance — #203  | Split framework/security and optional integration updates into focused compatibility PRs                                              |
| N-020 | Major frontend toolchain      | Queued maintenance — #204  | Plan TypeScript/ESLint/jsdom/lint-staged/Playwright migrations separately                                                             |
| N-021 | GitHub Actions v7             | Queued maintenance — #205  | Audit triggers, permissions, runtime and representative workflow compatibility before upgrade                                         |
| N-026 | Device Agent `pyasn1` CVE     | Security Work Package #208 | Upgrade only the Device Agent dependency boundary to remediate CVE-2026-33230; do not mix this independent supply-chain fix into #207 |

Soft blockers do not justify assumed completion. Missing actual-host or hardware evidence must remain explicitly unverified.
