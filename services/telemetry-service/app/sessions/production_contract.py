from __future__ import annotations

from dataclasses import dataclass
from typing import Any


EXPECTED_PRODUCTION_SERIES_COUNT = 34


@dataclass(frozen=True, slots=True)
class ProductionChannel:
    node_id: str
    equipment_id: str
    channel_id: str
    metric: str
    unit: str
    device_type: str
    profile_version: str
    register_key: str
    register_address: int

    @property
    def identity(self) -> tuple[str, str, str, str]:
        return (self.node_id, self.equipment_id, self.channel_id, self.metric)

    @property
    def metadata(self) -> dict[str, Any]:
        return {
            "device_type": self.device_type,
            "profile_version": self.profile_version,
            "register_key": self.register_key,
            "register_address": self.register_address,
        }


_XJP_CHANNELS = (
    ProductionChannel(
        "edge-01",
        "K106",
        "106-03",
        "temperature.probe",
        "degC",
        "dixell-xjp60d",
        "xjp60d-probe-map-v1",
        "probe_3",
        260,
    ),
    ProductionChannel(
        "edge-01",
        "K106",
        "106-04",
        "temperature.probe",
        "degC",
        "dixell-xjp60d",
        "xjp60d-probe-map-v1",
        "probe_4",
        262,
    ),
)
_LE01MP_REGISTERS = (
    ("voltage", 0, "electrical.voltage", "V"),
    ("current", 1, "electrical.current", "A"),
    ("frequency", 2, "electrical.frequency", "Hz"),
    ("active_power", 3, "electrical.power.active", "W"),
    ("reactive_power", 4, "electrical.power.reactive", "var"),
    ("apparent_power", 5, "electrical.power.apparent", "VA"),
    ("power_factor", 6, "electrical.power_factor", "ratio"),
    ("internal_temperature", 37, "temperature.internal", "degC"),
)
_LE01MP_CHANNELS = tuple(
    ProductionChannel(
        "edge-01",
        f"LE01MP-{unit_id}",
        f"{unit_id}-{key.replace('_', '-')}",
        metric,
        unit,
        "f-and-f-le-01mp",
        "le01mp-validated-register-subset-v1",
        key,
        address,
    )
    for unit_id in (200, 201, 202, 203)
    for key, address, metric, unit in _LE01MP_REGISTERS
)

PRODUCTION_CHANNELS = _XJP_CHANNELS + _LE01MP_CHANNELS
PRODUCTION_CHANNEL_BY_IDENTITY = {
    channel.identity: channel for channel in PRODUCTION_CHANNELS
}
PRODUCTION_IDENTITIES = frozenset(PRODUCTION_CHANNEL_BY_IDENTITY)

assert len(PRODUCTION_CHANNELS) == EXPECTED_PRODUCTION_SERIES_COUNT
