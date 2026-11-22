/**
 * Minimal OOXML workbook writer (#1673): two sheets, inline strings, numeric cells where declared.
 * No dependency, fully offline. Timestamps stay ISO text so the exact instant AND its UTC offset are
 * preserved (an Excel date serial would drop the offset).
 */

import { createZip } from "./zip-store";

export interface XlsxSheet {
  name: string;
  /** First row is the header. */
  rows: readonly (readonly string[])[];
  /** Header names whose non-empty finite cells are written as numbers. */
  numericColumns?: ReadonlySet<string>;
  /** Column widths in characters, by header name. */
  widths?: Readonly<Record<string, number>>;
}

function escapeXml(value: string): string {
  // Strip characters that are illegal in XML 1.0, then escape the markup characters.
  return value
    .replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f￾￿]/g, "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

export function columnName(index: number): string {
  let name = "";
  let value = index;
  do {
    name = String.fromCharCode(65 + (value % 26)) + name;
    value = Math.floor(value / 26) - 1;
  } while (value >= 0);
  return name;
}

function isNumericCell(value: string): boolean {
  if (value.trim() === "") return false;
  const parsed = Number(value);
  return Number.isFinite(parsed) && /^[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?$/.test(value.trim());
}

function sheetXml(sheet: XlsxSheet): string {
  const header = sheet.rows[0] ?? [];
  const numeric = new Set(header.flatMap((name, index) => (sheet.numericColumns?.has(name) ? [index] : [])));
  const columns = header
    .map((name, index) => {
      const width = sheet.widths?.[name] ?? Math.min(48, Math.max(10, name.length + 2));
      return `<col min="${index + 1}" max="${index + 1}" width="${width}" customWidth="1"/>`;
    })
    .join("");
  const rows = sheet.rows
    .map((row, rowIndex) => {
      const cells = row
        .map((value, columnIndex) => {
          const reference = `${columnName(columnIndex)}${rowIndex + 1}`;
          if (rowIndex === 0) {
            return `<c r="${reference}" s="1" t="inlineStr"><is><t xml:space="preserve">${escapeXml(value)}</t></is></c>`;
          }
          if (value === "") return "";
          if (numeric.has(columnIndex) && isNumericCell(value)) {
            return `<c r="${reference}"><v>${Number(value)}</v></c>`;
          }
          return `<c r="${reference}" t="inlineStr"><is><t xml:space="preserve">${escapeXml(value)}</t></is></c>`;
        })
        .join("");
      return `<row r="${rowIndex + 1}">${cells}</row>`;
    })
    .join("");
  const lastColumn = columnName(Math.max(0, header.length - 1));
  return (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
    '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">' +
    `<dimension ref="A1:${lastColumn}${Math.max(1, sheet.rows.length)}"/>` +
    '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>' +
    `<cols>${columns}</cols><sheetData>${rows}</sheetData>` +
    (header.length > 0 ? `<autoFilter ref="A1:${lastColumn}${Math.max(1, sheet.rows.length)}"/>` : "") +
    "</worksheet>"
  );
}

/** Excel limits sheet names to 31 characters and forbids : \ / ? * [ ]. */
export function safeSheetName(name: string, fallback: string): string {
  const cleaned = name
    .replace(/[:\\/?*[\]]/g, " ")
    .trim()
    .slice(0, 31);
  return cleaned || fallback;
}

export function createXlsx(sheets: readonly XlsxSheet[], created: Date = new Date()): Uint8Array {
  const names = sheets.map((sheet, index) => safeSheetName(sheet.name, `Sheet${index + 1}`));
  const stamp = created.toISOString().replace(/\.\d{3}Z$/, "Z");
  return createZip(
    [
      {
        name: "[Content_Types].xml",
        data:
          '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
          '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">' +
          '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>' +
          '<Default Extension="xml" ContentType="application/xml"/>' +
          '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>' +
          '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>' +
          '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>' +
          sheets
            .map(
              (_, index) =>
                `<Override PartName="/xl/worksheets/sheet${index + 1}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>`,
            )
            .join("") +
          "</Types>",
      },
      {
        name: "_rels/.rels",
        data:
          '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
          '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
          '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>' +
          '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>' +
          "</Relationships>",
      },
      {
        name: "docProps/core.xml",
        data:
          '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
          '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">' +
          "<dc:creator>NEXOLAB</dc:creator>" +
          `<dcterms:created xsi:type="dcterms:W3CDTF">${stamp}</dcterms:created>` +
          "</cp:coreProperties>",
      },
      {
        name: "xl/workbook.xml",
        data:
          '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
          '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>' +
          names
            .map(
              (name, index) =>
                `<sheet name="${escapeXml(name)}" sheetId="${index + 1}" r:id="rId${index + 1}"/>`,
            )
            .join("") +
          "</sheets></workbook>",
      },
      {
        name: "xl/_rels/workbook.xml.rels",
        data:
          '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
          '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
          sheets
            .map(
              (_, index) =>
                `<Relationship Id="rId${index + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet${index + 1}.xml"/>`,
            )
            .join("") +
          `<Relationship Id="rId${sheets.length + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>` +
          "</Relationships>",
      },
      {
        name: "xl/styles.xml",
        data:
          '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
          '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">' +
          '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font></fonts>' +
          '<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>' +
          '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>' +
          '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>' +
          '<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/></cellXfs>' +
          '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>' +
          "</styleSheet>",
      },
      ...sheets.map((sheet, index) => ({
        name: `xl/worksheets/sheet${index + 1}.xml`,
        data: sheetXml(sheet),
      })),
    ],
    created,
  );
}
