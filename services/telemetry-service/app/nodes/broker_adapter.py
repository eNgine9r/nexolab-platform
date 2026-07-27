from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

import paho.mqtt.client as mqtt

from app.nodes.broker_models import CentralNodeBrokerCommand


_REQUEST_TOPIC = "$CONTROL/dynamic-security/v1"
_RESPONSE_TOPIC = "$CONTROL/dynamic-security/v1/response"


class BrokerControlError(RuntimeError):
    code = "broker_control_error"
    retryable = True


class BrokerControlUnavailableError(BrokerControlError):
    code = "broker_control_unavailable"


class BrokerControlCommandError(BrokerControlError):
    code = "broker_control_command_failed"


class BrokerControlPermanentError(BrokerControlError):
    code = "broker_control_permanent_failure"
    retryable = False


class BrokerControlAdapter(Protocol):
    def apply(self, command: CentralNodeBrokerCommand, *, secret: str | None) -> None: ...


@dataclass(frozen=True, slots=True)
class DynamicSecurityResponse:
    command: str
    data: dict[str, Any] | None
    error: str | None


class MosquittoDynamicSecurityAdapter:
    def __init__(
        self,
        *,
        host: str,
        port: int,
        username: str,
        password_file: str,
        client_id: str = "nexolab-broker-control",
        timeout_seconds: float = 8.0,
        keepalive_seconds: int = 30,
    ) -> None:
        self._host = _required_text(host, "broker control host", 255)
        if port < 1 or port > 65535:
            raise ValueError("broker control port is invalid")
        self._port = port
        self._username = _required_text(username, "broker control username", 255)
        self._password_file = _required_text(
            password_file, "broker control password file", 1024
        )
        self._client_id = _required_text(client_id, "broker control client id", 255)
        if timeout_seconds <= 0:
            raise ValueError("broker control timeout must be positive")
        self._timeout_seconds = timeout_seconds
        self._keepalive_seconds = keepalive_seconds

    def apply(self, command: CentralNodeBrokerCommand, *, secret: str | None) -> None:
        if command.command_type == "upsert_credential":
            if secret is None:
                raise BrokerControlPermanentError(
                    "broker credential command has no decrypted secret"
                )
            self._upsert_credential(command, secret)
            return
        if secret is not None:
            raise BrokerControlPermanentError(
                "broker lifecycle command unexpectedly contains secret material"
            )
        if command.command_type == "disable_client":
            self._set_enabled(command.username, enabled=False, missing_ok=True)
            return
        if command.command_type == "enable_client":
            self._set_enabled(command.username, enabled=True, missing_ok=False)
            return
        raise BrokerControlPermanentError(
            f"unsupported broker command type: {command.command_type}"
        )

    def _upsert_credential(
        self,
        command: CentralNodeBrokerCommand,
        secret: str,
    ) -> None:
        role_name = f"nexolab-node-{command.organization_id}-{_node_id(command.username)}"
        topics = tuple(
            f"nexolab/v1/{command.organization_id}/{_node_id(command.username)}/{stream}"
            for stream in ("telemetry", "health", "status")
        )
        self._reconcile_role(role_name, topics)
        client = self._get_client(command.username)
        if client is None:
            self._expect_success(
                {
                    "command": "createClient",
                    "username": command.username,
                    "password": secret,
                    "clientid": command.client_id,
                }
            )
            client = self._get_client(command.username)
            if client is None:
                raise BrokerControlPermanentError(
                    "broker did not persist the created client"
                )
        client_id = client.get("clientid")
        if client_id != command.client_id:
            raise BrokerControlPermanentError(
                "broker client id does not match Node Registry identity"
            )
        self._expect_success(
            {
                "command": "setClientPassword",
                "username": command.username,
                "password": secret,
            }
        )
        roles = client.get("roles")
        role_names = {
            item.get("rolename")
            for item in roles
            if isinstance(item, dict) and isinstance(item.get("rolename"), str)
        } if isinstance(roles, list) else set()
        if role_name not in role_names:
            response = self._request(
                {
                    "command": "addClientRole",
                    "username": command.username,
                    "rolename": role_name,
                    "priority": 100,
                }
            )
            if response.error and not _already_exists(response.error):
                raise BrokerControlCommandError(_safe_broker_error(response.error))
        self._set_enabled(
            command.username,
            enabled=command.desired_enabled,
            missing_ok=False,
        )

    def _reconcile_role(self, role_name: str, topics: tuple[str, ...]) -> None:
        role = self._get_role(role_name)
        if role is None:
            self._expect_success(
                {"command": "createRole", "rolename": role_name}
            )
            role = self._get_role(role_name)
            if role is None:
                raise BrokerControlPermanentError(
                    "broker did not persist the created role"
                )
        existing_acls = role.get("acls")
        if not isinstance(existing_acls, list):
            existing_acls = []
        desired = {
            ("publishClientSend", topic, True, 100)
            for topic in topics
        }
        current: set[tuple[str, str, bool, int]] = set()
        for item in existing_acls:
            if not isinstance(item, dict):
                raise BrokerControlPermanentError("broker role ACL response is malformed")
            acltype = item.get("acltype")
            topic = item.get("topic")
            allow = item.get("allow")
            priority = item.get("priority", -1)
            if not isinstance(acltype, str) or not isinstance(topic, str):
                raise BrokerControlPermanentError("broker role ACL response is malformed")
            if not isinstance(allow, bool) or not isinstance(priority, int):
                raise BrokerControlPermanentError("broker role ACL response is malformed")
            current.add((acltype, topic, allow, priority))
        for acltype, topic, _allow, _priority in sorted(current - desired):
            response = self._request(
                {
                    "command": "removeRoleACL",
                    "rolename": role_name,
                    "acltype": acltype,
                    "topic": topic,
                }
            )
            if response.error and not _not_found(response.error):
                raise BrokerControlCommandError(_safe_broker_error(response.error))
        for acltype, topic, allow, priority in sorted(desired - current):
            response = self._request(
                {
                    "command": "addRoleACL",
                    "rolename": role_name,
                    "acltype": acltype,
                    "topic": topic,
                    "allow": allow,
                    "priority": priority,
                }
            )
            if response.error and not _already_exists(response.error):
                raise BrokerControlCommandError(_safe_broker_error(response.error))

    def _set_enabled(self, username: str, *, enabled: bool, missing_ok: bool) -> None:
        client = self._get_client(username)
        if client is None:
            if missing_ok:
                return
            raise BrokerControlCommandError("broker client does not exist")
        command = "enableClient" if enabled else "disableClient"
        self._expect_success({"command": command, "username": username})

    def _get_client(self, username: str) -> dict[str, Any] | None:
        response = self._request({"command": "getClient", "username": username})
        if response.error:
            if _not_found(response.error):
                return None
            raise BrokerControlCommandError(_safe_broker_error(response.error))
        data = response.data
        client = None if data is None else data.get("client")
        if not isinstance(client, dict) or client.get("username") != username:
            raise BrokerControlPermanentError("broker getClient response is malformed")
        return client

    def _get_role(self, role_name: str) -> dict[str, Any] | None:
        response = self._request({"command": "getRole", "rolename": role_name})
        if response.error:
            if _not_found(response.error):
                return None
            raise BrokerControlCommandError(_safe_broker_error(response.error))
        data = response.data
        role = None if data is None else data.get("role")
        if not isinstance(role, dict) or role.get("rolename") != role_name:
            raise BrokerControlPermanentError("broker getRole response is malformed")
        return role

    def _expect_success(self, command: dict[str, Any]) -> DynamicSecurityResponse:
        response = self._request(command)
        if response.error:
            raise BrokerControlCommandError(_safe_broker_error(response.error))
        return response

    def _request(self, command: dict[str, Any]) -> DynamicSecurityResponse:
        expected_command = command.get("command")
        if not isinstance(expected_command, str) or not expected_command:
            raise ValueError("dynamic security command name is required")
        password = _read_secret(self._password_file)
        connected = threading.Event()
        subscribed = threading.Event()
        received = threading.Event()
        result: dict[str, object] = {}
        client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=f"{self._client_id}-{uuid4().hex[:12]}",
            protocol=mqtt.MQTTv5,
        )
        client.username_pw_set(self._username, password)

        def on_connect(
            mqtt_client: mqtt.Client,
            _userdata: object,
            _flags: mqtt.ConnectFlags,
            reason_code: mqtt.ReasonCode,
            _properties: mqtt.Properties | None,
        ) -> None:
            if reason_code.is_failure:
                result["error"] = BrokerControlUnavailableError(
                    "broker control authentication failed"
                )
                connected.set()
                return
            mqtt_client.subscribe(_RESPONSE_TOPIC, qos=1)
            connected.set()

        def on_subscribe(
            _mqtt_client: mqtt.Client,
            _userdata: object,
            _mid: int,
            reason_codes: list[mqtt.ReasonCode],
            _properties: mqtt.Properties | None,
        ) -> None:
            if not reason_codes or any(code.is_failure for code in reason_codes):
                result["error"] = BrokerControlUnavailableError(
                    "broker control response subscription was rejected"
                )
            subscribed.set()

        def on_message(
            _mqtt_client: mqtt.Client,
            _userdata: object,
            message: mqtt.MQTTMessage,
        ) -> None:
            if message.topic != _RESPONSE_TOPIC:
                return
            try:
                parsed = _parse_response(message.payload, expected_command)
            except BrokerControlError as error:
                result["error"] = error
            else:
                result["response"] = parsed
            received.set()

        client.on_connect = on_connect
        client.on_subscribe = on_subscribe
        client.on_message = on_message
        try:
            client.connect(
                self._host,
                self._port,
                keepalive=self._keepalive_seconds,
                clean_start=mqtt.MQTT_CLEAN_START_FIRST_ONLY,
            )
            client.loop_start()
            if not connected.wait(self._timeout_seconds):
                raise BrokerControlUnavailableError("broker control connect timed out")
            if "error" in result:
                raise _as_control_error(result["error"])
            if not subscribed.wait(self._timeout_seconds):
                raise BrokerControlUnavailableError(
                    "broker control subscription timed out"
                )
            if "error" in result:
                raise _as_control_error(result["error"])
            payload = json.dumps(
                {"commands": [command]},
                separators=(",", ":"),
                sort_keys=True,
            )
            info = client.publish(_REQUEST_TOPIC, payload, qos=1)
            if info.rc != mqtt.MQTT_ERR_SUCCESS:
                raise BrokerControlUnavailableError(
                    "broker control command publish failed"
                )
            if not received.wait(self._timeout_seconds):
                raise BrokerControlUnavailableError("broker control response timed out")
            if "error" in result:
                raise _as_control_error(result["error"])
            response = result.get("response")
            if not isinstance(response, DynamicSecurityResponse):
                raise BrokerControlPermanentError("broker control response is missing")
            return response
        except BrokerControlError:
            raise
        except OSError as error:
            raise BrokerControlUnavailableError(
                "broker control connection failed"
            ) from error
        finally:
            try:
                client.disconnect()
            except Exception:
                pass
            client.loop_stop()


