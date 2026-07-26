"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { AlertTriangle, ChevronRight, LoaderCircle, LogIn, RotateCcw } from "lucide-react";

import type { EdgeNode } from "@/data/dashboard";
import { hasPermission } from "@/features/security/security-session";
import { useDashboardSecurity } from "@/hooks/use-dashboard-security";
import { useDashboardTelemetry } from "@/hooks/use-dashboard-telemetry";

import { AlarmsPanel } from "./alarms-panel";
import { CamerasPanel } from "./cameras-panel";
import { KpiCard } from "./kpi-card";
import { LabMap } from "./lab-map";
import { NodesPanel } from "./nodes-panel";
import { Panel } from "./panel";
import { SessionsPanel } from "./sessions-panel";
import { Sidebar } from "./sidebar";
import { TelemetryStatusBar } from "./telemetry-status-bar";
import { TemperatureChart } from "./temperature-chart";
import { Topbar } from "./topbar";

function PanelAction({ label }: { label: string }) {
  return (
    <button className="inline-flex items-center gap-1 rounded-lg border border-white/[0.065] bg-white/[0.02] px-2.5 py-1.5 text-[8px] font-medium text-slate-500 transition hover:border-blue-400/25 hover:text-slate-200">
      {label}
      <ChevronRight className="h-3 w-3" />
    </button>
  );
}

function liveNode(status: ReturnType<typeof useDashboardTelemetry>["status"], records: number): EdgeNode {
  const state: EdgeNode["state"] =
    status === "live" ? "online" : status === "offline" || status === "error" ? "offline" : "warning";

  return {
    id: "edge-01",
    name: "Production Device Agent",
    channels: `${records} / 34 latest records`,
    cpu: null,
    ram: null,
    state,
    spark: [],
  };
}

