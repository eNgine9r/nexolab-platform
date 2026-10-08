"use client";

import { formatOperationalTimestamp } from "@/features/display-time/format";
import { useDisplayTimeZone } from "@/hooks/use-display-time-zone";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { ArrowLeft, FileCheck2, LoaderCircle, RefreshCw } from "lucide-react";

import {
  createAuthenticatedFetch,
  hasPermission,
  HttpSecuritySessionClient,
} from "@/features/security/security-session";
import { createRuntimeCredentialProvider } from "@/features/security/supabase-auth";
import { createReportApiClient } from "@/lib/reports/api-client";
import { getReportsApiBaseUrl } from "@/lib/reports/runtime-config";
import type { ReportOutputState, TestReport } from "@/lib/reports/types";

import { ReportObject, ReportTechnicalDetails } from "./report-identity";
import { reportTitle } from "@/lib/reports/presentation";

import { ReportOutputPanel } from "./report-output-panel";

function formatDate(value: string, displayTimeZone: string): string {
  return formatOperationalTimestamp(new Date(value), displayTimeZone, {
    dateStyle: "medium",
    timeStyle: "medium",
  });
}

export function ReportOutputWorkspace({ reportId }: { reportId: string }) {
  const displayTimeZone = useDisplayTimeZone();
  const [report, setReport] = useState<TestReport | null>(null);
  const [versions, setVersions] = useState<TestReport[]>([]);
  const [output, setOutput] = useState<ReportOutputState | null>(null);
  const [canRender, setCanRender] = useState(false);
  const [canApprove, setCanApprove] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<Error | null>(null);

  const load = useCallback(
    async (signal?: AbortSignal) => {
      setLoading(true);
      try {
        const client = createReportApiClient();
        const current = await client.getReport(reportId, signal);
        const credentials = createRuntimeCredentialProvider(null);
        const authenticatedFetch = createAuthenticatedFetch(fetch.bind(globalThis), credentials);
        const securityClient = new HttpSecuritySessionClient({
          apiBaseUrl: getReportsApiBaseUrl(),
          fetchImpl: authenticatedFetch,
        });
        const [page, outputState, securityResult, snapshot] = await Promise.all([
          client.listReports({ sessionId: current.session_id, limit: 200 }, signal),
          client.getOutputState(current.id, signal),
          securityClient.getSession(),
          credentials(),
        ]);
        const organizationId = snapshot.organizationId;
        setReport(current);
        setVersions(page.items);
        setOutput(outputState);
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
    const timer = window.setTimeout(() => {
      void load(controller.signal);
    }, 0);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [load]);

  if (loading && (report === null || output === null)) {
    return (
      <section
        className="panel grid min-h-[420px] place-items-center p-8"
        data-testid="rendered-report-detail"
      >
        <div className="text-center">
          <LoaderCircle className="mx-auto h-8 w-8 animate-spin text-cyan-300" />
          <p className="mt-4 text-sm font-semibold text-slate-200">Завантаження деталей звіту</p>
          <p className="mt-2 text-[11px] text-slate-500">
            Перевіряємо organization scope та immutable metadata…
          </p>
        </div>
      </section>
    );
  }

  if (error || report === null || output === null) {
    return (
      <section
        className="panel grid min-h-[420px] place-items-center p-8"
        data-testid="rendered-report-detail"
      >
        <div className="max-w-xl text-center">
          <FileCheck2 className="mx-auto h-8 w-8 text-red-300" />
          <p className="mt-4 text-sm font-semibold text-slate-100">Деталі звіту недоступні</p>
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
            <h1 className="mt-2 text-2xl font-semibold break-words text-white sm:text-3xl">
              {reportTitle(report)}
            </h1>
            <ReportObject report={report} />
            <p className="mt-2 text-[11px] text-slate-500">
              Згенеровано {formatDate(report.generated_at, displayTimeZone)} · {report.generated_by}
            </p>
          </div>
          <button
            type="button"
            onClick={() => void load()}
            disabled={loading}
            className="icon-button"
            aria-label="Оновити деталі звіту"
          >
            <RefreshCw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
          </button>
        </div>

        <ReportTechnicalDetails report={report} />
      </section>

      <ReportOutputPanel
        report={report}
        reportVersions={versions}
        output={output}
        canRender={canRender}
        canApprove={canApprove}
        loading={loading}
        onReload={() => load()}
      />
    </div>
  );
}
