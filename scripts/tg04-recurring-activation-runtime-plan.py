#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
TELEMETRY_ROOT = ROOT / "services" / "telemetry-service"
sys.path.insert(0, str(TELEMETRY_ROOT))
from app.daily_reports.domain import latest_due_report_date, resolve_report_window  # noqa: E402

EXPECTED_PROFILE_NAME = "TestLAB · CoolJet · Daily 07:50"
EXPECTED_TIMEZONE = "Europe/Kyiv"
EXPECTED_WEEKDAYS = (0, 1, 2, 3, 4)
EXPECTED_HOUR = 7
EXPECTED_MINUTE = 50
EXPECTED_WINDOW_MINUTES = 720
POSTGRES = "nexolab-central-postgres-1"
GATEWAY = "nexolab-central-telegram-gateway-1"
RUNTIME_READ_TIMEOUT_SECONDS = 15.0
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


class PlanError(RuntimeError):
    pass


@dataclass(frozen=True)
class Profile:
    id: str
    organization_id: str
    name: str
    timezone: str
    report_hour: int
    report_minute: int
    weekdays: tuple[int, ...]
    analysis_window_minutes: int
    created_at: datetime


def _run(command: list[str]) -> str:
    try:
        result = subprocess.run(
            command,
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=RUNTIME_READ_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as error:
        raise PlanError("runtime_read_timeout") from error
    if result.returncode != 0:
        raise PlanError("runtime_read_failed")
    return result.stdout.strip()


def _pg_json(sql: str) -> Any:
    output = _run([
        "docker", "exec", POSTGRES, "sh", "-ec",
        'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At -c "$1"', "sh", sql,
    ])
    try:
        return json.loads(output)
    except json.JSONDecodeError as error:
        raise PlanError("postgres_json_invalid") from error


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise PlanError("timestamp_naive")
    return parsed.astimezone(UTC)


def _load_profile() -> Profile:
    rows = _pg_json("""
SELECT COALESCE(json_agg(json_build_object(
  'id', id,
  'organization_id', organization_id,
  'name', name,
  'timezone', timezone,
  'report_hour', report_hour,
  'report_minute', report_minute,
  'weekdays', weekdays,
  'analysis_window_minutes', analysis_window_minutes,
  'created_at', created_at
) ORDER BY id), '[]'::json)
FROM refrigeration_daily_report_profiles
WHERE enabled = true;
""")
    if not isinstance(rows, list) or len(rows) != 1:
        raise PlanError("enabled_profile_count_must_be_one")
    raw = rows[0]
    profile = Profile(
        id=str(raw["id"]),
        organization_id=str(raw["organization_id"]),
        name=str(raw["name"]),
        timezone=str(raw["timezone"]),
        report_hour=int(raw["report_hour"]),
        report_minute=int(raw["report_minute"]),
        weekdays=tuple(int(value) for value in raw["weekdays"]),
        analysis_window_minutes=int(raw["analysis_window_minutes"]),
        created_at=_parse_datetime(str(raw["created_at"])),
    )
    if not UUID_RE.fullmatch(profile.id) or not UUID_RE.fullmatch(profile.organization_id):
        raise PlanError("profile_identity_invalid")
    if (
        profile.name != EXPECTED_PROFILE_NAME
        or profile.timezone != EXPECTED_TIMEZONE
        or profile.report_hour != EXPECTED_HOUR
        or profile.report_minute != EXPECTED_MINUTE
        or profile.weekdays != EXPECTED_WEEKDAYS
        or profile.analysis_window_minutes != EXPECTED_WINDOW_MINUTES
    ):
        raise PlanError("enabled_profile_contract_mismatch")
    return profile


def _load_snapshots(profile: Profile) -> list[dict[str, Any]]:
    if not UUID_RE.fullmatch(profile.organization_id):
        raise PlanError("organization_identity_invalid")
    sql = f"""
SELECT COALESCE(json_agg(json_build_object(
  'id', id,
  'profile_id', profile_id,
  'local_report_date', local_report_date,
  'scheduled_for', scheduled_for,
  'payload_sha256', payload_sha256
) ORDER BY scheduled_for, id), '[]'::json)
FROM refrigeration_daily_report_snapshots
WHERE organization_id = '{profile.organization_id}';
"""
    rows = _pg_json(sql)
    if not isinstance(rows, list):
        raise PlanError("snapshot_payload_invalid")
    return rows


def _load_outbox(expected_organization_id: str) -> tuple[list[dict[str, Any]], int, bool]:
    code = r'''
import json, os, sqlite3, sys
path=os.environ.get("TELEGRAM_STATE_DB_PATH", "/app/data/telegram-delivery/outbox.db")
thread=os.environ.get("TELEGRAM_DESTINATION_MESSAGE_THREAD_ID", "")
chat=os.environ.get("TELEGRAM_DESTINATION_CHAT_ID", "")
backend_org=os.environ.get("NEXOLAB_BACKEND_ORGANIZATION_ID", "")
template=os.environ.get("TELEGRAM_MINI_APP_URL_TEMPLATE", "")
username=os.environ.get("NEXOLAB_BACKEND_USERNAME", "")
if not thread.isdigit() or int(thread) <= 0:
    raise SystemExit(4)
config_ready=(chat.startswith("-") and chat[1:].isdigit() and backend_org == sys.argv[1] and bool(template) and bool(username))
con=sqlite3.connect(f"file:{path}?mode=ro", uri=True)
con.row_factory=sqlite3.Row
rows=[]
for row in con.execute("SELECT id,snapshot_id,snapshot_sha256,destination_chat_id,destination_message_thread_id,state,attempts,last_error_code,telegram_message_id,sent_at,duplicate_risk,created_at,updated_at FROM telegram_deliveries ORDER BY id"):
    rows.append({
      "id": row["id"], "snapshot_id": row["snapshot_id"], "snapshot_sha256": row["snapshot_sha256"],
      "destination": (
          "topic"
          if row["destination_chat_id"] == chat and int(row["destination_message_thread_id"] or 0) == int(thread)
          else "general"
          if row["destination_chat_id"] == chat and int(row["destination_message_thread_id"] or 0) == 0
          else "foreign"
      ),
      "state": row["state"], "attempts": row["attempts"], "last_error_code": row["last_error_code"],
      "telegram_message_id_present": row["telegram_message_id"] is not None,
      "sent_at": row["sent_at"], "duplicate_risk": bool(row["duplicate_risk"]),
      "created_at": row["created_at"], "updated_at": row["updated_at"],
    })
print(json.dumps({"rows":rows,"max_age_hours":int(os.environ.get("TELEGRAM_MAX_SNAPSHOT_AGE_HOURS","36")),"delivery_config_ready":config_ready}, sort_keys=True))
'''
    raw = _run(["docker", "exec", GATEWAY, "python3", "-c", code, expected_organization_id])
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as error:
        raise PlanError("outbox_json_invalid") from error
    rows = payload.get("rows")
    max_age = int(payload.get("max_age_hours", 0))
    config_ready = payload.get("delivery_config_ready") is True
    if not isinstance(rows, list) or not 1 <= max_age <= 168:
        raise PlanError("outbox_runtime_contract_invalid")
    if not config_ready:
        raise PlanError("gateway_delivery_runtime_contract_invalid")
    return rows, max_age, config_ready


def _fingerprint(rows: list[dict[str, Any]]) -> str:
    payload = json.dumps(rows, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return hashlib.sha256(payload).hexdigest()


def compute_plan(now: datetime | None = None, *, fingerprint_through_id: int | None = None) -> dict[str, Any]:
    resolved_now = (now or datetime.now(UTC)).astimezone(UTC)
    profile = _load_profile()
    snapshots = _load_snapshots(profile)
    outbox, max_age_hours, delivery_config_ready = _load_outbox(profile.organization_id)
    if any(row.get("destination") == "foreign" for row in outbox):
        raise PlanError("foreign_outbox_destination")

    due_date = latest_due_report_date(
        resolved_now,
        timezone=profile.timezone,
        report_hour=profile.report_hour,
        report_minute=profile.report_minute,
        weekdays=profile.weekdays,
    )
    predicted_generation = 0
    due_scheduled_for: datetime | None = None
    due_exists = False
    if due_date is not None:
        window = resolve_report_window(
            due_date,
            timezone=profile.timezone,
            report_hour=profile.report_hour,
            report_minute=profile.report_minute,
            analysis_window_minutes=profile.analysis_window_minutes,
        )
        due_scheduled_for = window.scheduled_for
        matches = [
            row for row in snapshots
            if str(row.get("profile_id")) == profile.id
            and str(row.get("local_report_date")) == due_date.isoformat()
        ]
        if len(matches) > 1:
            raise PlanError("duplicate_due_snapshot")
        due_exists = len(matches) == 1
        if not due_exists and due_scheduled_for >= profile.created_at:
            predicted_generation = 1

    cutoff = resolved_now - timedelta(hours=max_age_hours)
    eligible = [
        row for row in snapshots
        if cutoff <= _parse_datetime(str(row["scheduled_for"])) <= resolved_now
    ]
    topic_rows_by_snapshot: dict[str, list[dict[str, Any]]] = {}
    for row in outbox:
        if row.get("destination") == "topic":
            topic_rows_by_snapshot.setdefault(str(row.get("snapshot_id")), []).append(row)
    for rows in topic_rows_by_snapshot.values():
        if len(rows) > 1:
            raise PlanError("duplicate_topic_outbox_identity")

    missing_existing = sum(
        1
        for row in eligible
        if not any(
            delivery.get("state") == "sent" and not delivery.get("duplicate_risk")
            for delivery in topic_rows_by_snapshot.get(str(row["id"]), [])
        )
    )
    new_due_deliverable = 0
    if predicted_generation and due_scheduled_for is not None and cutoff <= due_scheduled_for <= resolved_now:
        new_due_deliverable = 1
    predicted_immediate = missing_existing + new_due_deliverable

    prefix_rows = (
        [row for row in outbox if int(row["id"]) <= fingerprint_through_id]
        if fingerprint_through_id is not None
        else outbox
    )
    return {
        "ok": True,
        "profile": EXPECTED_PROFILE_NAME,
        "schedule": "Europe/Kyiv Mon-Fri 07:50",
        "analysis_window_minutes": EXPECTED_WINDOW_MINUTES,
        "now_utc": resolved_now.isoformat(),
        "due_local_report_date": due_date.isoformat() if due_date else None,
        "due_snapshot_exists": due_exists,
        "predicted_snapshot_generation_count": predicted_generation,
        "snapshot_total_count": len(snapshots),
        "eligible_existing_snapshot_count": len(eligible),
        "missing_existing_topic_delivery_count": missing_existing,
        "predicted_immediate_delivery_count": predicted_immediate,
        "gateway_max_snapshot_age_hours": max_age_hours,
        "delivery_runtime_config_ready": delivery_config_ready,
        "outbox_rows": len(outbox),
        "outbox_max_id": max((int(row["id"]) for row in outbox), default=0),
        "outbox_non_sent_rows": sum(1 for row in outbox if row.get("state") != "sent"),
        "outbox_duplicate_risk_rows": sum(1 for row in outbox if bool(row.get("duplicate_risk"))),
        "outbox_topic_sent_rows": sum(1 for row in outbox if row.get("destination") == "topic" and row.get("state") == "sent"),
        "outbox_fingerprint": _fingerprint(outbox),
        "prefix_outbox_rows": len(prefix_rows),
        "prefix_outbox_fingerprint": _fingerprint(prefix_rows),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only TG-04 recurring activation plan")
    parser.add_argument("--now", help="Optional timezone-aware ISO timestamp for deterministic tests")
    parser.add_argument("--fingerprint-through-id", type=int)
    args = parser.parse_args()
    now = _parse_datetime(args.now) if args.now else None
    try:
        print(json.dumps(compute_plan(now, fingerprint_through_id=args.fingerprint_through_id), sort_keys=True))
    except PlanError as error:
        print(json.dumps({"ok": False, "error": str(error)}, sort_keys=True))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
