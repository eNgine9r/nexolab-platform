#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import date
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from typing import Any


class PolicyFailure(ValueError):
    pass


@dataclass(frozen=True)
class Finding:
    target: str
    vulnerability: str
    package: str
    installed_version: str
    fixed_version: str
    severity: str

    @property
    def key(self) -> tuple[str, str]:
        return self.package, self.vulnerability


def load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PolicyFailure(f"cannot read valid JSON from {path}") from exc
    if not isinstance(payload, dict):
        raise PolicyFailure(f"{path} must contain a JSON object")
    return payload


def load_policy_validator(root: Path) -> Any:
    path = root / "scripts" / "validate-container-supply-chain.py"
    spec = spec_from_file_location("container_supply_chain_validator", path)
    if spec is None or spec.loader is None:
        raise PolicyFailure("cannot load container supply-chain validator")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_exceptions(
    root: Path,
    path: Path,
    *,
    image_id: str,
    today: date,
) -> dict[tuple[str, str], dict[str, str]]:
    validator = load_policy_validator(root)
    try:
        validator.validate_exceptions(path, today)
    except validator.ValidationFailure as exc:
        raise PolicyFailure(str(exc)) from exc

    payload = load_json(path)
    selected: dict[tuple[str, str], dict[str, str]] = {}
    for item in payload["exceptions"]:
        if item["image_id"] != image_id:
            continue
        selected[(item["package"], item["vulnerability"])] = item
    return selected


def parse_findings(report: dict[str, Any]) -> list[Finding]:
    schema_version = report.get("SchemaVersion")
    if not isinstance(schema_version, int) or schema_version < 2:
        raise PolicyFailure("Trivy report has an unsupported SchemaVersion")
    results = report.get("Results")
    if not isinstance(results, list):
        raise PolicyFailure("Trivy report Results must be a list")

    findings: list[Finding] = []
    for result_index, result in enumerate(results):
        if not isinstance(result, dict):
            raise PolicyFailure(f"Results[{result_index}] must be an object")
        target = result.get("Target")
        if not isinstance(target, str) or not target.strip():
            raise PolicyFailure(f"Results[{result_index}].Target is required")
        vulnerabilities = result.get("Vulnerabilities") or []
        if not isinstance(vulnerabilities, list):
            raise PolicyFailure(
                f"Results[{result_index}].Vulnerabilities must be a list or null"
            )
        for finding_index, item in enumerate(vulnerabilities):
            label = f"Results[{result_index}].Vulnerabilities[{finding_index}]"
            if not isinstance(item, dict):
                raise PolicyFailure(f"{label} must be an object")
            vulnerability = item.get("VulnerabilityID")
            package = item.get("PkgName")
            severity = item.get("Severity")
            if not isinstance(vulnerability, str) or not vulnerability.strip():
                raise PolicyFailure(f"{label}.VulnerabilityID is required")
            if not isinstance(package, str) or not package.strip():
                raise PolicyFailure(f"{label}.PkgName is required")
            if not isinstance(severity, str) or not severity.strip():
                raise PolicyFailure(f"{label}.Severity is required")
            normalized_severity = severity.upper()
            if normalized_severity not in {
                "UNKNOWN",
                "LOW",
                "MEDIUM",
                "HIGH",
                "CRITICAL",
            }:
                raise PolicyFailure(f"{label}.Severity is unsupported")
            findings.append(
                Finding(
                    target=target.strip(),
                    vulnerability=vulnerability.strip(),
                    package=package.strip(),
                    installed_version=str(item.get("InstalledVersion") or ""),
                    fixed_version=str(item.get("FixedVersion") or ""),
                    severity=normalized_severity,
                )
            )
    return findings


def find_stale_exceptions(
    findings: list[Finding],
    exceptions: dict[tuple[str, str], dict[str, str]],
) -> list[tuple[str, str]]:
    active_keys = {
        finding.key
        for finding in findings
        if finding.severity in {"HIGH", "CRITICAL"}
    }
    return sorted(set(exceptions) - active_keys)


def evaluate(
    findings: list[Finding],
    exceptions: dict[tuple[str, str], dict[str, str]],
) -> tuple[list[Finding], list[Finding]]:
    blocked: list[Finding] = []
    accepted: list[Finding] = []
    for finding in findings:
        if finding.severity == "CRITICAL":
            blocked.append(finding)
            continue
        if finding.severity == "HIGH":
            if finding.vulnerability.startswith("CVE-") and finding.key in exceptions:
                accepted.append(finding)
            else:
                blocked.append(finding)
    return blocked, accepted


def format_finding(finding: Finding) -> str:
    fix = finding.fixed_version or "no fixed version"
    installed = finding.installed_version or "unknown"
    return (
        f"{finding.severity} {finding.vulnerability} package={finding.package} "
        f"installed={installed} fixed={fix} target={finding.target}"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--image-id", required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument(
        "--exceptions",
        type=Path,
        default=Path("security/vulnerability-exceptions.json"),
    )
    parser.add_argument("--today", type=date.fromisoformat, default=date.today())
    args = parser.parse_args()

    root = args.root.resolve()
    report_path = args.report if args.report.is_absolute() else root / args.report
    exceptions_path = (
        args.exceptions if args.exceptions.is_absolute() else root / args.exceptions
    )
    report = load_json(report_path)
    findings = parse_findings(report)
    exceptions = load_exceptions(
        root,
        exceptions_path,
        image_id=args.image_id,
        today=args.today,
    )
    stale = find_stale_exceptions(findings, exceptions)
    if stale:
        formatted = ", ".join(f"{package}/{cve}" for package, cve in stale)
        raise PolicyFailure(
            "stale vulnerability exceptions must be removed: " + formatted
        )

    blocked, accepted = evaluate(findings, exceptions)

    for finding in accepted:
        decision = exceptions[finding.key]
        print(
            "Accepted HIGH vulnerability: "
            f"{format_finding(finding)} owner={decision['owner']} "
            f"expires_on={decision['expires_on']}"
        )
    if blocked:
        for finding in blocked:
            print(f"Blocked vulnerability: {format_finding(finding)}")
        raise PolicyFailure(
            f"{len(blocked)} unapproved HIGH/CRITICAL vulnerabilities block release"
        )

    high_or_critical = sum(
        finding.severity in {"HIGH", "CRITICAL"} for finding in findings
    )
    print(
        "Container vulnerability policy passed: "
        f"{len(findings)} findings, {high_or_critical} high/critical, "
        f"{len(accepted)} accepted exceptions."
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except PolicyFailure as exc:
        print(f"Container vulnerability policy failed: {exc}")
        raise SystemExit(1) from exc
