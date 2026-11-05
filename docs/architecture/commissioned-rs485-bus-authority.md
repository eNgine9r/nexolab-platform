# Persisted RS-485 commissioning buses

Status: accepted by Product Owner, 2026-11-05. Implementation and hardware acceptance remain subject to the associated review and verification in #1505.

## Decision

The static `RS485_BUS_CONFIG_JSON` topology remains authoritative for existing configured buses. A separate local SQLite commissioning-bus authority records a stable `/dev/serial/by-id` path, a deterministic bus identity derived from that path, the fixed serial profile and a two-stage lifecycle. Only explicitly activated entries are reconciled into the runtime topology at startup. No cloud service or network connection is needed.

Each physical bus has a single operation lock shared by commissioning and its scheduler worker. A successful, fresh, bounded read-only preflight is required before a free adapter can be enrolled. An empty registry bus is persisted before any device or target becomes active. A prepared bus is ignored after a restart; an active bus with no active targets cannot poll. The existing device activation journal controls target activation and recovery separately. Device telemetry must remain scoped to its physical bus and historical identities must not be reassigned.

Canonical stable identities and serial settings are immutable for a commissioned bus. Configured paths, duplicate identities and mismatched framing fail closed. The runtime checks resolved serial aliases before physical reads; a disconnected or conflicting adapter reports a communication failure rather than fabricated or stale live values. Existing static buses cannot be overwritten by commissioning. An activated bus cannot be silently removed as part of rollback while other devices may use it.

## Failure and verification boundaries

The separate bus authority and device registry are not one transaction. Their operation order must ensure that every interrupted state is safe: a prepared bus is not pollable; an active bus with an empty or reserve-only registry produces no acquisition; an active device requires a durable active bus and shared bus lock. Tests must cover each boundary, retries, restart, alias collisions, serial changes and mixed existing traffic. Any unrecoverable identity inconsistency stops the affected action or reports failure rather than moving devices between buses.

This decision authorizes source implementation only. Real-device acceptance, CI, deployment, rollback execution and any separately required site cutover remain distinct gates. Modbus writes, hardware writes and device parameter changes are prohibited.
