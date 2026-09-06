# RFX-07 Offline Refrigerant Property Provider Evaluation

Date: 2026-09-06
Issue: #953
Target profile: `LOCAL_LAN`

## Decision

Adopt **CoolProp 8.0.0 / HEOS** as the first canonical local refrigerant-property provider, with the dependency pair pinned to `CoolProp==8.0.0` and `numpy==2.5.2`.

Canonical provider profile: `coolprop-heos/8.0.0`.

This decision exposes only a provider boundary for saturation-temperature lookup from **absolute pressure** with an explicit `dew_evaporation` or `bubble_condensation` phase. It does not implement pressure normalization, saturation derived metrics, superheat, subcooling, telemetry materialization, UI activation, or hardware acceptance.

## License and public packaging evidence

CoolProp 8.0.0 package metadata reports MIT licensing and `Requires-Python >=3.9`. The package declares `numpy>=1.20`; NEXOLAB pins NumPy explicitly so the mandatory runtime dependency set is not left floating.

Public package/reference locations used during evaluation:

- PyPI project: `https://pypi.org/project/CoolProp/`
- CoolProp high-level API: `https://coolprop.org/coolprop/HighLevelAPI.html`
- CoolProp source/release repository: `https://github.com/CoolProp/CoolProp`

The high-level API uses vapor quality `Q=1` for saturated vapor/dew and `Q=0` for saturated liquid/bubble. RFX-07 keeps those semantics behind NEXOLAB names rather than exposing a generic ambiguous saturation call.

## Actual Raspberry Pi ARM64 evidence

Host: `nexolab-edge-01`
Platform: Linux `aarch64`
Python: `3.13.5`

Downloaded provider wheel:

- `coolprop-8.0.0-cp312-abi3-manylinux2014_aarch64.manylinux_2_17_aarch64.whl`
- size: approximately 10.7 MB
- SHA-256: `113fc0e97f2b64617141d453ddc0439987b32aa3f6f4a45b928b2030c68292fa`

Resolved NumPy wheel:

- `numpy-2.5.2-cp313-cp313-manylinux_2_27_aarch64.manylinux_2_28_aarch64.whl`
- size: approximately 15.6 MB
- SHA-256: `0aadf13b60048d501e05fa699efaf7734e2494f3498a4c2a5521d822640324f3`

A fresh virtual environment installed both packages from a local wheelhouse using `pip --no-index --find-links=...`; provider import and calculation succeeded. A separate `strace -e trace=network` smoke around 20 representative R290 calculations recorded **no network syscalls**.

CoolProp version: `8.0.0`
CoolProp revision: `ae81610e7d23efc57f9d051c8e70a4d66e87537f`

## Resource envelope measured on Raspberry Pi

Five cold provider-library imports were approximately `2.78–2.84 s`, with observed peak RSS approximately `86–87 MiB`. A 5,000-call R290 dew-point loop at 500 kPa averaged approximately `102 µs/call` after initialization.

The committed verifier uses deliberately looser acceptance ceilings to avoid overfitting one observation:

- initialization `<= 5 s`;
- peak RSS `<= 128 MiB`;
- representative warm call mean `<= 500 µs`.

These are dependency/runtime-envelope gates, not real-time control requirements. CoolProp is never placed in the Device Agent or Modbus path.

## Supported initial refrigerant vocabulary

RFX-07 accepts only refrigerants explicitly exercised by committed fixtures:

- `R290`;
- `R134A`;
- `R404A`;
- `R407C`.

CoolProp 8.0.0 on the target host did not resolve `R448A`, `R449A`, or `R452A` by those identifiers. They therefore fail closed as `unsupported_refrigerant`. RFX-06 circuit configuration may still persist such a refrigerant code; provider availability is a separate authority and must not be inferred from configuration validity.

## Numerical regression fixtures

`docs/refrigeration-property-provider-golden-v1.json` contains controlled provider-generation fixtures produced on the target ARM64 host from the exact wheel and revision above. They include:

- R290 at 0.1, 0.5, 1.0 and 2.0 MPa absolute;
- R134A at 0.5 MPa;
- R404A at 1.0 MPa with explicit bubble/dew values;
- R407C at 1.0 MPa with explicit bubble/dew values and visible glide.

Fixture tolerance is `1e-6 K` for the pinned-provider regression. These fixtures establish deterministic version regression and phase semantics; they are not a claim of independent physical calibration. Real-circuit calculation acceptance remains a later hardware/runtime boundary.

## Fail-closed behavior

The NEXOLAB adapter rejects non-finite, zero, and negative pressure before calling the provider. Unsupported refrigerants fail with `unsupported_refrigerant`. Positive pressures outside the provider saturation domain return `provider_domain_error`. The committed regression probes both sides explicitly: R407C at 100 Pa absolute is rejected below its supported saturation domain, and R290 at 1,000,000,000 Pa absolute is rejected above its supported saturation domain. Non-finite results and unexpected provider failures have distinct typed failure reasons.

There is no standard-atmosphere fallback, online lookup, generic refrigerant substitution, or inferred alias outside the explicitly accepted mapping.

## Update and rollback

Provider identity is versioned in the profile string and exact Python requirements. Any provider or NumPy update is a future focused dependency Work Package with fixture/resource/offline reruns. The current offline bundle remains rollbackable as an application/container bundle; RFX-07 adds no migration or persistent-data rewrite.

## Remaining boundary

RFX-07 makes the property provider available to a future calculation engine only. The next Work Package may implement absolute-pressure normalization and derived thermodynamics using RFX-06 semantic bindings/configuration plus this provider. That future package must preserve input/configuration/provider provenance and the ADR freshness/quality contract.
