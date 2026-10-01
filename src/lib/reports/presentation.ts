import type { ReportSessionSummary, TestReport } from "./types";

export function reportSessionSummary(report: TestReport): ReportSessionSummary | null {
  const value = report.session_summary;
  if (!value || typeof value !== "object") return null;
  for (const [key, limit] of [
    ["session_number", 64],
    ["title", 256],
    ["test_object", 256],
  ] as const) {
    const field = value[key];
    if (typeof field !== "string" || !field.trim() || field.length > limit) return null;
  }
  return value;
}

export function reportTitle(report: TestReport): string {
  const summary = reportSessionSummary(report);
  return summary ? `${summary.session_number} · ${summary.title}` : "Звіт випробування";
}
