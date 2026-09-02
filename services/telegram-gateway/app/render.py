from __future__ import annotations

from datetime import datetime
import math
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.domain import RenderedMessage, ReportSnapshot


_STATUS_LABELS = {
    "normal": "🟢 НОРМА",
    "attention": "🟡 УВАГА",
    "critical": "🔴 КРИТИЧНО",
    "incomplete": "⚪ НЕПОВНІ ДАНІ",
}


class RenderError(ValueError):
    pass


def render_report(
    snapshot: ReportSnapshot,
    *,
    mini_app_url_template: str,
    max_chars: int = 3900,
) -> RenderedMessage:
    payload = snapshot.payload
    report = _mapping(payload.get("report"))
    identity = _mapping(payload.get("identity"))
    quality = _mapping(payload.get("quality"))
    m_packets = _mapping(payload.get("m_packets"))
    circuit = _mapping(payload.get("refrigeration_circuit"))
    compressor = _mapping(payload.get("compressor"))
    energy = _mapping(payload.get("energy"))
    defrost = _mapping(payload.get("defrost"))
    alerts = _mapping(payload.get("alerts"))

    equipment = _first_text(identity, "equipment_name", "equipment_code") or "Обладнання не вказано"
    equipment = _clip_line(equipment, 120)
    status = _STATUS_LABELS.get(str(report.get("status", "incomplete")), "⚪ НЕПОВНІ ДАНІ")
    date_time = _report_date_time(report, snapshot)

    lines = [
        "❄️ NEXOLAB · Ранковий звіт",
        equipment,
        date_time,
        "",
        status,
        "",
        "🌡 М-пакети",
        f"Tmin  {_temperature(m_packets.get('minimum_c'))}",
        f"Tmax  {_temperature(m_packets.get('maximum_c'))}",
        f"Валідні {_count_pair(m_packets)}",
        "",
        "❄️ Холодильний контур",
        f"Кипіння: {_metric(circuit.get('evaporation_saturation_temperature'), '°C')}",
        f"Перегрів: {_metric(circuit.get('superheat'), 'K')}",
        f"Конденсація: {_metric(circuit.get('condensation_saturation_temperature'), '°C')}",
        f"Переохолодження: {_metric(circuit.get('subcooling'), 'K')}",
        "",
        f"⚙️ Компресор: {_compressor(compressor, quality)}",
        f"⚡ Енергія: {_energy(energy, report, quality)}",
        f"🔄 Відтайка: {_defrost(defrost)}",
    ]

    warning = _warning_summary(alerts, quality)
    if warning:
        lines.extend(["", warning])
    text = "\n".join(lines).strip()
    if len(text) > max_chars:
        text = text[: max_chars - 1].rstrip() + "…"
    button_url = mini_app_url_template.replace(
        "{snapshot_id}", quote(snapshot.id, safe="")
    )
    return RenderedMessage(text=text, button_url=button_url)


def _report_date_time(report: dict[str, Any], snapshot: ReportSnapshot) -> str:
    timezone_name = report.get("timezone")
    if not isinstance(timezone_name, str) or not timezone_name.strip():
        timezone_name = "Europe/Kyiv"
    try:
        zone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        zone = ZoneInfo("Europe/Kyiv")
    scheduled = report.get("scheduled_for")
    parsed = _datetime_value(scheduled) or snapshot.scheduled_for
    local = parsed.astimezone(zone)
    return local.strftime("%d.%m.%Y · %H:%M")


def _temperature(value: object) -> str:
    number = _finite(value)
    return "недоступно" if number is None else f"{number:+.1f} °C"


def _count_pair(section: dict[str, Any]) -> str:
    valid = section.get("valid_channels")
    configured = section.get("configured_channels")
    if not isinstance(valid, int) or isinstance(valid, bool):
        return "недоступно"
    if not isinstance(configured, int) or isinstance(configured, bool) or configured < 0:
        return "недоступно"
    return f"{valid}/{configured}"


def _metric(value: object, default_unit: str) -> str:
    section = _mapping(value)
    if section.get("status") != "available":
        return "недоступно"
    number = _finite(section.get("value"))
    if number is None:
        for key in ("value_c", "temperature_c", "value_k", "delta_k"):
            number = _finite(section.get(key))
            if number is not None:
                break
    if number is None:
        return "недоступно"
    unit = section.get("unit")
    rendered_unit = unit.strip() if isinstance(unit, str) and unit.strip() else default_unit
    return f"{number:.1f} {rendered_unit}".strip()


def _compressor(section: dict[str, Any], quality: dict[str, Any]) -> str:
    if section.get("status") != "available":
        return "недоступно"
    duty = _finite(section.get("duty_percent"))
    if duty is None:
        return "недоступно"
    suffix = " · неповні дані" if _quality_has(quality, "compressor_coverage_incomplete") else ""
    return f"{duty:.1f} %{suffix}"


def _energy(section: dict[str, Any], report: dict[str, Any], quality: dict[str, Any]) -> str:
    if section.get("status") != "available":
        return "недоступно"
    value = _finite(section.get("interval_kwh"))
    if value is None:
        return "недоступно"
    minutes = report.get("analysis_window_minutes")
    window = ""
    if isinstance(minutes, int) and not isinstance(minutes, bool) and minutes > 0:
        hours = minutes / 60.0
        window = f" / {hours:g} год"
    suffix = " · неповні дані" if _quality_has(quality, "energy_evidence_unavailable") else ""
    return f"{value:.2f} kWh{window}{suffix}"


def _defrost(section: dict[str, Any]) -> str:
    if section.get("status") != "available":
        return "недоступно"
    seconds = _finite(section.get("duration_seconds"))
    if seconds is None or seconds < 0:
        return "недоступно"
    minutes = seconds / 60.0
    if math.isclose(minutes, round(minutes), abs_tol=1e-9):
        return f"{int(round(minutes))} хв"
    return f"{minutes:.1f} хв"


def _warning_summary(alerts: dict[str, Any], quality: dict[str, Any]) -> str | None:
    active = alerts.get("active_count")
    active_count = active if isinstance(active, int) and not isinstance(active, bool) and active >= 0 else 0
    quality_status = quality.get("status")
    parts: list[str] = []
    if active_count:
        parts.append(f"активні тривоги: {active_count}")
    if quality_status == "incomplete":
        parts.append("якість даних: неповні дані")
    if not parts:
        return None
    return "⚠️ " + "; ".join(parts)


def _quality_has(quality: dict[str, Any], reason: str) -> bool:
    reasons = quality.get("reasons")
    return isinstance(reasons, list) and reason in reasons


def _mapping(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _first_text(value: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        item = value.get(key)
        if isinstance(item, str) and item.strip():
            return item.strip()
    return None


def _finite(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _datetime_value(value: object) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _clip_line(value: str, maximum: int) -> str:
    normalized = " ".join(value.split())
    if len(normalized) <= maximum:
        return normalized
    return normalized[: maximum - 1].rstrip() + "…"
