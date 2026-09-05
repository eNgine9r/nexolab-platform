from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.commissioning.preflight_client import (
    DeviceAgentPreflightClient,
    DeviceAgentPreflightCommand,
    DeviceAgentPreflightError,
)
from app.commissioning.preflight_repository import CommissioningPreflightRepository
from app.commissioning.models import EquipmentCommissioningPreflightAttempt
from app.security.repository import AuditEventInput


@dataclass(slots=True)
class CommissioningPreflightService:
    repository: CommissioningPreflightRepository
    client: DeviceAgentPreflightClient
    deadline_seconds: float

    def run(
        self,
        session_id: str,
        *,
        organization_id: str,
        expected_version: int,
        idempotency_key: str,
        actor_subject: str,
        started_audit_event: AuditEventInput,
        completed_audit_event: AuditEventInput,
    ) -> EquipmentCommissioningPreflightAttempt:
        prepared = self.repository.prepare(
            session_id,
            organization_id=organization_id,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            actor_subject=actor_subject,
            deadline_seconds=self.deadline_seconds,
            audit_event=started_audit_event,
        )
        if prepared.replayed:
            return prepared.attempt
        command = DeviceAgentPreflightCommand(**prepared.command)  # type: ignore[arg-type]
        try:
            evidence = self.client.run(command)
        except DeviceAgentPreflightError as error:
            evidence = _control_plane_failure(command, error)
        return self.repository.complete(
            prepared.attempt.id,
            organization_id=organization_id,
            evidence=evidence,
            audit_event=completed_audit_event,
        )


def _control_plane_failure(
    command: DeviceAgentPreflightCommand,
    error: DeviceAgentPreflightError,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "result": "failed",
        "code": error.code,
        "evidence_level": "unverified",
        "node_id": command.node_id,
        "bus_id": command.bus_id,
        "stable_transport_identifier": command.stable_transport_identifier,
        "unit_id": command.unit_id,
        "profile_id": command.profile_id,
        "profile_version": command.profile_version,
        "read_method": "modbus_rtu_fc03",
        "function_codes": [3],
        "checks": [
            {
                "key": "device_agent_transport",
                "state": "failed",
                "detail": error.message,
            },
            {
                "key": "write_safety",
                "state": "passed",
                "detail": "Commissioning preflight contract exposes FC03 reads only; Modbus writes and hardware writes are not representable.",
            },
        ],
        "observations": [],
        "warnings": ["No live Device Agent evidence was received for this attempt."],
        "duration_ms": 0,
        "modbus_writes": "none",
        "hardware_writes": "none",
    }
