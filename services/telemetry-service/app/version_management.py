from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.security.authorization import Permission
from app.security.dependencies import AuthorizedRequest, SecurityDependencies
from app.security.repository import AuditEventInput, SecurityRepository


SHA = re.compile(r"^[0-9a-f]{40}$")
BUNDLE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
UPDATE_POLICY_SCHEMA = 1
UPDATE_CHECK_REQUEST_SCHEMA = 1
UPDATE_SCHEDULE_LOCAL_TIME = "02:00"


class VersionActionRequest(BaseModel):
    action: Literal["update", "rollback"]
    target_bundle_id: str = Field(min_length=1, max_length=128)
    confirmation: str = Field(min_length=1, max_length=160)
    reason: str | None = Field(default=None, max_length=1024)


class UpdatePolicyRequest(BaseModel):
    automatic_updates_enabled: bool


class UpdateCheckRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=1024)


@dataclass(frozen=True, slots=True)
class VersionCatalogEntry:
    bundle_id: str
    release: str
    source_commit: str
    created_at: str
    platform: str
    schema_head: str
    upgrade_from: tuple[str, ...]
    runtime_compatible_schema_heads: tuple[str, ...]
    manifest_sha256: str
    bundle_root: str

    def payload(self) -> dict[str, Any]:
        return {
            "bundle_id": self.bundle_id,
            "release": self.release,
            "source_commit": self.source_commit,
            "created_at": self.created_at,
            "platform": self.platform,
            "schema_head": self.schema_head,
            "upgrade_from": list(self.upgrade_from),
            "runtime_compatible_schema_heads": list(
                self.runtime_compatible_schema_heads
            ),
            "manifest_sha256": self.manifest_sha256,
            "validated": True,
        }


