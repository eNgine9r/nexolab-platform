"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { ArrowLeft, FileCheck2, Fingerprint, LoaderCircle, RefreshCw } from "lucide-react";

import { createReportApiClient } from "@/lib/reports/api-client";
import type { TestReport } from "@/lib/reports/types";

import { ReportOutputPanel } from "./report-output-panel";

function formatDate(value: string): string {
  return new Intl.DateTimeFormat("uk-UA", {
    dateStyle: "medium",
    timeStyle: "medium",
  }).format(new Date(value));
}

export function ReportOutputWorkspace({ reportId }: { reportId: string }) {
  const [report, setReport] = useState<TestReport | null>(null);
  const [versions, setVersions] = useState<TestReport[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  const load = useCallback(
    async (signal?: AbortSignal) => {
      setLoading(true);
      try {
        const client = createReportApiClient();
        const current = await client.getReport(reportId, signal);
        const page = await client.listReports({ sessionId: current.session_id, limit: 200 }, signal);
        setReport(current);
        setVersions(page.items);
        setError(null);
      } catch (nextError) {
        if (!signal?.aborted) {
          setError(nextError instanceof Error ? nextError : new Error("Звіт не вдалося завантажити."));
        }
      } finally {
        if (!signal?.aborted) setLoading(false);
      }
    },
    [reportId],
  );

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  if (loading && report === null) {
    return (
      <section
        className="panel grid min-h-[420px] place-items-center p-8"
        data-testid="rendered-report-detail"
      >
        <div className="text-center">
          <LoaderCircle className="mx-auto h-8 w-8 animate-spin text-cyan-300" />
          <p className="mt-4 text-sm font-semibold text-slate-200">Завантаження report detail</p>
          <p className="mt-2 text-[11px] text-slate-500">
            Перевіряємо organization scope та immutable metadata…
          </p>
        </div>
      </section>
    );
  }

  if (error || report === null) {
    return (
      <section
        className="panel grid min-h-[420px] place-items-center p-8"
        data-testid="rendered-report-detail"
      >
        <div className="max-w-xl text-center">
          <FileCheck2 className="mx-auto h-8 w-8 text-red-300" />
          <p className="mt-4 text-sm font-semibold text-slate-100">Report detail недоступний</p>
          <p className="mt-2 text-[11px] leading-5 text-slate-500">{error?.message ?? "Звіт не знайдено."}</p>
          <Link
            href="/reports"
            className="mt-5 inline-flex items-center gap-2 rounded-xl border border-white/10 px-4 py-2 text-[11px] text-slate-200"
          >
            <ArrowLeft className="h-4 w-4" />
            До списку звітів
          </Link>
        </div>
      </section>
    );
  }

  return (
    <div className="space-y-4" data-testid="rendered-report-detail">
      <section className="panel p-5 sm:p-6">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <Link
              href="/reports"
              className="inline-flex items-center gap-2 text-[10px] font-semibold text-cyan-300"
            >
              <ArrowLeft className="h-3.5 w-3.5" />
              Усі звіти
            </Link>
            <p className="mt-4 text-[9px] font-semibold tracking-[0.16em] text-cyan-300 uppercase">
              Immutable report · version {report.version}
            </p>
            <h1 className="mt-2 text-2xl font-semibold text-white sm:text-3xl">
              Session {report.session_id}
            </h1>
            <p className="mt-2 text-[11px] text-slate-500">
              Згенеровано {formatDate(report.generated_at)} · {report.generated_by}
            </p>
          </div>
          <button
            type="button"
            onClick={() => void load()}
            disabled={loading}
            className="icon-button"
            aria-label="Оновити report detail"
          >
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
          </button>
        </div>

        <div className="mt-5 grid gap-3 md:grid-cols-2">
          <HashCard label="Source SHA-256" value={report.source_sha256} />
          <HashCard label="Manifest SHA-256" value={report.manifest_sha256} />
        </div>

        <div className="mt-4 grid gap-3 sm:grid-cols-3">
          <Meta label="Config snapshot" value={report.config_snapshot_id} />
          <Meta label="Generator" value={report.generator_version} />
          <Meta label="Frozen artifacts" value={String(report.artifacts.length)} />
        </div>
      </section>

      <ReportOutputPanel report={report} reportVersions={versions} />
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
