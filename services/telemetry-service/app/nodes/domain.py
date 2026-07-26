from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
from dataclasses import dataclass
from enum import StrEnum
from typing import Final


NODE_ID_PATTERN: Final = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?$")
PROVISIONING_SECRET_PREFIX: Final = "nxl_node_"
PBKDF2_ITERATIONS: Final = 210_000
DEFAULT_CLOCK_WARNING_MS: Final = 30_000
DEFAULT_CLOCK_CRITICAL_MS: Final = 120_000


class NodeDomainError(ValueError):
    code = "node_domain_error"


class NodeTopicAuthorizationError(NodeDomainError):
    code = "node_topic_not_owned"


class NodeStateTransitionError(NodeDomainError):
    code = "node_state_transition_invalid"


class NodeState(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    REVOKED = "revoked"


class ClockStatus(StrEnum):
    UNKNOWN = "unknown"
    OK = "ok"
    WARNING = "warning"
    CRITICAL = "critical"


class NodeTopicStream(StrEnum):
    TELEMETRY = "telemetry"
    HEALTH = "health"
    EVENTS = "events"
    STATUS = "status"


@dataclass(frozen=True, slots=True)
class ProvisionNodeCommand:
    node_id: str
    display_name: str
    idempotency_key: str
    actor_subject: str
    clock_warning_ms: int = DEFAULT_CLOCK_WARNING_MS
    clock_critical_ms: int = DEFAULT_CLOCK_CRITICAL_MS

    def __post_init__(self) -> None:
        normalize_node_id(self.node_id)
        _required_text(self.display_name, "display_name", 255)
        _required_text(self.idempotency_key, "idempotency_key", 128)
        _required_text(self.actor_subject, "actor_subject", 255)
        validate_clock_thresholds(self.clock_warning_ms, self.clock_critical_ms)

    @property
    def command_sha256(self) -> str:
        return canonical_sha256(
            {
                "action": "provision",
                "node_id": normalize_node_id(self.node_id),
                "display_name": self.display_name.strip(),
                "idempotency_key": self.idempotency_key.strip(),
                "actor_subject": self.actor_subject.strip(),
                "clock_warning_ms": self.clock_warning_ms,
                "clock_critical_ms": self.clock_critical_ms,
            }
        )


@dataclass(frozen=True, slots=True)
class RotateNodeCredentialCommand:
    node_id: str
    idempotency_key: str
    actor_subject: str
    reason: str

    def __post_init__(self) -> None:
        normalize_node_id(self.node_id)
        _required_text(self.idempotency_key, "idempotency_key", 128)
        _required_text(self.actor_subject, "actor_subject", 255)
        _required_text(self.reason, "reason", 1024)

    @property
    def command_sha256(self) -> str:
        return canonical_sha256(
            {
                "action": "rotate_credential",
                "node_id": normalize_node_id(self.node_id),
                "idempotency_key": self.idempotency_key.strip(),
                "actor_subject": self.actor_subject.strip(),
                "reason": self.reason.strip(),
            }
        )


def normalize_node_id(value: str) -> str:
    normalized = value.strip().lower()
    if not NODE_ID_PATTERN.fullmatch(normalized):
        raise NodeDomainError(
            "node_id must use lowercase letters, digits and internal hyphens (1..64 characters)"
        )
    return normalized


def validate_clock_thresholds(warning_ms: int, critical_ms: int) -> None:
    if warning_ms <= 0:
        raise NodeDomainError("clock_warning_ms must be positive")
    if critical_ms <= warning_ms:
        raise NodeDomainError("clock_critical_ms must be greater than clock_warning_ms")


def classify_clock_offset(
    offset_ms: int | None,
    *,
    warning_ms: int,
    critical_ms: int,
) -> ClockStatus:
    validate_clock_thresholds(warning_ms, critical_ms)
    if offset_ms is None:
        return ClockStatus.UNKNOWN
    absolute = abs(offset_ms)
    if absolute < warning_ms:
        return ClockStatus.OK
    if absolute < critical_ms:
        return ClockStatus.WARNING
    return ClockStatus.CRITICAL


def build_node_topic(
    organization_id: str,
    node_id: str,
    stream: NodeTopicStream | str,
) -> str:
    organization = _required_text(organization_id, "organization_id", 64)
    normalized_node = normalize_node_id(node_id)
    resolved_stream = NodeTopicStream(stream)
    return f"nexolab/v1/{organization}/{normalized_node}/{resolved_stream.value}"


def authorize_node_topic(
    *,
    organization_id: str,
    node_id: str,
    topic: str,
) -> NodeTopicStream:
    expected_prefix = f"nexolab/v1/{_required_text(organization_id, 'organization_id', 64)}/{normalize_node_id(node_id)}/"
    if "+" in topic or "#" in topic or not topic.startswith(expected_prefix):
        raise NodeTopicAuthorizationError("node may publish only to its own exact MQTT namespace")
    suffix = topic[len(expected_prefix) :]
    if "/" in suffix:
        raise NodeTopicAuthorizationError("node topic must contain exactly one stream segment")
    try:
        return NodeTopicStream(suffix)
    except ValueError as error:
        raise NodeTopicAuthorizationError("unsupported node MQTT stream") from error


def transition_node_state(current: NodeState | str, target: NodeState | str) -> NodeState:
    source = NodeState(current)
    destination = NodeState(target)
    allowed: dict[NodeState, frozenset[NodeState]] = {
        NodeState.PENDING: frozenset({NodeState.ACTIVE, NodeState.REVOKED}),
        NodeState.ACTIVE: frozenset({NodeState.SUSPENDED, NodeState.REVOKED}),
        NodeState.SUSPENDED: frozenset({NodeState.ACTIVE, NodeState.REVOKED}),
        NodeState.REVOKED: frozenset(),
    }
    if destination not in allowed[source]:
        raise NodeStateTransitionError(f"cannot transition node from {source.value} to {destination.value}")
    return destination


def generate_provisioning_secret() -> str:
    return f"{PROVISIONING_SECRET_PREFIX}{secrets.token_urlsafe(32)}"


def hash_provisioning_secret(secret: str, *, salt_hex: str | None = None) -> tuple[str, str, str]:
    normalized = _required_text(secret, "secret", 255)
    if not normalized.startswith(PROVISIONING_SECRET_PREFIX):
        raise NodeDomainError("invalid provisioning secret prefix")
    salt = secrets.token_bytes(32) if salt_hex is None else bytes.fromhex(salt_hex)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        normalized.encode("utf-8"),
        salt,
        PBKDF2_ITERATIONS,
    )
    fingerprint = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
    return salt.hex(), digest.hex(), fingerprint


def verify_provisioning_secret(secret: str, *, salt_hex: str, expected_hash_hex: str) -> bool:
    try:
        _, actual_hash, _ = hash_provisioning_secret(secret, salt_hex=salt_hex)
    except (NodeDomainError, ValueError):
        return False
    return hmac.compare_digest(actual_hash, expected_hash_hex)


def canonical_sha256(payload: dict[str, object]) -> str:
    content = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(content).hexdigest()


def _required_text(value: str, field: str, max_length: int) -> str:
    normalized = value.strip()
    if not normalized:
        raise NodeDomainError(f"{field} is required")
    if len(normalized) > max_length:
        raise NodeDomainError(f"{field} exceeds {max_length} characters")
    return normalized
