from __future__ import annotations

import asyncio
import logging

from app.equipment_discovery.policy import DiscoveryPolicy, ResolvedDiscoveryScope
from app.equipment_discovery.repository import (
    EquipmentDiscoveryRepository,
    ScanAlreadyRunningError,
)
from app.equipment_discovery.scanner import LocalLanDiscoveryScanner, ScanCancelledError
from app.security.authorization import Role
from app.security.repository import AuditEventInput


_LOGGER = logging.getLogger(__name__)
_SCHEDULED_ACTOR = "system:equipment-discovery-scheduler"


class EquipmentDiscoveryService:
    def __init__(
        self,
        repository: EquipmentDiscoveryRepository,
        policy: DiscoveryPolicy,
        *,
        scanner: LocalLanDiscoveryScanner | None = None,
        schedule_interval_seconds: int = 0,
        scheduled_organization_id: str | None = None,
    ) -> None:
        self._repository = repository
        self._policy = policy
        self._scanner = scanner or LocalLanDiscoveryScanner(
            connect_timeout_seconds=policy.connect_timeout_seconds,
            concurrency=policy.concurrency,
        )
        self._schedule_interval_seconds = schedule_interval_seconds
        self._scheduled_organization_id = scheduled_organization_id
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._scheduler_task: asyncio.Task[None] | None = None

    @property
    def policy(self) -> DiscoveryPolicy:
        return self._policy

    @property
    def schedule_interval_seconds(self) -> int:
        return self._schedule_interval_seconds

    def reconcile_interrupted_scans(self) -> int:
        return self._repository.reconcile_interrupted_scans()

    def start_scheduler(self) -> bool:
        if (
            self._schedule_interval_seconds <= 0
            or not self._policy.enabled
            or not self._scheduled_organization_id
        ):
            return False
        if self._scheduler_task is not None and not self._scheduler_task.done():
            return True
        self._scheduler_task = asyncio.get_running_loop().create_task(
            self._run_scheduler(),
            name="equipment-discovery-scheduler",
        )
        return True

    def launch(
        self,
        scan_id: str,
        *,
        organization_id: str,
        scope: ResolvedDiscoveryScope,
    ) -> None:
        task = asyncio.get_running_loop().create_task(
            self._run_scan(scan_id, organization_id=organization_id, scope=scope),
            name=f"equipment-discovery-{scan_id}",
        )
        self._tasks[scan_id] = task
        task.add_done_callback(lambda _: self._tasks.pop(scan_id, None))

    async def shutdown(self) -> None:
        if self._scheduler_task is not None:
            self._scheduler_task.cancel()
            await asyncio.gather(self._scheduler_task, return_exceptions=True)
            self._scheduler_task = None
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _run_scheduler(self) -> None:
        while True:
            await asyncio.sleep(self._schedule_interval_seconds)
            try:
                await self._run_scheduled_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                _LOGGER.exception("scheduled equipment discovery scan could not be created")

    async def _run_scheduled_once(self) -> bool:
        if not self._scheduled_organization_id or not self._policy.enabled:
            return False
        scope = self._policy.resolve()
        audit_event = AuditEventInput(
            organization_id=self._scheduled_organization_id,
            actor_identity_id=None,
            actor_subject=_SCHEDULED_ACTOR,
            actor_roles=frozenset({Role.ADMINISTRATOR}),
            action="equipment_discovery.scan_scheduled",
            entity_type="equipment_discovery_scan",
            entity_id="pending",
            reason="Low-frequency configured LOCAL_LAN discovery scan",
        )
        try:
            scan = await asyncio.to_thread(
                self._repository.start_scan,
                organization_id=self._scheduled_organization_id,
                requested_cidrs=scope.cidrs,
                requested_ports=scope.ports,
                host_budget=len(scope.addresses),
                probe_budget=scope.probe_budget,
                actor_subject=_SCHEDULED_ACTOR,
                audit_event=audit_event,
                trigger="scheduled",
            )
        except ScanAlreadyRunningError:
            return False
        self.launch(
            scan.id,
            organization_id=self._scheduled_organization_id,
            scope=scope,
        )
        return True

    async def _run_scan(
        self,
        scan_id: str,
        *,
        organization_id: str,
        scope: ResolvedDiscoveryScope,
    ) -> None:
        async def cancel_check() -> bool:
            return await asyncio.to_thread(
                self._repository.cancel_requested,
                scan_id,
                organization_id=organization_id,
            )

        try:
            result = await self._scanner.scan(scope, cancel_check=cancel_check)
            await asyncio.to_thread(
                self._repository.apply_scan_result,
                scan_id,
                organization_id=organization_id,
                result=result,
            )
        except ScanCancelledError:
            await asyncio.to_thread(
                self._repository.finish_cancelled,
                scan_id,
                organization_id=organization_id,
            )
        except asyncio.CancelledError:
            await asyncio.to_thread(
                self._repository.finish_failed,
                scan_id,
                organization_id=organization_id,
                error_code="equipment_discovery_service_stopped",
                error_message="Discovery service stopped before the scan completed",
            )
            raise
        except Exception as error:
            await asyncio.to_thread(
                self._repository.finish_failed,
                scan_id,
                organization_id=organization_id,
                error_code="equipment_discovery_scan_failed",
                error_message=str(error) or error.__class__.__name__,
            )
