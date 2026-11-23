"""Tests for the CVE exposure evidence tool and its dispatch-only workflow."""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "docs" / "security" / "tools" / "cve_exposure_inventory.py"
WORKFLOW = ROOT / ".github" / "workflows" / "cve-exposure-evidence.yml"
SPEC = importlib.util.spec_from_file_location("cve_exposure_inventory", TOOL)
assert SPEC and SPEC.loader
INV = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = INV
SPEC.loader.exec_module(INV)

CVE = "CVE-2026-124709"


def _elf(*parts: bytes) -> bytes:
    return b"\x7fELF" + b"\x00" * 60 + b"\x00".join(parts)


def _export(path: Path, files: dict[str, bytes]) -> None:
    with tarfile.open(path, "w") as archive:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))


TRIVY = {
    "Metadata": {"OS": {"Family": "debian", "Name": "13.8"}},
    "Results": [
        {
            "Target": "image (debian 13.8)",
            "Class": "os-pkgs",
            "Vulnerabilities": [
                {"VulnerabilityID": CVE, "PkgName": "libssl3t64", "InstalledVersion": "3.5.9-1~deb13u1",
                 "FixedVersion": "", "Severity": "HIGH"},
                {"VulnerabilityID": "CVE-2026-1", "PkgName": "zlib1g", "InstalledVersion": "1", "Severity": "LOW"},
            ],
        }
    ],
}


class InventoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def summary(self, files: dict[str, bytes], inspect: object, trivy: object = TRIVY) -> dict:
        export = self.dir / "image.tar"
        _export(export, files)
        return INV.build_summary(cve=CVE, image_id="device-agent", arch="arm64", export=export,
                                 inspect=inspect, trivy=trivy)

    def test_clean_image_reports_no_quic_use_and_installed_packages(self) -> None:
        files = {
            "usr/lib/aarch64-linux-gnu/libssl.so.3": _elf(b"SSL_new_listener", b"OSSL_QUIC_server_method"),
            "usr/lib/aarch64-linux-gnu/libcrypto.so.3": _elf(b"EVP"),
            "usr/local/lib/python3.13/lib-dynload/_ssl.so": _elf(b"libssl.so.3", b"SSL_connect"),
            "usr/local/lib/python3.13/lib-dynload/_hashlib.so": _elf(b"libcrypto.so.3"),
            "usr/bin/unrelated": _elf(b"libc.so.6"),
            "app/main.py": b"print('not an ELF')",
            "var/lib/dpkg/status.d/libssl3t64": b"Package: libssl3t64\nVersion: 3.5.9-1~deb13u1\n",
        }
        inspect = [{"Architecture": "arm64", "Os": "linux",
                    "Config": {"ExposedPorts": {"8081/tcp": {}}, "User": "65532"}}]
        result = self.summary(files, inspect)
        self.assertEqual(result["openssl_packages"], {"libssl3t64": "3.5.9-1~deb13u1"})
        kinds = {row["path"].rsplit("/", 1)[-1]: row["kind"] for row in result["libssl_consumers"]}
        self.assertEqual(kinds["_ssl.so"], "libssl")
        self.assertEqual(kinds["_hashlib.so"], "libcrypto-only")
        self.assertEqual(kinds["libssl.so.3"], "openssl-library")
        self.assertNotIn("unrelated", kinds)
        self.assertEqual(result["quic_server_api_outside_openssl_libraries"], [])
        self.assertEqual(result["udp_ports"], [])
        self.assertEqual(result["user"], "65532")
        assessment = result["assessment"]
        self.assertTrue(assessment["affected_package_present"])
        self.assertFalse(assessment["fix_available"])
        self.assertFalse(assessment["quic_server_api_used_outside_openssl"])
        self.assertFalse(assessment["udp_exposed"])
        self.assertEqual(assessment["other_high_critical"], [])
        self.assertEqual(result["trivy"]["severity_counts"], {"HIGH": 1, "LOW": 1})

    def test_detects_quic_server_consumer_udp_and_other_high_findings(self) -> None:
        trivy = json.loads(json.dumps(TRIVY))
        trivy["Results"][0]["Vulnerabilities"].append(
            {"VulnerabilityID": "CVE-2026-2", "PkgName": "libexpat1", "InstalledVersion": "2",
             "FixedVersion": "3", "Severity": "CRITICAL"}
        )
        files = {
            "usr/sbin/quic-server": _elf(b"libssl.so.3", b"SSL_new_listener"),
            "var/lib/dpkg/status": b"Package: openssl\nVersion: 3.5.9-1~deb13u1\n\nPackage: libssl3t64\nVersion: 3.5.9-1~deb13u1\n",
        }
        inspect = {"Config": {"ExposedPorts": {"4433/udp": {}, "8080/tcp": {}}}}
        result = self.summary(files, inspect, trivy)
        self.assertEqual(result["quic_server_api_outside_openssl_libraries"], ["usr/sbin/quic-server"])
        self.assertEqual(result["openssl_packages"]["openssl"], "3.5.9-1~deb13u1")
        self.assertEqual(result["udp_ports"], ["4433/udp"])
        self.assertEqual(result["user"], "root")
        self.assertTrue(result["assessment"]["quic_server_api_used_outside_openssl"])
        self.assertTrue(result["assessment"]["udp_exposed"])
        self.assertEqual(result["assessment"]["other_high_critical"], ["CRITICAL CVE-2026-2 libexpat1 2"])
        row = INV.markdown_row(result)
        self.assertIn("YES", row)
        self.assertIn("4433/udp", row)

    def test_fix_available_is_reported(self) -> None:
        trivy = json.loads(json.dumps(TRIVY))
        trivy["Results"][0]["Vulnerabilities"][0]["FixedVersion"] = "3.5.10-1~deb13u1"
        result = self.summary({"etc/hostname": b"x"}, {}, trivy)
        self.assertTrue(result["assessment"]["fix_available"])

    def test_unaffected_image(self) -> None:
        result = self.summary({"etc/hostname": b"x"}, {}, {"Results": []})
        self.assertFalse(result["assessment"]["affected_package_present"])
        self.assertIn("not affected", INV.markdown_row(result))

    def test_cli_writes_summary(self) -> None:
        export = self.dir / "image.tar"
        _export(export, {"etc/hostname": b"x"})
        (self.dir / "inspect.json").write_text("[]", encoding="utf-8")
        (self.dir / "trivy.json").write_text(json.dumps(TRIVY), encoding="utf-8")
        output = self.dir / "summary.json"
        code = INV.main(["--cve", CVE, "--image-id", "device-agent", "--arch", "amd64", "--export", str(export),
                         "--inspect", str(self.dir / "inspect.json"), "--trivy", str(self.dir / "trivy.json"),
                         "--output", str(output)])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.read_text(encoding="utf-8"))["arch"], "amd64")


