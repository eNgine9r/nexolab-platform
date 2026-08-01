"use client";

import Link from "next/link";
import { AlertTriangle, LoaderCircle, LogIn, RotateCcw } from "lucide-react";

import type { SecuritySessionDiagnostics } from "@/features/security/security-session";
import type { DashboardSecurityErrorCode } from "@/hooks/use-dashboard-security";

type SecurityGateState = "loading" | "unauthenticated" | "forbidden" | "error";

type SecurityGateProps = {
  state: SecurityGateState;
  error: string | null;
  errorCode: DashboardSecurityErrorCode | null;
  diagnostics: SecuritySessionDiagnostics | null;
  onRetry: () => void;
};

function titleFor(state: SecurityGateState, errorCode: DashboardSecurityErrorCode | null): string {
  if (state === "loading") return "Перевірка захищеної сесії";
  if (state === "unauthenticated") return "Потрібен вхід до системи";
  if (state === "forbidden") return "Доступ до dashboard відхилено";
  if (errorCode === "SESSION_MIXED_CONTENT") return "Несумісна схема підключення";
  if (errorCode === "SESSION_REQUEST_TIMEOUT") return "API NEXOLAB не відповідає";
  if (errorCode === "SESSION_API_UNREACHABLE_OR_ORIGIN_BLOCKED") {
    return "Сервіс захищеної сесії недоступний";
  }
  if (errorCode === "SESSION_API_ERROR") return "Помилка API захищеної сесії";
  return "Помилка конфігурації захищеної сесії";
}

function Diagnostics({ diagnostics, errorCode }: Pick<SecurityGateProps, "diagnostics" | "errorCode">) {
  if (!diagnostics) return null;

  return (
    <dl className="mt-5 grid gap-2 rounded-2xl border border-white/[0.07] bg-black/10 p-4 text-xs text-slate-400">
      <div className="grid gap-1 sm:grid-cols-[112px_1fr]">
        <dt className="text-slate-500">Код</dt>
        <dd className="font-mono break-all text-slate-300">{errorCode ?? "UNKNOWN"}</dd>
      </div>
      <div className="grid gap-1 sm:grid-cols-[112px_1fr]">
        <dt className="text-slate-500">Dashboard origin</dt>
        <dd className="font-mono break-all text-slate-300">
          {diagnostics.browserOrigin ?? "server-side / unavailable"}
        </dd>
      </div>
      <div className="grid gap-1 sm:grid-cols-[112px_1fr]">
        <dt className="text-slate-500">Session API</dt>
        <dd className="font-mono break-all text-slate-300">
          {diagnostics.apiOrigin}
          {diagnostics.endpointPath}
        </dd>
      </div>
      {diagnostics.httpStatus !== null ? (
        <div className="grid gap-1 sm:grid-cols-[112px_1fr]">
          <dt className="text-slate-500">HTTP status</dt>
          <dd className="font-mono text-slate-300">{diagnostics.httpStatus}</dd>
        </div>
      ) : null}
    </dl>
  );
}

export function SecurityGate({ state, error, errorCode, diagnostics, onRetry }: SecurityGateProps) {
  const loading = state === "loading";
  const unauthenticated = state === "unauthenticated";

  return (
    <main className="grid min-h-screen place-items-center bg-[#06142a] p-4 text-slate-100">
      <section
        aria-live="polite"
        className="w-full max-w-lg rounded-3xl border border-cyan-400/15 bg-[#091a31]/95 p-6 shadow-2xl shadow-black/30"
      >
        <div className="flex items-start gap-3">
          <div className="grid h-12 w-12 shrink-0 place-items-center rounded-2xl border border-cyan-300/20 bg-cyan-400/10">
            {loading ? (
              <LoaderCircle className="h-6 w-6 animate-spin text-cyan-300" />
            ) : (
              <AlertTriangle className="h-6 w-6 text-amber-300" />
            )}
          </div>
          <div>
            <p className="text-xs tracking-[0.2em] text-cyan-300 uppercase">NEXOLAB Security Gate</p>
            <h1 className="mt-1 text-xl font-semibold text-white">{titleFor(state, errorCode)}</h1>
          </div>
        </div>
        <p className="mt-5 text-sm leading-6 text-slate-400">
          {loading
            ? "Backend перевіряє JWT, членство в організації та дозволи dashboard/telemetry. Дані не завантажуються до завершення перевірки."
            : (error ?? "Поточна сесія не має доступу до вибраної організації.")}
        </p>
        <Diagnostics diagnostics={diagnostics} errorCode={errorCode} />
        <div className="mt-6 flex flex-wrap gap-3">
          {unauthenticated ? (
            <Link
              href="/login"
              className="inline-flex items-center gap-2 rounded-xl bg-blue-500 px-4 py-2.5 text-sm font-medium text-white hover:bg-blue-400"
            >
              <LogIn className="h-4 w-4" />
              Увійти
            </Link>
          ) : null}
          {!loading ? (
            <button
              type="button"
              onClick={onRetry}
              className="inline-flex items-center gap-2 rounded-xl border border-white/10 px-4 py-2.5 text-sm text-slate-200 hover:border-cyan-300/30"
            >
              <RotateCcw className="h-4 w-4" />
              Повторити перевірку
            </button>
          ) : null}
        </div>
      </section>
    </main>
  );
}
