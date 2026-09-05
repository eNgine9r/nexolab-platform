from __future__ import annotations

from decimal import Decimal, InvalidOperation


class AnalogScalingUnavailableError(ValueError):
    """Fail-closed software scaling failure with a stable reason code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def canonical_decimal(value: Decimal | int | str) -> Decimal:
    try:
        result = value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise AnalogScalingUnavailableError(
            "analog_raw_value_invalid", "analog value must be a finite decimal"
        ) from error
    if not result.is_finite():
        raise AnalogScalingUnavailableError(
            "analog_raw_value_invalid", "analog value must be a finite decimal"
        )
    return result


def scale_linear_two_point(
    raw_value: Decimal | int | str,
    *,
    raw_min: Decimal | int | str,
    raw_max: Decimal | int | str,
    engineering_min: Decimal | int | str,
    engineering_max: Decimal | int | str,
) -> Decimal:
    """Map one accepted raw sample to engineering units with exact Decimal arithmetic."""

    raw = canonical_decimal(raw_value)
    lower = canonical_decimal(raw_min)
    upper = canonical_decimal(raw_max)
    eng_lower = canonical_decimal(engineering_min)
    eng_upper = canonical_decimal(engineering_max)

    if lower >= upper:
        raise AnalogScalingUnavailableError(
            "analog_raw_domain_invalid", "raw_min must be strictly less than raw_max"
        )
    if raw < lower:
        raise AnalogScalingUnavailableError(
            "analog_under_range", "raw value is below the accepted analog profile domain"
        )
    if raw > upper:
        raise AnalogScalingUnavailableError(
            "analog_over_range", "raw value is above the accepted analog profile domain"
        )

    return eng_lower + (raw - lower) * (eng_upper - eng_lower) / (upper - lower)
