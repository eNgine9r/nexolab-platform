"""NEXOLAB read-only APT hold policy checks (mocked inventory only)."""

import importlib.util
import unittest
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "verify-host-container-runtime-package-policy.py"
SPEC = importlib.util.spec_from_file_location("host_package_policy", SOURCE)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def command(held=None, version="1.0", packages=None):
    packages = module.PACKAGES if packages is None else packages
    held = module.PACKAGES if held is None else held

    def invoke(args):
        if args == ["apt-mark", "showhold"]:
            return "\n".join(held) + ("\n" if held else "")
        if args[:3] == ["dpkg-query", "-W", "-f=${binary:Package}\t${Version}\n"]:
            return "".join(f"{name}\t{version}\n" for name in packages)
        raise AssertionError(f"unexpected command: {args}")

    return invoke


class PackagePolicyTests(unittest.TestCase):
    def test_all_held_is_guarded(self):
        result = module.inspect(command())
        self.assertEqual(result["status"], "guarded")
        self.assertEqual(result["unprotected"], [])
        self.assertFalse(result["mutation_performed"])

    def test_packagekit_scenario_is_unprotected(self):
        result = module.inspect(command(held=("docker-ce", "docker-ce-cli")))
        self.assertEqual(result["status"], "unprotected")
        self.assertIn("containerd.io", result["unprotected"])
        self.assertEqual(len(result["packages"]), 6)

    def test_no_held_packages(self):
        result = module.inspect(command(held=()))
        self.assertEqual(result["status"], "unprotected")
        self.assertEqual(len(result["unprotected"]), 6)

    def test_missing_installed_package_blocks(self):
        with self.assertRaisesRegex(module.PackagePolicyError, "missing_or_unexpected"):
            module.inspect(command(packages=module.PACKAGES[:-1]))

    def test_duplicate_inventory_blocks(self):
        with self.assertRaisesRegex(module.PackagePolicyError, "invalid_dpkg"):
            module.inspect(command(packages=module.PACKAGES + ("docker-ce",)))

    def test_bad_hold_inventory_blocks(self):
        with self.assertRaisesRegex(module.PackagePolicyError, "invalid_apt_hold"):
            module.inspect(command(held=("docker-ce cli",)))

    def test_inventory_failure_blocks(self):
        def fail(_):
            raise module.PackagePolicyError("local_package_inventory_unavailable")
        with self.assertRaises(module.PackagePolicyError):
            module.inspect(fail)

    def test_no_shell_or_write_commands(self):
        calls = []
        original = command()
        def audited(args):
            calls.append(args)
            return original(args)
        module.inspect(audited)
        self.assertEqual([x[0] for x in calls], ["apt-mark", "dpkg-query"])
        self.assertIn("showhold", calls[0])
        self.assertNotIn("hold", calls[0])


if __name__ == "__main__":
    unittest.main()
