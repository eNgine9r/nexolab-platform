"""Persistent presentation names for commissioned temperature inputs.

This is deliberately independent from telemetry identity and the Device Agent.
"""
from __future__ import annotations

from datetime import UTC, datetime
from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import DateTime, ForeignKey, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.db import Base, Database
from app.nodes.domain import NodeState
from app.nodes.models import CentralNode
from app.refrigeration.commissioned_channels import (
    CommissionedTemperature,
    CommissionedTemperatureInventory,
    section_temperature,
)
from app.security.authorization import Permission
from app.security.dependencies import AuthorizedRequest, SecurityDependencies
from app.security.repository import AuditEventInput, SecurityRepository


class CommissionedChannelName(Base):
    __tablename__ = "commissioned_channel_names"

    organization_id: Mapped[str] = mapped_column(String(36), ForeignKey("security_organizations.id", ondelete="RESTRICT"), primary_key=True)
    node_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    channel_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


def default_channel_name(item: CommissionedTemperature) -> str:
    return f"{item.controller_label.split(' · ')[0]} · Вхід {item.input_number}"


class ChannelNameRequest(BaseModel):
    node_id: str = Field(min_length=1, max_length=64)
    display_name: str | None = Field(default=None, max_length=128)

    @field_validator("display_name")
    @classmethod
    def normalized_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = " ".join(value.split())
        if not value or any(ord(char) < 32 for char in value):
            raise ValueError("Display name must be nonempty printable text; use null to reset")
        return value


class ChannelNameResponse(BaseModel):
    node_id: str
    equipment_id: str
    channel_id: str
    controller_label: str
    input_number: int
    display_name: str
    custom_name: str | None = None


class ChannelNameCollection(BaseModel):
    state: str
    node_id: str | None = None
    items: list[ChannelNameResponse] = Field(default_factory=list)


