from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.alerts.domain import (
    AlertRuleConfiguration,
    AlertState,
)
from app.alerts.models import (
    AlertInstance,
    AlertRule,
    AlertRuleVersion,
    AlertTransition,
)
from app.alerts.schemas import AlertLifecycleCommand, AlertRuleCreate
from app.db import Database
from app.sessions.models import TestSession


class AlertRepositoryError(RuntimeError):
    code = "alert_repository_error"


class AlertNotFoundError(AlertRepositoryError):
    code = "alert_not_found"


class AlertRuleNotFoundError(AlertRepositoryError):
    code = "alert_rule_not_found"


class AlertConflictError(AlertRepositoryError):
    code = "alert_conflict"


class AlertRuleConflictError(AlertRepositoryError):
    code = "alert_rule_conflict"


@dataclass(frozen=True, slots=True)
class Page:
    items: list[object]
    count: int
    limit: int
    offset: int

    @property
    def next_offset(self) -> int | None:
        candidate = self.offset + len(self.items)
        return candidate if candidate < self.count else None


@dataclass(frozen=True, slots=True)
class RuleRecord:
    rule: AlertRule
    version: AlertRuleVersion


@dataclass(frozen=True, slots=True)
class LifecycleResult:
    alert: AlertInstance
    transition: AlertTransition
    replayed: bool


