from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from commissioning_preflight import PROFILES, is_stable_serial_identifier

_ALLOWED_FIELDS = {
    "activation_id",
    "action",
    "node_id",
    "bus_id",
    "stable_transport_identifier",
    "unit_id",
    "profile_id",
    "profile_version",
}


@dataclass(frozen=True, slots=True)
class CommissioningActivationRequest:
    activation_id: str
    action: str
    node_id: str
    bus_id: str
    stable_transport_identifier: str
    unit_id: int
    profile_id: str
    profile_version: str


def parse_activation_request(payload: object) -> CommissioningActivationRequest:
    if not isinstance(payload, dict):
        raise ValueError("activation request body must be an object")
    unknown = sorted(set(payload) - _ALLOWED_FIELDS)
    if unknown:
        raise ValueError("unsupported activation request fields: " + ", ".join(unknown))
    activation_id = _text(payload.get("activation_id"), "activation_id", 64)
    action = _text(payload.get("action"), "action", 16)
    if action not in {"activate", "rollback"}:
        raise ValueError("action must be activate or rollback")
    node_id = _text(payload.get("node_id"), "node_id", 64)
    bus_id = _text(payload.get("bus_id"), "bus_id", 64)
    stable = _text(payload.get("stable_transport_identifier"), "stable_transport_identifier", 255)
    if not is_stable_serial_identifier(stable):
        raise ValueError("stable_transport_identifier must use /dev/serial/by-id/<device-id>")
    unit_id = payload.get("unit_id")
    if not isinstance(unit_id, int) or isinstance(unit_id, bool) or not 1 <= unit_id <= 247:
        raise ValueError("unit_id must be an integer in 1..247")
    profile_id = _text(payload.get("profile_id"), "profile_id", 128)
    profile_version = _text(payload.get("profile_version"), "profile_version", 128)
    profile = PROFILES.get(profile_id)
    if profile is None or profile.profile_version != profile_version:
        raise ValueError("unsupported activation profile/version")
    return CommissioningActivationRequest(
        activation_id, action, node_id, bus_id, stable, unit_id, profile_id, profile_version
    )


def activation_fingerprint(request: CommissioningActivationRequest) -> str:
    payload = asdict(request)
    payload.pop("action", None)
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


class CommissioningActivationJournal:
    def __init__(self, database_path: Path) -> None:
        self._connection = sqlite3.connect(database_path, check_same_thread=False)
        self._connection.execute("PRAGMA busy_timeout = 5000")
        self._lock = threading.Lock()
        with self._connection:
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS commissioning_activation_journal (
                    activation_id TEXT PRIMARY KEY,
                    fingerprint_sha256 TEXT NOT NULL,
                    state TEXT NOT NULL,
                    document TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    def load(self, activation_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT fingerprint_sha256, state, document FROM commissioning_activation_journal WHERE activation_id = ?",
                (activation_id,),
            ).fetchone()
        if row is None:
            return None
        document = json.loads(str(row[2]))
        if not isinstance(document, dict):
            raise RuntimeError("activation journal document is invalid")
        return {"fingerprint_sha256": str(row[0]), "state": str(row[1]), **document}

    def save(self, activation_id: str, fingerprint: str, state: str, document: dict[str, Any]) -> None:
        encoded = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO commissioning_activation_journal(activation_id, fingerprint_sha256, state, document, updated_at)
                VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(activation_id) DO UPDATE SET
                    fingerprint_sha256 = excluded.fingerprint_sha256,
                    state = excluded.state,
                    document = excluded.document,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (activation_id, fingerprint, state, encoded),
            )


def _text(value: object, label: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string")
    normalized = value.strip()
    if not normalized or len(normalized) > maximum or any(ord(char) < 32 for char in normalized):
        raise ValueError(f"{label} is invalid")
    return normalized
