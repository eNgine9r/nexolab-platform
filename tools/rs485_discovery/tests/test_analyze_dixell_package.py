from __future__ import annotations

import importlib.util
import io
import json
import sys
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPT_DIR))
SCRIPT = SCRIPT_DIR / "analyze_dixell_package.py"
spec = importlib.util.spec_from_file_location("analyze_dixell_package", SCRIPT)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


class AnalyzeDixellPackageTests(unittest.TestCase):
    def test_expand_zip_with_nested_tar_gz(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            payload = json.dumps(
                {
                    "variables": [
                        {
                            "name": "Probe 3 temperature",
                            "address": 288,
                            "function": 3,
                            "scale": 0.1,
                            "unit": "degC",
                        }
                    ]
                }
            ).encode()

            nested = root / "library.tar.gz"
            with tarfile.open(nested, "w:gz") as package:
                info = tarfile.TarInfo("payload/registers.json")
                info.size = len(payload)
                package.addfile(info, io.BytesIO(payload))

            outer = root / "library.zip"
            with zipfile.ZipFile(outer, "w") as package:
                package.write(nested, "LIBPackage-XJP60D.tar.gz")

            workspace = root / "workspace"
            workspace.mkdir()
            manifest = module.expand_bundle(outer, workspace)

            self.assertEqual([item["kind"] for item in manifest], ["zip", "tar"])
            documents = list(workspace.rglob("registers.json"))
            self.assertEqual(len(documents), 1)

            report = module.library_analyzer.analyze(
                workspace,
                "XJP60D",
                "1.6",
                module.library_analyzer.DEFAULT_KEYWORDS,
            )
            self.assertEqual(report["statistics"]["candidate_count"], 1)
            self.assertEqual(report["candidates"][0]["address"], 288)

    def test_tar_rejects_parent_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive = root / "unsafe.tar.gz"
            content = b"{}"
            with tarfile.open(archive, "w:gz") as package:
                info = tarfile.TarInfo("../outside.json")
                info.size = len(content)
                package.addfile(info, io.BytesIO(content))

            with self.assertRaises(ValueError):
                module.extract_tar(archive, root / "extract")

    def test_tar_rejects_links(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            archive = root / "unsafe-link.tar.gz"
            with tarfile.open(archive, "w:gz") as package:
                info = tarfile.TarInfo("link")
                info.type = tarfile.SYMTYPE
                info.linkname = "/etc/passwd"
                package.addfile(info)

            with self.assertRaises(ValueError):
                module.extract_tar(archive, root / "extract")


if __name__ == "__main__":
    unittest.main()
