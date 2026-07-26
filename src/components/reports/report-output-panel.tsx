"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  BadgeCheck,
  Download,
  FileOutput,
  FileSpreadsheet,
  FileText,
  LoaderCircle,
  RefreshCw,
  ShieldCheck,
} from "lucide-react";

import {
  createAuthenticatedFetch,
  hasPermission,
  HttpSecuritySessionClient,
} from "@/features/security/security-session";
import { createRuntimeCredentialProvider } from "@/features/security/supabase-auth";
import {
  createReportActionIdempotencyKey,
  createReportApiClient,
} from "@/lib/reports/api-client";
import { getReportsApiBaseUrl } from "@/lib/reports/runtime-config";
import type {
  ReportOutputState,
  ReportRender,
  ReportRenderFormat,
  TestReport,
} from "@/lib/reports/types";

function formatDate(value: string | null): string {
  if (!value) return "—";
  return new Intl.DateTimeFormat("uk-UA", {
    dateStyle: "medium",
    timeStyle: "medium",
  }).format(new Date(value));
}

function formatBytes(value: number): string {
  if (value < 1024) return `${value} Б`;
  if (value < 1024 * 1024)
    return `${new Intl.NumberFormat("uk-UA", { maximumFractionDigits: 1 }).format(value / 1024)} КБ`;
  return `${new Intl.NumberFormat("uk-UA", { maximumFractionDigits: 1 }).format(value / 1024 / 1024)} МБ`;
}

function compactHash(value: string): string {
  return `${value.slice(0, 12)}…${value.slice(-8)}`;
}

