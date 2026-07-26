"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Archive,
  CheckCircle2,
  Download,
  FileCheck2,
  FileJson2,
  FileSpreadsheet,
  Fingerprint,
  LoaderCircle,
  RefreshCw,
  ShieldCheck,
  WifiOff,
} from "lucide-react";

import {
  createAuthenticatedFetch,
  hasPermission,
  HttpSecuritySessionClient,
} from "@/features/security/security-session";
import { createRuntimeCredentialProvider } from "@/features/security/supabase-auth";
import { createReportApiClient, createReportIdempotencyKey } from "@/lib/reports/api-client";
import { getReportsApiBaseUrl } from "@/lib/reports/runtime-config";
import type { ReportArtifact, TestReport } from "@/lib/reports/types";
import { createSessionApiClient } from "@/lib/sessions/api-client";
import type { LaboratorySession } from "@/lib/sessions/types";

function formatDate(value: string): string {
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

function artifactIcon(artifact: ReportArtifact) {
  if (artifact.media_type.includes("csv")) return FileSpreadsheet;
  return FileJson2;
}

function compactHash(value: string): string {
  return `${value.slice(0, 12)}…${value.slice(-8)}`;
}

export function ReportsWorkspace() {
  const [reports, setReports] = useState<TestReport[]>([]);
  const [sessions, setSessions] = useState<LaboratorySession[]>([]);
  const [selectedReportId, setSelectedReportId] = useState<string | null>(null);
  const [selectedSessionId, setSelectedSessionId] = useState("");
  const [reason, setReason] = useState("");
  const [loading, setLoading] = useState(true);
  const [mutating, setMutating] = useState(false);
  const [downloading, setDownloading] = useState<string | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [actionError, setActionError] = useState<Error | null>(null);
  const [canGenerate, setCanGenerate] = useState(false);
  const [generation, setGeneration] = useState(0);
  const [lastSuccessfulAt, setLastSuccessfulAt] = useState<number | null>(null);
  const [now, setNow] = useState(() => Date.now());

  const selectedReport = useMemo(
    () => reports.find((item) => item.id === selectedReportId) ?? null,
    [reports, selectedReportId],
  );
  const selectedSession = useMemo(
    () => sessions.find((item) => item.id === selectedSessionId) ?? null,
    [selectedSessionId, sessions],
  );

  const load = useCallback(async (signal: AbortSignal) => {
    setLoading(true);
    try {
      const credentials = createRuntimeCredentialProvider(null);
      const authenticatedFetch = createAuthenticatedFetch(fetch.bind(globalThis), credentials);
      const securityClient = new HttpSecuritySessionClient({
        apiBaseUrl: getReportsApiBaseUrl(),
        fetchImpl: authenticatedFetch,
      });
      const [reportPage, completedPage, archivedPage, securityResult, snapshot] = await Promise.all([
        createReportApiClient().listReports({ limit: 200 }, signal),
        createSessionApiClient().listSessions({ state: "completed", limit: 100 }, signal),
        createSessionApiClient().listSessions({ state: "archived", limit: 100 }, signal),
        securityClient.getSession(),
        credentials(),
      ]);
      const terminalSessions = [...completedPage.items, ...archivedPage.items].sort((left, right) =>
        right.updated_at.localeCompare(left.updated_at),
      );
      setReports(reportPage.items);
      setSessions(terminalSessions);
      setSelectedReportId((current) => {
        if (current && reportPage.items.some((item) => item.id === current)) return current;
        return reportPage.items[0]?.id ?? null;
      });
      setSelectedSessionId((current) => {
        if (current && terminalSessions.some((item) => item.id === current)) return current;
        return terminalSessions[0]?.id ?? "";
      });
      const organizationId = snapshot.organizationId;
      setCanGenerate(
        Boolean(
          securityResult.ok &&
          organizationId &&
          hasPermission(securityResult.value, organizationId, "reports.generate"),
        ),
      );
      setError(null);
      setLastSuccessfulAt(Date.now());
    } catch (nextError) {
      if (!signal.aborted) {
        setError(nextError instanceof Error ? nextError : new Error("Не вдалося завантажити звіти."));
      }
    } finally {
      if (!signal.aborted) setLoading(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    const initial = window.setTimeout(() => void load(controller.signal), 0);
    return () => {
      controller.abort();
      window.clearTimeout(initial);
    };
  }, [generation, load]);

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1_000);
    return () => window.clearInterval(timer);
  }, []);

  const stale = lastSuccessfulAt !== null && now - lastSuccessfulAt > 30_000;

  const refresh = () => {
    setLoading(true);
    setGeneration((value) => value + 1);
  };

  const generateReport = async () => {
    if (!selectedSessionId || !canGenerate) return;
    setMutating(true);
    setActionError(null);
    try {
      const response = await createReportApiClient().generateReport(
        selectedSessionId,
        reason,
        createReportIdempotencyKey(selectedSessionId),
      );
      setReports((items) => [response, ...items.filter((item) => item.id !== response.id)]);
      setSelectedReportId(response.id);
      setReason("");
      setLastSuccessfulAt(Date.now());
    } catch (nextError) {
      setActionError(nextError instanceof Error ? nextError : new Error("Звіт не вдалося сформувати."));
    } finally {
      setMutating(false);
    }
  };

  const downloadArtifact = async (report: TestReport, artifact: ReportArtifact) => {
    const key = `${report.id}:${artifact.name}`;
    setDownloading(key);
    setActionError(null);
    try {
      const result = await createReportApiClient().downloadArtifact(report.id, artifact.name);
      if (result.sha256 && result.sha256 !== artifact.sha256) {
        throw new Error("SHA-256 завантаженого артефакту не відповідає manifest metadata.");
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
      setActionError(nextError instanceof Error ? nextError : new Error("Артефакт не вдалося завантажити."));
    } finally {
      setDownloading(null);
    }
  };

  return (
    <div className="space-y-4" data-testid="reports-workspace">
      <section className="panel p-5 sm:p-6">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
          <div>
            <p className="text-[9px] font-semibold tracking-[0.18em] text-cyan-300 uppercase">
              Sprint 13 · Immutable Evidence
            </p>
            <h1 className="mt-2 text-2xl font-semibold text-white sm:text-3xl">Звіти випробувань</h1>
            <p className="mt-2 max-w-3xl text-[12px] leading-6 text-slate-400">
              Відтворювані версії звітів, deterministic CSV/JSON, SHA-256 і організаційно ізольоване
              завантаження evidence.
            </p>
          </div>
          <div className="grid grid-cols-3 gap-2 sm:min-w-[460px]">
            <Summary label="Версій" value={reports.length} />
            <Summary label="Сесій" value={new Set(reports.map((item) => item.session_id)).size} />
            <Summary
              label="Артефактів"
              value={reports.reduce((sum, item) => sum + item.artifacts.length, 0)}
            />
          </div>
        </div>
      </section>

      {canGenerate ? (
        <section className="panel p-4 sm:p-5" data-testid="report-generation-panel">
          <div className="grid gap-3 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)_auto] xl:items-end">
            <label className="space-y-2">
              <span className="text-[10px] font-semibold tracking-[0.12em] text-slate-500 uppercase">
                Завершена сесія
              </span>
              <select
                value={selectedSessionId}
                onChange={(event) => setSelectedSessionId(event.target.value)}
                className="form-input"
                data-testid="report-session-select"
              >
                {sessions.length === 0 ? <option value="">Немає reportable сесій</option> : null}
                {sessions.map((session) => (
                  <option key={session.id} value={session.id}>
                    {session.session_number} · {session.test_object} · {session.state}
                  </option>
                ))}
              </select>
            </label>
            <label className="space-y-2">
              <span className="text-[10px] font-semibold tracking-[0.12em] text-slate-500 uppercase">
                Причина генерації
              </span>
              <input
                value={reason}
                onChange={(event) => setReason(event.target.value)}
                placeholder="Контрольований evidence export…"
                className="form-input"
              />
            </label>
            <button
              type="button"
              onClick={() => void generateReport()}
              disabled={mutating || !selectedSessionId}
              className="inline-flex min-h-10 items-center justify-center gap-2 rounded-xl border border-cyan-300/25 bg-cyan-400/10 px-4 text-[11px] font-semibold text-cyan-100 transition hover:bg-cyan-400/15 disabled:cursor-not-allowed disabled:opacity-45"
              data-testid="generate-report"
            >
              {mutating ? (
                <LoaderCircle className="h-4 w-4 animate-spin" />
              ) : (
                <FileCheck2 className="h-4 w-4" />
              )}
              Сформувати версію
            </button>
          </div>
          {selectedSession ? (
            <p className="mt-3 text-[10px] text-slate-500">
              Source boundary: {selectedSession.started_at ? formatDate(selectedSession.started_at) : "—"} —{" "}
              {selectedSession.completed_at ? formatDate(selectedSession.completed_at) : "—"}
            </p>
          ) : null}
        </section>
      ) : (
        <section className="panel flex items-center gap-3 p-4 text-[11px] text-slate-400">
          <ShieldCheck className="h-5 w-5 text-cyan-300" />
          Поточна роль має read-only доступ. Генерація потребує permission
          <code className="rounded bg-white/[0.04] px-1.5 py-0.5 text-cyan-200">reports.generate</code>.
        </section>
      )}

      {actionError ? (
        <section className="rounded-2xl border border-red-300/20 bg-red-400/[0.06] p-4 text-[11px] text-red-200">
          {actionError.message}
        </section>
      ) : null}

      <section className="panel overflow-hidden">
        <div className="flex items-center justify-between border-b border-white/[0.055] p-4 sm:p-5">
          <div>
            <h2 className="text-sm font-semibold text-white">Версії звітів</h2>
            <p className="mt-1 text-[10px] text-slate-500">
              {stale ? "Дані можуть бути застарілими" : "Immutable source snapshots"}
            </p>
          </div>
          <button
            type="button"
            onClick={refresh}
            disabled={loading}
            className="icon-button"
            aria-label="Оновити звіти"
          >
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
          </button>
        </div>

        {loading && reports.length === 0 ? (
          <Status
            icon={LoaderCircle}
            title="Завантаження звітів"
            detail="Читаємо immutable report metadata…"
            spin
          />
        ) : error && reports.length === 0 ? (
          <Status icon={WifiOff} title="Reports API недоступний" detail={error.message} />
        ) : reports.length === 0 ? (
          <Status
            icon={Archive}
            title="Звітів ще немає"
            detail="Сформуйте першу версію для завершеної сесії."
          />
        ) : (
          <div className="grid min-h-[560px] xl:grid-cols-[380px_minmax(0,1fr)]">
            <div className="border-b border-white/[0.055] xl:border-r xl:border-b-0">
              {reports.map((report) => (
                <button
                  type="button"
                  key={report.id}
                  onClick={() => setSelectedReportId(report.id)}
                  className={`block w-full border-b border-white/[0.045] p-4 text-left transition ${
                    selectedReportId === report.id ? "bg-cyan-400/[0.06]" : "hover:bg-white/[0.025]"
                  }`}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="truncate text-[12px] font-semibold text-slate-100">
                        Session {report.session_id}
                      </p>
                      <p className="mt-1 text-[10px] text-slate-500">
                        Версія {report.version} · {formatDate(report.generated_at)}
                      </p>
                    </div>
                    <span className="rounded-lg border border-emerald-300/20 bg-emerald-400/[0.06] px-2 py-1 text-[9px] font-semibold text-emerald-200">
                      {report.session_state}
                    </span>
                  </div>
                  <p className="mt-3 font-mono text-[9px] text-cyan-300/80">
                    {compactHash(report.source_sha256)}
                  </p>
                </button>
              ))}
            </div>

            <div className="p-4 sm:p-5" data-testid="report-detail">
              {selectedReport ? (
                <ReportDetail
                  report={selectedReport}
                  downloading={downloading}
                  onDownload={downloadArtifact}
                />
              ) : (
                <Status
                  icon={FileCheck2}
                  title="Оберіть звіт"
                  detail="Виберіть immutable report version у списку."
                />
              )}
            </div>
          </div>
        )}
      </section>
    </div>
  );
}

function ReportDetail({
  report,
  downloading,
  onDownload,
}: {
  report: TestReport;
  downloading: string | null;
  onDownload: (report: TestReport, artifact: ReportArtifact) => Promise<void>;
}) {
  return (
    <div className="space-y-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <p className="text-[9px] font-semibold tracking-[0.14em] text-cyan-300 uppercase">
            Report version {report.version}
          </p>
          <h3 className="mt-2 text-xl font-semibold text-white">Session {report.session_id}</h3>
          <p className="mt-2 text-[11px] text-slate-500">
            Згенеровано {formatDate(report.generated_at)} · {report.generated_by}
          </p>
        </div>
        <div className="rounded-xl border border-emerald-300/20 bg-emerald-400/[0.055] px-3 py-2 text-[10px] text-emerald-200">
          <CheckCircle2 className="mr-2 inline h-3.5 w-3.5" />
          Append-only
        </div>
      </div>

      <div className="grid gap-3 md:grid-cols-2">
        <HashCard label="Source SHA-256" value={report.source_sha256} />
        <HashCard label="Manifest SHA-256" value={report.manifest_sha256} />
      </div>

      <div className="grid gap-3 sm:grid-cols-3">
        <Meta label="Config snapshot" value={report.config_snapshot_id} />
        <Meta label="Generator" value={report.generator_version} />
        <Meta
          label="Source window"
          value={`${formatDate(report.source_started_at)} — ${formatDate(report.source_ended_at)}`}
        />
      </div>

      <div>
        <h4 className="text-[11px] font-semibold text-slate-200">Evidence artifacts</h4>
        <div className="mt-3 space-y-2">
          {report.artifacts.map((artifact) => {
            const Icon = artifactIcon(artifact);
            const key = `${report.id}:${artifact.name}`;
            return (
              <div
                key={artifact.id}
                className="flex flex-col gap-3 rounded-2xl border border-white/[0.06] bg-white/[0.018] p-4 sm:flex-row sm:items-center sm:justify-between"
              >
                <div className="flex min-w-0 items-center gap-3">
                  <div className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-cyan-400/[0.07] text-cyan-300">
                    <Icon className="h-4 w-4" />
                  </div>
                  <div className="min-w-0">
                    <p className="truncate text-[11px] font-semibold text-slate-100">{artifact.name}</p>
                    <p className="mt-1 text-[9px] text-slate-500">
                      {formatBytes(artifact.size_bytes)}
                      {artifact.row_count === null ? "" : ` · ${artifact.row_count} rows`}
                      {` · ${compactHash(artifact.sha256)}`}
                    </p>
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => void onDownload(report, artifact)}
                  disabled={downloading === key}
                  className="inline-flex items-center justify-center gap-2 rounded-xl border border-white/[0.08] bg-white/[0.025] px-3 py-2 text-[10px] font-semibold text-slate-200 transition hover:border-cyan-300/25 hover:text-cyan-200 disabled:opacity-45"
                  data-testid={`download-${artifact.name}`}
                >
                  {downloading === key ? (
                    <LoaderCircle className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Download className="h-3.5 w-3.5" />
                  )}
                  Завантажити
                </button>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

function Summary({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-2xl border border-white/[0.06] bg-white/[0.02] px-3 py-3 text-center">
      <p className="text-lg font-semibold text-white">{value}</p>
      <p className="mt-1 text-[9px] text-slate-500">{label}</p>
    </div>
  );
}

function HashCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl border border-cyan-300/[0.09] bg-cyan-400/[0.025] p-4">
      <p className="flex items-center gap-2 text-[9px] font-semibold tracking-[0.12em] text-slate-500 uppercase">
        <Fingerprint className="h-3.5 w-3.5 text-cyan-300" />
        {label}
      </p>
      <p className="mt-2 font-mono text-[10px] leading-5 break-all text-cyan-100/85">{value}</p>
    </div>
  );
}

function Meta({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-white/[0.055] bg-white/[0.018] p-3">
      <p className="text-[9px] text-slate-600">{label}</p>
      <p className="mt-1 text-[10px] leading-5 break-all text-slate-300">{value}</p>
    </div>
  );
}

function Status({
  icon: Icon,
  title,
  detail,
  spin = false,
}: {
  icon: typeof FileCheck2;
  title: string;
  detail: string;
  spin?: boolean;
}) {
  return (
    <div className="grid min-h-64 place-items-center p-8 text-center">
      <div>
        <Icon className={`mx-auto h-8 w-8 text-slate-600 ${spin ? "animate-spin" : ""}`} />
        <p className="mt-4 text-sm font-semibold text-slate-200">{title}</p>
        <p className="mt-2 max-w-lg text-[11px] leading-5 text-slate-500">{detail}</p>
      </div>
    </div>
  );
}
