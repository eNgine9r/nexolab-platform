#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import platform
import resource
import sys
import time
from pathlib import Path

TELEMETRY = Path(__file__).resolve().parents[1]
ROOT = TELEMETRY.parents[1]
sys.path.insert(0, str(TELEMETRY))

from app.refrigeration.property_provider import (
    CANONICAL_PROPERTY_PROVIDER_PROFILE,
    SaturationPhase,
    create_refrigerant_property_provider,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--require-arm64", action="store_true")
    parser.add_argument("--iterations", type=int, default=5000)
    parser.add_argument("--max-init-seconds", type=float, default=5.0)
    parser.add_argument("--max-rss-mib", type=float, default=128.0)
    parser.add_argument("--max-call-us", type=float, default=500.0)
    args = parser.parse_args()
    if args.iterations <= 0:
        raise SystemExit("iterations must be greater than zero")

    architecture = platform.machine().lower()
    if args.require_arm64 and architecture not in {"aarch64", "arm64"}:
        raise SystemExit(f"ARM64 required, found {architecture}")

    init_started = time.perf_counter()
    provider = create_refrigerant_property_provider(CANONICAL_PROPERTY_PROVIDER_PROFILE)
    init_seconds = time.perf_counter() - init_started

    call_started = time.perf_counter()
    result = None
    for _ in range(args.iterations):
        result = provider.saturation_temperature(
            "R290", 500_000.0, SaturationPhase.DEW_EVAPORATION
        )
    call_seconds = time.perf_counter() - call_started
    mean_call_us = call_seconds / args.iterations * 1_000_000.0
    max_rss_mib = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0

    evidence = {
        "architecture": architecture,
        "python": platform.python_version(),
        "provider_id": provider.provider_id,
        "provider_version": provider.provider_version,
        "provider_revision": provider.provider_revision,
        "provider_profile": provider.provider_profile,
        "supported_refrigerants": list(provider.supported_refrigerants),
        "iterations": args.iterations,
        "init_seconds": round(init_seconds, 6),
        "mean_call_us": round(mean_call_us, 3),
        "max_rss_mib": round(max_rss_mib, 3),
        "sample_temperature_k": result.temperature_k if result is not None else None,
    }
    print(json.dumps(evidence, sort_keys=True))

    if init_seconds > args.max_init_seconds:
        raise SystemExit("provider initialization exceeded bounded threshold")
    if max_rss_mib > args.max_rss_mib:
        raise SystemExit("provider RSS exceeded bounded threshold")
    if mean_call_us > args.max_call_us:
        raise SystemExit("provider call latency exceeded bounded threshold")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