export function ReportOutputPanel({
  report,
  reportVersions,
}: {
  report: TestReport;
  reportVersions: TestReport[];
}) {
  const [output, setOutput] = useState<ReportOutputState | null>(null);
  const [loading, setLoading] = useState(true);
  const [action, setAction] = useState<string | null>(null);
  const [downloading, setDownloading] = useState<string | null>(null);
  const [reason, setReason] = useState("Reviewed immutable evidence and protocol output");
  const [replacementReportId, setReplacementReportId] = useState("");
  const [canRender, setCanRender] = useState(false);
  const [canApprove, setCanApprove] = useState(false);
  const [error, setError] = useState<Error | null>(null);

  const replacements = useMemo(
    () =>
      reportVersions
        .filter((candidate) => candidate.session_id === report.session_id && candidate.version > report.version)
        .sort((left, right) => left.version - right.version),
    [report.session_id, report.version, reportVersions],
  );

  const load = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    try {
      const credentials = createRuntimeCredentialProvider(null);
      const authenticatedFetch = createAuthenticatedFetch(fetch.bind(globalThis), credentials);
      const securityClient = new HttpSecuritySessionClient({
        apiBaseUrl: getReportsApiBaseUrl(),
        fetchImpl: authenticatedFetch,
      });
      const [state, securityResult, snapshot] = await Promise.all([
        createReportApiClient().getOutputState(report.id, signal),
        securityClient.getSession(),
        credentials(),
      ]);
      const organizationId = snapshot.organizationId;
      setOutput(state);
      setCanRender(
        Boolean(
          securityResult.ok &&
            organizationId &&
            hasPermission(securityResult.value, organizationId, "reports.generate"),
        ),
      );
      setCanApprove(
        Boolean(
          securityResult.ok &&
            organizationId &&
            hasPermission(securityResult.value, organizationId, "reports.approve"),
        ),
      );
      setReplacementReportId((current) =>
        current && replacements.some((item) => item.id === current)
          ? current
          : (replacements[0]?.id ?? ""),
      );
      setError(null);
    } catch (nextError) {
      if (!signal?.aborted) {
        setError(nextError instanceof Error ? nextError : new Error("Output state не вдалося завантажити."));
      }
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, [replacements, report.id]);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  const runRender = async (format: ReportRenderFormat) => {
    setAction(`render-${format}`);
    setError(null);
    try {
      await createReportApiClient().renderReport(
        report.id,
        format,
        createReportActionIdempotencyKey(`render-${format}`, report.id),
        report.manifest_sha256,
        `Controlled ${format.toUpperCase()} render from immutable evidence`,
      );
      await load();
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError : new Error("Rendered artifact не вдалося створити."));
    } finally {
      setAction(null);
    }
  };

  const approve = async () => {
    if (!reason.trim()) return;
    setAction("approve");
    setError(null);
    try {
      await createReportApiClient().approveReport(
        report.id,
        reason,
        new Date().toISOString(),
        createReportActionIdempotencyKey("approve", report.id),
        report.manifest_sha256,
      );
      await load();
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError : new Error("Звіт не вдалося затвердити."));
    } finally {
      setAction(null);
    }
  };

  const supersede = async () => {
    if (!reason.trim() || !replacementReportId) return;
    setAction("supersede");
    setError(null);
    try {
      await createReportApiClient().supersedeReport(
        report.id,
        replacementReportId,
        reason,
        new Date().toISOString(),
        createReportActionIdempotencyKey("supersede", report.id),
        report.manifest_sha256,
      );
      await load();
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError : new Error("Звіт не вдалося позначити superseded."));
    } finally {
      setAction(null);
    }
  };

  const download = async (render: ReportRender) => {
    setDownloading(render.id);
    setError(null);
    try {
      const result = await createReportApiClient().downloadRender(
        report.id,
        render.id,
        render.artifact_name,
      );
      if (result.sha256 && result.sha256 !== render.sha256) {
        throw new Error("SHA-256 завантаженого rendered artifact не відповідає metadata.");
      }
      if (result.manifestSha256 && result.manifestSha256 !== report.manifest_sha256) {
        throw new Error("Rendered artifact прив’язаний до іншого manifest SHA-256.");
      }
      const objectUrl = URL.createObjectURL(result.blob);
      const anchor = document.createElement("a");
      anchor.href = objectUrl;
      anchor.download = result.filename;
      anchor.rel = "noopener";
      document.body.append(anchor);
      anchor.click();
      anchor.remove();
      window.setTimeout(() => URL.revokeObjectURL(objectUrl), 0);
    } catch (nextError) {
      setError(nextError instanceof Error ? nextError : new Error("Rendered artifact не вдалося завантажити."));
    } finally {
      setDownloading(null);
    }
  };

  if (loading && output === null) {
    return (
      <section className="rounded-2xl border border-white/[0.06] bg-white/[0.018] p-5" data-testid="report-output-panel">
        <LoaderCircle className="h-5 w-5 animate-spin text-cyan-300" />
        <p className="mt-3 text-[11px] text-slate-400">Читаємо rendered outputs та approval event stream…</p>
      </section>
    );
  }

  const approval = output?.approval;

  return (
    <section className="space-y-4 rounded-2xl border border-cyan-300/[0.1] bg-cyan-400/[0.025] p-4 sm:p-5" data-testid="report-output-panel">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <p className="text-[9px] font-semibold tracking-[0.14em] text-cyan-300 uppercase">
            Rendered protocol lifecycle
          </p>
          <h4 className="mt-2 text-base font-semibold text-white">XLSX, PDF та approval state</h4>
          <p className="mt-2 text-[10px] leading-5 text-slate-500">
            Усі outputs прив’язані до manifest {compactHash(report.manifest_sha256)} і зберігаються append-only.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span
            className="rounded-xl border border-emerald-300/20 bg-emerald-400/[0.06] px-3 py-2 text-[10px] font-semibold text-emerald-200"
            data-testid="report-approval-state"
          >
            <BadgeCheck className="mr-2 inline h-3.5 w-3.5" />
            {approval?.state ?? "generated"}
          </span>
          <button type="button" onClick={() => void load()} className="icon-button" aria-label="Оновити outputs">
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
          </button>
        </div>
      </div>

      {approval?.approved_by ? (
        <div className="grid gap-3 sm:grid-cols-2">
          <OutputMeta label="Затвердив" value={approval.approved_by} />
          <OutputMeta label="Час затвердження" value={formatDate(approval.approved_at)} />
          <OutputMeta label="Причина" value={approval.approval_reason ?? "—"} />
          <OutputMeta
            label="Superseded by"
            value={approval.superseded_by_report_id ?? "Активна затверджена версія"}
          />
        </div>
      ) : null}

      <div>
        <div className="flex items-center justify-between gap-3">
          <h5 className="text-[11px] font-semibold text-slate-200">Rendered artifacts</h5>
          {canRender ? (
            <div className="flex gap-2">
              <ActionButton
                testId="render-xlsx"
                label="XLSX"
                icon={FileSpreadsheet}
                busy={action === "render-xlsx"}
                onClick={() => void runRender("xlsx")}
              />
              <ActionButton
                testId="render-pdf"
                label="PDF"
                icon={FileText}
                busy={action === "render-pdf"}
                onClick={() => void runRender("pdf")}
              />
            </div>
          ) : null}
        </div>

        <div className="mt-3 space-y-2">
          {output?.renders.length ? (
            output.renders.map((render) => (
              <div
                key={render.id}
                className="flex flex-col gap-3 rounded-2xl border border-white/[0.06] bg-slate-950/25 p-4 sm:flex-row sm:items-center sm:justify-between"
              >
                <div className="flex items-center gap-3">
                  <div className="grid h-9 w-9 place-items-center rounded-xl bg-cyan-400/[0.08] text-cyan-300">
                    <FileOutput className="h-4 w-4" />
                  </div>
                  <div>
                    <p className="text-[11px] font-semibold text-slate-100">{render.artifact_name}</p>
                    <p className="mt-1 text-[9px] text-slate-500">
                      {render.renderer_version} · {formatBytes(render.size_bytes)} · {compactHash(render.sha256)}
                    </p>
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => void download(render)}
                  disabled={downloading === render.id}
                  className="inline-flex items-center justify-center gap-2 rounded-xl border border-white/[0.08] bg-white/[0.025] px-3 py-2 text-[10px] font-semibold text-slate-200 transition hover:border-cyan-300/25 hover:text-cyan-200 disabled:opacity-45"
                  data-testid={`download-render-${render.format}`}
                >
                  {downloading === render.id ? (
                    <LoaderCircle className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Download className="h-3.5 w-3.5" />
                  )}
                  Завантажити
                </button>
              </div>
            ))
          ) : (
            <div className="rounded-2xl border border-dashed border-white/[0.08] p-5 text-center text-[10px] text-slate-500">
              Rendered artifacts ще не створені.
            </div>
          )}
        </div>
      </div>

      {canApprove ? (
        <div className="space-y-3 border-t border-white/[0.06] pt-4" data-testid="report-approval-actions">
          <label className="block space-y-2">
            <span className="text-[9px] font-semibold tracking-[0.12em] text-slate-500 uppercase">
              Approval reason
            </span>
            <input
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              className="form-input"
              data-testid="report-approval-reason"
            />
          </label>

          {approval?.state === "approved" && replacements.length > 0 ? (
            <label className="block space-y-2">
              <span className="text-[9px] font-semibold tracking-[0.12em] text-slate-500 uppercase">
                Replacement version
              </span>
              <select
                value={replacementReportId}
                onChange={(event) => setReplacementReportId(event.target.value)}
                className="form-input"
                data-testid="report-replacement-select"
              >
                {replacements.map((candidate) => (
                  <option key={candidate.id} value={candidate.id}>
                    Version {candidate.version} · {candidate.id}
                  </option>
                ))}
              </select>
            </label>
          ) : null}

          <div className="flex flex-wrap gap-2">
            {approval?.state === "generated" ? (
              <ActionButton
                testId="approve-report"
                label="Затвердити"
                icon={ShieldCheck}
                busy={action === "approve"}
                disabled={!reason.trim()}
                onClick={() => void approve()}
              />
            ) : null}
            {approval?.state === "approved" && replacements.length > 0 ? (
              <ActionButton
                testId="supersede-report"
                label="Замінити версією"
                icon={RefreshCw}
                busy={action === "supersede"}
                disabled={!reason.trim() || !replacementReportId}
                onClick={() => void supersede()}
              />
            ) : null}
          </div>
        </div>
      ) : (
        <div className="flex items-center gap-3 border-t border-white/[0.06] pt-4 text-[10px] text-slate-500">
          <ShieldCheck className="h-4 w-4 text-cyan-300" />
          Approval actions потребують permission <code className="text-cyan-200">reports.approve</code>.
        </div>
      )}

      {error ? (
        <div className="rounded-xl border border-red-300/20 bg-red-400/[0.06] p-3 text-[10px] text-red-200">
          {error.message}
        </div>
      ) : null}
    </section>
  );
}

function ActionButton({
  testId,
  label,
  icon: Icon,
  busy,
  disabled = false,
  onClick,
}: {
  testId: string;
  label: string;
  icon: typeof FileOutput;
  busy: boolean;
  disabled?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={busy || disabled}
      className="inline-flex items-center justify-center gap-2 rounded-xl border border-cyan-300/20 bg-cyan-400/[0.07] px-3 py-2 text-[10px] font-semibold text-cyan-100 transition hover:bg-cyan-400/[0.12] disabled:cursor-not-allowed disabled:opacity-45"
      data-testid={testId}
    >
      {busy ? <LoaderCircle className="h-3.5 w-3.5 animate-spin" /> : <Icon className="h-3.5 w-3.5" />}
      {label}
    </button>
  );
}

function OutputMeta({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-white/[0.055] bg-slate-950/20 p-3">
      <p className="text-[9px] text-slate-600">{label}</p>
      <p className="mt-1 text-[10px] leading-5 break-all text-slate-300">{value}</p>
    </div>
  );
}
