from __future__ import annotations

import gzip
import importlib.util
import io
import json
import sys
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "decode_dixell_evopack.py"
spec = importlib.util.spec_from_file_location("decode_dixell_evopack", SCRIPT)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def encode(member_name: str, payload: bytes) -> bytes:
    key = module.derive_member_key(member_name)
    return bytes(byte ^ key[index % len(key)] for index, byte in enumerate(payload))


class DecodeDixellEvopackTests(unittest.TestCase):
    def test_key_uses_first_twenty_basename_bytes(self) -> None:
        key = module.derive_member_key("LIBInstall-LIB20250704-json.sh")
        decoded_material = bytes(byte ^ module.XOR_CONSTANT for byte in key)
        self.assertEqual(decoded_material, b"LIBInstall-LIB202507")

    def test_short_name_is_nul_padded(self) -> None:
        key = module.derive_member_key("epkginfo")
        decoded_material = bytes(byte ^ module.XOR_CONSTANT for byte in key)
        self.assertEqual(decoded_material, b"epkginfo" + b"\x00" * 12)

    def test_decode_archive_restores_script_and_gzip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            outer = root / "library.zip"
            script_name = "LIBInstall-LIB20250704-json.sh"
            package_name = "LIBPackage-LIB20250704-XJP60D_000E00100001.tar.gz"
            script = b"#!/bin/sh\nexit 0\n"

            payload = json.dumps({"name": "Probe 3", "address": 260}).encode()
            tar_buffer = io.BytesIO()
            with tarfile.open(fileobj=tar_buffer, mode="w") as package:
                info = tarfile.TarInfo("registers.json")
                info.size = len(payload)
                package.addfile(info, io.BytesIO(payload))
            compressed = gzip.compress(tar_buffer.getvalue(), mtime=0)

            with zipfile.ZipFile(outer, "w") as package:
                package.writestr(script_name, encode(script_name, script))
                package.writestr(package_name, encode(package_name, compressed))

            output = root / "decoded"
            report = module.decode_archive(outer, output)

            self.assertEqual((output / script_name).read_bytes(), script)
            self.assertEqual((output / package_name).read_bytes(), compressed)
            kinds = {item["name"]: item["decoded_kind"] for item in report["members"]}
            self.assertEqual(kinds[script_name], "script")
            self.assertEqual(kinds[package_name], "gzip")

    def test_rejects_parent_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            outer = root / "unsafe.zip"
            with zipfile.ZipFile(outer, "w") as package:
                package.writestr("../outside", b"payload")

            with self.assertRaises(ValueError):
                module.decode_archive(outer, root / "decoded")


if __name__ == "__main__":
    unittest.main()
