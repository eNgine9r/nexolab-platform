from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException

from app.refrigeration.api import _draft_response
from app.refrigeration.equipment_api import equipment_response
from app.refrigeration.equipment_repository import (
    DEFAULT_ORGANIZATION_ID,
    EquipmentNotFoundError,
    EquipmentRepositoryError,
    PostgresRefrigerationEquipmentRepository,
)
from app.refrigeration.lifecycle_api import _access_dependency, _binding_response
from app.refrigeration.lifecycle_repository import (
    EquipmentLifecycleRepositoryError,
    PostgresEquipmentLifecycleRepository,
)
from app.refrigeration.repository import (
    LayoutRepositoryError,
    PostgresRefrigerationLayoutRepository,
)
from app.refrigeration.sensor_configuration_repository import (
    PostgresSensorConfigurationRepository,
)
from app.refrigeration.storage import ObjectStorage
from app.refrigeration.structural_schemas import (
    RefrigerationStructuralSnapshotResponse,
    StructuralChannelResponse,
    StructuralSampleState,
)
from app.security.authorization import Permission
from app.security.dependencies import AuthorizedRequest, SecurityDependencies


def create_refrigeration_structural_router(
    equipment_repository: PostgresRefrigerationEquipmentRepository,
    lifecycle_repository: PostgresEquipmentLifecycleRepository,
    sensor_configuration_repository: PostgresSensorConfigurationRepository,
    layout_repository: PostgresRefrigerationLayoutRepository,
    storage: ObjectStorage,
    *,
    signed_url_seconds: int,
    security_dependencies: SecurityDependencies | None = None,
    default_organization_id: str = DEFAULT_ORGANIZATION_ID,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/equipment", tags=["refrigeration-structural-snapshot"])
    read_access = _access_dependency(
        security_dependencies,
        Permission.READ_DASHBOARD,
        default_organization_id,
    )

    @router.get(
        "/{equipment_id}/structural-snapshot",
        response_model=RefrigerationStructuralSnapshotResponse,
    )
    def get_structural_snapshot(
        equipment_id: str,
        authorized: AuthorizedRequest = Depends(read_access),
    ) -> RefrigerationStructuralSnapshotResponse:
        organization_id = authorized.principal.organization_id
        try:
            equipment = equipment_repository.get_active(
                equipment_id,
                organization_id=organization_id,
            )
            draft = layout_repository.get_or_create_draft(
                equipment_id,
                organization_id=organization_id,
            )
            bindings = lifecycle_repository.list_bindings(
                equipment_id,
                include_history=False,
                organization_id=organization_id,
            )
            if equipment.climate_chamber_id is not None:
                _, available_channels = (
                    sensor_configuration_repository.list_climate_chamber_channels(
                        equipment.climate_chamber_id,
                        organization_id=organization_id,
                    )
                )
            elif equipment.node_id is not None:
                _, available_channels = lifecycle_repository.list_available_sensors(
                    equipment_id,
                    organization_id=organization_id,
                )
            else:
                available_channels = []
        except EquipmentNotFoundError as error:
            raise HTTPException(
                status_code=404,
                detail={"code": error.code, "message": str(error)},
            ) from error
        except (
            EquipmentRepositoryError,
            EquipmentLifecycleRepositoryError,
            LayoutRepositoryError,
        ) as error:
            raise HTTPException(
                status_code=500,
                detail={
                    "code": getattr(error, "code", "structural_snapshot_error"),
                    "message": str(error),
                },
            ) from error

        layout = _draft_response(
            layout_repository,
            storage,
            draft,
            signed_url_seconds,
        )
        return RefrigerationStructuralSnapshotResponse(
            equipment=equipment_response(equipment),
            active_image=layout.image,
            layout=layout,
            layout_revision=draft.version,
            placements_count=len(draft.placements),
            bindings=[_binding_response(item) for item in bindings],
            channels=[
                StructuralChannelResponse(
                    channel_id=item.channel_id,
                    metric=item.metric,
                    unit=item.unit,
                    latest_value=item.latest_value,
                    quality=item.quality,
                    captured_at=item.captured_at,
                    sample_state=_sample_state(item.latest_value, item.quality),
                    is_bound=item.binding is not None,
                    bound_equipment_id=(
                        item.binding.equipment_id if item.binding is not None else None
                    ),
                    bound_slot_key=(
                        item.binding.slot_key if item.binding is not None else None
                    ),
                )
                for item in available_channels
            ],
            generated_at=datetime.now(UTC),
        )

    return router


def _sample_state(latest_value: float | None, quality: str) -> StructuralSampleState:
    if latest_value is None:
        return "unknown"
    if quality.strip().lower() not in {"good", "ok", "valid"}:
        return "stale"
    return "known"