class ChannelNameStore:
    def __init__(
        self,
        database: Database,
        *,
        read_commissioned: Callable[[], CommissionedTemperatureInventory | None] | None,
        commissioned_organization_id: str,
    ) -> None:
        self._engine = database.engine
        self._read = read_commissioned
        self._organization_id = commissioned_organization_id

    @staticmethod
    def _owns_active_node(session: Session, organization_id: str, node_id: str) -> bool:
        owners = session.execute(
            select(CentralNode.organization_id, CentralNode.state)
            .where(CentralNode.node_id == node_id).limit(2)
        ).all()
        return len(owners) == 1 and tuple(owners[0]) == (
            organization_id, NodeState.ACTIVE.value
        )

    def _inventory(self, organization_id: str) -> CommissionedTemperatureInventory | None:
        if self._read is None or organization_id != self._organization_id:
            return None
        return self._read()

    @staticmethod
    def _names(
        session: Session, organization_id: str, node_id: str, channel_ids: list[str]
    ) -> dict[str, str]:
        if not channel_ids:
            return {}
        rows = session.scalars(
            select(CommissionedChannelName).where(
                CommissionedChannelName.organization_id == organization_id,
                CommissionedChannelName.node_id == node_id,
                CommissionedChannelName.channel_id.in_(channel_ids),
            )
        )
        return {item.channel_id: item.display_name for item in rows}

    def get_names(
        self, organization_id: str, node_id: str, channel_ids: list[str]
    ) -> dict[str, str]:
        with Session(self._engine) as session:
            if not self._owns_active_node(session, organization_id, node_id):
                return {}
            return self._names(session, organization_id, node_id, channel_ids)

    def list(self, organization_id: str) -> ChannelNameCollection:
        inventory = self._inventory(organization_id)
        if inventory is None:
            return ChannelNameCollection(state="unavailable")
        with Session(self._engine) as session:
            if not self._owns_active_node(session, organization_id, inventory.node_id):
                return ChannelNameCollection(state="unavailable")
            labels = self._names(
                session, organization_id, inventory.node_id,
                [channel.channel_id for channel in inventory.channels],
            )
            return ChannelNameCollection(
                state="available",
                node_id=inventory.node_id,
                items=[
                    ChannelNameResponse(
                        node_id=inventory.node_id,
                        equipment_id=item.equipment_id,
                        channel_id=item.channel_id,
                        controller_label=item.controller_label,
                        input_number=item.input_number,
                        custom_name=labels.get(item.channel_id),
                        display_name=labels.get(item.channel_id) or default_channel_name(item),
                    )
                    for item in sorted(inventory.channels, key=lambda c: (c.equipment_id, c.input_number))
                ],
            )

    def set_name(
        self, organization_id: str, node_id: str, channel_id: str,
        display_name: str | None, audit_repository: SecurityRepository,
        audit_event: AuditEventInput,
    ) -> ChannelNameResponse:
        identity = section_temperature(channel_id)
        if identity is None:
            raise HTTPException(422, detail={"code": "invalid_channel_id", "message": "Only commissioned Dixell inputs can be renamed"})
        inventory = self._inventory(organization_id)
        if inventory is None:
            raise HTTPException(503, detail={"code": "commissioning_unavailable", "message": "Acquisition inventory is unavailable"})
        if inventory.node_id != node_id:
            raise HTTPException(404, detail={"code": "channel_not_found", "message": "Channel is not on the requested node"})
        item = next((entry for entry in inventory.channels if entry.channel_id == channel_id), None)
        if item is None:
            raise HTTPException(404, detail={"code": "channel_not_found", "message": "Channel is not commissioned"})
        with Session(self._engine, expire_on_commit=False) as session:
            with session.begin():
                if not self._owns_active_node(session, organization_id, node_id):
                    raise HTTPException(404, detail={"code": "node_not_found", "message": "Node not available"})
                key = (organization_id, node_id, channel_id)
                row = session.get(CommissionedChannelName, key, with_for_update=True)
                previous = row.display_name if row else None
                if display_name is None:
                    if row:
                        session.delete(row)
                elif row:
                    row.display_name = display_name
                    row.updated_at = datetime.now(UTC)
                else:
                    session.add(CommissionedChannelName(
                        organization_id=organization_id, node_id=node_id,
                        channel_id=channel_id, display_name=display_name,
                        updated_at=datetime.now(UTC),
                    ))
                if previous != display_name:
                    audit_repository.append_audit_event(
                        AuditEventInput(
                            organization_id=audit_event.organization_id,
                            actor_identity_id=audit_event.actor_identity_id,
                            actor_subject=audit_event.actor_subject,
                            actor_roles=audit_event.actor_roles,
                            action="equipment.channel_display_name.updated",
                            entity_type="commissioned_channel",
                            entity_id=f"{node_id}/{channel_id}",
                            before_snapshot={"display_name": previous},
                            after_snapshot={"display_name": display_name},
                            request_id=audit_event.request_id,
                            source_ip=audit_event.source_ip,
                            user_agent=audit_event.user_agent,
                        ), session=session,
                    )
        return ChannelNameResponse(
            node_id=node_id, equipment_id=item.equipment_id,
            channel_id=channel_id, controller_label=item.controller_label,
            input_number=item.input_number,
            display_name=display_name or default_channel_name(item),
            custom_name=display_name,
        )


def create_channel_names_router(
    store: ChannelNameStore,
    security_dependencies: SecurityDependencies,
    security_repository: SecurityRepository,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/equipment/commissioned-channels", tags=["equipment-channel-names"])
    read_access = security_dependencies.authorized_request(Permission.READ_DASHBOARD)
    write_access = security_dependencies.authorized_request(Permission.MANAGE_EQUIPMENT)

    @router.get("", response_model=ChannelNameCollection)
    def list_channels(
        authorized: AuthorizedRequest = Depends(read_access),
    ) -> ChannelNameCollection:
        return store.list(authorized.principal.organization_id)

    @router.put("/{channel_id}/display-name", response_model=ChannelNameResponse)
    def update_channel(
        channel_id: str,
        payload: ChannelNameRequest,
        request: Request,
        authorized: AuthorizedRequest = Depends(write_access),
    ) -> ChannelNameResponse:
        return store.set_name(
            authorized.principal.organization_id, payload.node_id,
            channel_id, payload.display_name,
            security_repository,
            AuditEventInput(
                organization_id=authorized.principal.organization_id,
                actor_identity_id=authorized.identity_id,
                actor_subject=authorized.principal.subject,
                actor_roles=authorized.principal.roles,
                action="equipment.channel_display_name.updated",
                entity_type="commissioned_channel",
                entity_id=channel_id,
                request_id=request.headers.get("X-Request-ID"),
                source_ip=request.client.host if request.client else None,
                user_agent=request.headers.get("User-Agent"),
            ),
        )

    return router
