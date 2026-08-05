"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { ChevronRight, Settings2 } from "lucide-react";

import { hasPermission } from "@/features/security/security-session";
import { useDashboardSecurity } from "@/hooks/use-dashboard-security";
import { useDashboardTelemetry } from "@/hooks/use-dashboard-telemetry";
import { useXjp60dSensorManagement } from "@/hooks/use-xjp60d-sensor-management";

import { AlarmsPanel } from "./alarms-panel";
import { CamerasPanel } from "./cameras-panel";
import { KpiCard } from "./kpi-card";
import { LabMap } from "./lab-map";
import { LiveInventoryPanel } from "./live-inventory-panel";
import { NodesPanel } from "./nodes-panel";
import { Panel } from "./panel";
import { SecurityGate } from "./security-gate";
import { SensorManagementDialog } from "./sensor-management-dialog";
import { SessionsPanel } from "./sessions-panel";
import { Sidebar } from "./sidebar";
import { TelemetryStatusBar } from "./telemetry-status-bar";
import { TemperatureChart } from "./temperature-chart";
import { Topbar } from "./topbar";

function PanelAction({ label, href }: { label: string; href: string }) {
  return (
    <Link
      href={href}
      className="inline-flex items-center gap-1 rounded-lg border border-white/[0.065] bg-white/[0.02] px-2.5 py-1.5 text-[8px] font-medium text-slate-500 transition hover:border-blue-400/25 hover:text-slate-200"
    >
      {label}
      <ChevronRight className="h-3 w-3" />
    </Link>
  );
}

export function DashboardShell() {
  const router = useRouter();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [sensorDialogOpen, setSensorDialogOpen] = useState(false);
  const security = useDashboardSecurity();
  const securityReady = security.mode === "demo" || security.state === "ready";
  const organizationId = security.membership?.organizationId ?? null;
  const sensorManagement = useXjp60dSensorManagement({
    enabled: security.mode === "live" && securityReady,
    organizationId,
  });
  const telemetry = useDashboardTelemetry({
    enabled: securityReady,
    organizationId,
    temperatureChannelIds: security.mode === "live" ? sensorManagement.activeChannelIds : null,
  });

  if (
    security.mode === "live" &&
    (security.state === "loading" ||
      security.state === "unauthenticated" ||
      security.state === "forbidden" ||
      security.state === "error")
  ) {
    return (
      <SecurityGate
        state={security.state}
        error={security.error}
        errorCode={security.errorCode}
        diagnostics={security.diagnostics}
        onRetry={security.retry}
      />
    );
  }

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
  const canManageSensors =
    security.mode === "demo" ||
    Boolean(
      security.session &&
      security.membership &&
      hasPermission(security.session, security.membership.organizationId, "equipment.manage"),
    );

  return (
    <div className="min-h-screen bg-[#06142a] text-slate-100">
      <Sidebar open={sidebarOpen} onClose={() => setSidebarOpen(false)} />
      <div className="min-h-screen lg:pl-[264px]">
        <Topbar
          title="Огляд"
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
                action={<PanelAction label="Всі вузли" href="/nodes" />}
                className="xl:col-span-3"
              >
                {telemetry.mode === "live" ? (
                  <LiveInventoryPanel samples={liveSamples} status={telemetry.status} />
                ) : (
                  <NodesPanel />
                )}
              </Panel>
              <Panel
                title={telemetry.mode === "live" ? "XJP60D температури" : "Температури · demo preview"}
                action={
                  telemetry.mode === "live" ? (
                    <button
                      type="button"
                      onClick={() => setSensorDialogOpen(true)}
                      aria-label="Керувати температурними датчиками"
                      title="Керувати температурними датчиками"
                      className="grid h-8 w-8 place-items-center rounded-lg border border-white/[0.065] bg-white/[0.02] text-slate-500 transition hover:border-cyan-300/25 hover:text-cyan-200"
                    >
                      <Settings2 className="h-3.5 w-3.5" />
                    </button>
                  ) : undefined
                }
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
                action={<PanelAction label="Всі тривоги" href="/alerts" />}
                className="xl:col-span-3"
              >
                <AlarmsPanel mode={telemetry.mode} samples={liveSamples} />
              </Panel>
            </section>

            <section className="mt-3 grid grid-cols-1 gap-3 xl:grid-cols-12">
              <Panel
                title="Активні лабораторні сесії"
                action={<PanelAction label="Всі сесії" href="/sessions" />}
                className="xl:col-span-4"
              >
                <SessionsPanel />
              </Panel>
              <Panel title="Схема лабораторії · demo layout" className="xl:col-span-5">
                <LabMap />
              </Panel>
              <Panel
                title="Камери · demo preview"
                action={<PanelAction label="Всі камери" href="/cameras" />}
                className="xl:col-span-3"
              >
                <CamerasPanel />
              </Panel>
            </section>
          </div>
        </main>
      </div>

      <SensorManagementDialog
        open={sensorDialogOpen}
        canManage={canManageSensors}
        management={sensorManagement}
        onClose={() => setSensorDialogOpen(false)}
        onSaved={() => {
          telemetry.retry();
          telemetry.retryHistory();
        }}
      />
    </div>
  );
}
