import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { reportTitle } from "@/lib/reports/presentation";
import type { TestReport } from "@/lib/reports/types";
import { ReportObject, ReportTechnicalDetails } from "./report-identity";

const report = {
  id: "report-uuid",
  session_id: "session-uuid",
  version: 2,
  session_summary: { session_number: "NX-42", title: "Охолодження", test_object: "Камера K106" },
  source_sha256: "source-hash",
  manifest_sha256: "manifest-hash",
  config_snapshot_id: "config-id",
  generator_version: "v1",
  artifacts: [],
} as unknown as TestReport;
describe("frozen report display identity", () => {
  it("uses the frozen number, title and object with separate technical diagnostics", () => {
    expect(reportTitle(report)).toBe("NX-42 · Охолодження");
    render(
      <>
        <ReportObject report={report} />
        <ReportTechnicalDetails report={report} />
      </>,
    );
    expect(screen.getByText("Об’єкт: Камера K106")).toBeInTheDocument();
    const details = screen.getByTestId("report-technical-details");
    expect(details).not.toHaveAttribute("open");
    expect(details.querySelector("summary")).toHaveTextContent("Технічні дані звіту");
    for (const value of [
      report.id,
      report.session_id,
      report.source_sha256,
      report.manifest_sha256,
      report.config_snapshot_id,
    ])
      expect(details).toHaveTextContent(value);
  });
  it.each([
    undefined,
    null,
    {},
    { session_number: "NX", title: " ", test_object: "K106" },
    { session_number: "x".repeat(65), title: "Test", test_object: "K106" },
  ])("uses an honest legacy/malformed fallback (%j)", (session_summary) => {
    const legacy = { ...report, session_summary } as TestReport;
    expect(reportTitle(legacy)).toBe("Звіт випробування");
    render(<ReportObject report={legacy} />);
    expect(screen.getByText("Назву випробування не збережено в цій версії звіту.")).toBeInTheDocument();
    expect(screen.queryByText(report.session_id)).not.toBeInTheDocument();
  });
});
