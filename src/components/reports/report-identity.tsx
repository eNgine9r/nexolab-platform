import type { TestReport } from "@/lib/reports/types";
import { reportSessionSummary } from "@/lib/reports/presentation";

export function ReportObject({ report }: { report: TestReport }) {
  const summary = reportSessionSummary(report);
  return (
    <p className="mt-2 text-[11px] break-words text-slate-400">
      {summary ? `Об’єкт: ${summary.test_object}` : "Назву випробування не збережено в цій версії звіту."}
    </p>
  );
}

export function ReportTechnicalDetails({ report }: { report: TestReport }) {
  const fields = [
    ["Report ID", report.id],
    ["Session ID", report.session_id],
    ["Source SHA-256", report.source_sha256],
    ["Manifest SHA-256", report.manifest_sha256],
    ["Config snapshot", report.config_snapshot_id],
    ["Generator", report.generator_version],
    ["Frozen artifacts", String(report.artifacts.length)],
  ];
  return (
    <details
      className="mt-4 rounded-xl border border-white/[0.06] p-3"
      data-testid="report-technical-details"
    >
      <summary className="cursor-pointer text-[11px] font-semibold text-slate-300">
        Технічні дані звіту
      </summary>
      <dl className="mt-3 grid gap-3 sm:grid-cols-2">
        {fields.map(([label, value]) => (
          <div key={label}>
            <dt className="text-[9px] text-slate-500">{label}</dt>
            <dd className="mt-1 font-mono text-[10px] break-all text-slate-300">{value}</dd>
          </div>
        ))}
      </dl>
    </details>
  );
}