class VersionManagementStore:
    """Durable bounded handoff between the API and privileged host workers."""

    def __init__(self, root: str | Path, *, catalog_limit: int = 20) -> None:
        self.root = Path(root)
        self.catalog_limit = catalog_limit

    def snapshot(self) -> dict[str, Any]:
        current = self._read_optional_json(self.root / "current.json")
        catalog, rejected = self._catalog()
        operations = self._operations()
        current_bundle_id = _optional_text(current, "bundle_id") if current else None
        current_catalog_entry = next(
            (item for item in catalog if item.bundle_id == current_bundle_id),
            None,
        )
        known = bool(
            current
            and current_catalog_entry
            and current.get("runtime_state_known", True) is True
            and current.get("release") == current_catalog_entry.release
            and current.get("source_commit") == current_catalog_entry.source_commit
            and current.get("platform") == current_catalog_entry.platform
        )
        return {
            "current": self._current_payload(current, known),
            "catalog": [item.payload() for item in catalog],
            "rejected_packages": rejected,
            "history": operations,
            "active_operation": next(
                (
                    item
                    for item in operations
                    if item.get("status") in {"queued", "running"}
                ),
                None,
            ),
            "update_policy": self._update_policy(),
            "update_check": self._update_check(),
            "offline": True,
            "catalog_limit": self.catalog_limit,
        }

    def set_update_policy(
        self,
        enabled: bool,
        authorized: AuthorizedRequest,
        *,
        before_publish: Callable[[dict[str, Any], dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        self.root.mkdir(parents=True, exist_ok=True, mode=0o750)
        with (self.root / "update-plane.lock").open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            previous = self._update_policy()
            policy = {
                "schema_version": UPDATE_POLICY_SCHEMA,
                "automatic_updates_enabled": enabled,
                "schedule_local_time": UPDATE_SCHEDULE_LOCAL_TIME,
                "updated_at": _now(),
                "updated_by": authorized.principal.subject,
                "error_code": None,
            }
            if before_publish is not None:
                before_publish(previous, policy)
            self._atomic_json(self.root / "update-policy.json", policy)
            return policy

    def enqueue_update_check(
        self,
        authorized: AuthorizedRequest,
        *,
        reason: str | None = None,
        before_publish: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        self.root.mkdir(parents=True, exist_ok=True, mode=0o750)
        with (self.root / "update-plane.lock").open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            snapshot = self.snapshot()
            if snapshot["active_operation"] is not None:
                raise VersionManagementError(
                    "operation_in_progress",
                    "A version update or rollback is active; update discovery is temporarily unavailable",
                )
            if any((self.root / "update-check-requests").glob("*.json")):
                raise VersionManagementError(
                    "update_check_in_progress",
                    "An update check is already queued",
                )
            current_check = snapshot["update_check"]
            if current_check and current_check.get("status") == "checking":
                raise VersionManagementError(
                    "update_check_in_progress",
                    "An update check is already running",
                )
            request_id = str(uuid4())
            check_request = {
                "schema_version": UPDATE_CHECK_REQUEST_SCHEMA,
                "id": request_id,
                "organization_id": authorized.principal.organization_id,
                "actor_subject": authorized.principal.subject,
                "source": "manual",
                "status": "queued",
                "requested_at": _now(),
                "reason": reason.strip() if reason and reason.strip() else None,
            }
            if before_publish is not None:
                before_publish(check_request)
            self._atomic_json(
                self.root / "update-check-requests" / f"{request_id}.json",
                check_request,
            )
            return check_request

    def enqueue(
        self,
        payload: VersionActionRequest,
        authorized: AuthorizedRequest,
        *,
        before_publish: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        self.root.mkdir(parents=True, exist_ok=True, mode=0o750)
        with (self.root / "queue.lock").open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            return self._enqueue_locked(payload, authorized, before_publish)

    def _enqueue_locked(
        self,
        payload: VersionActionRequest,
        authorized: AuthorizedRequest,
        before_publish: Callable[[dict[str, Any]], None] | None,
    ) -> dict[str, Any]:
        target_id = payload.target_bundle_id.strip()
        if not BUNDLE_ID.fullmatch(target_id):
            raise VersionManagementError("invalid_bundle_id", "Invalid bundle identifier")
        expected_confirmation = (
            f"APPLY {target_id}" if payload.action == "update" else f"ROLLBACK {target_id}"
        )
        if payload.confirmation != expected_confirmation:
            raise VersionManagementError(
                "confirmation_mismatch",
                f"Confirmation must exactly match {expected_confirmation!r}",
            )

        snapshot = self.snapshot()
        if snapshot["active_operation"] is not None:
            raise VersionManagementError(
                "operation_in_progress", "Another version operation is active"
            )
        current = snapshot["current"]
        if current is None or not current["known_packaged_release"]:
            raise VersionManagementError(
                "current_release_unverified",
                "Current deployment is not bound to a validated local package",
            )
        target = next(
            (item for item in snapshot["catalog"] if item["bundle_id"] == target_id),
            None,
        )
        if target is None:
            raise VersionManagementError(
                "target_release_unverified", "Target is not a validated local package"
            )
        if target["platform"] != current["platform"]:
            raise VersionManagementError(
                "platform_incompatible", "Target package platform does not match runtime"
            )
        if target_id == current["bundle_id"]:
            raise VersionManagementError(
                "target_is_current", "Target package is already deployed"
            )

        current_schema = current["schema_head"]
        if payload.action == "update":
            compatible = current_schema in target["upgrade_from"]
        else:
            if target_id != current.get("previous_bundle_id"):
                raise VersionManagementError(
                    "rollback_target_not_previous",
                    "Rollback is limited to the explicit previous known-good package",
                )
            compatible = current_schema in target["runtime_compatible_schema_heads"]
        if not compatible:
            raise VersionManagementError(
                "schema_compatibility_unknown",
                "Target does not explicitly declare compatibility with the current schema",
            )

        operation_id = str(uuid4())
        now = _now()
        operation = {
            "schema_version": 1,
            "id": operation_id,
            "organization_id": authorized.principal.organization_id,
            "actor_subject": authorized.principal.subject,
            "action": payload.action,
            "source_bundle_id": current["bundle_id"],
            "source_release": current["release"],
            "target_bundle_id": target_id,
            "target_release": target["release"],
            "target_commit": target["source_commit"],
            "status": "queued",
            "started_at": now,
            "ended_at": None,
            "backup_evidence_id": None,
            "result_code": None,
            "reason": payload.reason.strip() if payload.reason else None,
        }
        if before_publish is not None:
            before_publish(operation)
        self._atomic_json(self.root / "requests" / f"{operation_id}.json", operation)
        self._atomic_json(self.root / "operations" / f"{operation_id}.json", operation)
        return operation

    def _update_policy(self) -> dict[str, Any]:
        payload = self._read_optional_json(self.root / "update-policy.json")
        default = {
            "schema_version": UPDATE_POLICY_SCHEMA,
            "automatic_updates_enabled": False,
            "schedule_local_time": UPDATE_SCHEDULE_LOCAL_TIME,
            "updated_at": None,
            "updated_by": None,
            "error_code": None,
        }
        if payload is None:
            return default
        try:
            if payload.get("schema_version") != UPDATE_POLICY_SCHEMA:
                raise ValueError("unsupported update policy schema")
            if not isinstance(payload.get("automatic_updates_enabled"), bool):
                raise ValueError("automatic update policy must be boolean")
            if payload.get("schedule_local_time") != UPDATE_SCHEDULE_LOCAL_TIME:
                raise ValueError("automatic update schedule must remain fixed at 02:00")
            return {
                **default,
                "automatic_updates_enabled": payload["automatic_updates_enabled"],
                "updated_at": _optional_text(payload, "updated_at"),
                "updated_by": _optional_text(payload, "updated_by"),
            }
        except ValueError:
            return {**default, "error_code": "invalid_update_policy"}

    def _update_check(self) -> dict[str, Any] | None:
        payload = self._read_optional_json(self.root / "update-check.json")
        if payload is None:
            return None
        if payload.get("schema_version") != 1 or not isinstance(payload.get("status"), str):
            return {
                "schema_version": 1,
                "status": "failed",
                "source": "host",
                "actor": "system:update-plane",
                "started_at": None,
                "completed_at": None,
                "result_code": "invalid_update_check_state",
                "message": "Host update-check state is invalid.",
                "current_commit": None,
                "target_commit": None,
                "candidate_available": False,
                "activation_eligible": False,
                "blocked_reason": "invalid_update_check_state",
            }
        return payload

    def _catalog(self) -> tuple[list[VersionCatalogEntry], list[dict[str, str]]]:
        entries: list[VersionCatalogEntry] = []
        rejected: list[dict[str, str]] = []
        catalog_root = self.root / "catalog"
        if not catalog_root.is_dir():
            return entries, rejected
        for manifest_path in sorted(catalog_root.glob("*/manifest.json")):
            try:
                entries.append(_parse_manifest(manifest_path))
            except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
                rejected.append(
                    {
                        "directory": manifest_path.parent.name,
                        "code": "invalid_package_manifest",
                        "message": "Package manifest or host validation marker failed verification.",
                    }
                )
        entries.sort(key=lambda item: (item.created_at, item.bundle_id), reverse=True)
        return entries[: self.catalog_limit], rejected[: self.catalog_limit]

    def _operations(self) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for path in (self.root / "operations").glob("*.json"):
            try:
                payload = self._read_json(path)
                if payload.get("schema_version") == 1:
                    result.append(payload)
            except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
                continue
        result.sort(key=lambda item: str(item.get("started_at", "")), reverse=True)
        return result[:100]

    def _current_payload(
        self, current: dict[str, Any] | None, known: bool
    ) -> dict[str, Any] | None:
        if current is None:
            return None
        required = (
            "bundle_id",
            "release",
            "source_commit",
            "build_timestamp",
            "runtime_mode",
            "platform",
            "schema_head",
            "deployed_at",
            "health",
        )
        if any(key not in current for key in required):
            return None
        return {
            key: current.get(key)
            for key in (
                *required,
                "previous_bundle_id",
                "previous_release",
                "last_operation_id",
            )
        } | {
            "known_packaged_release": known,
            "runtime_state_known": current.get("runtime_state_known", True) is True,
        }

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError(f"{path} must contain an object")
        return payload

    def _read_optional_json(self, path: Path) -> dict[str, Any] | None:
        try:
            return self._read_json(path)
        except FileNotFoundError:
            return None
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
            return None

    @staticmethod
    def _atomic_json(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o750)
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o640)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False, sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink()


class VersionManagementError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def create_version_management_router(
    store: VersionManagementStore,
    dependencies: SecurityDependencies,
    security_repository: SecurityRepository,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/system/version", tags=["version-management"])
    access = dependencies.authorized_request(Permission.MANAGE_PROJECT_VERSIONS)

    def authenticated_access(
        authorized: AuthorizedRequest = Depends(access),
    ) -> AuthorizedRequest:
        if not dependencies.authentication_required:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "code": "authenticated_administrator_required",
                    "message": "Version management requires authenticated administrator mode",
                },
            )
        return authorized

    @router.get("")
    def read_version(_: AuthorizedRequest = Depends(authenticated_access)) -> dict[str, Any]:
        return store.snapshot()

    @router.put("/update/policy")
    def set_update_policy(
        payload: UpdatePolicyRequest,
        request: Request,
        authorized: AuthorizedRequest = Depends(authenticated_access),
    ) -> dict[str, Any]:
        def audit_before_publish(previous: dict[str, Any], policy: dict[str, Any]) -> None:
            security_repository.append_audit_event(
                AuditEventInput(
                    organization_id=authorized.principal.organization_id,
                    actor_identity_id=authorized.identity_id,
                    actor_subject=authorized.principal.subject,
                    actor_roles=authorized.principal.roles,
                    action="project_version.update_policy.set",
                    entity_type="project_version_update_policy",
                    entity_id="automatic-updates",
                    before_snapshot={
                        "automatic_updates_enabled": previous["automatic_updates_enabled"],
                        "schedule_local_time": previous["schedule_local_time"],
                    },
                    after_snapshot={
                        "automatic_updates_enabled": policy["automatic_updates_enabled"],
                        "schedule_local_time": policy["schedule_local_time"],
                    },
                    request_id=request.headers.get("X-Request-ID"),
                    source_ip=request.client.host if request.client else None,
                    user_agent=request.headers.get("User-Agent"),
                )
            )

        return store.set_update_policy(
            payload.automatic_updates_enabled,
            authorized,
            before_publish=audit_before_publish,
        )

    @router.post("/update/checks", status_code=status.HTTP_202_ACCEPTED)
    def request_update_check(
        payload: UpdateCheckRequest,
        request: Request,
        authorized: AuthorizedRequest = Depends(authenticated_access),
    ) -> dict[str, Any]:
        def audit_before_publish(check_request: dict[str, Any]) -> None:
            security_repository.append_audit_event(
                AuditEventInput(
                    organization_id=authorized.principal.organization_id,
                    actor_identity_id=authorized.identity_id,
                    actor_subject=authorized.principal.subject,
                    actor_roles=authorized.principal.roles,
                    action="project_version.update_check.requested",
                    entity_type="project_version_update_check",
                    entity_id=check_request["id"],
                    after_snapshot={
                        "source": "manual",
                        "status": "queued",
                    },
                    reason=payload.reason,
                    request_id=request.headers.get("X-Request-ID"),
                    source_ip=request.client.host if request.client else None,
                    user_agent=request.headers.get("User-Agent"),
                )
            )

        try:
            return store.enqueue_update_check(
                authorized,
                reason=payload.reason,
                before_publish=audit_before_publish,
            )
        except VersionManagementError as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": error.code, "message": str(error)},
            ) from error

    @router.post("/actions", status_code=status.HTTP_202_ACCEPTED)
    def request_action(
        payload: VersionActionRequest,
        request: Request,
        authorized: AuthorizedRequest = Depends(authenticated_access),
    ) -> dict[str, Any]:
        def audit_before_publish(operation: dict[str, Any]) -> None:
            security_repository.append_audit_event(
                AuditEventInput(
                    organization_id=authorized.principal.organization_id,
                    actor_identity_id=authorized.identity_id,
                    actor_subject=authorized.principal.subject,
                    actor_roles=authorized.principal.roles,
                    action=f"project_version.{payload.action}.requested",
                    entity_type="project_version_operation",
                    entity_id=operation["id"],
                    before_snapshot={
                        "bundle_id": operation["source_bundle_id"],
                        "release": operation["source_release"],
                    },
                    after_snapshot={
                        "bundle_id": operation["target_bundle_id"],
                        "release": operation["target_release"],
                        "commit": operation["target_commit"],
                        "status": "queued",
                    },
                    reason=payload.reason,
                    request_id=request.headers.get("X-Request-ID"),
                    source_ip=request.client.host if request.client else None,
                    user_agent=request.headers.get("User-Agent"),
                )
            )

        try:
            operation = store.enqueue(
                payload,
                authorized,
                before_publish=audit_before_publish,
            )
        except VersionManagementError as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": error.code, "message": str(error)},
            ) from error
        return operation

    return router


def _parse_manifest(path: Path) -> VersionCatalogEntry:
    raw = path.read_bytes()
    manifest_digest = hashlib.sha256(raw).hexdigest()
    validation = json.loads((path.parent / ".nexolab-validated.json").read_text(encoding="utf-8"))
    if not isinstance(validation, dict) or validation.get("manifest_sha256") != manifest_digest:
        raise ValueError("host validation marker does not match the package manifest")
    payload = json.loads(raw)
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise ValueError("unsupported offline manifest schema")
    policy = payload.get("persistent_data_policy")
    if not isinstance(policy, dict) or any(
        policy.get(key) is not expected
        for key, expected in (
            ("packaged", False),
            ("delete_volumes", False),
            ("compose_down_v_allowed", False),
        )
    ):
        raise ValueError("unsafe persistent-data policy")
    management = payload.get("version_management")
    if not isinstance(management, dict):
        raise ValueError("version_management compatibility metadata is required")
    schema = management.get("database_schema")
    if not isinstance(schema, dict):
        raise ValueError("database_schema compatibility metadata is required")
    bundle_id = _required_string(management, "bundle_id")
    commit = _required_string(payload, "source_commit")
    if not BUNDLE_ID.fullmatch(bundle_id) or not SHA.fullmatch(commit):
        raise ValueError("invalid bundle identity")
    if path.parent.name != bundle_id:
        raise ValueError("catalog directory does not match bundle identity")
    return VersionCatalogEntry(
        bundle_id=bundle_id,
        release=_required_string(payload, "bundle_version"),
        source_commit=commit,
        created_at=_required_string(payload, "created_at"),
        platform=_required_string(payload, "platform"),
        schema_head=_required_string(schema, "head"),
        upgrade_from=_string_tuple(schema, "upgrade_from"),
        runtime_compatible_schema_heads=_string_tuple(
            schema, "runtime_compatible_schema_heads"
        ),
        manifest_sha256=manifest_digest,
        bundle_root=str(path.parent.resolve()),
    )


def _required_string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value.strip()


def _string_tuple(payload: dict[str, Any], key: str) -> tuple[str, ...]:
    value = payload.get(key)
    if not isinstance(value, list) or not value or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise ValueError(f"{key} must be a non-empty string array")
    return tuple(sorted(set(item.strip() for item in value)))


def _optional_text(payload: dict[str, Any] | None, key: str) -> str | None:
    value = payload.get(key) if payload else None
    return value.strip() if isinstance(value, str) and value.strip() else None


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
