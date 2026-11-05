"""Durable, fail-closed authority for explicitly commissioned RS-485 buses.

Prepared entries are never exposed as pollable. This module does not open a
serial port or change the acquisition registry; the activation coordinator owns
those operations and must preserve the activation journal's recovery rules.
"""
from __future__ import annotations

import math
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path

from commissioning_connections import commissioning_bus_id
from commissioning_preflight import canonical_serial_identifier, is_stable_serial_identifier


@dataclass(frozen=True, slots=True)
class CommissionedBus:
    bus_id: str
    stable_path: str
    baudrate: int
    parity: str
    stopbits: int
    timeout_seconds: float
    retries: int


def validate_bus(bus: CommissionedBus) -> CommissionedBus:
    stable = canonical_serial_identifier(bus.stable_path)
    if not is_stable_serial_identifier(stable) or stable != bus.stable_path:
        raise ValueError("A canonical stable serial identity is required")
    if bus.bus_id != commissioning_bus_id(stable):
        raise ValueError("Commissioning bus does not match its stable serial identity")
    if not isinstance(bus.baudrate, int) or isinstance(bus.baudrate, bool) or not 300 <= bus.baudrate <= 115200:
        raise ValueError("Invalid commissioning baudrate")
    if bus.parity not in {"N", "E", "O"} or isinstance(bus.stopbits, bool) or bus.stopbits not in {1, 2}:
        raise ValueError("Invalid commissioning serial framing")
    if not isinstance(bus.timeout_seconds, (int, float)) or isinstance(bus.timeout_seconds, bool) or not math.isfinite(bus.timeout_seconds) or not 0.05 <= bus.timeout_seconds <= 5:
        raise ValueError("Invalid commissioning serial timeout")
    if not isinstance(bus.retries, int) or isinstance(bus.retries, bool) or not 0 <= bus.retries <= 5:
        raise ValueError("Invalid commissioning serial retry count")
    return bus


class CommissionedBusStore:
    """SQLite-backed immutable identity and two-phase bus lifecycle."""

    def __init__(self, database_path: Path) -> None:
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(database_path, check_same_thread=False)
        self._connection.execute("PRAGMA busy_timeout = 5000")
        self._lock = threading.Lock()
        with self._connection:
            self._connection.execute("""
                CREATE TABLE IF NOT EXISTS commissioning_bus_authority (
                    bus_id TEXT PRIMARY KEY,
                    stable_path TEXT NOT NULL UNIQUE,
                    baudrate INTEGER NOT NULL,
                    parity TEXT NOT NULL,
                    stopbits INTEGER NOT NULL,
                    timeout_seconds REAL NOT NULL,
                    retries INTEGER NOT NULL,
                    activation_id TEXT NOT NULL,
                    state TEXT NOT NULL CHECK(state IN ('prepared', 'active'))
                )
            """)
            self._connection.execute("""
                CREATE TABLE IF NOT EXISTS commissioning_bus_audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    bus_id TEXT NOT NULL,
                    activation_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
            """)

    def prepare(self, bus: CommissionedBus, *, activation_id: str, protected_paths: set[str]) -> str:
        validate_bus(bus)
        if not isinstance(activation_id, str) or not activation_id or activation_id.strip() != activation_id or len(activation_id) > 64 or any(ord(char) < 32 for char in activation_id):
            raise ValueError("A bounded activation identity is required")
        if bus.stable_path in {canonical_serial_identifier(path) for path in protected_paths}:
            raise ValueError("Configured RS-485 adapter is protected")
        with self._lock:
            try:
                self._connection.execute("BEGIN IMMEDIATE")
                row = self._connection.execute(
                    "SELECT bus_id, stable_path, baudrate, parity, stopbits, timeout_seconds, retries, activation_id, state "
                    "FROM commissioning_bus_authority WHERE bus_id = ? OR stable_path = ?",
                    (bus.bus_id, bus.stable_path),
                ).fetchone()
                if row is not None:
                    existing = validate_bus(CommissionedBus(*row[:7]))
                    if existing != bus:
                        raise ValueError("Commissioning bus identity or serial profile conflicts")
                    if row[8] == "prepared" and row[7] != activation_id:
                        raise ValueError("Commissioning bus is prepared by another activation")
                    self._connection.commit()
                    return str(row[8])
                self._connection.execute(
                    "INSERT INTO commissioning_bus_authority VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'prepared')",
                    (bus.bus_id, bus.stable_path, bus.baudrate, bus.parity, bus.stopbits,
                     bus.timeout_seconds, bus.retries, activation_id),
                )
                self._connection.execute(
                    "INSERT INTO commissioning_bus_audit (bus_id, activation_id, action) VALUES (?, ?, 'prepared')",
                    (bus.bus_id, activation_id),
                )
                self._connection.commit()
                return "prepared"
            except Exception:
                self._connection.rollback()
                raise

    def activate(self, bus: CommissionedBus, *, activation_id: str) -> None:
        validate_bus(bus)
        with self._lock, self._connection:
            cursor = self._connection.execute(
                "UPDATE commissioning_bus_authority SET state = 'active' "
                "WHERE bus_id = ? AND stable_path = ? AND activation_id = ? AND state = 'prepared' "
                "AND baudrate = ? AND parity = ? AND stopbits = ? AND timeout_seconds = ? AND retries = ?",
                (bus.bus_id, bus.stable_path, activation_id, bus.baudrate, bus.parity,
                 bus.stopbits, bus.timeout_seconds, bus.retries),
            )
            if cursor.rowcount != 1:
                raise ValueError("Prepared commissioning bus does not match activation")
            self._connection.execute(
                "INSERT INTO commissioning_bus_audit (bus_id, activation_id, action) VALUES (?, ?, 'active')",
                (bus.bus_id, activation_id),
            )

    def cancel_prepared(self, bus_id: str, *, activation_id: str) -> bool:
        with self._lock, self._connection:
            cursor = self._connection.execute(
                "DELETE FROM commissioning_bus_authority WHERE bus_id = ? AND activation_id = ? AND state = 'prepared'",
                (bus_id, activation_id),
            )
            if cursor.rowcount == 1:
                self._connection.execute(
                    "INSERT INTO commissioning_bus_audit (bus_id, activation_id, action) VALUES (?, ?, 'cancel_prepared')",
                    (bus_id, activation_id),
                )
                return True
            return False

    def active_buses(self) -> tuple[CommissionedBus, ...]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT bus_id, stable_path, baudrate, parity, stopbits, timeout_seconds, retries "
                "FROM commissioning_bus_authority WHERE state = 'active' ORDER BY bus_id"
            ).fetchall()
        return tuple(validate_bus(CommissionedBus(*row)) for row in rows)

    def close(self) -> None:
        self._connection.close()
