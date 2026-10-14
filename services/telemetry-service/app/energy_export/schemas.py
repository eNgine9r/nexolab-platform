from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


KYIV = ZoneInfo("Europe/Kyiv")
STEPS = (0, 10, 30, 60, 300, 600, 900, 1800, 3600)
METRICS = {
    "electrical.power.active": ("P", "W", "Активна потужність"),
    "electrical.voltage": ("U", "V", "Напруга"),
    "electrical.current": ("I", "A", "Струм"),
    "electrical.frequency": ("f", "Hz", "Частота"),
    "electrical.power.reactive": ("Q", "var", "Реактивна потужність"),
    "electrical.power.apparent": ("S", "VA", "Повна потужність"),
    "electrical.power_factor": ("PF", "ratio", "Коефіцієнт потужності"),
    "temperature.internal": ("T", "degC", "Температура лічильника"),
    "electrical.energy.active": ("EΣ", "kWh", "Спожита електроенергія"),
}
COUNTER = "electrical.energy.active"


def normalized_unit(value: str) -> str:
    result = value.strip().casefold()
    return "degc" if result in {"degc", "°c"} else result


def utc(value: datetime | str) -> datetime:
    result = datetime.fromisoformat(value) if isinstance(value, str) else value
    return (result.replace(tzinfo=UTC) if result.tzinfo is None else result).astimezone(UTC)


def iso(value: datetime | str) -> str:
    return utc(value).isoformat(timespec="microseconds").replace("+00:00", "Z")


class ExportError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class SeriesSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    node_id: str = Field(min_length=1, max_length=128)
    equipment_id: str = Field(min_length=1, max_length=128)
    channel_id: str = Field(min_length=1, max_length=128)
    metric: str = Field(min_length=1, max_length=128)
    unit: str = Field(min_length=1, max_length=32)

    @property
    def key(self) -> tuple[str, ...]:
        return self.node_id, self.equipment_id, self.channel_id, self.metric, self.unit


class CatalogSeries(SeriesSelection):
    equipment_name: str
    meter_label: str
    parameter_name: str
    name_source: str = "telemetry_identity"


class ExportOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    series: list[SeriesSelection] = Field(min_length=1, max_length=64)
    from_at: datetime = Field(alias="from")
    to_at: datetime = Field(alias="to")
    step_seconds: Literal[0, 10, 30, 60, 300, 600, 900, 1800, 3600] = 0
    statistics: list[Literal["avg", "min", "max"]] = Field(default_factory=lambda: ["avg"], min_length=1, max_length=3)
    format: Literal["xlsx", "csv"] = "xlsx"

    @field_validator("from_at", "to_at")
    @classmethod
    def aware_kyiv_or_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("Потрібна часова позначка з UTC offset.")
        # UTC is the machine contract. Explicit Kyiv wall-time offsets must be real,
        # including spring gaps and the two autumn occurrences.
        if value.utcoffset().total_seconds() != 0:
            local = value.astimezone(KYIV)
            if local.replace(tzinfo=None) != value.replace(tzinfo=None) or local.utcoffset() != value.utcoffset():
                raise ValueError("Дата або UTC offset не відповідають Europe/Kyiv.")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def valid_selection(self) -> ExportOptions:
        if self.from_at >= self.to_at:
            raise ValueError("Початок має передувати завершенню.")
        if len({item.key for item in self.series}) != len(self.series):
            raise ValueError("Вибрані серії не повинні дублюватися.")
        if len(set(self.statistics)) != len(self.statistics):
            raise ValueError("Статистики не повинні дублюватися.")
        return self
