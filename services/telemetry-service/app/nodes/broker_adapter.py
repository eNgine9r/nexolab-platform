from __future__ import annotations

import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from app.nodes.broker_control import BrokerControlOperation
from app.nodes.broker_models import CentralNodeBrokerCommand


class BrokerControlAdapterError(RuntimeError):
    def __init__(self, code: str, detail: str, *, retryable: bool) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.retryable = retryable


@dataclass(frozen=True, slots=True)
class DynamicSecurityClientState:
    client_id: str
    disabled: bool
    roles: frozenset[str]


class DynamicSecurityAdminAdapter:
    """Apply broker-control commands through the hardened dynsec admin executable.

    Password material is written only to a mode-0600 temporary file, never placed in
    argv, environment variables, logs or exception messages. The executable is expected
    to implement the command contract from ``nexolab-dynsec-admin``.
    """

    def __init__(
        self,
        *,
        executable: str,
        broker_host: str,
        broker_port: int,
        admin_username: str,
        admin_client_id: str,
        admin_password_file: str,
        timeout_seconds: float,
    ) -> None:
        executable_path = Path(executable)
        password_path = Path(admin_password_file)
        if not executable_path.is_file() or not os.access(executable_path, os.X_OK):
            raise BrokerControlAdapterError(
                "broker_admin_unavailable",
                "broker administration executable is not available",
                retryable=False,
            )
        if not password_path.is_file() or not os.access(password_path, os.R_OK):
            raise BrokerControlAdapterError(
                "broker_admin_secret_unavailable",
                "broker administrator password file is not readable",
                retryable=False,
            )
        self._executable = str(executable_path)
        self._timeout_seconds = timeout_seconds
        self._environment = {
            "NEXOLAB_MQTT_BROKER_HOST": broker_host,
            "NEXOLAB_MQTT_BROKER_PORT": str(broker_port),
            "NEXOLAB_MQTT_ADMIN_USERNAME": _required(admin_username, "admin username"),
            "NEXOLAB_MQTT_ADMIN_CLIENT_ID": _required(
                admin_client_id,
                "admin client ID",
            ),
            "NEXOLAB_MQTT_ADMIN_PASSWORD_FILE": str(password_path),
        }

    def apply(self, command: CentralNodeBrokerCommand, secret: str | None) -> None:
        operation = BrokerControlOperation(command.operation)
        username = node_broker_username(command.organization_id, command.node_id)
        client_id = node_broker_client_id(command.organization_id, command.node_id)

        if operation is BrokerControlOperation.PROVISION:
            self._with_secret(
                secret,
                lambda secret_file: self._run_mutation(
                    "create-node",
                    username,
                    client_id,
                    command.organization_id,
                    command.node_id,
                    secret_file,
                ),
            )
            state = self._read_client(username)
            expected_role = node_broker_role(command.organization_id, command.node_id)
            if state.client_id != client_id or expected_role not in state.roles:
                raise BrokerControlAdapterError(
                    "broker_reconciliation_mismatch",
                    "broker client identity or role does not match the requested node",
                    retryable=False,
                )
            return

        if operation is BrokerControlOperation.ROTATE:
            self._with_secret(
                secret,
                lambda secret_file: self._run_mutation(
                    "rotate-password",
                    username,
                    secret_file,
                ),
            )
            state = self._read_client(username)
            if state.client_id != client_id:
                raise BrokerControlAdapterError(
                    "broker_reconciliation_mismatch",
                    "broker client ID does not match the requested node",
                    retryable=False,
                )
            return

        if secret is not None:
            raise BrokerControlAdapterError(
                "broker_command_invalid",
                "secret-free broker operation unexpectedly contained secret material",
                retryable=False,
            )

        if operation is BrokerControlOperation.ENABLE:
            self._run_mutation("enable-client", username)
            state = self._read_client(username)
            if state.client_id != client_id or state.disabled is not False:
                raise BrokerControlAdapterError(
                    "broker_reconciliation_mismatch",
                    "broker client was not enabled after the command",
                    retryable=True,
                )
            return

        if operation is BrokerControlOperation.DISABLE:
            self._run_mutation("disable-client", username)
            state = self._read_client(username)
            if state.client_id != client_id or state.disabled is not True:
                raise BrokerControlAdapterError(
                    "broker_reconciliation_mismatch",
                    "broker client was not disabled after the command",
                    retryable=True,
                )
            return

        if operation is BrokerControlOperation.DELETE:
            if not self._client_exists(username):
                return
            self._run_mutation("delete-client", username)
            if self._client_exists(username):
                raise BrokerControlAdapterError(
                    "broker_reconciliation_mismatch",
                    "broker client still exists after the delete command",
                    retryable=True,
                )
            return

        raise BrokerControlAdapterError(
            "broker_command_unsupported",
            "broker-control operation is not supported",
            retryable=False,
        )

    def _with_secret(self, secret: str | None, callback) -> None:
        if secret is None:
            raise BrokerControlAdapterError(
                "broker_command_invalid",
                "broker credential command is missing encrypted secret material",
                retryable=False,
            )
        descriptor, path = tempfile.mkstemp(prefix="nexolab-broker-secret-")
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(secret)
            callback(path)
        finally:
            try:
                os.unlink(path)
            except FileNotFoundError:
                pass

    def _run_mutation(self, *arguments: str) -> None:
        # Mutation output is intentionally ignored after a zero exit status. Each
        # lifecycle operation is followed by an independent, strictly parsed broker
        # state read, which is the authoritative reconciliation boundary.
        self._run(*arguments)

    def _read_client(self, username: str) -> DynamicSecurityClientState:
        result = self._run("get-client", username)
        return parse_dynamic_security_client(result.stdout)

    def _client_exists(self, username: str) -> bool:
        result = self._run("list-clients")
        clients = {line.strip() for line in result.stdout.splitlines() if line.strip()}
        return username in clients

    def _run(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        environment.update(self._environment)
        try:
            result = subprocess.run(
                [self._executable, *arguments],
                check=False,
                capture_output=True,
                text=True,
                timeout=self._timeout_seconds,
                env=environment,
            )
        except subprocess.TimeoutExpired as error:
            raise BrokerControlAdapterError(
                "broker_command_timeout",
                "broker administration command timed out",
                retryable=True,
            ) from error
        except OSError as error:
            raise BrokerControlAdapterError(
                "broker_admin_unavailable",
                "broker administration command could not be started",
                retryable=True,
            ) from error

        if result.returncode != 0:
            permanent = result.returncode in {64, 65, 66, 67, 68, 69, 70, 71}
            raise BrokerControlAdapterError(
                "broker_command_rejected" if permanent else "broker_unavailable",
                "broker administration command failed",
                retryable=not permanent,
            )
        return result


def parse_dynamic_security_client(output: str) -> DynamicSecurityClientState:
    client_id: str | None = None
    disabled: bool | None = None
    roles: set[str] = set()

    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("Clientid:"):
            client_id = line.partition(":")[2].strip()
            continue
        if line.startswith("Disabled:"):
            value = line.partition(":")[2].strip().lower()
            if value not in {"true", "false"}:
                raise BrokerControlAdapterError(
                    "broker_response_invalid",
                    "broker client disabled state is invalid",
                    retryable=False,
                )
            disabled = value == "true"
            continue
        if "(priority:" in line:
            role = line.split("(priority:", 1)[0].strip(" -\t")
            if role.startswith("Roles:"):
                role = role.partition(":")[2].strip()
            if role:
                roles.add(role)

    if client_id is None or not client_id:
        raise BrokerControlAdapterError(
            "broker_response_invalid",
            "broker client response did not contain an exact client ID",
            retryable=False,
        )
    # Mosquitto omits the optional ``disabled`` field for the normal enabled state.
    # An explicit true remains authoritative; absence therefore normalizes to false.
    return DynamicSecurityClientState(
        client_id=client_id,
        disabled=False if disabled is None else disabled,
        roles=frozenset(roles),
    )


def node_broker_username(organization_id: str, node_id: str) -> str:
    return f"node:{_required(organization_id, 'organization ID')}:{_required(node_id, 'node ID')}"


def node_broker_client_id(organization_id: str, node_id: str) -> str:
    return f"nexolab-{_required(organization_id, 'organization ID')}-{_required(node_id, 'node ID')}"


def node_broker_role(organization_id: str, node_id: str) -> str:
    return f"nexolab-node-{_required(organization_id, 'organization ID')}-{_required(node_id, 'node ID')}"


def _required(value: str, label: str) -> str:
    normalized = value.strip()
    if not normalized or any(character.isspace() for character in normalized):
        raise BrokerControlAdapterError(
            "broker_command_invalid",
            f"{label} is invalid",
            retryable=False,
        )
    return normalized
