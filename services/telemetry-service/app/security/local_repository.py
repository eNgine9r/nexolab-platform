from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Iterable
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import Database
from app.security.authentication import VerifiedIdentityClaims
from app.security.authorization import Role
from app.security.local_models import SecurityLocalAccount, SecurityLocalSession
from app.security.models import (
    SecurityIdentity,
    SecurityMembershipRole,
    SecurityOrganization,
    SecurityOrganizationMembership,
)


LOCAL_AUTH_PROVIDER = "nexolab-local"


class LocalAuthRepositoryError(RuntimeError):
    code = "local_auth_repository_error"


class LocalAccountExistsError(LocalAuthRepositoryError):
    code = "local_account_exists"


class LocalAccountNotFoundError(LocalAuthRepositoryError):
    code = "local_account_not_found"


class LocalSessionInvalidError(LocalAuthRepositoryError):
    code = "local_session_invalid"


@dataclass(frozen=True, slots=True)
class LocalAccountRecord:
    id: str
    identity_id: str
    username: str
    subject: str
    email: str | None
    display_name: str | None
    password_hash: str
    is_active: bool
    failed_login_count: int
    locked_until: datetime | None

    @property
    def claims(self) -> VerifiedIdentityClaims:
        return VerifiedIdentityClaims(
            provider=LOCAL_AUTH_PROVIDER,
            subject=self.subject,
            email=self.email,
            display_name=self.display_name,
        )


@dataclass(frozen=True, slots=True)
class LocalSessionRecord:
    id: str
    account: LocalAccountRecord
    expires_at: datetime


