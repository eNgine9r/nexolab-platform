from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "validate-adr-registry.py"
SPEC = importlib.util.spec_from_file_location("validate_adr_registry", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
AdrValidationError = MODULE.AdrValidationError


class AdrRegistryTests(unittest.TestCase):
    def make_fixture(self) -> Path:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        adr_dir = root / "docs/adr"
        legacy_dir = root / "docs/architecture"
        adr_dir.mkdir(parents=True)
        legacy_dir.mkdir(parents=True)

        (adr_dir / "0001-central-telemetry-ingestion.md").write_text(
            "# ADR-0001: Central telemetry ingestion architecture\n\n"
            "## Status\n\nAccepted.\n",
            encoding="utf-8",
        )
        (adr_dir / "0003-example-decision.md").write_text(
            "# ADR 0003: Example decision\n\n"
            "- Status: Proposed\n"
            "- Date: 2026-08-06\n",
            encoding="utf-8",
        )
        (adr_dir / "README.md").write_text(
            "# ADRs\n\n"
            "## Registry\n\n"
            "| ID | Title | Status | Date | Supersedes | Canonical record |\n"
            "| --- | --- | --- | --- | --- | --- |\n"
            "| 0001 | Central telemetry ingestion architecture | Accepted | "
            "2026-07-23 | — | "
            "[0001-central-telemetry-ingestion.md]"
            "(0001-central-telemetry-ingestion.md) |\n"
            "| 0003 | Example decision | Proposed | 2026-08-06 | — | "
            "[0003-example-decision.md](0003-example-decision.md) |\n\n"
            "## Historical numbering gaps\n\n"
            "| ID | Classification | Evidence |\n"
            "| --- | --- | --- |\n"
            "| 0002 | Unassigned historical gap | No supported evidence |\n",
            encoding="utf-8",
        )
        (legacy_dir / "adr-0001-telemetry-ingestion.md").write_text(
            "# ADR-0001 legacy compatibility path\n\n"
            "[Canonical](../adr/0001-central-telemetry-ingestion.md)\n\n"
            "[Registry](../adr/README.md)\n",
            encoding="utf-8",
        )
        return root

    def test_valid_registry_passes(self) -> None:
        MODULE.validate(self.make_fixture())

    def test_duplicate_adr_number_fails(self) -> None:
        root = self.make_fixture()
        (root / "docs/adr/0001-duplicate.md").write_text(
            "# ADR 0001: Duplicate\n\n- Status: Accepted\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(AdrValidationError, "duplicate canonical ADR identifier"):
            MODULE.validate(root)

    def test_broken_index_target_fails(self) -> None:
        root = self.make_fixture()
        index = root / "docs/adr/README.md"
        index.write_text(
            index.read_text(encoding="utf-8").replace(
                "(0003-example-decision.md)",
                "(0003-missing-decision.md)",
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(AdrValidationError, "registry target mismatch"):
            MODULE.validate(root)

    def test_missing_legacy_pointer_fails(self) -> None:
        root = self.make_fixture()
        (root / "docs/architecture/adr-0001-telemetry-ingestion.md").write_text(
            "# Broken legacy file\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(AdrValidationError, "does not point"):
            MODULE.validate(root)

    def test_undocumented_gap_fails(self) -> None:
        root = self.make_fixture()
        index = root / "docs/adr/README.md"
        index.write_text(
            index.read_text(encoding="utf-8").replace(
                "| 0002 | Unassigned historical gap | No supported evidence |\n",
                "",
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(AdrValidationError, "historical gap mismatch"):
            MODULE.validate(root)


if __name__ == "__main__":
    unittest.main()
