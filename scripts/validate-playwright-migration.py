#!/usr/bin/env python3
"""Validate the focused Playwright migration without changing browser-test intent."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_CONFIGS = (
    "playwright.alerts.config.ts",
    "playwright.broker-control.config.ts",
    "playwright.dashboard.config.ts",
    "playwright.disaster-recovery.config.ts",
    "playwright.device-agent-fleet.config.ts",
    "playwright.local-auth.config.ts",
    "playwright.nodes.config.ts",
    "playwright.observability.config.ts",
    "playwright.production.config.ts",
    "playwright.rendered-reports.config.ts",
    "playwright.reports.config.ts",
    "playwright.security.config.ts",
    "playwright.sessions.config.ts",
)
ANSI_ESCAPE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
REMOVED_API_PATTERNS = {
    "_react selector": re.compile(r"_react\s*="),
    "_vue selector": re.compile(r"_vue\s*="),
    ":light selector suffix": re.compile(r":light(?:\(|\b)"),
    "browserType.launch devtools option": re.compile(r"\bdevtools\s*:"),
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=ROOT,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def parse_test_listing(output: str) -> tuple[list[str], int, int]:
    clean = ANSI_ESCAPE.sub("", output)
    discovered = [
        line.strip()
        for line in clean.splitlines()
        if "›" in line and not line.lstrip().startswith("Error:")
    ]
    summary_match = re.search(r"Total:\s+(\d+)\s+tests?\s+in\s+(\d+)\s+files?", clean)
    if summary_match is None:
        raise RuntimeError(f"Unable to parse Playwright --list summary:\n{clean}")
    return discovered, int(summary_match.group(1)), int(summary_match.group(2))


def scan_removed_apis() -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    paths = list(ROOT.glob("playwright*.config.ts")) + list((ROOT / "e2e").rglob("*.ts"))
    for path in sorted(paths):
        text = path.read_text(encoding="utf-8")
        for label, pattern in REMOVED_API_PATTERNS.items():
            for match in pattern.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                findings.append(
                    {
                        "api": label,
                        "path": str(path.relative_to(ROOT)),
                        "line": line,
                    }
                )
    return findings


def collect(expected_version: str) -> dict[str, Any]:
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    declared = package["devDependencies"].get("@playwright/test")
    if declared != expected_version:
        raise RuntimeError(
            f"Expected package.json @playwright/test={expected_version}, found {declared!r}"
        )

    cli = ROOT / "node_modules" / ".bin" / "playwright"
    if not cli.exists():
        raise RuntimeError("Playwright CLI is not installed in node_modules")
    version_result = run([str(cli), "--version"])
    if version_result.returncode != 0:
        raise RuntimeError(version_result.stdout)
    installed_version = version_result.stdout.strip().removeprefix("Version ")
    if installed_version != expected_version:
        raise RuntimeError(
            f"Expected installed Playwright {expected_version}, found {installed_version}"
        )

    actual_configs = tuple(path.name for path in sorted(ROOT.glob("playwright*.config.ts")))
    if actual_configs != EXPECTED_CONFIGS:
        raise RuntimeError(
            "Playwright config inventory changed. "
            f"Expected {EXPECTED_CONFIGS!r}, found {actual_configs!r}"
        )

    removed_api_findings = scan_removed_apis()
    if removed_api_findings:
        raise RuntimeError(
            "Removed Playwright APIs/selectors remain in the browser suite: "
            + json.dumps(removed_api_findings, indent=2)
        )

    configs: list[dict[str, Any]] = []
    total_tests = 0
    for config_name in EXPECTED_CONFIGS:
        result = run(
            [
                str(cli),
                "test",
                f"--config={config_name}",
                "--list",
            ]
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"Config {config_name} failed to load/list tests:\n{result.stdout}"
            )
        tests, test_count, file_count = parse_test_listing(result.stdout)
        if test_count != len(tests):
            raise RuntimeError(
                f"Config {config_name} reported {test_count} tests but listed {len(tests)}"
            )
        total_tests += test_count
        configs.append(
            {
                "config": config_name,
                "sha256": sha256(ROOT / config_name),
                "test_count": test_count,
                "file_count": file_count,
                "tests": tests,
            }
        )

    return {
        "schema_version": 1,
        "playwright_version": installed_version,
        "config_count": len(configs),
        "total_discovered_tests": total_tests,
        "removed_api_findings": removed_api_findings,
        "configs": configs,
    }


def compare_contracts(before: dict[str, Any], after: dict[str, Any]) -> None:
    comparable_keys = ("config_count", "total_discovered_tests", "configs")
    differences = {
        key: {"before": before.get(key), "after": after.get(key)}
        for key in comparable_keys
        if before.get(key) != after.get(key)
    }
    if differences:
        raise RuntimeError(
            "Playwright migration changed config/test discovery contracts:\n"
            + json.dumps(differences, indent=2)
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-version", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--compare", type=Path)
    args = parser.parse_args()

    evidence = collect(args.expected_version)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")

    if args.compare is not None:
        before = json.loads(args.compare.read_text(encoding="utf-8"))
        compare_contracts(before, evidence)

    print(
        "Playwright migration contract passed: "
        f"version={evidence['playwright_version']} "
        f"configs={evidence['config_count']} "
        f"tests={evidence['total_discovered_tests']}"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, OSError, json.JSONDecodeError) as error:
        print(f"Playwright migration contract failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
