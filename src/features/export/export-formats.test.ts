import { mkdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { parseCsv } from "./csv-parse";
import { dashboardCsvToXlsx, xlsxFilenameFromCsv } from "./dashboard-xlsx";
import { columnName, createXlsx, safeSheetName } from "./xlsx-writer";
import { createZip, crc32 } from "./zip-store";

/** Independent minimal reader for STORE zips: validates structure, CRCs and returns the entries. */
function readZip(bytes: Uint8Array): Map<string, string> {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  let endOffset = -1;
  for (let index = bytes.length - 22; index >= 0; index -= 1) {
    if (view.getUint32(index, true) === 0x06054b50) {
      endOffset = index;
      break;
    }
  }
  expect(endOffset).toBeGreaterThanOrEqual(0);
  const count = view.getUint16(endOffset + 10, true);
  let cursor = view.getUint32(endOffset + 16, true);
  const entries = new Map<string, string>();
  for (let entry = 0; entry < count; entry += 1) {
    expect(view.getUint32(cursor, true)).toBe(0x02014b50);
    const crc = view.getUint32(cursor + 16, true);
    const size = view.getUint32(cursor + 20, true);
    const nameLength = view.getUint16(cursor + 28, true);
    const localOffset = view.getUint32(cursor + 42, true);
    const name = new TextDecoder().decode(bytes.subarray(cursor + 46, cursor + 46 + nameLength));
    expect(view.getUint32(localOffset, true)).toBe(0x04034b50);
    expect(view.getUint16(localOffset + 8, true)).toBe(0); // STORE
    const localNameLength = view.getUint16(localOffset + 26, true);
    const start = localOffset + 30 + localNameLength;
    const data = bytes.subarray(start, start + size);
    expect(crc32(data)).toBe(crc);
    entries.set(name, new TextDecoder().decode(data));
    cursor += 46 + nameLength;
  }
  return entries;
}

describe("zip store", () => {
  it("computes the standard CRC-32 and round-trips entries including UTF-8 names", () => {
    expect(crc32(new TextEncoder().encode("123456789"))).toBe(0xcbf43926);
    const entries = readZip(
      createZip([
        { name: "a.txt", data: "hello" },
        { name: "дані/б.txt", data: "привіт, світе" },
      ]),
    );
    expect(entries.get("a.txt")).toBe("hello");
    expect(entries.get("дані/б.txt")).toBe("привіт, світе");
  });
});

describe("csv parser", () => {
  it("handles quotes, doubled quotes, embedded commas/newlines, CRLF and BOM", () => {
    expect(parseCsv('﻿a,b,c\r\n1,"x,y","he said ""hi"""\n"line1\nline2",,\n')).toEqual([
      ["a", "b", "c"],
      ["1", "x,y", 'he said "hi"'],
      ["line1\nline2", "", ""],
    ]);
    expect(parseCsv("")).toEqual([]);
    expect(parseCsv("a,b")).toEqual([["a", "b"]]);
  });
});

describe("xlsx writer", () => {
  it("names columns like a spreadsheet and sanitises sheet names", () => {
    expect([0, 25, 26, 27, 701, 702].map(columnName)).toEqual(["A", "Z", "AA", "AB", "ZZ", "AAA"]);
    expect(safeSheetName("a:b/c?[d]*e\\f", "x")).toBe("a b c  d  e f");
    expect(safeSheetName("   ", "Sheet1")).toBe("Sheet1");
    expect(safeSheetName("x".repeat(40), "s")).toHaveLength(31);
  });

  it("writes a well-formed workbook with typed numbers, text and escaped XML", () => {
    const entries = readZip(
      createXlsx([
        {
          name: "Дані",
          rows: [
            ["when", "value", "note"],
            ["2026-11-20T08:00:00+02:00", "4.25", 'a<b & "c"'],
            ["2026-11-20T08:00:10+02:00", "", "no measurement"],
            ["2026-11-20T08:00:20+02:00", "not-a-number", "x\u0001y"],
          ],
          numericColumns: new Set(["value"]),
        },
      ]),
    );
    for (const name of [
      "[Content_Types].xml",
      "_rels/.rels",
      "xl/workbook.xml",
      "xl/_rels/workbook.xml.rels",
      "xl/styles.xml",
      "xl/worksheets/sheet1.xml",
    ]) {
      const xml = entries.get(name);
      expect(xml, name).toBeDefined();
      const parsed = new DOMParser().parseFromString(xml!, "application/xml");
      expect(parsed.getElementsByTagName("parsererror"), name).toHaveLength(0);
    }
    const sheet = entries.get("xl/worksheets/sheet1.xml")!;
    expect(sheet).toContain('<c r="B2"><v>4.25</v></c>');
    expect(sheet).not.toContain('r="B3"'); // empty stays empty, never zero
    expect(sheet).toContain('r="B4" t="inlineStr"'); // non-numeric stays text
    expect(sheet).toContain("a&lt;b &amp; &quot;c&quot;");
    expect(sheet).not.toContain("\u0001");
    expect(entries.get("xl/workbook.xml")).toContain('name="Дані"');
  });
});

const CSV =
  "timestamp_utc,timestamp_local,node,device,channel,metric,value,unit,quality,event_id,raw_value,raw_signed_int16,operator_celsius_degC,operator_scale_degC_per_count,operator_scale_basis\n" +
  "2026-11-20T06:00:00Z,2026-11-20T08:00:00+02:00,edge-1,K106,106-01,temperature.probe,4.25,degC,valid,e1,,,,,\n" +
  "2026-11-20T06:00:10Z,2026-11-20T08:00:10+02:00,edge-1,K106,106-01,temperature.probe,,degC,communication_error,e2,,,,,\n" +
  "2026-11-20T06:00:20Z,2026-11-20T08:00:20+02:00,edge-1,EMBRACO-2,2-cabinet-temperature,temperature.cabinet,,degC,unknown,e3,-22,-22,-0.22,0.01,candidate_0p01_hmi_not_calibrated\n";

describe("Saved Dashboard CSV → XLSX", () => {
  const meta = {
    dashboardName: "Аналіз <тест>",
    fromIso: "2026-11-20T06:00:00.000Z",
    toIso: "2026-11-20T07:00:00.000Z",
    displayTimeZone: "Europe/Kyiv",
    generatedAt: new Date("2026-11-22T06:00:00Z"),
  };

  it("carries every CSV cell verbatim, types only numeric columns and documents the export", () => {
    const entries = readZip(dashboardCsvToXlsx(CSV, meta));
    const sheet = entries.get("xl/worksheets/sheet1.xml")!;
    // value column is G; the valid reading is a number, the failed polls stay empty (not 0).
    expect(sheet).toContain('<c r="G2"><v>4.25</v></c>');
    expect(sheet).not.toContain('r="G3"');
    expect(sheet).not.toContain('r="G4"');
    // Quality is preserved as text, timestamps keep their UTC offset as text.
    expect(sheet).toContain("communication_error");
    expect(sheet).toContain("2026-11-20T08:00:10+02:00");
    // Operator-derived provisional columns stay numeric where present.
    expect(sheet).toContain("<v>-0.22</v>");
    expect(sheet).toContain("<v>0.01</v>");
    expect(sheet).toContain("candidate_0p01_hmi_not_calibrated");
    const description = entries.get("xl/worksheets/sheet2.xml")!;
    expect(description).toContain("Аналіз &lt;тест&gt;");
    expect(description).toContain("Europe/Kyiv");
    expect(description).toContain('<t xml:space="preserve">3</t>'); // three measurements
    expect(entries.get("xl/workbook.xml")).toContain('name="Вимірювання"');
  });

  it("derives the xlsx filename from the CSV filename", () => {
    expect(xlsxFilenameFromCsv("live-dashboard-x.csv")).toBe("live-dashboard-x.xlsx");
    expect(xlsxFilenameFromCsv("export")).toBe("export.xlsx");
  });

  it("writes a sample file for independent reader verification when requested", () => {
    if (!process.env.NEXOLAB_WRITE_XLSX_SAMPLE) return;
    const dir = join(tmpdir(), "nexolab-xlsx-sample");
    mkdirSync(dir, { recursive: true });
    writeFileSync(join(dir, "sample.xlsx"), dashboardCsvToXlsx(CSV, meta));
  });
});
