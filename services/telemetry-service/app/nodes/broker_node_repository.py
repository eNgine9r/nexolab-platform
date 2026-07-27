from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.nodes.broker_control import BrokerControlOperation
from app.nodes.domain import NodeState, canonical_sha256, transition_node_state
from app.nodes.models import CentralNode
from app.nodes.repository import NodeRepository, _required_text
from app.security.authorization import Role


class BrokerSynchronizedNodeRepository(NodeRepository):
    """Node repository variant that closes the suspended-to-active broker gap.

    The base repository already writes provision, rotate, disable and delete commands in
    the lifecycle transaction. Reactivation needs an additional secret-free ENABLE
    command because a suspended Dynamic Security client remains disabled otherwise.
    """

    def for_organization(
        self,
        organization_id: str,
    ) -> "BrokerSynchronizedNodeRepository":
        normalized = _required_text(organization_id, "organization_id", 36)
        return BrokerSynchronizedNodeRepository(
            self._database,
            security_repository=self._security_repository,
            broker_control_repository=self._broker_control_repository,
            organization_id=normalized,
        )

    def activate(
        self,
        node_id: str,
        *,
        actor_subject: str,
        actor_identity_id: str | None,
        actor_roles: frozenset[Role],
        reason: str,
    ) -> CentralNode:
        normalized_reason = _required_text(reason, "reason", 1024)
        actor = _required_text(actor_subject, "actor_subject", 255)

        with Session(self._engine, expire_on_commit=False) as session:
            with session.begin():
                node = self._node_for_update(session, node_id)
                source = NodeState(node.state)
                if source is NodeState.ACTIVE:
                    session.expunge(node)
                    return node

                transition_node_state(source, NodeState.ACTIVE)
                now = datetime.now(UTC)
                before = {
                    "state": source.value,
                    "state_reason": node.state_reason,
                }
                node.state = NodeState.ACTIVE.value
                node.state_reason = normalized_reason
                node.updated_at = now
                session.flush()

                broker_pending = source is NodeState.SUSPENDED
                if broker_pending:
                    command_sha256 = canonical_sha256(
                        {
                            "operation": BrokerControlOperation.ENABLE.value,
                            "organization_id": node.organization_id,
                            "node_record_id": node.id,
                            "node_id": node.node_id,
                            "source_state": source.value,
                            "target_state": NodeState.ACTIVE.value,
                            "actor_subject": actor,
                            "reason": normalized_reason,
                            "transitioned_at": now.isoformat(),
                        }
                    )
                    self._enqueue_broker_command(
                        session,
                        node=node,
                        operation=BrokerControlOperation.ENABLE,
                        credential=None,
                        secret=None,
                        deduplication_key=(
                            f"node:{node.id}:state:active:{command_sha256[:24]}"
                        ),
                        command_sha256=command_sha256,
                        available_at=now,
                    )

                self._audit(
                    session,
                    node=node,
                    identity_id=actor_identity_id,
                    actor_subject=actor,
                    actor_roles=actor_roles,
                    action="node.active",
                    reason=normalized_reason,
                    before_snapshot=before,
                    after_snapshot={
                        "state": node.state,
                        "state_reason": node.state_reason,
                        **({"broker_sync": "pending"} if broker_pending else {}),
                    },
                )

            session.expunge(node)
            return node
