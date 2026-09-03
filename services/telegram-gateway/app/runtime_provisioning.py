from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import getpass
import ipaddress
import json
import os
import re
from pathlib import Path
import secrets
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request

from app.group_identification import GroupIdentity, identify_group
from app.http_transport import HttpResponse, HttpTransport, HttpTransportError, urlopen_transport

_DEFAULT_BACKEND_BASE_URL = "http://172.18.48.66:8082"
_DEFAULT_SECRET_DIR = "/etc/nexolab/telegram"
_DEFAULT_GROUP_TITLE = "TestLAB"
_TARGET_USERNAME = "nexolab-telegram"
_TARGET_ROLE = "laboratory_technician"
_TARGET_PERMISSIONS = ("reports.read",)


class RuntimeProvisioningError(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _validate_backend_origin(value: str) -> str:
    normalized = value.strip().rstrip("/")
    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise RuntimeProvisioningError("backend_origin_invalid")
    if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
        raise RuntimeProvisioningError("backend_origin_invalid")
    host = parsed.hostname
    if host is None:
        raise RuntimeProvisioningError("backend_origin_invalid")
    if host == "localhost":
        return normalized
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        if re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", host) is None:
            raise RuntimeProvisioningError("backend_origin_not_local")
    else:
        if not (address.is_private or address.is_loopback or address.is_link_local):
            raise RuntimeProvisioningError("backend_origin_not_local")
    return normalized


@dataclass(frozen=True, slots=True)
class TokenPair:
    access_token: str
    refresh_token: str


@dataclass(frozen=True, slots=True)
class ProvisioningResult:
    group_title: str
    group_type: str
    bot_username: str
    organization_id: str
    backend_username: str
    backend_role: str
    backend_permissions: tuple[str, ...]
    backend_identity_id: str
    runtime_env_path: str


class BackendAdminClient:
    def __init__(
        self,
        base_url: str,
        *,
        timeout_seconds: float = 10.0,
        transport: HttpTransport = urlopen_transport,
    ) -> None:
        self._base_url = _validate_backend_origin(base_url)
        self._timeout_seconds = timeout_seconds
        self._transport = transport

    def login(self, username: str, password: str) -> TokenPair:
        value = self._json_request(
            "POST",
            "/api/v1/auth/local/login",
            payload={"username": username, "password": password},
        )
        access = value.get("access_token")
        refresh = value.get("refresh_token")
        if not isinstance(access, str) or not isinstance(refresh, str):
            raise RuntimeProvisioningError("backend_login_contract_invalid")
        return TokenPair(access_token=access, refresh_token=refresh)

    def logout(self, refresh_token: str) -> None:
        self._json_request(
            "POST",
            "/api/v1/auth/local/logout",
            payload={"refresh_token": refresh_token},
            allow_empty=True,
        )

    def session(self, access_token: str) -> dict[str, Any]:
        return self._json_request(
            "GET",
            "/api/v1/auth/session",
            access_token=access_token,
        )

    def list_users(self, access_token: str, organization_id: str) -> list[dict[str, Any]]:
        value = self._json_request(
            "GET",
            "/api/v1/admin/users",
            access_token=access_token,
            organization_id=organization_id,
        )
        items = value.get("items")
        if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
            raise RuntimeProvisioningError("backend_users_contract_invalid")
        return items

    def create_user(
        self,
        access_token: str,
        organization_id: str,
        *,
        username: str,
        password: str,
    ) -> dict[str, Any]:
        return self._json_request(
            "POST",
            "/api/v1/admin/users",
            access_token=access_token,
            organization_id=organization_id,
            payload={
                "username": username,
                "password": password,
                "display_name": "NEXOLAB Telegram Gateway",
                "role": _TARGET_ROLE,
                "permissions": list(_TARGET_PERMISSIONS),
                "reason": "TG-04 Telegram gateway least-privilege service principal",
            },
            expected_status=201,
        )

    def _json_request(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        access_token: str | None = None,
        organization_id: str | None = None,
        expected_status: int | None = None,
        allow_empty: bool = False,
    ) -> dict[str, Any]:
        headers = {"Accept": "application/json", "User-Agent": "nexolab-tg04-provisioning/1"}
        data = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"
        if organization_id:
            headers["X-Organization-ID"] = organization_id
        request = Request(
            f"{self._base_url}{path}",
            data=data,
            headers=headers,
            method=method,
        )
        try:
            response = self._transport(request, self._timeout_seconds)
        except HttpTransportError as error:
            raise RuntimeProvisioningError("backend_network_error") from error
        if expected_status is None:
            if response.status < 200 or response.status >= 300:
                raise RuntimeProvisioningError(f"backend_http_{response.status}")
        elif response.status != expected_status:
            raise RuntimeProvisioningError(f"backend_http_{response.status}")
        if allow_empty and not response.body:
            return {}
        try:
            value = json.loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise RuntimeProvisioningError("backend_response_invalid") from error
        if not isinstance(value, dict):
            raise RuntimeProvisioningError("backend_response_invalid")
        return value


def _admin_organization(session: dict[str, Any]) -> str:
    memberships = session.get("memberships")
    if not isinstance(memberships, list):
        raise RuntimeProvisioningError("admin_session_contract_invalid")
    candidates: list[str] = []
    for item in memberships:
        if not isinstance(item, dict):
            continue
        permissions = item.get("permissions")
        organization_id = item.get("organization_id")
        if isinstance(permissions, list) and "memberships.manage" in permissions and isinstance(organization_id, str):
            candidates.append(organization_id)
    if len(candidates) != 1:
        raise RuntimeProvisioningError("admin_organization_ambiguous")
    return candidates[0]


def _validate_backend_user(record: dict[str, Any]) -> tuple[str, str]:
    if record.get("username") != _TARGET_USERNAME or record.get("is_active") is not True:
        raise RuntimeProvisioningError("backend_principal_invalid")
    if record.get("role") != _TARGET_ROLE:
        raise RuntimeProvisioningError("backend_principal_role_invalid")
    granted = record.get("granted_permissions")
    effective = record.get("effective_permissions")
    if granted != list(_TARGET_PERMISSIONS) or effective != list(_TARGET_PERMISSIONS):
        raise RuntimeProvisioningError("backend_principal_permissions_invalid")
    identity_id = record.get("identity_id")
    account_id = record.get("id")
    if not isinstance(identity_id, str) or not isinstance(account_id, str):
        raise RuntimeProvisioningError("backend_principal_contract_invalid")
    return account_id, identity_id


def _write_private_file(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    finally:
        if temporary.exists():
            temporary.unlink()


def _read_private_file(path: Path) -> str | None:
    try:
        value = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    except OSError as error:
        raise RuntimeProvisioningError("managed_secret_unreadable") from error
    if not value:
        raise RuntimeProvisioningError("managed_secret_empty")
    return value


def provision_backend_principal(
    client: BackendAdminClient,
    *,
    admin_username: str,
    admin_password: str,
    secret_dir: Path,
) -> tuple[str, str]:
    admin_tokens = client.login(admin_username, admin_password)
    try:
        organization_id = _admin_organization(client.session(admin_tokens.access_token))
        users = client.list_users(admin_tokens.access_token, organization_id)
        existing = next((item for item in users if item.get("username") == _TARGET_USERNAME), None)
        final_secret = secret_dir / "nexolab-backend-password"
        pending_secret = secret_dir / ".nexolab-backend-password.pending"
        password = _read_private_file(final_secret) or _read_private_file(pending_secret)

        if existing is None:
            if password is None:
                password = secrets.token_urlsafe(36)
                _write_private_file(pending_secret, password)
            record = client.create_user(
                admin_tokens.access_token,
                organization_id,
                username=_TARGET_USERNAME,
                password=password,
            )
        else:
            record = existing
            if password is None:
                raise RuntimeProvisioningError("backend_principal_exists_without_managed_secret")

        _, identity_id = _validate_backend_user(record)
        validation_tokens = client.login(_TARGET_USERNAME, password)
        _best_effort_logout(client, validation_tokens.refresh_token)
        if pending_secret.exists():
            os.replace(pending_secret, final_secret)
            os.chmod(final_secret, 0o600)
        return organization_id, identity_id
    finally:
        _best_effort_logout(client, admin_tokens.refresh_token)


def _best_effort_logout(client: BackendAdminClient, refresh_token: str) -> None:
    try:
        client.logout(refresh_token)
    except RuntimeProvisioningError:
        pass


def write_disabled_runtime_env(
    path: Path,
    *,
    group: GroupIdentity,
    organization_id: str,
) -> None:
    direct_link = f"https://t.me/{group.bot_username}?startapp=report_{{snapshot_id}}"
    lines = [
        "# TG-04 prepared runtime configuration. Delivery remains disabled until explicit cutover approval.",
        "TELEGRAM_ENABLED=false",
        "TELEGRAM_MINIAPP_ENABLED=false",
        "TELEGRAM_MINIAPP_INIT_DATA_MAX_AGE_SECONDS=300",
        "TELEGRAM_GATEWAY_SECRETS_DIR=/etc/nexolab/telegram",
        f"TELEGRAM_DESTINATION_CHAT_ID={group.chat_id}",
        f"TELEGRAM_MINI_APP_URL_TEMPLATE={direct_link}",
        f"TELEGRAM_NEXOLAB_BACKEND_ORGANIZATION_ID={organization_id}",
        f"TELEGRAM_NEXOLAB_BACKEND_USERNAME={_TARGET_USERNAME}",
        "TELEGRAM_NEXOLAB_BACKEND_AUTH_MODE=local",
        "TELEGRAM_POLL_INTERVAL_SECONDS=30",
        "TELEGRAM_MAX_ATTEMPTS=6",
        "TELEGRAM_RETRY_INITIAL_SECONDS=5",
        "TELEGRAM_RETRY_MAX_SECONDS=300",
        "TELEGRAM_MAX_DELIVERIES_PER_RUN=50",
        "",
    ]
    _write_private_file(path, "\n".join(lines))


def provision_runtime(
    *,
    admin_username: str,
    admin_password: str,
    backend_base_url: str,
    secret_dir: Path,
    group: GroupIdentity,
    transport: HttpTransport = urlopen_transport,
) -> ProvisioningResult:
    client = BackendAdminClient(backend_base_url, transport=transport)
    organization_id, identity_id = provision_backend_principal(
        client,
        admin_username=admin_username,
        admin_password=admin_password,
        secret_dir=secret_dir,
    )
    runtime_env_path = secret_dir / "telegram.env"
    write_disabled_runtime_env(
        runtime_env_path,
        group=group,
        organization_id=organization_id,
    )
    return ProvisioningResult(
        group_title=group.title,
        group_type=group.chat_type,
        bot_username=group.bot_username,
        organization_id=organization_id,
        backend_username=_TARGET_USERNAME,
        backend_role=_TARGET_ROLE,
        backend_permissions=_TARGET_PERMISSIONS,
        backend_identity_id=identity_id,
        runtime_env_path=str(runtime_env_path),
    )


def _read_required_secret(path: Path, code: str) -> str:
    value = _read_private_file(path)
    if value is None:
        raise RuntimeProvisioningError(code)
    return value


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prepare disabled TG-04 runtime configuration through audited NEXOLAB APIs."
    )
    parser.add_argument("--backend-base-url", default=_DEFAULT_BACKEND_BASE_URL)
    parser.add_argument("--secret-dir", default=_DEFAULT_SECRET_DIR)
    parser.add_argument("--group-title", default=_DEFAULT_GROUP_TITLE)
    args = parser.parse_args()

    if os.geteuid() != 0:
        print(json.dumps({"ok": False, "error": "root_required"}))
        return 2
    admin_username = input("NEXOLAB admin username: ").strip()
    admin_password = getpass.getpass("NEXOLAB admin password: ")
    if not admin_username or not admin_password:
        print(json.dumps({"ok": False, "error": "admin_credentials_required"}))
        return 2
    secret_dir = Path(args.secret_dir)
    try:
        bot_token = _read_required_secret(secret_dir / "bot-token", "telegram_bot_token_unavailable")
        group = identify_group(
            token=bot_token,
            target_title=args.group_title,
            transport=urlopen_transport,
        )
        result = provision_runtime(
            admin_username=admin_username,
            admin_password=admin_password,
            backend_base_url=args.backend_base_url,
            secret_dir=secret_dir,
            group=group,
        )
    except RuntimeProvisioningError as error:
        print(json.dumps({"ok": False, "error": error.code}, ensure_ascii=False, sort_keys=True))
        return 2
    except Exception as error:
        code = getattr(error, "code", "runtime_provisioning_failed")
        print(json.dumps({"ok": False, "error": str(code)}, ensure_ascii=False, sort_keys=True))
        return 2
    payload = asdict(result)
    print(json.dumps({"ok": True, "result": payload}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