class WorkflowContractTests(unittest.TestCase):
    def test_dispatch_only_read_only_and_both_architectures(self) -> None:
        text = WORKFLOW.read_text(encoding="utf-8")
        on_block = text.split("\non:\n", 1)[1].split("\npermissions:", 1)[0]
        self.assertIn("workflow_dispatch:", on_block)
        for trigger in ("pull_request", "push:", "schedule:", "workflow_run"):
            self.assertNotIn(trigger, on_block)
        self.assertIn("permissions:\n  contents: read\n", text)
        self.assertNotIn("write", text.split("\npermissions:", 1)[1].split("\n\n", 1)[0])
        self.assertIn('"linux/arm64": ("arm64", "ubuntu-24.04-arm")', text)
        self.assertIn('"linux/amd64": ("amd64", "ubuntu-24.04")', text)
        self.assertIn("aquasecurity/trivy-action@ed142fd0673e97e23eac54620cfb913e5ce36c25", text)
        self.assertIn("persist-credentials: false", text)
        for forbidden in ("docker push", "docker login", "push: true", "vulnerability-exceptions.json"):
            self.assertNotIn(forbidden, text)

    def test_tooling_runs_from_workflow_commit_and_source_from_the_assessed_ref(self) -> None:
        text = WORKFLOW.read_text(encoding="utf-8")
        evidence = text.split("\n  evidence:\n", 1)[1].split("\n  summary:\n", 1)[0]
        self.assertIn("ref: ${{ inputs.ref }}\n          path: target", evidence)
        self.assertIn('-f "target/${{ matrix.dockerfile }}"', evidence)
        self.assertIn('"target/${{ matrix.context }}"', evidence)
        self.assertIn("python3 -I docs/security/tools/cve_exposure_inventory.py", evidence)
        self.assertNotIn("target/docs/security/tools", evidence)

    def test_gate_and_evidence_use_the_same_trivy_pin(self) -> None:
        gate = (ROOT / ".github" / "workflows" / "container-supply-chain.yml").read_text(encoding="utf-8")
        self.assertIn("aquasecurity/trivy-action@ed142fd0673e97e23eac54620cfb913e5ce36c25", gate)


if __name__ == "__main__":
    unittest.main()