class LocalAuthRepository:
    def __init__(self, database: Database) -> None:
        self._engine = database.engine

    def bootstrap_account(
        self,
        *,
        username: str,
        password_hash: str,
        email: str | None,
        display_name: str | None,
        organization_id: str,
        organization_slug: str,
        organization_name: str,
        roles: Iterable[Role],
    ) -> LocalAccountRecord:
        normalized_username = normalize_username(username)
        resolved_roles = frozenset(roles)
        if not resolved_roles:
            raise ValueError("at least one role is required")
        now = datetime.now(UTC)
        account_id = str(uuid4())
        identity_id = str(uuid4())
        membership_id = str(uuid4())

        with Session(self._engine, expire_on_commit=False) as session:
            with session.begin():
                existing = session.scalar(
                    select(SecurityLocalAccount).where(
                        SecurityLocalAccount.username == normalized_username
                    )
                )
                if existing is not None:
                    raise LocalAccountExistsError(
                        f"local account {normalized_username!r} already exists"
                    )

                organization = session.get(SecurityOrganization, organization_id)
                if organization is None:
                    organization = SecurityOrganization(
                        id=organization_id,
                        slug=organization_slug,
                        name=organization_name,
                        is_active=True,
                    )
                    session.add(organization)
                elif not organization.is_active:
                    organization.is_active = True

                identity = SecurityIdentity(
                    id=identity_id,
                    provider=LOCAL_AUTH_PROVIDER,
                    subject=account_id,
                    email=normalize_optional(email),
                    display_name=normalize_optional(display_name),
                    is_active=True,
                    created_at=now,
                    last_authenticated_at=now,
                )
                session.add(identity)
                session.add(
                    SecurityLocalAccount(
                        id=account_id,
                        identity_id=identity_id,
                        username=normalized_username,
                        password_hash=password_hash,
                        is_active=True,
                        failed_login_count=0,
                        locked_until=None,
                        password_changed_at=now,
                        created_at=now,
                        updated_at=now,
                    )
                )
                session.add(
                    SecurityOrganizationMembership(
                        id=membership_id,
                        organization_id=organization_id,
                        identity_id=identity_id,
                        is_active=True,
                        created_at=now,
                    )
                )
                session.add_all(
                    SecurityMembershipRole(
                        membership_id=membership_id,
                        role=role.value,
                        assigned_by="local-auth-bootstrap",
                        assigned_at=now,
                    )
                    for role in sorted(resolved_roles, key=lambda item: item.value)
                )

        return self.get_account(normalized_username)

    def get_account(self, username: str) -> LocalAccountRecord:
        normalized = normalize_username(username)
        with Session(self._engine) as session:
            row = session.execute(
                select(SecurityLocalAccount, SecurityIdentity)
                .join(
                    SecurityIdentity,
                    SecurityIdentity.id == SecurityLocalAccount.identity_id,
                )
                .where(SecurityLocalAccount.username == normalized)
            ).one_or_none()
            if row is None:
                raise LocalAccountNotFoundError(
                    f"local account {normalized!r} was not found"
                )
            account, identity = row
            return _account_record(account, identity)

    def record_failed_login(
        self,
        *,
        account_id: str,
        max_failed_attempts: int,
        lockout_seconds: int,
        now: datetime,
    ) -> datetime | None:
        with Session(self._engine, expire_on_commit=False) as session:
            with session.begin():
                account = session.get(SecurityLocalAccount, account_id)
                if account is None:
                    return None
                account.failed_login_count += 1
                if account.failed_login_count >= max_failed_attempts:
                    account.failed_login_count = 0
                    account.locked_until = now + timedelta(seconds=lockout_seconds)
                account.updated_at = now
            return _as_utc(account.locked_until)

    def record_successful_login(self, *, account_id: str, now: datetime) -> None:
        with Session(self._engine) as session:
            with session.begin():
                account = session.get(SecurityLocalAccount, account_id)
                if account is None:
                    raise LocalAccountNotFoundError("local account no longer exists")
                identity = session.get(SecurityIdentity, account.identity_id)
                if identity is None:
                    raise LocalAccountNotFoundError("local identity no longer exists")
                account.failed_login_count = 0
                account.locked_until = None
                account.updated_at = now
                identity.last_authenticated_at = now

    def create_session(
        self,
        *,
        account_id: str,
        refresh_token_hash: str,
        expires_at: datetime,
        source_ip: str | None,
        user_agent: str | None,
        now: datetime,
    ) -> str:
        session_id = str(uuid4())
        with Session(self._engine) as session:
            with session.begin():
                account = session.get(SecurityLocalAccount, account_id)
                if account is None or not account.is_active:
                    raise LocalAccountNotFoundError("local account is not active")
                session.add(
                    SecurityLocalSession(
                        id=session_id,
                        account_id=account_id,
                        refresh_token_hash=refresh_token_hash,
                        created_at=now,
                        last_refreshed_at=now,
                        expires_at=expires_at,
                        revoked_at=None,
                        source_ip=bounded(source_ip, 64),
                        user_agent=bounded(user_agent, 512),
                    )
                )
        return session_id

    def rotate_refresh_token(
        self,
        *,
        refresh_token_hash: str,
        replacement_hash: str,
        now: datetime,
    ) -> LocalSessionRecord:
        with Session(self._engine, expire_on_commit=False) as session:
            with session.begin():
                row = session.execute(
                    select(SecurityLocalSession, SecurityLocalAccount, SecurityIdentity)
                    .join(
                        SecurityLocalAccount,
                        SecurityLocalAccount.id == SecurityLocalSession.account_id,
                    )
                    .join(
                        SecurityIdentity,
                        SecurityIdentity.id == SecurityLocalAccount.identity_id,
                    )
                    .where(
                        SecurityLocalSession.refresh_token_hash
                        == refresh_token_hash
                    )
                    .with_for_update()
                ).one_or_none()
                if row is None:
                    raise LocalSessionInvalidError("refresh session was not found")
                local_session, account, identity = row
                self._assert_session_rows_active(
                    local_session,
                    account,
                    identity,
                    now=now,
                )
                local_session.refresh_token_hash = replacement_hash
                local_session.last_refreshed_at = now
                return LocalSessionRecord(
                    id=local_session.id,
                    account=_account_record(account, identity),
                    expires_at=_as_utc(local_session.expires_at),
                )

    def revoke_session_by_refresh_token(
        self,
        *,
        refresh_token_hash: str,
        now: datetime,
    ) -> bool:
        with Session(self._engine) as session:
            with session.begin():
                local_session = session.scalar(
                    select(SecurityLocalSession)
                    .where(
                        SecurityLocalSession.refresh_token_hash
                        == refresh_token_hash
                    )
                    .with_for_update()
                )
                if local_session is None:
                    return False
                if local_session.revoked_at is None:
                    local_session.revoked_at = now
                return True

    def validate_access_session(
        self,
        *,
        session_id: str,
        subject: str,
        now: datetime | None = None,
    ) -> None:
        checked_at = now or datetime.now(UTC)
        with Session(self._engine) as session:
            row = session.execute(
                select(SecurityLocalSession, SecurityLocalAccount, SecurityIdentity)
                .join(
                    SecurityLocalAccount,
                    SecurityLocalAccount.id == SecurityLocalSession.account_id,
                )
                .join(
                    SecurityIdentity,
                    SecurityIdentity.id == SecurityLocalAccount.identity_id,
                )
                .where(SecurityLocalSession.id == session_id)
            ).one_or_none()
            if row is None:
                raise LocalSessionInvalidError("local access session was not found")
            local_session, account, identity = row
            self._assert_session_rows_active(
                local_session,
                account,
                identity,
                now=checked_at,
            )
            if identity.subject != subject:
                raise LocalSessionInvalidError("local session subject mismatch")

    def reset_password(
        self,
        *,
        username: str,
        password_hash: str,
        now: datetime,
    ) -> None:
        normalized = normalize_username(username)
        with Session(self._engine) as session:
            with session.begin():
                account = session.scalar(
                    select(SecurityLocalAccount)
                    .where(SecurityLocalAccount.username == normalized)
                    .with_for_update()
                )
                if account is None:
                    raise LocalAccountNotFoundError(
                        f"local account {normalized!r} was not found"
                    )
                account.password_hash = password_hash
                account.password_changed_at = now
                account.failed_login_count = 0
                account.locked_until = None
                account.updated_at = now
                sessions = session.scalars(
                    select(SecurityLocalSession).where(
                        SecurityLocalSession.account_id == account.id,
                        SecurityLocalSession.revoked_at.is_(None),
                    )
                )
                for local_session in sessions:
                    local_session.revoked_at = now

    def revoke_all_sessions(self, *, username: str, now: datetime) -> int:
        account = self.get_account(username)
        count = 0
        with Session(self._engine) as session:
            with session.begin():
                sessions = session.scalars(
                    select(SecurityLocalSession).where(
                        SecurityLocalSession.account_id == account.id,
                        SecurityLocalSession.revoked_at.is_(None),
                    )
                )
                for local_session in sessions:
                    local_session.revoked_at = now
                    count += 1
        return count

    @staticmethod
    def _assert_session_rows_active(
        local_session: SecurityLocalSession,
        account: SecurityLocalAccount,
        identity: SecurityIdentity,
        *,
        now: datetime,
    ) -> None:
        if local_session.revoked_at is not None:
            raise LocalSessionInvalidError("local session is revoked")
        if _as_utc(local_session.expires_at) <= now:
            raise LocalSessionInvalidError("local session is expired")
        if not account.is_active or not identity.is_active:
            raise LocalSessionInvalidError("local account is inactive")


def normalize_username(value: str) -> str:
    normalized = value.strip().casefold()
    if len(normalized) < 3 or len(normalized) > 128:
        raise ValueError("username must contain between 3 and 128 characters")
    if any(character.isspace() for character in normalized):
        raise ValueError("username must not contain whitespace")
    return normalized


def normalize_optional(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def bounded(value: str | None, limit: int) -> str | None:
    normalized = normalize_optional(value)
    return normalized[:limit] if normalized is not None else None


def _account_record(
    account: SecurityLocalAccount,
    identity: SecurityIdentity,
) -> LocalAccountRecord:
    return LocalAccountRecord(
        id=account.id,
        identity_id=account.identity_id,
        username=account.username,
        subject=identity.subject,
        email=identity.email,
        display_name=identity.display_name,
        password_hash=account.password_hash,
        is_active=bool(account.is_active and identity.is_active),
        failed_login_count=account.failed_login_count,
        locked_until=_as_utc(account.locked_until),
    )


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
