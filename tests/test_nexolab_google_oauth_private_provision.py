"""Local credential wizard acceptance (synthetic secrets only, no auth services)."""
from __future__ import annotations

import importlib.util
import io
import os
import stat
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "operations" / "nexolab_google_oauth_private_provision.py"
SPEC = importlib.util.spec_from_file_location("nexolab_google_provision", SCRIPT)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MOD)

TEST_CLIENT = "123456789-abcdef.apps.googleusercontent.com"
TEST_SECRET = "GOCSPX-example-do-not-use-for-production"
TEST_EMAIL = "lab-operator@example.test"


class PrivateGoogleOAuthProvisioningTests(unittest.TestCase):
    def test_synthetic_credentials_have_correct_permissions_and_no_logging(self) -> None:
        with tempfile.TemporaryDirectory() as scratch:
            target = Path(scratch) / "private"
            output = io.StringIO()
            with redirect_stdout(output):
                MOD.provision(
                    target, client_id=TEST_CLIENT, client_secret=TEST_SECRET, email=TEST_EMAIL
                )
                MOD.check_local_files(target)
            self.assertEqual(output.getvalue(), "")
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o700)
            env_file = target / MOD.ENV_NAME
            allowlist = target / MOD.ALLOWLIST_NAME
            self.assertEqual(stat.S_IMODE(env_file.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(allowlist.stat().st_mode), 0o600)
            data = env_file.read_text()
            self.assertIn(f"OAUTH2_PROXY_CLIENT_ID={TEST_CLIENT}\n", data)
            self.assertIn(f"OAUTH2_PROXY_CLIENT_SECRET={TEST_SECRET}\n", data)
            self.assertEqual(len(data.splitlines()), 3)
            self.assertEqual(allowlist.read_text(), TEST_EMAIL + "\n")
            self.assertNotIn(TEST_SECRET, output.getvalue())

    def test_cannot_overwrite_existing_google_client_implicitly(self) -> None:
        with tempfile.TemporaryDirectory() as scratch:
            target = Path(scratch) / "private"
            MOD.provision(target, client_id=TEST_CLIENT, client_secret=TEST_SECRET, email=TEST_EMAIL)
            before = (target / MOD.ENV_NAME).read_bytes()
            with self.assertRaises(MOD.ProvisioningError):
                MOD.provision(target, client_id=TEST_CLIENT, client_secret=TEST_SECRET, email=TEST_EMAIL)
            self.assertEqual((target / MOD.ENV_NAME).read_bytes(), before)

    def test_bad_client_id_rejected_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as scratch:
            target = Path(scratch) / "private"
            with self.assertRaises(MOD.ProvisioningError):
                MOD.provision(target, client_id="not-a-google-web-client", client_secret=TEST_SECRET, email=TEST_EMAIL)
            self.assertFalse(target.exists())

    def test_newline_in_client_secret_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as scratch:
            with self.assertRaises(MOD.ProvisioningError):
                MOD.provision(Path(scratch) / "private", client_id=TEST_CLIENT, client_secret="good\nINJECT=1", email=TEST_EMAIL)

    def test_multiline_email_denied(self) -> None:
        with tempfile.TemporaryDirectory() as scratch:
            with self.assertRaises(MOD.ProvisioningError):
                MOD.provision(Path(scratch) / "private", client_id=TEST_CLIENT, client_secret=TEST_SECRET, email="good@example.test\nbad@example.test")

    def test_symlinked_secrets_directory_refused(self) -> None:
        with tempfile.TemporaryDirectory() as scratch:
            base = Path(scratch)
            real = base / "real"
            real.mkdir(mode=0o700)
            alias = base / "alias"
            alias.symlink_to(real, target_is_directory=True)
            with self.assertRaises(MOD.ProvisioningError):
                MOD.provision(alias, client_id=TEST_CLIENT, client_secret=TEST_SECRET, email=TEST_EMAIL)
            self.assertEqual(list(real.iterdir()), [])

    def test_wrong_directory_permissions_refused(self) -> None:
        with tempfile.TemporaryDirectory() as scratch:
            target = Path(scratch) / "private"
            target.mkdir(mode=0o755)
            os.chmod(target, 0o755)
            with self.assertRaises(MOD.ProvisioningError):
                MOD.provision(target, client_id=TEST_CLIENT, client_secret=TEST_SECRET, email=TEST_EMAIL)

    def test_symlinked_credential_file_refused(self) -> None:
        with tempfile.TemporaryDirectory() as scratch:
            target = Path(scratch) / "private"
            target.mkdir(mode=0o700)
            outside = Path(scratch) / "outside"
            outside.write_text("unaltered")
            (target / MOD.ENV_NAME).symlink_to(outside)
            with self.assertRaises(MOD.ProvisioningError):
                MOD.provision(target, client_id=TEST_CLIENT, client_secret=TEST_SECRET, email=TEST_EMAIL)
            self.assertEqual(outside.read_text(), "unaltered")


if __name__ == "__main__":
    unittest.main()
