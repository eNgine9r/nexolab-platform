from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
HOOK = ROOT / "src/hooks/use-xjp60d-sensor-management.ts"
ROUTE = ROOT / "src/app/api/device-agent/xjp60d/route.ts"


class UIAcquisitionBoundaryTests(unittest.TestCase):
    def test_mount_and_refresh_use_get_only(self) -> None:
        source = HOOK.read_text(encoding="utf-8")
        refresh_block = re.search(
            r"const refresh = useCallback\(async \(\) => \{(?P<body>.*?)\n  \}, \[",
            source,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(refresh_block)
        body = refresh_block.group("body") if refresh_block else ""
        self.assertIn('method: "GET"', body)
        self.assertNotIn('method: "POST"', body)
        self.assertNotIn('method: "PUT"', body)

        # The only automatically invoked callback is refresh(). Discovery and
        # save remain explicit operator actions returned by the hook.
        self.assertEqual(source.count("void refresh();"), 1)
        self.assertNotIn("void discover();", source)
        self.assertNotIn("void save(", source)

    def test_next_route_keeps_get_separate_from_explicit_service_operations(self) -> None:
        source = ROUTE.read_text(encoding="utf-8")
        get_handler = re.search(
            r"export async function GET.*?return relayAgent\(request, AGENT_CONFIGURATION_PATH, \{ method: \"GET\"",
            source,
            flags=re.DOTALL,
        )
        post_handler = re.search(
            r"export async function POST.*?AGENT_DISCOVERY_PATH, \{ method: \"POST\"",
            source,
            flags=re.DOTALL,
        )
        put_handler = re.search(
            r"export async function PUT.*?AGENT_CONFIGURATION_PATH.*?method: \"PUT\"",
            source,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(get_handler)
        self.assertIsNotNone(post_handler)
        self.assertIsNotNone(put_handler)

    def test_normal_telemetry_routes_do_not_reference_device_agent_control_path(self) -> None:
        normal_roots = [
            ROOT / "src/lib/telemetry",
            ROOT / "src/hooks/use-dashboard-telemetry.ts",
            ROOT / "src/hooks/use-live-telemetry.ts",
            ROOT / "src/hooks/use-energy-telemetry.ts",
        ]
        offenders: list[str] = []
        for root in normal_roots:
            files = [root] if root.is_file() else list(root.rglob("*.ts"))
            for file in files:
                if "/api/device-agent/xjp60d" in file.read_text(encoding="utf-8"):
                    offenders.append(str(file.relative_to(ROOT)))
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
