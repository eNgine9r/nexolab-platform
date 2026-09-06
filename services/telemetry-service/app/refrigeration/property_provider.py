from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import ClassVar, Literal

CANONICAL_PROPERTY_PROVIDER_ID = "coolprop-heos"
CANONICAL_PROPERTY_PROVIDER_VERSION = "8.0.0"
CANONICAL_PROPERTY_PROVIDER_PROFILE = (
    f"{CANONICAL_PROPERTY_PROVIDER_ID}/{CANONICAL_PROPERTY_PROVIDER_VERSION}"
)

PropertyProviderFailureReason = Literal[
    "invalid_pressure",
    "unsupported_refrigerant",
    "unsupported_phase",
    "unsupported_provider_profile",
    "provider_version_mismatch",
    "provider_domain_error",
    "provider_error",
    "non_finite_result",
]


class SaturationPhase(str, Enum):
    DEW_EVAPORATION = "dew_evaporation"
    BUBBLE_CONDENSATION = "bubble_condensation"


class PropertyProviderError(ValueError):
    def __init__(self, reason: PropertyProviderFailureReason, message: str) -> None:
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class SaturationTemperatureResult:
    refrigerant_code: str
    absolute_pressure_pa: float
    phase: SaturationPhase
    temperature_k: float
    provider_id: str
    provider_version: str
    provider_revision: str
    provider_profile: str


class CoolPropRefrigerantPropertyProvider:
    provider_id = CANONICAL_PROPERTY_PROVIDER_ID
    provider_version = CANONICAL_PROPERTY_PROVIDER_VERSION
    provider_profile = CANONICAL_PROPERTY_PROVIDER_PROFILE

    _provider_names: ClassVar[dict[str, str]] = {
        "R134A": "HEOS::R134a",
        "R290": "HEOS::R290",
        "R404A": "HEOS::R404A",
        "R407C": "HEOS::R407C",
    }

    def __init__(self) -> None:
        import CoolProp
        from CoolProp.CoolProp import PropsSI, get_global_param_string

        actual_version = str(CoolProp.__version__)
        if actual_version != self.provider_version:
            raise PropertyProviderError(
                "provider_version_mismatch",
                f"CoolProp version {actual_version!r} does not match pinned {self.provider_version!r}",
            )
        self._props_si = PropsSI
        self.provider_revision = str(get_global_param_string("gitrevision"))

    @property
    def supported_refrigerants(self) -> tuple[str, ...]:
        return tuple(sorted(self._provider_names))

    def saturation_temperature(
        self,
        refrigerant_code: str,
        absolute_pressure_pa: float,
        phase: SaturationPhase | str,
    ) -> SaturationTemperatureResult:
        try:
            pressure = float(absolute_pressure_pa)
        except (TypeError, ValueError, OverflowError) as exc:
            raise PropertyProviderError(
                "invalid_pressure",
                "absolute saturation pressure must be numeric, finite and greater than zero",
            ) from exc
        if not math.isfinite(pressure) or pressure <= 0.0:
            raise PropertyProviderError(
                "invalid_pressure",
                "absolute saturation pressure must be finite and greater than zero",
            )

        code = refrigerant_code.strip().upper()
        provider_name = self._provider_names.get(code)
        if provider_name is None:
            raise PropertyProviderError(
                "unsupported_refrigerant",
                f"refrigerant {refrigerant_code!r} is not accepted by {self.provider_profile}",
            )

        try:
            resolved_phase = SaturationPhase(phase)
        except ValueError as exc:
            raise PropertyProviderError(
                "unsupported_phase",
                f"unsupported saturation phase {phase!r}",
            ) from exc

        quality = 1.0 if resolved_phase is SaturationPhase.DEW_EVAPORATION else 0.0
        try:
            temperature = float(
                self._props_si("T", "P", pressure, "Q", quality, provider_name)
            )
        except ValueError as exc:
            raise PropertyProviderError(
                "provider_domain_error",
                f"{self.provider_profile} rejected {code} at {pressure} Pa",
            ) from exc
        except Exception as exc:  # pragma: no cover - defensive provider boundary
            raise PropertyProviderError(
                "provider_error",
                f"{self.provider_profile} failed while evaluating {code}",
            ) from exc

        if not math.isfinite(temperature):
            raise PropertyProviderError(
                "non_finite_result",
                f"{self.provider_profile} returned a non-finite saturation temperature",
            )

        return SaturationTemperatureResult(
            refrigerant_code=code,
            absolute_pressure_pa=pressure,
            phase=resolved_phase,
            temperature_k=temperature,
            provider_id=self.provider_id,
            provider_version=self.provider_version,
            provider_revision=self.provider_revision,
            provider_profile=self.provider_profile,
        )


def create_refrigerant_property_provider(
    profile: str,
) -> CoolPropRefrigerantPropertyProvider:
    normalized = profile.strip()
    if normalized != CANONICAL_PROPERTY_PROVIDER_PROFILE:
        raise PropertyProviderError(
            "unsupported_provider_profile",
            f"unsupported refrigerant property provider profile {profile!r}",
        )
    return CoolPropRefrigerantPropertyProvider()
