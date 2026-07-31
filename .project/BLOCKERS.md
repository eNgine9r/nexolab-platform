# NEXOLAB Blockers

Updated: 2026-08-01

## Hard blockers

No hard blocker prevents completion of Issue #183.

The following remain hard-stop conditions for later work:

- destructive database or persistent-volume operation;
- production/site cutover without explicit approval;
- Modbus or other unsafe hardware write;
- secret exposure;
- missing mandatory credentials/device access for the scoped acceptance;
- unresolved materially different product architecture choice;
- inability to preserve local laboratory data.

## Resolved or clarified by Issue #183

| ID    | Area                      | Result                                                                                          |
| ----- | ------------------------- | ----------------------------------------------------------------------------------------------- |
| N-001 | Roadmap                   | A code-backed vertical roadmap and ordered Work Package queue now exist                         |
| N-002 | Dependency classification | Dependencies are classified as local mandatory, optional online, development-only or prohibited |
| N-003 | Hardware boundary         | Narrow 34-series edge evidence is separated from broader unverified hardware/site acceptance    |

## Open soft blockers and risks

| ID    | Area                          | Status                    | Required action                                                                                                                                                                                                                                                                 |
| ----- | ----------------------------- | ------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| N-004 | Recovery                      | Open — Issue #189         | Execute and retain consolidated PostgreSQL, MinIO, MQTT, edge SQLite, restart, rollback and approved power-loss evidence                                                                                                                                                        |
| N-005 | Runtime resilience            | Partial — Issue #189      | Narrow edge MQTT/restart evidence exists; broader central-host and power-loss behavior remains unverified                                                                                                                                                                       |
| N-006 | Formatting baseline           | Active — Issues #185/#191 | Resolve historical Prettier debt only through controlled formatting-only Pull Requests; PR #192 contains the verified inventory                                                                                                                                                 |
| N-007 | Offline installation          | Open — Issue #187         | Build and prove a checksummed local OCI installation/update bundle on a clean disconnected host                                                                                                                                                                                 |
| N-008 | Offline authentication        | Open — Issue #188         | Select and prove a fail-closed local operator identity and RBAC lifecycle                                                                                                                                                                                                       |
| N-009 | GitHub source of truth        | Queued — Issue #186       | Reconcile stale trackers, legacy M1 Issues and superseded/non-mergeable PRs after PR #190 merges                                                                                                                                                                                |
| N-010 | Live/KK2 defect               | Blocked on #186           | PR #175 is draft and non-mergeable; rebase/recreate it as one clean Work Package before implementation continues                                                                                                                                                                |
| N-011 | Residual Modbus mapping       | Open                      | LE-01MP cumulative-energy register `7` and broader XJP60D semantics remain explicitly unverified                                                                                                                                                                                |
| N-012 | MQTT-to-PostgreSQL durability | Confirmed — Issue #198    | Edge SQLite is deleted after broker QoS 1 acknowledgement, while central persistence is still in memory. A Telemetry Service termination during PostgreSQL outage can lose acknowledged telemetry; implement durable local staging/replay before claiming end-to-end durability |

Soft blockers do not justify assumed completion. Continue with an independent queued Work Package only after its predecessor is marked `done`; do not treat `review` as authorization to bundle successor Issues into the same branch.