function SecurityGate({
  state,
  error,
  onRetry,
}: {
  state: "loading" | "unauthenticated" | "forbidden" | "error";
  error: string | null;
  onRetry: () => void;
}) {
  const loading = state === "loading";
  const unauthenticated = state === "unauthenticated";
  return (
    <main className="grid min-h-screen place-items-center bg-[#06142a] p-4 text-slate-100">
      <section className="w-full max-w-lg rounded-3xl border border-cyan-400/15 bg-[#091a31]/95 p-6 shadow-2xl shadow-black/30">
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
            <h1 className="mt-1 text-xl font-semibold text-white">
              {loading
                ? "Перевірка захищеної сесії"
                : unauthenticated
                  ? "Потрібен вхід до системи"
                  : "Доступ до dashboard відхилено"}
            </h1>
          </div>
        </div>
        <p className="mt-5 text-sm leading-6 text-slate-400">
          {loading
            ? "Backend перевіряє JWT, членство в організації та дозволи dashboard/telemetry. Дані не завантажуються до завершення перевірки."
            : (error ?? "Поточна сесія не має доступу до вибраної організації.")}
        </p>
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

export function DashboardShell() {
  const router = useRouter();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [activeItem, setActiveItem] = useState("Огляд");
  const security = useDashboardSecurity();
  const securityReady = security.mode === "demo" || security.state === "ready";
  const telemetry = useDashboardTelemetry({
    enabled: securityReady,
    organizationId: security.membership?.organizationId ?? null,
  });

  if (
    security.mode === "live" &&
    (security.state === "loading" ||
      security.state === "unauthenticated" ||
      security.state === "forbidden" ||
      security.state === "error")
  ) {
    return <SecurityGate state={security.state} error={security.error} onRetry={security.retry} />;
  }

  const nodes =
    telemetry.mode === "live"
      ? [liveNode(telemetry.status, telemetry.view?.freshSamples.length ?? 0)]
      : undefined;
  const liveSamples = telemetry.view?.samples ?? [];
  const mobileStatusTone =
    telemetry.status === "live"
      ? "border-emerald-300/10 bg-emerald-400/[0.04] text-emerald-400"
      : telemetry.status === "demo"
        ? "border-blue-300/10 bg-blue-400/[0.04] text-blue-300"
        : "border-amber-300/10 bg-amber-400/[0.04] text-amber-300";
  const canCreateSession =
    security.mode === "demo" ||
    Boolean(
      security.session &&
      security.membership &&
      hasPermission(security.session, security.membership.organizationId, "sessions.manage"),
    );

  return (
    <div className="min-h-screen bg-[#06142a] text-slate-100">
      <Sidebar
        open={sidebarOpen}
        activeItem={activeItem}
        onClose={() => setSidebarOpen(false)}
        onSelect={setActiveItem}
      />
      <div className="min-h-screen lg:pl-[264px]">
        <Topbar
          title={activeItem}
          onMenuOpen={() => setSidebarOpen(true)}
          showCreateSession={canCreateSession}
          securitySession={security.session}
          selectedMembership={security.membership}
          onOrganizationChange={security.selectOrganization}
          onSignOut={() => {
            void security.signOut().then(() => router.replace("/login"));
          }}
        />
        <main className="relative overflow-hidden p-3 sm:p-4 xl:p-5 2xl:p-6">
          <div className="pointer-events-none absolute -top-40 -right-24 h-[420px] w-[420px] rounded-full bg-blue-500/[0.07] blur-3xl" />
          <div className="pointer-events-none absolute bottom-0 left-1/4 h-[300px] w-[300px] rounded-full bg-cyan-400/[0.035] blur-3xl" />

          <div className="relative mx-auto max-w-[1800px]">
            <div className="mb-4 flex items-end justify-between gap-4 px-1 lg:hidden">
              <div>
                <p className="text-[9px] tracking-[0.18em] text-cyan-300 uppercase">Control center</p>
                <h1 className="mt-1 text-xl font-semibold text-white">Огляд лабораторії</h1>
              </div>
              <span className={`rounded-full border px-3 py-1.5 text-[9px] capitalize ${mobileStatusTone}`}>
                ● {telemetry.status}
              </span>
            </div>

            <TelemetryStatusBar
              mode={telemetry.mode}
              status={telemetry.status}
              lastCapturedAt={telemetry.view?.lastCapturedAt ?? null}
              ageMs={telemetry.view?.ageMs ?? null}
              rejectedFutureSamples={telemetry.view?.rejectedFutureSamples ?? 0}
              error={telemetry.error}
              onRetry={telemetry.retry}
            />

            <section
              className="grid grid-cols-2 gap-2.5 md:grid-cols-3 xl:grid-cols-6 xl:gap-3"
              aria-label="Ключові показники"
            >
              {telemetry.kpis.map((item, index) => (
                <KpiCard key={item.label} item={item} index={index} />
              ))}
            </section>

            <section className="mt-3 grid grid-cols-1 gap-3 xl:grid-cols-12">
              <Panel
                title={telemetry.mode === "live" ? "Production node" : "Вузли системи · demo"}
                action={<PanelAction label="Всі вузли" />}
                className="xl:col-span-3"
              >
                <NodesPanel nodes={nodes} />
              </Panel>
              <Panel
                title={telemetry.mode === "live" ? "XJP60D температури" : "Температури · demo preview"}
                className="xl:col-span-6"
              >
                <TemperatureChart
                  mode={telemetry.mode}
                  status={telemetry.status}
                  samples={telemetry.temperatures}
                  historySamples={telemetry.historySamples}
                  historyRange={telemetry.historyRange}
                  historyStatus={telemetry.historyStatus}
                  historyWindow={telemetry.historyWindow}
                  historyError={telemetry.historyError}
                  onHistoryRangeChange={telemetry.setHistoryRange}
                  onHistoryRetry={telemetry.retryHistory}
                />
              </Panel>
              <Panel
                title={telemetry.mode === "live" ? "Telemetry alarms" : "Тривоги · demo"}
                action={<PanelAction label="Всі тривоги" />}
                className="xl:col-span-3"
              >
                <AlarmsPanel mode={telemetry.mode} samples={liveSamples} />
              </Panel>
            </section>

            <section className="mt-3 grid grid-cols-1 gap-3 xl:grid-cols-12">
              <Panel
                title="Активні лабораторні сесії"
                action={<PanelAction label="Всі сесії" />}
                className="xl:col-span-4"
              >
                <SessionsPanel />
              </Panel>
              <Panel
                title="Схема лабораторії · demo layout"
                action={<PanelAction label="Лабораторія 1" />}
                className="xl:col-span-5"
              >
                <LabMap />
              </Panel>
              <Panel
                title="Камери · demo preview"
                action={<PanelAction label="Всі камери" />}
                className="xl:col-span-3"
              >
                <CamerasPanel />
              </Panel>
            </section>
          </div>
        </main>
      </div>
    </div>
  );
}