class AlertRepository:
    def __init__(
        self,
        database: Database,
        *,
        organization_id: str | None = None,
    ) -> None:
        self._engine = database.engine
        self._database = database
        self._organization_id = organization_id

    def for_organization(self, organization_id: str) -> "AlertRepository":
        normalized = organization_id.strip()
        if not normalized:
            raise ValueError("organization_id is required")
        return AlertRepository(self._database, organization_id=normalized)

    def create_rule(
        self,
        payload: AlertRuleCreate,
        *,
        actor_id: str,
    ) -> RuleRecord:
        organization_id = self._scope()
        actor = actor_id.strip()
        if not actor:
            raise ValueError("actor_id is required")
        AlertRuleConfiguration(
            condition=payload.condition,
            trigger_threshold=payload.trigger_threshold,
            clear_threshold=payload.clear_threshold,
            minimum_duration_seconds=payload.minimum_duration_seconds,
            clear_duration_seconds=payload.clear_duration_seconds,
            debounce_seconds=payload.debounce_seconds,
            cooldown_seconds=payload.cooldown_seconds,
        )
        now = datetime.now(UTC)
        rule = AlertRule(
            id=str(uuid4()),
            organization_id=organization_id,
            name=payload.name,
            description=payload.description,
            enabled=True,
            severity=payload.severity.value,
            node_id=payload.node_id,
            equipment_id=payload.equipment_id,
            channel_id=payload.channel_id,
            metric=payload.metric,
            session_id=payload.session_id,
            current_version=1,
            created_by=actor,
            created_at=now,
            updated_at=now,
        )
        version = AlertRuleVersion(
            id=str(uuid4()),
            rule_id=rule.id,
            version=1,
            condition=payload.condition.value,
            trigger_threshold=payload.trigger_threshold,
            clear_threshold=payload.clear_threshold,
            minimum_duration_seconds=payload.minimum_duration_seconds,
            clear_duration_seconds=payload.clear_duration_seconds,
            debounce_seconds=payload.debounce_seconds,
            cooldown_seconds=payload.cooldown_seconds,
            configuration=payload.configuration,
            created_by=actor,
            created_at=now,
        )
        try:
            with Session(self._engine, expire_on_commit=False) as session:
                with session.begin():
                    if payload.session_id is not None:
                        self._require_session(session, payload.session_id)
                    session.add(rule)
                    session.add(version)
                session.expunge(rule)
                session.expunge(version)
        except IntegrityError as error:
            raise AlertRuleConflictError(
                f"alert rule {payload.name!r} already exists"
            ) from error
        return RuleRecord(rule=rule, version=version)

    def list_rules(
        self,
        *,
        enabled: bool | None,
        metric: str | None,
        limit: int,
        offset: int,
    ) -> Page:
        organization_id = self._scope()
        filters = [AlertRule.organization_id == organization_id]
        if enabled is not None:
            filters.append(AlertRule.enabled.is_(enabled))
        if metric is not None:
            filters.append(AlertRule.metric == metric)
        with Session(self._engine, expire_on_commit=False) as session:
            count = int(
                session.scalar(
                    select(func.count()).select_from(AlertRule).where(*filters)
                )
                or 0
            )
            rules = list(
                session.scalars(
                    select(AlertRule)
                    .where(*filters)
                    .order_by(AlertRule.created_at.desc(), AlertRule.id.desc())
                    .limit(limit)
                    .offset(offset)
                )
            )
            records: list[RuleRecord] = []
            for rule in rules:
                version = session.scalar(
                    select(AlertRuleVersion).where(
                        AlertRuleVersion.rule_id == rule.id,
                        AlertRuleVersion.version == rule.current_version,
                    )
                )
                if version is None:
                    raise AlertRepositoryError(
                        f"current version for alert rule {rule.id!r} is missing"
                    )
                session.expunge(rule)
                session.expunge(version)
                records.append(RuleRecord(rule=rule, version=version))
        return Page(items=list(records), count=count, limit=limit, offset=offset)

    def get_rule(self, rule_id: str) -> RuleRecord:
        organization_id = self._scope()
        with Session(self._engine, expire_on_commit=False) as session:
            rule = session.scalar(
                select(AlertRule).where(
                    AlertRule.id == rule_id,
                    AlertRule.organization_id == organization_id,
                )
            )
            if rule is None:
                raise AlertRuleNotFoundError(
                    f"alert rule {rule_id!r} was not found"
                )
            version = session.scalar(
                select(AlertRuleVersion).where(
                    AlertRuleVersion.rule_id == rule.id,
                    AlertRuleVersion.version == rule.current_version,
                )
            )
            if version is None:
                raise AlertRepositoryError(
                    f"current version for alert rule {rule.id!r} is missing"
                )
            session.expunge(rule)
            session.expunge(version)
            return RuleRecord(rule=rule, version=version)

    def list_alerts(
        self,
        *,
        state: AlertState | None,
        severity: str | None,
        metric: str | None,
        limit: int,
        offset: int,
    ) -> Page:
        organization_id = self._scope()
        filters = [AlertInstance.organization_id == organization_id]
        if state is not None:
            filters.append(AlertInstance.state == state.value)
        if severity is not None:
            filters.append(AlertInstance.severity == severity)
        if metric is not None:
            filters.append(AlertInstance.metric == metric)
        with Session(self._engine, expire_on_commit=False) as session:
            count = int(
                session.scalar(
                    select(func.count()).select_from(AlertInstance).where(*filters)
                )
                or 0
            )
            items = list(
                session.scalars(
                    select(AlertInstance)
                    .where(*filters)
                    .order_by(
                        AlertInstance.triggered_at.desc(),
                        AlertInstance.id.desc(),
                    )
                    .limit(limit)
                    .offset(offset)
                )
            )
            for item in items:
                session.expunge(item)
        return Page(items=list(items), count=count, limit=limit, offset=offset)

    def get_alert(self, alert_id: str) -> AlertInstance:
        organization_id = self._scope()
        with Session(self._engine, expire_on_commit=False) as session:
            alert = session.scalar(
                select(AlertInstance).where(
                    AlertInstance.id == alert_id,
                    AlertInstance.organization_id == organization_id,
                )
            )
            if alert is None:
                raise AlertNotFoundError(f"alert {alert_id!r} was not found")
            session.expunge(alert)
            return alert

    def transitions(
        self,
        alert_id: str,
        *,
        limit: int,
        offset: int,
    ) -> Page:
        organization_id = self._scope()
        with Session(self._engine, expire_on_commit=False) as session:
            self._locked_alert(
                session,
                organization_id,
                alert_id,
                lock=False,
            )
            base = select(AlertTransition).where(
                AlertTransition.alert_id == alert_id
            )
            count = int(
                session.scalar(
                    select(func.count())
                    .select_from(AlertTransition)
                    .where(AlertTransition.alert_id == alert_id)
                )
                or 0
            )
            items = list(
                session.scalars(
                    base.order_by(
                        AlertTransition.occurred_at.desc(),
                        AlertTransition.id.desc(),
                    )
                    .limit(limit)
                    .offset(offset)
                )
            )
            for item in items:
                session.expunge(item)
        return Page(items=list(items), count=count, limit=limit, offset=offset)

    def acknowledge(
        self,
        alert_id: str,
        payload: AlertLifecycleCommand,
        *,
        actor_id: str,
        actor_source: str,
        idempotency_key: str,
    ) -> LifecycleResult:
        return self._transition(
            alert_id,
            payload,
            actor_id=actor_id,
            actor_source=actor_source,
            idempotency_key=idempotency_key,
            action="acknowledged",
        )

    def close(
        self,
        alert_id: str,
        payload: AlertLifecycleCommand,
        *,
        actor_id: str,
        actor_source: str,
        idempotency_key: str,
    ) -> LifecycleResult:
        return self._transition(
            alert_id,
            payload,
            actor_id=actor_id,
            actor_source=actor_source,
            idempotency_key=idempotency_key,
            action="closed",
        )

    def _transition(
        self,
        alert_id: str,
        payload: AlertLifecycleCommand,
        *,
        actor_id: str,
        actor_source: str,
        idempotency_key: str,
        action: str,
    ) -> LifecycleResult:
        organization_id = self._scope()
        key = idempotency_key.strip()
        if not key:
            raise ValueError("idempotency_key is required")
        actor = actor_id.strip()
        source = actor_source.strip()
        if not actor or not source:
            raise ValueError("actor identity is required")
        with Session(self._engine, expire_on_commit=False) as session:
            with session.begin():
                alert = self._locked_alert(
                    session,
                    organization_id,
                    alert_id,
                    lock=True,
                )
                replay = session.scalar(
                    select(AlertTransition).where(
                        AlertTransition.alert_id == alert_id,
                        AlertTransition.idempotency_key == key,
                    )
                )
                if replay is not None:
                    session.expunge(alert)
                    session.expunge(replay)
                    return LifecycleResult(
                        alert=alert,
                        transition=replay,
                        replayed=True,
                    )

                previous_state = AlertState(alert.state)
                if action == "acknowledged":
                    if previous_state is not AlertState.ACTIVE:
                        raise AlertConflictError(
                            f"alert {alert_id!r} cannot be acknowledged from "
                            f"state {previous_state.value!r}"
                        )
                    next_state = AlertState.ACKNOWLEDGED
                    alert.acknowledged_at = payload.occurred_at
                elif action == "closed":
                    if previous_state is not AlertState.RESOLVED:
                        raise AlertConflictError(
                            f"alert {alert_id!r} cannot be closed from "
                            f"state {previous_state.value!r}"
                        )
                    next_state = AlertState.CLOSED
                    alert.closed_at = payload.occurred_at
                else:
                    raise ValueError(f"unsupported alert action {action!r}")

                alert.state = next_state.value
                alert.updated_at = payload.occurred_at
                alert.lock_version += 1
                transition = AlertTransition(
                    id=str(uuid4()),
                    alert_id=alert.id,
                    event_type=f"alert_{action}",
                    previous_state=previous_state.value,
                    next_state=next_state.value,
                    actor_id=actor,
                    actor_source=source,
                    reason=payload.reason,
                    idempotency_key=key,
                    payload={},
                    occurred_at=payload.occurred_at,
                )
                session.add(transition)
            session.expunge(alert)
            session.expunge(transition)
            return LifecycleResult(
                alert=alert,
                transition=transition,
                replayed=False,
            )

    def _scope(self) -> str:
        if self._organization_id is None:
            raise AlertRepositoryError("organization scope is required")
        return self._organization_id

    def _require_session(self, session: Session, session_id: str) -> None:
        organization_id = self._scope()
        exists = session.scalar(
            select(TestSession.id).where(
                TestSession.id == session_id,
                TestSession.organization_id == organization_id,
            )
        )
        if exists is None:
            raise AlertRuleNotFoundError(
                f"session {session_id!r} was not found"
            )

    @staticmethod
    def _locked_alert(
        session: Session,
        organization_id: str,
        alert_id: str,
        *,
        lock: bool,
    ) -> AlertInstance:
        statement = select(AlertInstance).where(
            AlertInstance.id == alert_id,
            AlertInstance.organization_id == organization_id,
        )
        if lock:
            statement = statement.with_for_update()
        alert = session.scalar(statement)
        if alert is None:
            raise AlertNotFoundError(f"alert {alert_id!r} was not found")
        return alert
