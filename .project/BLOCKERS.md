# NEXOLAB Blockers

Updated: 2026-07-31

## Hard blockers

None recorded for the workflow-foundation Pull Request.

Hard blockers for later product work include destructive database actions, production/site cutover, Modbus or other hardware writes, inability to preserve local telemetry, and required credentials or hardware being unavailable.

## Soft blockers and unknowns

| ID | Area | Status | Required action |
| --- | --- | --- | --- |
| N-001 | Roadmap | Open | Reconcile open Issues, current code and milestone documentation. |
| N-002 | Offline readiness | Open | Classify all runtime network, CDN, external API and paid-service dependencies. |
| N-003 | Hardware acceptance | Open | Separate code-complete status from evidence requiring real edge and central hosts. |
| N-004 | Recovery | Open | Verify local backup, restore, update and rollback procedures and evidence. |
| N-005 | Runtime resilience | Open | Verify power-loss, restart, MQTT outage and central outage behavior. |
| N-006 | Formatting baseline | Open — Issue #185 | Classify and resolve the existing repository-wide Prettier debt in controlled formatting-only Pull Requests. Until then, normal PRs validate only changed files. |

Soft blockers do not stop unrelated Ready Work Packages. No task may convert missing real-hardware evidence into an assumed pass.
