from __future__ import annotations

from dataclasses import dataclass
from email.header import decode_header, make_header
from typing import Literal, Mapping

OperatorIdentityMode = Literal["client", "tailscale_serve"]


class OperatorIdentityError(RuntimeError):
    code = "operator_identity_error"


class OperatorIdentityRequiredError(OperatorIdentityError):
    code = "operator_identity_required"


@dataclass(frozen=True, slots=True)
class OperatorIdentity:
    actor_id: str
    display_name: str | None
    provider: Literal["client", "tailscale"]
    authenticated: bool


class OperatorIdentityResolver:
    def __init__(self, mode: OperatorIdentityMode = "client") -> None:
        self.mode = mode

    def resolve(
        self,
        headers: Mapping[str, str],
        *,
        client_actor_id: str | None = None,
    ) -> OperatorIdentity:
        if self.mode == "tailscale_serve":
            login = _header_value(headers, "Tailscale-User-Login")
            if login is None:
                raise OperatorIdentityRequiredError(
                    "Tailscale Serve user identity is required for this operation"
                )
            return OperatorIdentity(
                actor_id=_bounded(login),
                display_name=_header_value(headers, "Tailscale-User-Name"),
                provider="tailscale",
                authenticated=True,
            )

        return OperatorIdentity(
            actor_id=_bounded(client_actor_id or "dashboard-operator"),
            display_name=None,
            provider="client",
            authenticated=False,
        )


def _header_value(headers: Mapping[str, str], name: str) -> str | None:
    value = headers.get(name)
    if value is None:
        value = headers.get(name.lower())
    if value is None:
        return None
    try:
        decoded = str(make_header(decode_header(value)))
    except (LookupError, UnicodeError):
        decoded = value
    normalized = " ".join(decoded.split())
    return normalized or None


def _bounded(value: str) -> str:
    normalized = " ".join(value.split()).strip()
    if not normalized:
        return "dashboard-operator"
    return normalized[:128]
