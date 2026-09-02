from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import json
import time
from typing import Any, Protocol
from urllib.request import Request

from app.config import Settings, read_secret_file
from app.domain import ReportSnapshot
from app.http_transport import HttpResponse, HttpTransport, HttpTransportError, urlopen_transport


class BackendError(RuntimeError):
    def __init__(self, code: str, *, retryable: bool) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable


class AccessTokenProvider(Protocol):
    refreshable: bool

    def get_access_token(self) -> str | None: ...
    def invalidate(self) -> None: ...


class NoAccessTokenProvider:
    refreshable = False

    def get_access_token(self) -> None:
        return None

    def invalidate(self) -> None:
        return None


class FileAccessTokenProvider:
    refreshable = True

    def __init__(self, path: str) -> None:
        self._path = path
        self._token: str | None = None

    def get_access_token(self) -> str:
        if self._token is None:
            self._token = read_secret_file(self._path, label="NEXOLAB backend bearer token")
        return self._token

    def invalidate(self) -> None:
        self._token = None


@dataclass(slots=True)
class _LocalTokenPair:
    access_token: str
    refresh_token: str
    access_expires_at: float
    refresh_expires_at: float


class LocalSessionAccessTokenProvider:
    refreshable = True

    def __init__(
        self,
        base_url: str,
        username: str,
        password_file: str,
        *,
        timeout_seconds: float,
        transport: HttpTransport = urlopen_transport,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._username = username.strip()
        self._password_file = password_file
        self._timeout_seconds = timeout_seconds
        self._transport = transport
        self._pair: _LocalTokenPair | None = None
    def get_access_token(self) -> str:
        now = time.monotonic()
        if self._pair is not None and now < self._pair.access_expires_at:
            return self._pair.access_token
        if self._pair is not None and now < self._pair.refresh_expires_at:
            try:
                self._pair = self._exchange(
                    "/api/v1/auth/local/refresh",
                    {"refresh_token": self._pair.refresh_token},
                )
                return self._pair.access_token
            except BackendError:
                self._pair = None
        password = read_secret_file(self._password_file, label="NEXOLAB backend password")
        self._pair = self._exchange(
            "/api/v1/auth/local/login",
            {"username": self._username, "password": password},
        )
        return self._pair.access_token

    def invalidate(self) -> None:
        if self._pair is not None:
            self._pair.access_expires_at = 0.0

    def _exchange(self, path: str, payload: dict[str, str]) -> _LocalTokenPair:
        request = Request(
            f"{self._base_url}{path}",
            data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            method="POST",
        )
        try:
            response = self._transport(request, self._timeout_seconds)
        except HttpTransportError as error:
            raise BackendError("backend_auth_network_error", retryable=True) from error
        if response.status < 200 or response.status >= 300:
            raise BackendError("backend_auth_rejected", retryable=response.status >= 500)
        value = _json_object(response, code="backend_auth_contract_error")
        access = value.get("access_token")
        refresh = value.get("refresh_token")
        expires = value.get("expires_in")
        refresh_expires = value.get("refresh_expires_in")
        if (
            not isinstance(access, str)
            or len(access) < 16
            or not isinstance(refresh, str)
            or len(refresh) < 16
            or not isinstance(expires, int | float)
            or not isinstance(refresh_expires, int | float)
        ):
            raise BackendError("backend_auth_contract_error", retryable=False)
        now = time.monotonic()
        return _LocalTokenPair(
            access_token=access,
            refresh_token=refresh,
            access_expires_at=now + max(1.0, float(expires) - 5.0),
            refresh_expires_at=now + max(1.0, float(refresh_expires) - 5.0),
        )


class SnapshotClient:
    def __init__(
        self,
        base_url: str,
        organization_id: str,
        token_provider: AccessTokenProvider,
        *,
        timeout_seconds: float,
        transport: HttpTransport = urlopen_transport,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._organization_id = organization_id.strip()
        self._token_provider = token_provider
        self._timeout_seconds = timeout_seconds
        self._transport = transport

    def list_snapshots(self, *, limit: int, offset: int = 0) -> list[ReportSnapshot]:
        if limit < 1 or limit > 200 or offset < 0:
            raise ValueError("snapshot pagination is out of bounds")
        response = self._get(
            f"/api/v1/daily-reports/snapshots?limit={limit}&offset={offset}"
        )
        value = _json_object(response, code="backend_snapshot_contract_error")
        items = value.get("items")
        if not isinstance(items, list):
            raise BackendError("backend_snapshot_contract_error", retryable=False)
        return [_parse_snapshot(item) for item in items]

    def _get(self, path: str) -> HttpResponse:
        response = self._perform_get(path)
        if response.status == 401 and self._token_provider.refreshable:
            self._token_provider.invalidate()
            response = self._perform_get(path)
        if response.status < 200 or response.status >= 300:
            raise BackendError(
                f"backend_http_{response.status}",
                retryable=response.status == 429 or response.status >= 500,
            )
        return response

    def _perform_get(self, path: str) -> HttpResponse:
        try:
            access_token = self._token_provider.get_access_token()
            headers = {
                "Accept": "application/json",
                "X-Organization-ID": self._organization_id,
            }
            if access_token:
                headers["Authorization"] = f"Bearer {access_token}"
            request = Request(f"{self._base_url}{path}", headers=headers, method="GET")
            return self._transport(request, self._timeout_seconds)
        except BackendError:
            raise
        except HttpTransportError as error:
            raise BackendError("backend_network_error", retryable=True) from error
        except Exception as error:
            raise BackendError("backend_request_error", retryable=False) from error


def build_snapshot_client(
    settings: Settings,
    *,
    transport: HttpTransport = urlopen_transport,
) -> SnapshotClient:
    mode = settings.nexolab_backend_auth_mode
    if mode == "none":
        provider: AccessTokenProvider = NoAccessTokenProvider()
    elif mode == "bearer":
        assert settings.nexolab_backend_bearer_token_file is not None
        provider = FileAccessTokenProvider(settings.nexolab_backend_bearer_token_file)
    else:
        assert settings.nexolab_backend_username is not None
        assert settings.nexolab_backend_password_file is not None
        provider = LocalSessionAccessTokenProvider(
            settings.nexolab_backend_base_url,
            settings.nexolab_backend_username,
            settings.nexolab_backend_password_file,
            timeout_seconds=settings.telegram_request_timeout_seconds,
            transport=transport,
        )
    return SnapshotClient(
        settings.nexolab_backend_base_url,
        settings.nexolab_backend_organization_id,
        provider,
        timeout_seconds=settings.telegram_request_timeout_seconds,
        transport=transport,
    )


def _json_object(response: HttpResponse, *, code: str) -> dict[str, Any]:
    try:
        value = json.loads(response.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise BackendError(code, retryable=False) from error
    if not isinstance(value, dict):
        raise BackendError(code, retryable=False)
    return value


def _parse_snapshot(value: object) -> ReportSnapshot:
    if not isinstance(value, dict):
        raise BackendError("backend_snapshot_contract_error", retryable=False)
    required_text = ("id", "organization_id", "profile_id", "equipment_id", "payload_sha256")
    values: dict[str, str] = {}
    for field in required_text:
        item = value.get(field)
        if not isinstance(item, str) or not item.strip():
            raise BackendError("backend_snapshot_contract_error", retryable=False)
        values[field] = item.strip()
    digest = values["payload_sha256"].lower()
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise BackendError("backend_snapshot_contract_error", retryable=False)
    scheduled_for = _parse_datetime(value.get("scheduled_for"))
    payload = value.get("payload")
    if not isinstance(payload, dict):
        raise BackendError("backend_snapshot_contract_error", retryable=False)
    return ReportSnapshot(
        id=values["id"],
        organization_id=values["organization_id"],
        profile_id=values["profile_id"],
        equipment_id=values["equipment_id"],
        scheduled_for=scheduled_for,
        payload_sha256=digest,
        payload=payload,
    )


def _parse_datetime(value: object) -> datetime:
    if not isinstance(value, str):
        raise BackendError("backend_snapshot_contract_error", retryable=False)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise BackendError("backend_snapshot_contract_error", retryable=False) from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise BackendError("backend_snapshot_contract_error", retryable=False)
    return parsed.astimezone(UTC)
