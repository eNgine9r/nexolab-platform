from __future__ import annotations

import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "run-authenticated-dashboard-acceptance.sh"
PROJECT_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


def _runner_bootstrap() -> str:
    lines = RUNNER.read_text(encoding="utf-8").splitlines()
    export_index = next(
        index
        for index, line in enumerate(lines)
        if line.startswith('export COMPOSE_PROJECT_NAME=')
    )
    return "\n".join(lines[: export_index + 1]) + '\nprintf "%s\\n" "$COMPOSE_PROJECT_NAME"\n'


def _render_project_name(override: str | None = None) -> str:
    environment = os.environ.copy()
    environment.pop("COMPOSE_PROJECT_NAME", None)
    if override is not None:
        environment["COMPOSE_PROJECT_NAME"] = override

    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        suffix=".sh",
        dir=RUNNER.parent,
        delete=False,
    ) as handle:
        handle.write(_runner_bootstrap())
        temporary = Path(handle.name)

    try:
        completed = subprocess.run(
            ["bash", str(temporary)],
            cwd=ROOT,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
        )
    finally:
        temporary.unlink(missing_ok=True)

    return completed.stdout.strip().splitlines()[-1]


class AuthenticatedDashboardComposeProjectNameTests(unittest.TestCase):
    def test_generated_default_is_compose_compatible(self) -> None:
        generated = _render_project_name()
        self.assertTrue(generated.startswith("nexolab-dashboard-acceptance-"))
        self.assertRegex(generated, PROJECT_NAME_RE)

    def test_independent_generated_runs_remain_distinguishable(self) -> None:
        first = _render_project_name()
        second = _render_project_name()
        self.assertNotEqual(first, second)

    def test_explicit_project_name_override_is_preserved(self) -> None:
        override = "nexolab_dashboard-acceptance_615"
        self.assertEqual(_render_project_name(override), override)


if __name__ == "__main__":
    unittest.main()
