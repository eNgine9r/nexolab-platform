from __future__ import annotations

import json
import multiprocessing
import os
import re
import secrets
import shutil
import tempfile
import threading
import time
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Callable

from app.db import Database
from app.energy_export.aggregation import available_steps, materialize_cells, timestamp
from app.energy_export.schemas import CatalogSeries, ExportError, ExportOptions, iso, utc
from app.energy_export.source import freeze_source, validate_catalog_selection


KIND = "nexolab-energy-export-v1"
ID = re.compile(r"^[a-f0-9]{32}$")
TERMINAL = {"failed", "canceled", "expired"}


@dataclass(frozen=True)
class ExportPolicy:
    max_pending: int = 4
    max_per_owner: int = 2
    max_records: int = 128
    max_job_bytes: int = 512 * 1024 * 1024
    max_total_bytes: int = 2 * 1024 * 1024 * 1024
    reserve_bytes: int = 128 * 1024 * 1024
    ttl_seconds: int = 3600
    retention_days: int = 365


@contextmanager
def _locked(directory: Path):
    # Locks protect only short export-manifest operations, never telemetry.
    with (directory / ".lock").open("a+b") as stream:
        if os.name == "nt":
            import msvcrt
            if stream.tell() == 0:
                stream.write(b"0"); stream.flush()
            stream.seek(0); msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                stream.seek(0); msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)


def _read(directory: Path) -> dict:
    path = directory / "manifest.json"
    if path.is_symlink() or path.stat().st_size > 256 * 1024:
        raise ExportError("job_unavailable", "Завдання недоступне.")
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("kind") != KIND or value.get("job_id") != directory.name:
        raise ExportError("job_unavailable", "Завдання недоступне.")
    return value


def _write(directory: Path, value: dict) -> None:
    temporary = directory / "manifest.tmp"
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, allow_nan=False)
        stream.flush(); os.fsync(stream.fileno())
    temporary.replace(directory / "manifest.json")


def _mutate(directory: Path, changes: dict) -> dict:
    with _locked(directory):
        value = _read(directory)
        if value["status"] in TERMINAL and changes.get("status") not in TERMINAL:
            return value
        value.update(changes)
        _write(directory, value)
        return value


def _directories(root: Path):
    if not root.exists():
        return
    for path in root.iterdir():
        if ID.fullmatch(path.name) and path.is_dir() and not path.is_symlink():
            try:
                _read(path)
                yield path
            except (OSError, ValueError, ExportError):
                continue


def _bytes(directory: Path) -> int:
    return sum(item.stat().st_size for item in directory.iterdir() if item.is_file() and not item.is_symlink())


def _clean_files(directory: Path) -> None:
    # Only inside this recognized private export directory; retain status/lock.
    _read(directory)
    for item in directory.iterdir():
        if item.name not in {"manifest.json", ".lock"} and item.is_file():
            item.unlink()


def _capacity(root: Path, directory: Path | None, policy: ExportPolicy) -> None:
    if shutil.disk_usage(root).free < policy.reserve_bytes:
        raise ExportError("insufficient_disk", "Недостатньо вільного місця для експорту. Оберіть коротший період.")
    if directory is not None and _bytes(directory) > policy.max_job_bytes:
        raise ExportError("export_too_large", "Експорт перевищує безпечний дисковий бюджет. Оберіть коротший період або менше параметрів.")
    if sum(_bytes(path) for path in root.iterdir() if ID.fullmatch(path.name) and path.is_dir() and not path.is_symlink()) > policy.max_total_bytes:
        raise ExportError("spool_full", "Сховище експорту заповнене. Скасуйте непотрібні завдання або зачекайте завершення строку зберігання.")


