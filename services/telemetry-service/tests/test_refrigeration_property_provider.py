from __future__ import annotations

import json
import math
import os
import subprocess
import sys
from pathlib import Path

import pytest
from app.refrigeration.property_provider import (
    CANONICAL_PROPERTY_PROVIDER_PROFILE,
    PropertyProviderError,
    SaturationPhase,
    create_refrigerant_property_provider,
)

_FIXTURE_PATH = Path(__file__).resolve().parents[3] / "docs" / "refrigeration-property-provider-golden-v1.json"
_FIXTURE = json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))


def test_provider_module_import_is_lazy_and_does_not_load_coolprop() -> None:
    code = (
        "import sys; "
        "import app.refrigeration.property_provider; "
        "assert 'CoolProp' not in sys.modules"
    )
    subprocess.run(
        [sys.executable, "-c", code],
        check=True,
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "PYTHONPATH": "."},
    )


def test_coolprop_profile_metadata_and_supported_refrigerants() -> None:
    provider = create_refrigerant_property_provider(CANONICAL_PROPERTY_PROVIDER_PROFILE)

    assert provider.provider_id == "coolprop-heos"
    assert provider.provider_version == "8.0.0"
    assert provider.provider_profile == "coolprop-heos/8.0.0"
    assert provider.supported_refrigerants == ("R134A", "R290", "R404A", "R407C")
    assert provider.provider_revision == _FIXTURE["provider"]["git_revision"]


@pytest.mark.parametrize("case", _FIXTURE["saturation_cases"])
def test_coolprop_saturation_matches_pinned_golden_fixture(case: dict[str, object]) -> None:
    provider = create_refrigerant_property_provider(CANONICAL_PROPERTY_PROVIDER_PROFILE)
    result = provider.saturation_temperature(
        refrigerant_code=str(case["refrigerant"]),
        absolute_pressure_pa=float(case["pressure_pa"]),
        phase=SaturationPhase(str(case["phase"])),
    )

    assert result.provider_profile == CANONICAL_PROPERTY_PROVIDER_PROFILE
    assert result.refrigerant_code == str(case["refrigerant"])
    assert result.absolute_pressure_pa == float(case["pressure_pa"])
    assert math.isclose(
        result.temperature_k,
        float(case["expected_temperature_k"]),
        rel_tol=0.0,
        abs_tol=float(_FIXTURE["provider"]["temperature_tolerance_k"]),
    )


def test_zeotropic_blend_requires_explicit_dew_bubble_semantics() -> None:
    provider = create_refrigerant_property_provider(CANONICAL_PROPERTY_PROVIDER_PROFILE)
    bubble = provider.saturation_temperature("R407C", 1_000_000.0, SaturationPhase.BUBBLE_CONDENSATION)
    dew = provider.saturation_temperature("R407C", 1_000_000.0, SaturationPhase.DEW_EVAPORATION)

    assert dew.temperature_k > bubble.temperature_k
    assert dew.temperature_k - bubble.temperature_k > 5.0


@pytest.mark.parametrize("pressure", [0.0, -1.0, float("nan"), float("inf"), "not-a-number", None])
def test_invalid_pressure_fails_closed_before_provider_call(pressure: object) -> None:
    provider = create_refrigerant_property_provider(CANONICAL_PROPERTY_PROVIDER_PROFILE)
    with pytest.raises(PropertyProviderError) as exc:
        provider.saturation_temperature("R290", pressure, SaturationPhase.DEW_EVAPORATION)
    assert exc.value.reason == "invalid_pressure"


def test_unsupported_refrigerant_fails_closed_without_alias_guessing() -> None:
    provider = create_refrigerant_property_provider(CANONICAL_PROPERTY_PROVIDER_PROFILE)
    for refrigerant in ("R448A", "R449A", "R452A", "NOT_A_REFRIGERANT"):
        with pytest.raises(PropertyProviderError) as exc:
            provider.saturation_temperature(refrigerant, 500_000.0, SaturationPhase.DEW_EVAPORATION)
        assert exc.value.reason == "unsupported_refrigerant"


@pytest.mark.parametrize(
    ("refrigerant", "pressure"),
    [("R407C", 100.0), ("R290", 1_000_000_000.0)],
    ids=["below-saturation-domain", "above-saturation-domain"],
)
def test_out_of_domain_pressure_is_a_typed_provider_failure(
    refrigerant: str, pressure: float
) -> None:
    provider = create_refrigerant_property_provider(CANONICAL_PROPERTY_PROVIDER_PROFILE)
    with pytest.raises(PropertyProviderError) as exc:
        provider.saturation_temperature(
            refrigerant, pressure, SaturationPhase.DEW_EVAPORATION
        )
    assert exc.value.reason == "provider_domain_error"


def test_unknown_provider_profile_fails_closed() -> None:
    with pytest.raises(PropertyProviderError) as exc:
        create_refrigerant_property_provider("unknown-provider/1")
    assert exc.value.reason == "unsupported_provider_profile"


def test_same_input_is_deterministic_with_pinned_provider() -> None:
    provider = create_refrigerant_property_provider(CANONICAL_PROPERTY_PROVIDER_PROFILE)
    values = [
        provider.saturation_temperature("R290", 500_000.0, SaturationPhase.DEW_EVAPORATION).temperature_k
        for _ in range(20)
    ]
    assert len(set(values)) == 1
