from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt

from app.security.authentication import VerifiedIdentityClaims
from app.security.local_repository import (
    LOCAL_AUTH_PROVIDER,
    LocalAccountNotFoundError,
    LocalAuthRepository,
    LocalSessionInvalidError,
)
from app.security.passwords import dummy_password_hash, verify_password
from app.security.repository import AuditEventInput, SecurityRepository


class LocalAuthenticationError(RuntimeError):
    code = "local_authentication_failed"


class InvalidLocalCredentialsError(LocalAuthenticationError):
    code = "invalid_local_credentials"


class LocalAccountLockedError(LocalAuthenticationError):
    code = "local_account_locked"


class InvalidLocalRefreshTokenError(LocalAuthenticationError):
    code = "invalid_local_refresh_token"


class LocalAccountAccessError(LocalAuthenticationError):
    code = "local_account_access_denied"


@dataclass(frozen=True, slots=True)
class LocalTokenPair:
    access_token: str
    refresh_token: str
    access_expires_at: datetime
    refresh_expires_at: datetime

    @property
    def access_expires_in(self) -> int:
        return max(0, int((self.access_expires_at - datetime.now(UTC)).total_seconds()))

    @property
    def refresh_expires_in(self) -> int:
        return max(0, int((self.refresh_expires_at - datetime.now(UTC)).total_seconds()))


class LocalAuthService:
    def __init__(
        self,
        repository: LocalAuthRepository,
        security_repository: SecurityRepository,
        *,
        private_key: str,
        algorithm: str,
        issuer: str,
        audience: str,
        access_token_seconds: int,
        refresh_token_seconds: int,
        max_failed_attempts: int,
        lockout_seconds: int,
    ) -> None:
        if algorithm != "RS256":
            raise ValueError("local authentication currently requires RS256")
        if not private_key.strip():
            raise ValueError("local authentication private key is required")
        if not issuer.strip() or not audience.strip():
            raise ValueError("local authentication issuer and audience are required")
        self._repository = repository
        self._security_repository = security_repository
        self._private_key = private_key
        self._algorithm = algorithm
        self._issuer = issuer
        self._audience = audience
        self._access_token_seconds = access_token_seconds
        self._refresh_token_seconds = refresh_token_seconds
        self._max_failed_attempts = max_failed_attempts
        self._lockout_seconds = lockout_seconds

    def login(
        self,
        *,
        username: str,
        password: str,
        source_ip: str | None,
        user_agent: str | None,
    ) -> LocalTokenPair:
        now = datetime.now(UTC)
        try:
            account = self._repository.get_account(username)
        except (LocalAccountNotFoundError, ValueError):
            verify_password(password, dummy_password_hash())
            raise InvalidLocalCredentialsError("invalid username or password") from None

        password_valid = verify_password(password, account.password_hash)
        if account.locked_until is not None and account.locked_until > now:
            raise LocalAccountLockedError("local account is temporarily locked")
        if not account.is_active or not password_valid:
            locked_until = self._repository.record_failed_login(
                account_id=account.id,
                max_failed_attempts=self._max_failed_attempts,
                lockout_seconds=self._lockout_seconds,
                now=now,
            )
            if locked_until is not None:
                raise LocalAccountLockedError("local account is temporarily locked")
            raise InvalidLocalCredentialsError("invalid username or password")

        security_session = self._security_repository.resolve_session(account.claims)
        if not security_session.memberships:
            raise LocalAccountAccessError(
                "local account has no active organization membership"
            )
        self._repository.record_successful_login(account_id=account.id, now=now)

        refresh_token = secrets.token_urlsafe(48)
        refresh_expires_at = now + timedelta(seconds=self._refresh_token_seconds)
        session_id = self._repository.create_session(
            account_id=account.id,
            refresh_token_hash=hash_refresh_token(refresh_token),
            expires_at=refresh_expires_at,
            source_ip=source_ip,
            user_agent=user_agent,
            now=now,
        )
        token_pair = self._token_pair(
            claims=account.claims,
            session_id=session_id,
            refresh_token=refresh_token,
            refresh_expires_at=refresh_expires_at,
            now=now,
        )
        first_membership = security_session.memberships[0]
        self._security_repository.append_audit_event(
            AuditEventInput(
                organization_id=first_membership.organization_id,
                actor_identity_id=account.identity_id,
                actor_subject=account.subject,
                actor_roles=first_membership.roles,
                action="security.local_login.succeeded",
                entity_type="local_auth_session",
                entity_id=session_id,
                after_snapshot={
                    "provider": LOCAL_AUTH_PROVIDER,
                    "username": account.username,
                    "session_expires_at": refresh_expires_at.isoformat(),
                },
                source_ip=source_ip,
                user_agent=user_agent,
            )
        )
        return token_pair

    def refresh(self, refresh_token: str) -> LocalTokenPair:
        now = datetime.now(UTC)
        replacement = secrets.token_urlsafe(48)
        try:
            session = self._repository.rotate_refresh_token(
                refresh_token_hash=hash_refresh_token(refresh_token),
                replacement_hash=hash_refresh_token(replacement),
                now=now,
            )
        except LocalSessionInvalidError as error:
            raise InvalidLocalRefreshTokenError(str(error)) from error

        security_session = self._security_repository.resolve_session(
            session.account.claims
        )
        if not security_session.memberships:
            raise LocalAccountAccessError(
                "local account has no active organization membership"
            )
        return self._token_pair(
            claims=session.account.claims,
            session_id=session.id,
            refresh_token=replacement,
            refresh_expires_at=session.expires_at,
            now=now,
        )

    def logout(self, refresh_token: str) -> None:
        if not refresh_token.strip():
            return
        self._repository.revoke_session_by_refresh_token(
            refresh_token_hash=hash_refresh_token(refresh_token),
            now=datetime.now(UTC),
        )

    def validate_access_claims(self, claims: VerifiedIdentityClaims) -> None:
        if claims.provider != LOCAL_AUTH_PROVIDER:
            raise LocalSessionInvalidError("unexpected local token provider")
        if claims.token_type != "access" or claims.session_id is None:
            raise LocalSessionInvalidError("local access token claims are incomplete")
        self._repository.validate_access_session(
            session_id=claims.session_id,
            subject=claims.subject,
        )

    def _token_pair(
        self,
        *,
        claims: VerifiedIdentityClaims,
        session_id: str,
        refresh_token: str,
        refresh_expires_at: datetime,
        now: datetime,
    ) -> LocalTokenPair:
        access_expires_at = now + timedelta(seconds=self._access_token_seconds)
        payload: dict[str, object] = {
            "iss": self._issuer,
            "aud": self._audience,
            "sub": claims.subject,
            "iat": now,
            "nbf": now,
            "exp": access_expires_at,
            "jti": str(uuid4()),
            "sid": session_id,
            "typ": "access",
        }
        if claims.email is not None:
            payload["email"] = claims.email
        if claims.display_name is not None:
            payload["name"] = claims.display_name
        access_token = jwt.encode(
            payload,
            self._private_key,
            algorithm=self._algorithm,
        )
        return LocalTokenPair(
            access_token=access_token,
            refresh_token=refresh_token,
            access_expires_at=access_expires_at,
            refresh_expires_at=refresh_expires_at,
        )


def hash_refresh_token(token: str) -> str:
    normalized = token.strip()
    if not normalized:
        raise InvalidLocalRefreshTokenError("refresh token is required")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()
