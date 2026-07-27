from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.nodes.broker_control import BrokerControlOperation, BrokerControlState
from app.nodes.domain import NodeState


BrokerDesiredState = Literal["provisioned", "enabled", "disabled", "deleted"]
BrokerSynchronizationState = Literal[
    "disabled",
    "unknown",
    "pending",
    "processing",
    "retrying",
    "applied",
    "failed",
    "out_of_sync",
]


class BrokerControlCommandRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    operation: BrokerControlOperation
    state: BrokerControlState
    attempts: int
    available_at: datetime
    last_attempt_at: datetime | None
    applied_at: datetime | None
    failed_at: datetime | None
    error_code: str | None
    error_detail: str | None
    created_at: datetime
    updated_at: datetime


class NodeBrokerControlRead(BaseModel):
    node_id: str
    lifecycle_state: NodeState
    enabled: bool
    desired_state: BrokerDesiredState
    synchronization: BrokerSynchronizationState
    synchronized: bool
    latest_command: BrokerControlCommandRead | None
    commands: list[BrokerControlCommandRead]
