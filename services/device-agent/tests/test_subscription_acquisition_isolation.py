from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


class SubscriptionAcquisitionIsolationTests(unittest.TestCase):
    def test_delivery_plane_has_no_hardware_or_scheduler_dependencies(self) -> None:
        delivery_files = (
            ROOT / "services/telemetry-service/app/api.py",
            ROOT / "services/telemetry-service/app/delivery.py",
            ROOT / "services/telemetry-service/app/live.py",
            ROOT / "services/telemetry-service/app/live_api.py",
        )
        forbidden = (
            "adaptive_scheduler",
            "acquisition_registry",
            "modbus_rtu",
            "xjp60d",
            "le01mp",
            "read_channel(",
            "read_metric(",
            ".reconcile(",
            "eligible_targets(",
            "priority_for(",
            "/api/v1/acquisition",
        )
        offenders = {
            str(path.relative_to(ROOT)): token
            for path in delivery_files
            for token in forbidden
            if token in path.read_text(encoding="utf-8").casefold()
        }
        self.assertEqual(offenders, {})

    def test_scheduler_has_no_client_subscription_inputs(self) -> None:
        acquisition_files = (
            ROOT / "services/device-agent/adaptive_scheduler.py",
            ROOT / "services/device-agent/adaptive_main.py",
            ROOT / "services/device-agent/acquisition_registry.py",
        )
        forbidden = (
            "websocket",
            "subscriber",
            "subscription",
            "client_count",
            "websocket_clients",
        )
        offenders = {
            str(path.relative_to(ROOT)): token
            for path in acquisition_files
            for token in forbidden
            if token in path.read_text(encoding="utf-8").casefold()
        }
        self.assertEqual(offenders, {})

    def test_live_callback_is_downstream_of_successful_persistence(self) -> None:
        ingestion = (
            ROOT / "services/telemetry-service/app/ingestion.py"
        ).read_text(encoding="utf-8")
        persist = ingestion.index("inserted = self._database.persist")
        committed_branch = ingestion.index("if inserted:", persist)
        fanout = ingestion.index("self._on_persisted(normalized)", committed_branch)

        self.assertLess(persist, committed_branch)
        self.assertLess(committed_branch, fanout)

    def test_live_hub_exposes_only_committed_event_publication(self) -> None:
        live = (
            ROOT / "services/telemetry-service/app/live.py"
        ).read_text(encoding="utf-8")
        self.assertIn("def publish_committed(", live)
        self.assertNotIn("\n    def publish(", live)
        self.assertIn(
            "loop.call_soon_threadsafe(self.publish_committed, payload)",
            live,
        )


if __name__ == "__main__":
    unittest.main()