def _parse_response(payload: bytes, expected_command: str) -> DynamicSecurityResponse:
    try:
        decoded = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise BrokerControlPermanentError(
            "broker control response is not valid UTF-8 JSON"
        ) from error
    if not isinstance(decoded, dict) or set(decoded) != {"responses"}:
        raise BrokerControlPermanentError("broker control response envelope is malformed")
    responses = decoded.get("responses")
    if not isinstance(responses, list) or len(responses) != 1:
        raise BrokerControlPermanentError("broker control response count is invalid")
    response = responses[0]
    if not isinstance(response, dict):
        raise BrokerControlPermanentError("broker control response item is malformed")
    command = response.get("command")
    if command != expected_command:
        raise BrokerControlPermanentError("broker control response command mismatch")
    error = response.get("error")
    if error is not None and not isinstance(error, str):
        raise BrokerControlPermanentError("broker control error is malformed")
    data = response.get("data")
    if data is not None and not isinstance(data, dict):
        raise BrokerControlPermanentError("broker control response data is malformed")
    allowed = {"command", "error", "data"}
    if not set(response).issubset(allowed):
        raise BrokerControlPermanentError("broker control response contains unknown fields")
    return DynamicSecurityResponse(command=command, data=data, error=error)


def _read_secret(path: str) -> str:
    try:
        value = Path(path).read_text(encoding="utf-8").strip()
    except OSError as error:
        raise BrokerControlUnavailableError(
            "broker control password file is not readable"
        ) from error
    if not value or any(character.isspace() for character in value):
        raise BrokerControlPermanentError(
            "broker control password file contains an invalid secret"
        )
    return value


def _node_id(username: str) -> str:
    parts = username.split(":", 2)
    if len(parts) != 3 or parts[0] != "node" or not parts[2]:
        raise BrokerControlPermanentError("broker node username is malformed")
    return parts[2]


def _not_found(message: str) -> bool:
    lowered = message.lower()
    return "not found" in lowered or "does not exist" in lowered


def _already_exists(message: str) -> bool:
    lowered = message.lower()
    return "already exists" in lowered or "already has" in lowered


def _safe_broker_error(message: str) -> str:
    normalized = " ".join(message.split())
    if not normalized:
        return "broker rejected the control command"
    return normalized[:512]


def _as_control_error(value: object) -> BrokerControlError:
    if isinstance(value, BrokerControlError):
        return value
    return BrokerControlPermanentError("broker control operation failed")


def _required_text(value: str, field: str, max_length: int) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field} is required")
    if len(normalized) > max_length:
        raise ValueError(f"{field} exceeds {max_length} characters")
    return normalized
