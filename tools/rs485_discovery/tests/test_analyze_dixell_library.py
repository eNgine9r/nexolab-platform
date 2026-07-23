from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "analyze_dixell_library.py"
spec = importlib.util.spec_from_file_location("analyze_dixell_library", SCRIPT)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class AnalyzeDixellLibraryTests(unittest.TestCase):
    def test_parse_int_like_accepts_decimal_and_hex(self) -> None:
        self.assertEqual(module.parse_int_like("123"), 123)
        self.assertEqual(module.parse_int_like("0x120"), 288)
        self.assertIsNone(module.parse_int_like(True))

    def test_analyze_finds_temperature_register(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            package = root / "package"
            package.mkdir()
            (package / "library.json").write_text(
                json.dumps(
                    {
                        "variables": [
                            {
                                "name": "Probe 3 temperature",
                                "address": "0x120",
                                "function": 3,
                                "scale": 0.1,
                                "unit": "degC",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            archive = root / "library.zip"
            with zipfile.ZipFile(archive, "w") as handle:
                handle.write(package / "library.json", "library.json")

            report = module.analyze(
                archive,
                "XJP60D",
                "1.6",
                module.DEFAULT_KEYWORDS,
            )

            self.assertEqual(report["statistics"]["candidate_count"], 1)
            candidate = report["candidates"][0]
            self.assertEqual(candidate["address"], 288)
            self.assertEqual(candidate["function"], 3)
            self.assertIn("temperature", candidate["matched_keywords"])

    def test_safe_extract_rejects_parent_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive = root / "unsafe.zip"
            with zipfile.ZipFile(archive, "w") as handle:
                handle.writestr("../outside.json", "{}")

            with self.assertRaises(ValueError):
                module.safe_extract_zip(archive, root / "extract")


if __name__ == "__main__":
    unittest.main()