def _worker(root_name: str, job_id: str, database_url: str, policy: ExportPolicy) -> None:
    root = Path(root_name)
    directory = root / job_id
    tempfile.tempdir = str(directory)  # openpyxl's write-only XML belongs to this job.
    if hasattr(os, "nice"):
        try:
            os.nice(5)
        except OSError:
            pass
    # These limits affect only this spawned exporter, never telemetry or hardware.
    for key in ("OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "OMP_NUM_THREADS"):
        os.environ[key] = "1"
    database = None
    try:
        value = _read(directory)
        options = ExportOptions.model_validate(value["options"])
        phase = value["phase"]
        def guard():
            current = _read(directory)
            if current["status"] in TERMINAL:
                raise ExportError(current["status"], "Завдання перервано.")
            if utc(current["expires_at"]) <= datetime.now(UTC):
                raise ExportError("expired", "Строк зберігання експорту завершився.")
            _capacity(root, directory, policy)
        def progress(count):
            guard()
            _mutate(directory, {"progress": {"processed": count, "total": value.get("preview", {}).get("output_rows") if phase == "render" else None, "unit": "output_rows" if phase == "render" else "source_events"}})
        guard()
        if phase == "preview":
            database = Database(database_url)
            frozen = freeze_source(database, directory / "source.sqlite", options, guard=guard, progress=progress)
            database.dispose(); database = None
            warnings = ["Крок визначено консервативно за збереженими інтервалами; пропуски можуть обмежувати доступні кроки."]
            if frozen["source_events"] == 0:
                warnings.append("У вибраному періоді збережених вимірювань немає.")
            cutoff = datetime.now(UTC) - timedelta(days=policy.retention_days)
            if options.from_at < cutoff:
                warnings.append("Частина періоду виходить за поточний строк зберігання історії.")
            preview = {**frozen, "available_steps": available_steps(frozen), "actual_first_utc": timestamp(frozen["first_us"]), "actual_last_utc": timestamp(frozen["last_us"]), "retention_days": policy.retention_days, "warnings": warnings, "output_rows": None, "estimated_bytes": None}
            _mutate(directory, {"preview": preview})
            prepared = materialize_cells(directory / "source.sqlite", options, frozen, guard=guard, progress=lambda _: guard())
            guard()
            _mutate(directory, {"status": "preview_ready", "preview": {**preview, **prepared}, "progress": {"processed": frozen["source_events"], "total": frozen["source_events"], "unit": "source_events"}})
        else:
            from app.energy_export.writer import write_artifact
            guard()
            result = write_artifact(directory / "source.sqlite", directory / f"artifact.{options.format}", options, [CatalogSeries.model_validate(item) for item in value["catalog"]], value["preview"], guard=guard, progress=progress)
            guard()
            _mutate(directory, {"status": "ready", "artifact": result, "progress": {"processed": result["output_rows"], "total": result["output_rows"], "unit": "output_rows"}})
    except Exception as error:
        code = error.code if isinstance(error, ExportError) else "job_failed"
        message = str(error) if isinstance(error, ExportError) else "Експорт не завершено. Повторіть запит або оберіть коротший період."
        try:
            current = _read(directory)
            status = current["status"] if current["status"] in TERMINAL else code if code in {"canceled", "expired"} else "failed"
            _mutate(directory, {"status": status, "error": {"code": code, "message": message}})
            _clean_files(directory)
        except (OSError, ValueError, ExportError):
            pass
    finally:
        if database is not None:
            database.dispose()


class ExportJobs:
    def __init__(self, database: Database, root: Path, *, policy: ExportPolicy = ExportPolicy(), clock: Callable[[], datetime] | None = None):
        self.database = database
        self.root = root.absolute()
        self.policy = policy
        self.clock = clock or (lambda: datetime.now(UTC))
        self._lock = threading.RLock()
        self._queue = deque()
        self._process = None
        self._active_id = None
        self._active_phase = None
        self._stop = threading.Event()
        self._thread = None
        self._tickets = {}
        self._startup_error = None

    def start(self):
        with self._lock:
            if self._thread is not None:
                return
            try:
                if self.root.is_symlink():
                    raise ExportError("spool_unavailable", "Сховище експорту недоступне.")
                self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
                for directory in _directories(self.root):
                    value = _read(directory)
                    if value["status"] in {"running", "queued"}:
                        _mutate(directory, {"status": "failed", "error": {"code": "interrupted", "message": "Завдання перервано перезапуском. Створіть новий експорт."}})
                        _clean_files(directory)
                self._thread = threading.Thread(target=self._loop, name="energy-export-coordinator", daemon=True)
                self._thread.start()
            except (OSError, ValueError, ExportError):
                self._startup_error = "Сховище експорту недоступне. Збір телеметрії продовжується."

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
        with self._lock:
            if self._process is not None:
                self._process.terminate(); self._process.join(timeout=2)
                if self._process.is_alive():
                    self._process.kill(); self._process.join(timeout=1)
            for job_id in [*self._queue, *([self._active_id] if self._active_id else [])]:
                directory = self.root / job_id
                value = _read(directory)
                if value["status"] in {"queued", "running"}:
                    _mutate(directory, {"status": "failed", "error": {"code": "interrupted", "message": "Завдання перервано. Створіть новий експорт."}})
                    _clean_files(directory)
                elif value["status"] in TERMINAL:
                    _clean_files(directory)
            self._queue.clear(); self._tickets.clear()
            self._process = self._active_id = self._active_phase = None

    def _ensure(self):
        if self._thread is None and self._startup_error is None:
            self.start()
        if self._startup_error is not None or self._stop.is_set():
            raise ExportError("service_unavailable", self._startup_error or "Сервіс експорту завершує роботу.")

    def create(self, owner: tuple[str, ...], options: ExportOptions):
        self._ensure()
        if options.to_at > self.clock() + timedelta(seconds=2):
            raise ExportError("future_period", "Завершення періоду не може бути в майбутньому.")
        if options.to_at - options.from_at > timedelta(days=self.policy.retention_days):
            raise ExportError("period_too_large", f"Період не повинен перевищувати строк зберігання: {self.policy.retention_days} діб.")
        selected = validate_catalog_selection(self.database, owner[0], options)
        with self._lock:
            self._expire()
            jobs = [_read(path) for path in _directories(self.root)]
            # Keep the manifest registry bounded without letting canceled/failed
            # jobs reserve global capacity for their entire diagnostic TTL.
            if len(jobs) >= self.policy.max_records:
                reclaimable = sorted((item for item in jobs if item["status"] in TERMINAL and item["job_id"] != self._active_id), key=lambda item: item["created_at"])
                for item in reclaimable:
                    directory = self.root / item["job_id"]
                    _clean_files(directory)
                    shutil.rmtree(directory)
                    self._tickets = {key: ticket for key, ticket in self._tickets.items() if ticket[0] != item["job_id"]}
                    jobs.remove(item)
                    if len(jobs) < self.policy.max_records:
                        break
            if len(jobs) >= self.policy.max_records or len(self._queue) + int(self._process is not None) >= self.policy.max_pending:
                raise ExportError("queue_full", "Черга експорту заповнена. Зачекайте або скасуйте непотрібні завдання.")
            if sum(tuple(item["owner"]) == owner and item["status"] in {"queued", "running", "preview_ready"} for item in jobs) >= self.policy.max_per_owner:
                raise ExportError("owner_limit", "У вас уже є незавершені експорти. Завершіть або скасуйте їх.")
            _capacity(self.root, None, self.policy)
            job_id = secrets.token_hex(16)
            directory = self.root / job_id
            directory.mkdir(mode=0o700)
            now = self.clock()
            value = {"kind": KIND, "job_id": job_id, "owner": list(owner), "status": "queued", "phase": "preview", "created_at": iso(now), "expires_at": iso(now + timedelta(seconds=self.policy.ttl_seconds)),
                     "options": options.model_dump(mode="json", by_alias=True), "catalog": [item.model_dump() for item in selected], "progress": {"processed": 0, "total": None, "unit": "source_events"}, "preview": None, "artifact": None, "error": None}
            _write(directory, value)
            self._queue.append(job_id)
            return self._public(value)

    def _owned(self, owner: tuple[str, ...], job_id: str) -> tuple[Path, dict]:
        self._ensure()
        if not ID.fullmatch(job_id):
            raise ExportError("job_not_found", "Завдання не знайдено.")
        directory = self.root / job_id
        try:
            if directory.is_symlink():
                raise OSError()
            value = _read(directory)
            if tuple(value["owner"]) != owner:
                raise OSError()
        except (OSError, ValueError, ExportError):
            raise ExportError("job_not_found", "Завдання не знайдено.") from None
        if utc(value["expires_at"]) <= self.clock() and value["status"] != "expired":
            value = _mutate(directory, {"status": "expired"})
            if self._active_id != job_id:
                _clean_files(directory)
        return directory, value

    @staticmethod
    def _public(value: dict):
        return {key: value.get(key) for key in ("job_id", "status", "phase", "created_at", "expires_at", "options", "progress", "preview", "artifact", "error")}

    def get(self, owner: tuple[str, ...], job_id: str):
        with self._lock:
            _, value = self._owned(owner, job_id)
            return self._public(value)

    def confirm(self, owner: tuple[str, ...], job_id: str):
        with self._lock:
            directory, value = self._owned(owner, job_id)
            if value["status"] != "preview_ready":
                raise ExportError("job_not_prepared", "Спочатку дочекайтеся попереднього перегляду.")
            options = ExportOptions.model_validate(value["options"])
            validate_catalog_selection(self.database, owner[0], options)
            _capacity(self.root, directory, self.policy)
            if value["preview"]["estimated_bytes"] > shutil.disk_usage(self.root).free - self.policy.reserve_bytes:
                raise ExportError("insufficient_disk", "Недостатньо місця для орієнтовного розміру файлу.")
            if len(self._queue) + int(self._process is not None) >= self.policy.max_pending:
                raise ExportError("queue_full", "Черга експорту заповнена. Зачекайте.")
            value = _mutate(directory, {"status": "queued", "phase": "render", "progress": {"processed": 0, "total": value["preview"]["output_rows"], "unit": "output_rows"}})
            self._queue.append(job_id)
            return self._public(value)

    def cancel(self, owner: tuple[str, ...], job_id: str):
        with self._lock:
            directory, value = self._owned(owner, job_id)
            if value["status"] != "expired":
                value = _mutate(directory, {"status": "canceled"})
            self._queue = deque(item for item in self._queue if item != job_id)
            if self._active_id != job_id:
                _clean_files(directory)
            self._tickets = {key: item for key, item in self._tickets.items() if item[0] != job_id}
            return self._public(value)

    def ticket(self, owner: tuple[str, ...], job_id: str, reauthorize: Callable[[], None] | None = None):
        with self._lock:
            directory, value = self._owned(owner, job_id)
            if value["status"] != "ready":
                if value["status"] == "expired":
                    raise ExportError("expired", "Строк зберігання експорту завершився. Створіть новий експорт.")
                raise ExportError("artifact_not_ready", "Файл ще не готовий.")
            validate_catalog_selection(self.database, owner[0], ExportOptions.model_validate(value["options"]))
            path = directory / f"artifact.{value['options']['format']}"
            if path.is_symlink() or not path.is_file() or path.stat().st_size != value["artifact"]["bytes"]:
                raise ExportError("artifact_unavailable", "Файл недоступний. Створіть новий експорт.")
            self._tickets = {key: item for key, item in self._tickets.items() if item[1] > time.monotonic() and item[0] != job_id}
            token = secrets.token_urlsafe(32)
            self._tickets[token] = (job_id, time.monotonic() + min(60, (utc(value["expires_at"]) - self.clock()).total_seconds()), owner, reauthorize)
            return {"ticket": token, "expires_in_seconds": 60}

    def consume_ticket(self, job_id: str, token: str):
        with self._lock:
            ticket = self._tickets.pop(token, None)
            if ticket is None or ticket[0] != job_id or ticket[1] <= time.monotonic():
                raise ExportError("download_expired", "Посилання недійсне або вже використане. Авторизуйте завантаження знову.")
            if ticket[3] is not None:
                ticket[3]()
            directory, value = self._owned(ticket[2], job_id)
            if value["status"] != "ready":
                raise ExportError("artifact_not_ready", "Файл недоступний.")
            validate_catalog_selection(self.database, ticket[2][0], ExportOptions.model_validate(value["options"]))
            format = value["options"]["format"]
            path = directory / f"artifact.{format}"
            if path.is_symlink() or not path.is_file():
                raise ExportError("artifact_unavailable", "Файл недоступний.")
            return path, f"nexolab-energy-{job_id[:12]}.{format}", format

    def _expire(self):
        for directory in list(_directories(self.root)):
            value = _read(directory)
            if utc(value["expires_at"]) <= self.clock():
                _mutate(directory, {"status": "expired"})
                if directory.name != self._active_id:
                    _clean_files(directory)
                    if utc(value["expires_at"]) + timedelta(days=1) <= self.clock():
                        shutil.rmtree(directory)

    def _loop(self):
        next_expiry_check = 0.0
        while not self._stop.wait(0.2):
            with self._lock:
                try:
                    if time.monotonic() >= next_expiry_check:
                        self._expire()
                        next_expiry_check = time.monotonic() + 5
                    if self._process is not None and not self._process.is_alive():
                        self._process.join()
                        directory = self.root / self._active_id
                        value = _read(directory)
                        if value["status"] in {"running", "queued"} and value["phase"] == self._active_phase and self._active_id not in self._queue:
                            _mutate(directory, {"status": "failed", "error": {"code": "worker_interrupted", "message": "Завдання перервано. Створіть новий експорт."}})
                            _clean_files(directory)
                        elif value["status"] in TERMINAL:
                            _clean_files(directory)
                        self._process = self._active_id = self._active_phase = None
                    if self._process is None and self._queue:
                        job_id = self._queue.popleft()
                        directory = self.root / job_id
                        if _read(directory)["status"] != "queued":
                            continue
                        launched = _mutate(directory, {"status": "running"})
                        process = multiprocessing.get_context("spawn").Process(target=_worker, args=(str(self.root), job_id, str(self.database.engine.url.render_as_string(hide_password=False)), self.policy), name="energy-export-worker", daemon=True)
                        try:
                            process.start()
                        except Exception:
                            _mutate(directory, {"status": "failed", "error": {"code": "worker_unavailable", "message": "Фоновий процес недоступний. Повторіть експорт."}})
                            _clean_files(directory)
                            continue
                        self._process, self._active_id = process, job_id
                        self._active_phase = launched["phase"]
                except (OSError, ValueError, ExportError):
                    # A failed export coordinator cannot stop ingestion or readiness.
                    continue
