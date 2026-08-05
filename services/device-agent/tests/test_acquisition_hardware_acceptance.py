from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = (
    Path(__file__).resolve().parents[3]
    / "scripts"
    / "acquisition_hardware_acceptance.py"
)
SPEC = importlib.util.spec_from_file_location(
    "acquisition_hardware_acceptance",
    MODULE_PATH,
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class HardwareAcceptanceTests(unittest.TestCase):
    def metrics(
        self,
        requests: int,
        *,
        discovery: int = 0,
        configuration: int = 0,
    ) -> dict[str, object]:
        return {
            "acquisition": {
                "normal": {
                    "physical_requests_total": requests,
                    "retry_attempts_total": 2,
                    "bus_busy_seconds_total": requests * 0.002,
                    "outcomes": {
                        "success": requests - 1,
                        "timeout": 1,
                    },
                },
                "service_operations": {
                    "discovery": {
                        "physical_requests_total": discovery,
                    },
                    "configuration_mutation": {
                        "requests_total": configuration,
                    },
                },
                "scheduler": {
                    "buses": {
                        "rs485-main": {
                            "scheduler_lag_seconds": {
                                "maximum": 0.01,
                            },
                            "missed_deadline_total": 1,
                            "overrun_total": 0,
                            "deferred_total": 3,
                        }
                    }
                },
            },
            "outbox": {"depth": 4},
        }

    def test_build_phase_uses_monotonic_deltas_and_resources(self) -> None:
        phase = MODULE.build_phase_evidence(
            name="overview",
            window_seconds=10,
            before_metrics=self.metrics(100),
            after_metrics=self.metrics(120),
            health={"status": "ok"},
            ready={"status": "ready"},
            cpu_usage_percent=12.5,
            rss_bytes=1024,
            disk_free_bytes=2048,
        )

        self.assertEqual(phase["normal_physical_requests_delta"], 20)
        self.assertEqual(
            phase["outcomes_delta"],
            {"success": 20, "timeout": 0},
        )
        self.assertEqual(phase["bus_utilization_percent"], 0.4)
        self.assertEqual(phase["outbox_depth"], 4)
        self.assertEqual(phase["health_status"], "ok")

    def test_append_and_validate_preserve_zero_mutation_contract(self) -> None:
        evidence = MODULE._base_evidence("abc123", "edge 01")
        phase = {
            "name": "no-browser",
            "window_seconds": 60,
            "normal_physical_requests_delta": 10,
            "retry_attempts_delta": 0,
            "outcomes_delta": {"success": 10},
            "bus_busy_seconds_delta": 0.02,
            "bus_utilization_percent": 0.033,
            "scheduler_lag_max_seconds": 0,
            "missed_deadlines_delta": 0,
            "overruns_delta": 0,
            "deferred_delta": 0,
            "cpu_percent": 1,
            "memory_rss_bytes": 100,
            "disk_free_bytes": 1000,
            "outbox_depth": 0,
            "ingestion_to_websocket_p95_ms": 0,
            "health_status": "ok",
            "ready_status": "ok",
        }

        MODULE.append_phase(
            evidence,
            phase,
            discovery_delta=0,
            configuration_delta=0,
        )

        self.assertEqual(
            MODULE.validate_evidence(evidence, require_complete=False),
            [],
        )
        self.assertEqual(evidence["node_id"], "edge-01")
        self.assertEqual(evidence["modbus_write_attempts"], 0)

    def test_complete_validation_reports_missing_phases(self) -> None:
        evidence = MODULE._base_evidence("abc123", "edge-01")

        errors = MODULE.validate_evidence(evidence, require_complete=True)

        self.assertTrue(
            any("at least one phase" in error for error in errors)
        )
        self.assertTrue(
            any("missing required phases" in error for error in errors)
        )

    def test_negative_counter_delta_is_rejected(self) -> None:
        with self.assertRaisesRegex(MODULE.EvidenceError, "counter decreased"):
            MODULE.build_phase_evidence(
                name="overview",
                window_seconds=10,
                before_metrics=self.metrics(120),
                after_metrics=self.metrics(100),
                health={"status": "ok"},
                ready={"status": "ok"},
                cpu_usage_percent=1,
                rss_bytes=1,
                disk_free_bytes=1,
            )

    def test_duplicate_phase_is_rejected(self) -> None:
        evidence = MODULE._base_evidence("abc123", "edge-01")
        phase = {
            "name": "overview",
            "window_seconds": 1,
            "normal_physical_requests_delta": 1,
            "memory_rss_bytes": 1,
            "disk_free_bytes": 1,
        }
        MODULE.append_phase(
            evidence,
            phase,
            discovery_delta=0,
            configuration_delta=0,
        )

        with self.assertRaisesRegex(MODULE.EvidenceError, "already exists"):
            MODULE.append_phase(
                evidence,
                phase,
                discovery_delta=0,
                configuration_delta=0,
            )

    def test_evidence_round_trip_is_machine_readable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evidence.json"
            evidence = MODULE._base_evidence("abc123", "edge-01")
            path.write_text(json.dumps(evidence), encoding="utf-8")

            loaded = MODULE.load_evidence(
                path,
                source_commit="abc123",
                node_id="edge-01",
            )

            self.assertEqual(loaded["classification"], "hardware")


if __name__ == "__main__":
    unittest.main()
