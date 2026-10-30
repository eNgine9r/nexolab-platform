"""#1421: hermetic fail-closed PackageKit/Docker APT policy acceptance."""
from __future__ import annotations

import importlib.util
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / "verify-host-container-runtime-package-policy.py"
SPEC = importlib.util.spec_from_file_location("host_package_policy", SOURCE)
assert SPEC is not None and SPEC.loader is not None
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def command(held=None, version="5:29.9.2-1~debian", packages=None, status_override=None):
    packages = module.PACKAGES if packages is None else packages
    held = module.PACKAGES if held is None else held
    status_override = status_override or {}

    def invoke(args):
        if args == ["apt-mark", "showhold"]:
            return "\n".join(held) + ("\n" if held else "")
        if args[:3] == [
            "dpkg-query", "-W",
            "-f=${binary:Package}\t${Version}\t${db:Status-Abbrev}\n",
        ]:
            if args[3:] != list(module.PACKAGES):
                raise AssertionError("dpkg list must be exactly six audited names")
            return "".join(
                f"{name}\t{version}\t{status_override.get(name, 'hi ' if name in held else 'ii ')}\n"
                for name in packages
            )
        raise AssertionError(f"unapproved read operation: {args}")

    return invoke


class PackagePolicyTests(unittest.TestCase):
    def test_all_six_installed_held_is_guarded(self):
        result = module.inspect(command())
        self.assertEqual(result["status"], "guarded")
        self.assertEqual(result["unprotected"], [])
        self.assertEqual(len(result["packages"]), 6)
        self.assertFalse(result["mutation_performed"])
        self.assertEqual(result["immutable_runtime_authority"], "unverified")

    def test_packagekit_upgrade_scenario_is_unprotected(self):
        result = module.inspect(command(held=("docker-ce", "docker-ce-cli")))
        self.assertEqual(result["status"], "unprotected")
        self.assertIn("containerd.io", result["unprotected"])

    def test_none_held_is_unprotected(self):
        result = module.inspect(command(held=()))
        self.assertEqual(result["status"], "unprotected")
        self.assertEqual(len(result["unprotected"]), 6)

    def test_missing_installed_package_blocks(self):
        with self.assertRaisesRegex(module.PackagePolicyError, "missing_or_unexpected"):
            module.inspect(command(packages=module.PACKAGES[:-1]))

    def test_duplicate_installed_package_blocks(self):
        with self.assertRaisesRegex(module.PackagePolicyError, "missing_or_unexpected"):
            module.inspect(command(packages=module.PACKAGES + ("docker-ce",)))

    def test_extra_installed_package_blocks(self):
        with self.assertRaisesRegex(module.PackagePolicyError, "missing_or_unexpected"):
            module.inspect(command(packages=module.PACKAGES + ("unknown-package",)))

    def test_uninstalled_but_version_reported_is_not_guarded(self):
        with self.assertRaisesRegex(module.PackagePolicyError, "not_fully_installed"):
            module.inspect(command(status_override={"docker-ce": "rc "}))

    def test_unpacked_not_configured_is_blocked(self):
        with self.assertRaisesRegex(module.PackagePolicyError, "not_fully_installed"):
            module.inspect(command(status_override={"containerd.io": "iU "}))

    def test_half_configured_is_blocked(self):
        with self.assertRaisesRegex(module.PackagePolicyError, "not_fully_installed"):
            module.inspect(command(status_override={"containerd.io": "iF "}))

    def test_reinstall_required_is_blocked(self):
        with self.assertRaisesRegex(module.PackagePolicyError, "not_fully_installed"):
            module.inspect(command(status_override={"containerd.io": "hiR"}))

    def test_hold_inventory_and_dpkg_desired_state_conflict_blocks(self):
        with self.assertRaisesRegex(module.PackagePolicyError, "contradictory"):
            module.inspect(command(status_override={"docker-ce": "ii "}))

    def test_dpkg_held_but_not_apt_hold_is_conflict(self):
        with self.assertRaisesRegex(module.PackagePolicyError, "contradictory"):
            module.inspect(command(held=(), status_override={"docker-ce": "hi "}))

    def test_empty_installed_inventory_blocks(self):
        with self.assertRaisesRegex(module.PackagePolicyError, "missing_or_oversized"):
            module.inspect(command(packages=()))

    def test_bad_hold_inventory_blocks(self):
        with self.assertRaisesRegex(module.PackagePolicyError, "invalid_apt_hold"):
            module.inspect(command(held=("docker-ce cli",)))

    def test_duplicate_hold_inventory_blocks(self):
        with self.assertRaisesRegex(module.PackagePolicyError, "duplicate_apt_hold"):
            module.inspect(command(held=("docker-ce", "docker-ce")))

    def test_bad_package_version_blocks(self):
        with self.assertRaisesRegex(module.PackagePolicyError, "invalid_protected_package_version"):
            module.inspect(command(version="1.0 invalid"))

    def test_other_unrelated_valid_hold_is_ignored(self):
        result = module.inspect(command(held=(*module.PACKAGES, "linux-image-arm64")))
        self.assertEqual(result["status"], "guarded")
        self.assertEqual([i["name"] for i in result["packages"]], list(module.PACKAGES))

    def test_unexpected_dpkg_format_blocks(self):
        def invoke(args):
            if args[0] == "apt-mark":
                return "\n".join(module.PACKAGES)
            return "docker-ce\t1.0\n"
        with self.assertRaisesRegex(module.PackagePolicyError, "invalid_dpkg"):
            module.inspect(invoke)

    def test_command_failure_blocks_without_secret_stderr(self):
        with patch.object(module.subprocess, "run", side_effect=subprocess.CalledProcessError(
            1, ["dpkg-query"], stderr="private diagnostic should never leak"
        )):
            with self.assertRaisesRegex(module.PackagePolicyError, "unavailable"):
                module.run_command(["dpkg-query", "-W"])
        result = io.StringIO()
        with patch.object(module, "inspect", side_effect=module.PackagePolicyError("private diagnostic")):
            with redirect_stdout(result):
                rc = module.main(["--check"])
        self.assertEqual(rc, 78)
        self.assertNotIn("private diagnostic", result.getvalue())
        self.assertEqual(json.loads(result.getvalue())["status"], "blocked")

    def test_timeout_blocks(self):
        with patch.object(module.subprocess, "run", side_effect=subprocess.TimeoutExpired(["apt-mark"], 10)):
            with self.assertRaisesRegex(module.PackagePolicyError, "unavailable"):
                module.run_command(["apt-mark", "showhold"])

    def test_oversized_inventory_blocks(self):
        with self.assertRaisesRegex(module.PackagePolicyError, "oversized"):
            module.inspect(lambda args: "a" * (module.MAX_OUTPUT_BYTES + 1))

    def test_only_readonly_commands_are_invoked(self):
        seen = []
        real = command()

        def audited(args):
            seen.append(args)
            return real(args)

        module.inspect(audited)
        self.assertEqual([c[0] for c in seen], ["apt-mark", "dpkg-query"])
        self.assertEqual(seen[0], ["apt-mark", "showhold"])
        self.assertEqual(len(seen[1][3:]), 6)
        self.assertFalse(any("hold" in cmd[1:] for cmd in seen if cmd[0] != "apt-mark"))
        self.assertFalse(any(token in str(seen) for token in ("systemctl", "docker exec", "apt install", "modbus")))

    def test_main_guarded_and_unprotected_exit_codes(self):
        out = io.StringIO()
        with patch.object(module, "inspect", return_value={"status": "guarded"}):
            with redirect_stdout(out):
                self.assertEqual(module.main(["--check"]), 0)
        with patch.object(module, "inspect", return_value={"status": "unprotected"}):
            with redirect_stdout(io.StringIO()):
                self.assertEqual(module.main([]), 78)


if __name__ == "__main__":
    unittest.main()
