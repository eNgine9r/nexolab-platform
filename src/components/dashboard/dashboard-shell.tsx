"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { ArrowUpRight, ChevronRight, Settings2 } from "lucide-react";

import { readCameraInventory } from "@/features/cameras/domain";
import { hasPermission } from "@/features/security/security-session";
import { useDashboardSecurity } from "@/hooks/use-dashboard-security";
import { useDashboardTelemetry } from "@/hooks/use-dashboard-telemetry";
import { useXjp60dSensorManagement } from "@/hooks/use-xjp60d-sensor-management";

import { AlarmsPanel } from "./alarms-panel";
import { KpiCard } from "./kpi-card";
import { LabMap } from "./lab-map";
import { LiveInventoryPanel } from "./live-inventory-panel";
import { NodesPanel } from "./nodes-panel";
import { OverviewSecondaryWorkspace } from "./overview-secondary-workspace";
import { OverviewWorkspaceLayout } from "./overview-workspace-layout";
import { Panel } from "./panel";
import { SecurityGate } from "./security-gate";
import { TemperatureVisibilityDialog } from "./temperature-visibility-dialog";
import { SessionsPanel } from "./sessions-panel";
import { canSeePlatformDestination, Sidebar } from "./sidebar";
import { TelemetryStatusBar } from "./telemetry-status-bar";
import { TemperatureChart } from "./temperature-chart";
import { Topbar } from "./topbar";
import {
  filterOverviewTemperatureDiagnostics,
  useOverviewTemperatureVisibility,
} from "./use-overview-temperature-visibility";

function PanelAction({ label, href }: { label: string; href: string }) {
  return (
    <Link
      href={href}
      className="inline-flex min-h-9 items-center gap-1 rounded-lg border border-white/10 bg-white/[0.03] px-3 py-1.5 text-xs font-medium text-slate-300 transition hover:border-cyan-300/30 hover:text-white focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cyan-400"
    >
      {label}
      <ChevronRight className="h-3 w-3" />
    </Link>
  );
}

