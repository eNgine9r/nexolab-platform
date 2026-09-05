from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from app.commissioning.activation_client import (
    DeviceAgentActivationClient,
    DeviceAgentActivationCommand,
    DeviceAgentActivationError,
)
from app.commissioning.activation_repository import CommissioningActivationRepository
from app.commissioning.models import EquipmentCommissioningActivationAttempt
from app.refrigeration.controller_binding_repository import (
    ControllerBindingError,
    PostgresRefrigerationControllerBindingRepository,
)
from app.refrigeration.schemas import RefrigerationControllerBindingWrite
from app.security.repository import AuditEventInput, SecurityRepository


@dataclass(slots=True)
class CommissioningActivationService:
    repository: CommissioningActivationRepository
    client: DeviceAgentActivationClient
    controller_binding_repository: PostgresRefrigerationControllerBindingRepository
    security_repository: SecurityRepository
    freshness_seconds: float
    verification_timeout_seconds: float
    poll_interval_seconds: float = 0.25
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
        binding_audit_event: AuditEventInput,
    ) -> EquipmentCommissioningActivationAttempt:
        prepared = self.repository.prepare(
            session_id,
            organization_id=organization_id,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            actor_subject=actor_subject,
            freshness_seconds=self.freshness_seconds,
            audit_event=started_audit_event,
        )
        if prepared.replayed:
            return prepared.attempt
        command = DeviceAgentActivationCommand(**prepared.command)  # type: ignore[arg-type]
        try:
            activation = self.client.execute(command)
        except DeviceAgentActivationError as error:
            return self.repository.complete(
                prepared.attempt.id,
                organization_id=organization_id,
                state="recovery_required",
                evidence=_unknown_mutation_evidence(command, error),
                audit_event=completed_audit_event,
            )
        if activation["state"] == "recovery_required":
            return self.repository.complete(
                prepared.attempt.id,
                organization_id=organization_id,
                state="recovery_required",
                evidence={"activation": activation, **_safety_evidence()},
                audit_event=completed_audit_event,
            )
        if activation["state"] == "rolled_back":
            return self.repository.complete(
                prepared.attempt.id,
                organization_id=organization_id,
                state="rolled_back",
                evidence={"activation": activation, **_safety_evidence()},
                audit_event=completed_audit_event,
            )

        try:
            health, telemetry = self._await_runtime_evidence(
                command=command,
                activation=activation,
                started_at=prepared.attempt.started_at,
            )
        except DeviceAgentActivationError as error:
            return self._rollback_after_failure(
                prepared.attempt,
                command,
                organization_id=organization_id,
                activation=activation,
                failure={"code": error.code, "message": error.message},
                completed_audit_event=completed_audit_event,
            )
        try:
            binding = self._persist_binding(
                prepared.attempt,
                activation,
                organization_id=organization_id,
                actor_subject=actor_subject,
                audit_event=binding_audit_event,
            )
        except ControllerBindingError as error:
            return self._rollback_after_failure(
                prepared.attempt,
                command,
                organization_id=organization_id,
                activation=activation,
                failure={"code": error.code, "message": str(error)},
                completed_audit_event=completed_audit_event,
            )

        return self.repository.complete(
            prepared.attempt.id,
            organization_id=organization_id,
            state="active",
            evidence={
                "activation": activation,
                "health": health,
                "telemetry": telemetry,
                "binding": binding,
                **_safety_evidence(),
            },
            audit_event=completed_audit_event,
        )

    def _await_runtime_evidence(
        self,
        *,
        command: DeviceAgentActivationCommand,
        activation: dict[str, Any],
        started_at: Any,
    ) -> tuple[dict[str, Any], dict[str, object]]:
        deadline = time.monotonic() + self.verification_timeout_seconds
        last_error: DeviceAgentActivationError | None = None
        while True:
            health: dict[str, Any] | None = None
            try:
                health = self.client.health(
                    node_id=command.node_id,
                    target_ids=list(activation["target_ids"]),
                )
                last_error = None
            except DeviceAgentActivationError as error:
                last_error = error
            telemetry = self.repository.telemetry_evidence(
                node_id=command.node_id,
                source=str(activation["telemetry_source"]),
                equipment_id=str(activation["telemetry_equipment_id"]),
                received_after=started_at,
            )
            if health is not None and telemetry is not None:
                return health, telemetry
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                if last_error is not None:
                    raise last_error
                raise DeviceAgentActivationError(
                    "activation_telemetry_timeout",
                    "No new local telemetry was persisted before the activation verification deadline",
                )
            time.sleep(min(self.poll_interval_seconds, remaining))

    def _persist_binding(
        self,
        attempt: EquipmentCommissioningActivationAttempt,
        activation: dict[str, Any],
        *,
        organization_id: str,
        actor_subject: str,
        audit_event: AuditEventInput,
    ) -> dict[str, object]:
        plan = attempt.plan
        if plan.get("binding_kind") != "refrigeration_controller":
            return {
                "kind": "commissioning_target",
                "equipment_id": str(plan["target_equipment_key"]),
                "session_id": attempt.session_id,
            }
        payload = RefrigerationControllerBindingWrite(
            node_id=str(plan["node_id"]),
            controller_family="embraco",
            controller_equipment_id=str(activation["telemetry_equipment_id"]),
            unit_id=int(plan["unit_id"]),
            profile_version=str(plan["profile_version"]),
        )
        binding = self.controller_binding_repository.replace_active(
            str(plan["target_equipment_key"]),
            payload,
            actor_id=actor_subject,
            organization_id=organization_id,
            audit_repository=self.security_repository,
            audit_event=audit_event,
        )
        return {
            "kind": "refrigeration_controller",
            "binding_id": binding.id,
            "equipment_id": binding.equipment_id,
            "controller_equipment_id": binding.controller_equipment_id,
        }

    def _rollback_after_failure(
        self,
        attempt: EquipmentCommissioningActivationAttempt,
        command: DeviceAgentActivationCommand,
        *,
        organization_id: str,
        activation: dict[str, Any],
        failure: dict[str, object],
        completed_audit_event: AuditEventInput,
    ) -> EquipmentCommissioningActivationAttempt:
        rollback_command = DeviceAgentActivationCommand(
            activation_id=command.activation_id,
            action="rollback",
            node_id=command.node_id,
            bus_id=command.bus_id,
            stable_transport_identifier=command.stable_transport_identifier,
            unit_id=command.unit_id,
            profile_id=command.profile_id,
            profile_version=command.profile_version,
        )
        try:
            rollback = self.client.execute(rollback_command)
        except DeviceAgentActivationError as error:
            rollback = {
                "state": "recovery_required",
                "code": error.code,
                "message": error.message,
                "modbus_writes": "none",
                "hardware_writes": "none",
            }
        final_state = (
            "rolled_back" if rollback.get("state") == "rolled_back" else "recovery_required"
        )
        return self.repository.complete(
            attempt.id,
            organization_id=organization_id,
            state=final_state,
            evidence={
                "activation": activation,
                "failure": failure,
                "rollback": rollback,
                **_safety_evidence(),
            },
            audit_event=completed_audit_event,
        )


def _unknown_mutation_evidence(
    command: DeviceAgentActivationCommand,
    error: DeviceAgentActivationError,
) -> dict[str, object]:
    return {
        "activation": {
            "activation_id": command.activation_id,
            "state": "unknown",
            "node_id": command.node_id,
            "bus_id": command.bus_id,
            "unit_id": command.unit_id,
            "profile_id": command.profile_id,
            "profile_version": command.profile_version,
        },
        "failure": {
            "code": error.code,
            "message": error.message,
            "mutation_state": "unknown_recovery_required",
        },
        **_safety_evidence(),
    }


def _safety_evidence() -> dict[str, object]:
    return {
        "polling_mode": "read_only_fc03",
        "modbus_writes": "none",
        "hardware_writes": "none",
        "controller_parameter_changes": "none",
    }
