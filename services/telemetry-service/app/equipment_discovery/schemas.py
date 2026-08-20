from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class DiscoveryScanRequest(BaseModel):
    cidrs: list[str] | None = Field(default=None, max_length=16)
    ports: list[int] | None = Field(default=None, max_length=32)


class DiscoveryScanResponse(BaseModel):
    id: str
    status: Literal["running", "completed", "cancelled", "failed"]
    requested_cidrs: list[str]
    requested_ports: list[int]
    host_budget: int
    probe_budget: int
    hosts_considered: int
    probes_attempted: int
    responsive_hosts: int
    duration_ms: int
    process_cpu_ms: int
    network_connect_attempts: int
    network_payload_bytes: int
    trigger: Literal["manual", "scheduled"]
    new_candidates: int
    changed_candidates: int
    disappeared_candidates: int
    cancel_requested: bool
    requested_by: str
    started_at: datetime
    completed_at: datetime | None
    error_code: str | None
    error_message: str | None


class DiscoveryServiceEvidence(BaseModel):
    port: int
    transport: Literal["tcp"] = "tcp"
    service: str
    evidence: Literal["connect_succeeded"] = "connect_succeeded"


class DiscoveryCandidateResponse(BaseModel):
    id: str
    candidate_key: str
    ip_address: str
    mac_address: str | None
    hostname: str | None
    source_interface: str | None
    source_subnet: str
    lifecycle: Literal[
        "new",
        "reviewed",
        "matched_existing",
        "adopted",
        "ignored",
        "disappeared",
    ]
    present: bool
    first_seen_at: datetime
    last_seen_at: datetime
    last_scan_id: str
    linked_equipment_key: str | None
    version: int
    services: list[DiscoveryServiceEvidence]
    evidence: dict[str, object]
    changed_since_previous_scan: bool


class DiscoveryCandidateActionRequest(BaseModel):
    action: Literal["review", "ignore", "link_existing", "adopt"]
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    linked_equipment_key: str | None = Field(default=None, min_length=1, max_length=255)

    @model_validator(mode="after")
    def validate_action_payload(self) -> "DiscoveryCandidateActionRequest":
        if self.action == "link_existing" and not self.linked_equipment_key:
            raise ValueError("linked_equipment_key is required for link_existing")
        if self.action != "link_existing" and self.linked_equipment_key is not None:
            raise ValueError("linked_equipment_key is only valid for link_existing")
        if self.action != "adopt" and self.display_name is not None:
            raise ValueError("display_name is only valid for adopt")
        return self


class NetworkAssetResponse(BaseModel):
    id: str
    asset_key: str
    display_name: str
    ip_address: str
    mac_address: str | None
    manufacturer: str | None
    model: str | None
    source_candidate_id: str
    status: Literal["active", "inactive"]
    version: int
    created_by: str
    created_at: datetime
    updated_at: datetime


class DiscoveryPolicyResponse(BaseModel):
    enabled: bool
    allowed_cidrs: list[str]
    allowed_ports: list[int]
    max_hosts: int
    max_ports: int
    connect_timeout_seconds: float
    concurrency: int
    schedule_interval_seconds: int
    probe_mode: Literal["tcp-connect-only"] = "tcp-connect-only"
    payload_bytes_sent_per_probe: Literal[0] = 0


class DiscoveryOverviewResponse(BaseModel):
    policy: DiscoveryPolicyResponse
    active_scan: DiscoveryScanResponse | None
    last_scan: DiscoveryScanResponse | None
    candidates: list[DiscoveryCandidateResponse]
    network_assets: list[NetworkAssetResponse]


class DiscoveryCandidateActionResponse(BaseModel):
    candidate: DiscoveryCandidateResponse
    network_asset: NetworkAssetResponse | None = None