export function DashboardShell() {
  const router = useRouter();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [temperatureVisibilityOpen, setTemperatureVisibilityOpen] = useState(false);
  const security = useDashboardSecurity();
  const securityReady = security.mode === "demo" || security.state === "ready";
  const organizationId = security.membership?.organizationId ?? null;
  const monitoring = useXjp60dSensorManagement({
    enabled: security.mode === "live" && securityReady,
    organizationId,
  });
  const temperatureVisibility = useOverviewTemperatureVisibility({
    enabled: security.mode === "live" && securityReady,
    organizationId,
    monitoredChannelIds: monitoring.monitoredChannelIds,
  });
  const telemetry = useDashboardTelemetry({
    enabled: securityReady,
    organizationId,
    temperatureChannelIds: security.mode === "live" ? temperatureVisibility.visibleChannelIds : null,
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

  const cameraInventory = readCameraInventory();
  const liveSamples = telemetry.view?.samples ?? [];
  const canCreateSession =
    security.mode === "demo" ||
    Boolean(
      security.session &&
      security.membership &&
      hasPermission(security.session, security.membership.organizationId, "sessions.manage"),
    );

  return (
    <div className="min-h-screen bg-[#07111f] text-slate-100">
      <Sidebar security={security} open={sidebarOpen} onClose={() => setSidebarOpen(false)} />
      <div className="min-h-screen lg:pl-[264px]">
        <Topbar
          showAlerts={security.mode === "demo" ? true : undefined}
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
        <main className="overview-shell relative overflow-hidden px-3 py-5 sm:px-5 lg:px-6 lg:py-6 2xl:px-8">
          <div
            className="pointer-events-none absolute -top-48 right-0 h-[480px] w-[650px] rounded-full bg-cyan-500/[0.045] blur-[110px]"
            aria-hidden="true"
          />
          <div
            className="pointer-events-none absolute top-72 -left-64 h-[420px] w-[420px] rounded-full bg-indigo-500/[0.04] blur-[110px]"
            aria-hidden="true"
          />
          <div className="relative mx-auto max-w-[1680px]">
            <header className="mb-5 flex flex-wrap items-end justify-between gap-4 border-b border-white/[0.07] pb-5">
              <div className="min-w-0">
                <p className="mb-2 flex items-center gap-2 text-[11px] font-semibold tracking-[0.16em] text-cyan-300/85 uppercase">
                  <span className="h-1.5 w-1.5 rounded-full bg-cyan-300" aria-hidden="true" />
                  NEXOLAB <span className="text-slate-600">/</span> Лабораторія
                </p>
                <h1 className="text-[1.7rem] leading-tight font-semibold tracking-[-0.045em] text-white sm:text-[2rem]">
                  Огляд лабораторії
                </h1>
                <p className="mt-1.5 text-[13px] leading-5 text-slate-400">
                  Показники, температури та події — в одному місці.
                </p>
              </div>
              <nav className="flex flex-wrap items-center gap-2" aria-label="Швидкі переходи">
                {canSeePlatformDestination(security, "/live") ? (
                  <Link
                    href="/live"
                    className="inline-flex min-h-10 items-center gap-2 rounded-xl border border-cyan-300/20 bg-cyan-400/[0.09] px-3.5 text-xs font-semibold text-cyan-100 transition hover:bg-cyan-400/[0.16] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cyan-400"
                  >
                    Live дані <ArrowUpRight className="h-3.5 w-3.5" aria-hidden="true" />
                  </Link>
                ) : null}
                {canSeePlatformDestination(security, "/sessions") ? (
                  <Link
                    href="/sessions"
                    className="inline-flex min-h-10 items-center gap-2 rounded-xl border border-white/10 bg-white/[0.035] px-3.5 text-xs font-semibold text-slate-200 transition hover:border-white/20 hover:bg-white/[0.06] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cyan-400"
                  >
                    Сесії <ChevronRight className="h-3.5 w-3.5" aria-hidden="true" />
                  </Link>
                ) : null}
              </nav>
            </header>

            <TelemetryStatusBar
              mode={telemetry.mode}
              status={telemetry.status}
              lastCapturedAt={telemetry.view?.lastCapturedAt ?? null}
              ageMs={telemetry.view?.ageMs ?? null}
              rejectedFutureSamples={telemetry.view?.rejectedFutureSamples ?? 0}
              error={telemetry.error}
              onRetry={telemetry.retry}
            />

            <section className="mt-5" aria-label="Ключові показники">
              <div className="mb-3 flex items-center justify-between px-0.5">
                <h2 className="text-xs font-semibold tracking-[0.08em] text-slate-300 uppercase">
                  Ключові показники
                </h2>
                <span className="text-[11px] text-slate-500">Поточний стан</span>
              </div>
              <div className="grid grid-cols-2 gap-2.5 md:grid-cols-3 xl:grid-cols-6 xl:gap-3">
                {telemetry.kpis.map((item) => (
                  <KpiCard key={item.label} item={item} variant="overview" />
                ))}
              </div>
            </section>

            <OverviewWorkspaceLayout
              primary={
                <Panel
                  title={telemetry.mode === "live" ? "Температура · XJP60D" : "Температури · demo preview"}
                  action={
                    telemetry.mode === "live" ? (
                      <button
                        type="button"
                        onClick={() => setTemperatureVisibilityOpen(true)}
                        disabled={monitoring.isLoading}
                        aria-label="Налаштувати датчики на графіку Огляду"
                        title="Налаштувати відображення на Огляді"
                        className="grid h-9 w-9 place-items-center rounded-lg border border-white/10 bg-white/[0.035] text-slate-300 transition hover:border-cyan-300/30 hover:text-cyan-200 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cyan-400 disabled:cursor-wait disabled:opacity-45"
                      >
                        <Settings2 className="h-3.5 w-3.5" />
                      </button>
                    ) : undefined
                  }
                  className="min-w-0"
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
                    targetDiagnostics={filterOverviewTemperatureDiagnostics(
                      monitoring.configuration?.target_diagnostics ?? [],
                      temperatureVisibility.visibleChannelIds,
                    )}
                    allMonitoredChannelsHidden={
                      temperatureVisibility.loaded &&
                      monitoring.monitoredChannelIds.length > 0 &&
                      temperatureVisibility.visibleChannelIds.length === 0
                    }
                  />
                </Panel>
              }
              attention={
                canSeePlatformDestination(security, "/alerts") ? (
                  <Panel
                    title={telemetry.mode === "live" ? "Потребує уваги" : "Тривоги · demo"}
                    action={
                      canSeePlatformDestination(security, "/alerts") ? (
                        <PanelAction label="Всі тривоги" href="/alerts" />
                      ) : null
                    }
                    className="min-w-0"
                  >
                    <AlarmsPanel
                      mode={telemetry.mode}
                      organizationId={organizationId}
                      samples={liveSamples}
                    />
                  </Panel>
                ) : null
              }
              supporting={
                canSeePlatformDestination(security, "/nodes") ? (
                  <Panel
                    title={telemetry.mode === "live" ? "Стан інфраструктури" : "Вузли системи · demo"}
                    action={
                      canSeePlatformDestination(security, "/nodes") ? (
                        <PanelAction label="Всі вузли" href="/nodes" />
                      ) : null
                    }
                    className="min-w-0"
                  >
                    {telemetry.mode === "live" ? (
                      <LiveInventoryPanel samples={liveSamples} status={telemetry.status} />
                    ) : (
                      <NodesPanel />
                    )}
                  </Panel>
                ) : null
              }
            />

            <OverviewSecondaryWorkspace
              cameraInventory={cameraInventory}
              showCameras={canSeePlatformDestination(security, "/cameras")}
              cameraAction={<PanelAction label="Всі камери" href="/cameras" />}
              sessions={
                <Panel
                  title="Лабораторні сесії"
                  action={
                    canSeePlatformDestination(security, "/sessions") ? (
                      <PanelAction label="Всі сесії" href="/sessions" />
                    ) : null
                  }
                >
                  <SessionsPanel organizationId={organizationId} />
                </Panel>
              }
              layouts={
                <Panel
                  title={security.mode === "demo" ? "Схема лабораторії · demo layout" : "Схеми обладнання"}
                  action={
                    canSeePlatformDestination(security, "/equipment-layouts") ? (
                      <PanelAction label="Всі схеми" href="/equipment-layouts" />
                    ) : null
                  }
                >
                  <LabMap mode={security.mode} enabled={securityReady} organizationId={organizationId} />
                </Panel>
              }
            />
          </div>
        </main>
      </div>

      <TemperatureVisibilityDialog
        key={`${organizationId ?? "unverified"}:${monitoring.configuration?.node_id ?? "unconfirmed"}`}
        organizationId={security.mode === "live" && securityReady ? organizationId : null}
        nodeId={monitoring.configuration?.node_id ?? null}
        open={temperatureVisibilityOpen}
        monitoredChannelIds={monitoring.monitoredChannelIds}
        visibleChannelIds={temperatureVisibility.visibleChannelIds}
        targetDiagnostics={monitoring.configuration?.target_diagnostics ?? []}
        monitoringError={monitoring.error}
        onApply={temperatureVisibility.setVisibleChannelIds}
        onClose={() => setTemperatureVisibilityOpen(false)}
      />
    </div>
  );
}
