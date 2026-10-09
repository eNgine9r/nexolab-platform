"""Offline-only tests for systemd credential handoff. No real account data."""
from __future__ import annotations

import base64
import importlib.util
import io
import os
import stat
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "operations" / "nexolab_google_oauth_private_exec.py"
SPEC = importlib.util.spec_from_file_location("nexolab_google_oauth_private_exec", SCRIPT)
assert SPEC and SPEC.loader
MOD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MOD)

CLIENT = "1234567-example.apps.googleusercontent.com"
SECRET = "GOCSPX-synthetic-do-not-use"
COOKIE = base64.b64encode(bytes(range(32))).decode("ascii")
EMAIL = "synthetic@example.test"


def create_fixture(root: Path) -> tuple[Path, Path]:
    cred, runtime = root / "credentials", root / "runtime"
    cred.mkdir(mode=0o700)
    runtime.mkdir(mode=0o700)
    (cred / "google-oauth.env").write_text(
        f"OAUTH2_PROXY_CLIENT_ID={CLIENT}\n"
        f"OAUTH2_PROXY_CLIENT_SECRET={SECRET}\n"
        f"OAUTH2_PROXY_COOKIE_SECRET={COOKIE}\n"
    )
    (cred / "allowed-emails.txt").write_text(EMAIL + "\n")
    return cred, runtime


class GoogleOAuthPrivateHandoffTests(unittest.TestCase):
    def test_no_real_secret_in_environment_argv_or_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            credentials, runtime = create_fixture(Path(tmp))
            stream = io.StringIO()
            with redirect_stdout(stream), redirect_stderr(stream):
                args = MOD.prepare_arguments(credentials, runtime, config_test=True)
            self.assertEqual(stream.getvalue(), "")
            self.assertIn("--config-test", args)
            self.assertEqual(args[args.index("--client-id") + 1], CLIENT)
            self.assertNotIn(SECRET, " ".join(args))
            self.assertNotIn(COOKIE, " ".join(args))
            self.assertNotIn(EMAIL, " ".join(args))
            self.assertNotIn("OAUTH2_PROXY_CLIENT_SECRET", " ".join(args))
            self.assertEqual(
                (runtime / "google-client-secret").read_text(), SECRET
            )
            self.assertEqual(
                (runtime / "oauth-cookie-secret").read_bytes(), base64.b64decode(COOKIE)
            )
            self.assertEqual(stat.S_IMODE((runtime / "google-client-secret").stat().st_mode), 0o600)
            self.assertEqual((runtime / "oauth-cookie-secret").stat().st_size, 32)
            self.assertEqual(stat.S_IMODE((runtime / "oauth-cookie-secret").stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(runtime.stat().st_mode), 0o700)

    def test_missing_credentials_denied(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cred, runtime = create_fixture(Path(tmp))
            (cred / "google-oauth.env").unlink()
            with self.assertRaises(MOD.CredentialError):
                MOD.prepare_arguments(cred, runtime)

    def test_bad_cookie_denied(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cred, runtime = create_fixture(Path(tmp))
            (cred / "google-oauth.env").write_text(
                f"OAUTH2_PROXY_CLIENT_ID={CLIENT}\n"
                f"OAUTH2_PROXY_CLIENT_SECRET={SECRET}\n"
                "OAUTH2_PROXY_COOKIE_SECRET=wrong\n"
            )
            with self.assertRaises(MOD.CredentialError):
                MOD.prepare_arguments(cred, runtime)

    def test_extra_environment_key_denied(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cred, runtime = create_fixture(Path(tmp))
            with (cred / "google-oauth.env").open("a") as f:
                f.write("OAUTH2_PROXY_SKIP_AUTH_ROUTES=^/api\n")
            with self.assertRaises(MOD.CredentialError):
                MOD.prepare_arguments(cred, runtime)

    def test_untrusted_credential_symlink_denied(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cred, runtime = create_fixture(Path(tmp))
            (cred / "google-oauth.env").unlink()
            (cred / "google-oauth.env").symlink_to(Path(tmp) / "missing")
            with self.assertRaises(MOD.CredentialError):
                MOD.prepare_arguments(cred, runtime)

    def test_two_google_identities_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cred, runtime = create_fixture(Path(tmp))
            (cred / "allowed-emails.txt").write_text(
                "synthetic@example.test\nother@example.test\n"
            )
            with self.assertRaises(MOD.CredentialError):
                MOD.prepare_arguments(cred, runtime)
            self.assertEqual(list(runtime.iterdir()), [])

    def test_domain_wildcard_denied_before_secret_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cred, runtime = create_fixture(Path(tmp))
            (cred / "allowed-emails.txt").write_text("*@example.test\n")
            with self.assertRaises(MOD.CredentialError):
                MOD.prepare_arguments(cred, runtime)
            self.assertEqual(list(runtime.iterdir()), [])

    def test_nonascii_allowlist_denied_before_secret_handoff(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cred, runtime = create_fixture(Path(tmp))
            (cred / "allowed-emails.txt").write_text("тест@example.test\n")
            with self.assertRaises(MOD.CredentialError):
                MOD.prepare_arguments(cred, runtime)
            self.assertEqual(list(runtime.iterdir()), [])

    def test_non_private_runtime_directory_denied(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cred, runtime = create_fixture(Path(tmp))
            os.chmod(runtime, 0o755)
            with self.assertRaises(MOD.CredentialError):
                MOD.prepare_arguments(cred, runtime)

    def test_symlinked_runtime_secret_denied(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cred, runtime = create_fixture(Path(tmp))
            target = Path(tmp) / "outside"
            target.write_text("safe")
            (runtime / "google-client-secret").symlink_to(target)
            with self.assertRaises(MOD.CredentialError):
                MOD.prepare_arguments(cred, runtime)
            self.assertEqual(target.read_text(), "safe")

    def test_no_client_credentials_literal_in_systemd_service(self) -> None:
        unit = (Path(__file__).resolve().parents[1] /
                "infrastructure/external-access/nexolab-google-oauth-stage.service.example").read_text()
        self.assertNotIn("EnvironmentFile=", unit)
        self.assertIn("DynamicUser=yes", unit)
        self.assertIn("LoadCredential=google-oauth.env:", unit)
        self.assertIn("LoadCredential=allowed-emails.txt:", unit)
        self.assertIn("RuntimeDirectoryMode=0700", unit)
        self.assertIn("NoNewPrivileges=yes", unit)
        self.assertIn("--run", unit)
        self.assertNotIn("[Install]", unit.replace("# Deliberately NO [Install] section.", ""))


if __name__ == "__main__":
    unittest.main()
