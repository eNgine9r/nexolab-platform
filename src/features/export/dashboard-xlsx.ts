import { parseCsv } from "./csv-parse";
import { createXlsx, type XlsxSheet } from "./xlsx-writer";

/** Columns of the Saved Dashboard CSV that carry numbers; everything else stays text. */
export const DASHBOARD_NUMERIC_COLUMNS: ReadonlySet<string> = new Set([
  "value",
  "raw_value",
  "raw_signed_int16",
  "operator_celsius_degC",
  "operator_scale_degC_per_count",
]);

export interface DashboardXlsxMeta {
  dashboardName: string;
  fromIso: string;
  toIso: string;
  displayTimeZone: string;
  generatedAt: Date;
}

export const XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";

export function xlsxFilenameFromCsv(csvFilename: string): string {
  return /\.csv$/i.test(csvFilename) ? csvFilename.replace(/\.csv$/i, ".xlsx") : `${csvFilename}.xlsx`;
}

/**
 * Converts the AUTHORITATIVE server CSV export (persisted rows, never chart vertices) into a workbook.
 * Every column, timestamp (UTC and local with offset), unit, channel identity and quality is carried
 * over verbatim; only numeric columns become numbers. Nothing is added, dropped or recomputed.
 */
export function dashboardCsvToXlsx(csvText: string, meta: DashboardXlsxMeta): Uint8Array {
  const rows = parseCsv(csvText).filter((row) => row.length > 1 || (row[0] ?? "") !== "");
  const dataRows = Math.max(0, rows.length - 1);
  const description: string[][] = [
    ["Параметр", "Значення"],
    ["Dashboard", meta.dashboardName],
    ["Початок інтервалу (UTC)", meta.fromIso],
    ["Кінець інтервалу (UTC)", meta.toIso],
    ["Часова зона відображення", meta.displayTimeZone],
    ["Експортовано (UTC)", meta.generatedAt.toISOString()],
    ["Кількість вимірювань", String(dataRows)],
    [
      "Джерело",
      "Збережені вимірювання Telemetry Service (повний експорт інтервалу, не стиснуті точки графіка).",
    ],
    [
      "Якість",
      "Стовпець quality наведено без змін. Порожнє значення — немає валідного вимірювання; воно не дорівнює нулю.",
    ],
    [
      "Час",
      "timestamp_utc — момент вимірювання в UTC; timestamp_local — той самий момент із зсувом часової зони.",
    ],
  ];
  const sheets: XlsxSheet[] = [
    {
      name: "Вимірювання",
      rows,
      numericColumns: DASHBOARD_NUMERIC_COLUMNS,
      widths: {
        timestamp_utc: 26,
        timestamp_local: 32,
        node: 16,
        device: 20,
        channel: 28,
        metric: 26,
        event_id: 38,
      },
    },
    { name: "Опис", rows: description, widths: { Параметр: 30, Значення: 90 } },
  ];
  return createXlsx(sheets, meta.generatedAt);
}
