from __future__ import annotations

from typing import Any
from zipfile import ZIP_DEFLATED, ZipFile

from openpyxl.workbook import workbook as workbook_module
from openpyxl.workbook.workbook import Workbook
from openpyxl.writer.excel import ExcelWriter

_MARKER = "_nexolab_preserves_core_properties"


def _save_workbook_preserving_core_properties(
    workbook: Workbook,
    filename: Any,
) -> bool:
    """Write an XLSX without replacing its explicit modified timestamp."""
    archive = ZipFile(filename, "w", ZIP_DEFLATED, allowZip64=True)
    writer = ExcelWriter(workbook, archive)
    writer.save()
    return True


def install_deterministic_workbook_save() -> None:
    """Install a narrow openpyxl compatibility shim once per process."""
    if getattr(workbook_module.save_workbook, _MARKER, False):
        return
    setattr(_save_workbook_preserving_core_properties, _MARKER, True)
    workbook_module.save_workbook = _save_workbook_preserving_core_properties
