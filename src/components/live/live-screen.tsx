"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { Activity, AlertTriangle, BarChart3, LayoutDashboard, LogIn, RotateCcw } from "lucide-react";

import { SecurityGate } from "@/components/dashboard/security-gate";
import { Sidebar } from "@/components/dashboard/sidebar";
import { Topbar } from "@/components/dashboard/topbar";
import { LiveDashboardWorkspace } from "@/components/live-dashboards/live-dashboard-workspace";
import { LiveDataWorkspace } from "@/components/live/live-data-workspace";
import { useDashboardSecurity } from "@/hooks/use-dashboard-security";

type LiveWorkspaceMode = "dashboards" | "explorer";

function LiveModeGate({ title, message, retry }: { title: string; message: string; retry?: () => void }) {
  return (
    <main className="grid min-h-screen place-items-center bg-[#06142a] p-4 text-slate-100">
      <section className="w-full max-w-lg rounded-3xl border border-cyan-400/15 bg-[#091a31]/95 p-6 shadow-2xl shadow-black/30">
        <div className="flex items-start gap-3">
          <div className="grid h-12 w-12 shrink-0 place-items-center rounded-2xl border border-cyan-300/20 bg-cyan-400/10">
            <Activity className="h-6 w-6 text-cyan-300" aria-hidden="true" />
          </div>
          <div>
            <p className="text-xs tracking-[0.2em] text-cyan-300 uppercase">NEXOLAB Live Gate</p>
            <h1 className="mt-1 text-xl font-semibold text-white">{title}</h1>
          </div>
        </div>
        <p className="mt-5 text-sm leading-6 text-slate-400">{message}</p>
        <div className="mt-6 flex flex-wrap gap-3">
          <Link
            href="/"
            className="inline-flex items-center gap-2 rounded-xl border border-white/10 px-4 py-2.5 text-sm text-slate-200 hover:border-cyan-300/30"
          >
            Повернутися до огляду
          </Link>
          {retry ? (
            <button
              type="button"
              onClick={retry}
              className="inline-flex items-center gap-2 rounded-xl bg-blue-500 px-4 py-2.5 text-sm font-medium text-white hover:bg-blue-400"
            >
              <RotateCcw className="h-4 w-4" aria-hidden="true" />
              Повторити
            </button>
          ) : null}
        </div>
      </section>
    </main>
  );
}

function requestedWorkspace(value: string | null): LiveWorkspaceMode {
  return value === "explorer" ? "explorer" : "dashboards";
}

export function LiveScreen() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const security = useDashboardSecurity();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [workspace, setWorkspace] = useState<LiveWorkspaceMode>(() =>
    requestedWorkspace(searchParams.get("workspace")),
  );
  const securityReady = security.mode === "live" && security.state === "ready";
  const canReadTelemetry =
    securityReady && Boolean(security.membership?.permissions.includes("telemetry.read"));
  const canReadDashboards =
    canReadTelemetry && Boolean(security.membership?.permissions.includes("dashboard.read"));
  const canManage =
    securityReady && Boolean(security.membership?.permissions.includes("live_dashboards.manage"));
  const effectiveWorkspace: LiveWorkspaceMode =
    workspace === "dashboards" && !canReadDashboards && canReadTelemetry ? "explorer" : workspace;

  const switchWorkspace = (next: LiveWorkspaceMode) => {
    setWorkspace(next);
    const params = new URLSearchParams(searchParams.toString());
    params.set("workspace", next);
    router.replace(`/live?${params.toString()}`, { scroll: false });
  };

  if (security.mode === "demo") {
    return (
      <LiveModeGate
        title="Live workspace доступний лише в live mode"
        message="Сторінка навмисно не підміняє локальні dashboard definitions або телеметрію демонстраційними даними. Налаштуйте Telemetry Service і NEXT_PUBLIC_NEXOLAB_DATA_MODE=live."
      />
    );
  }

  if (
    security.state === "loading" ||
    security.state === "unauthenticated" ||
    security.state === "forbidden" ||
    security.state === "error"
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

  if (!canReadTelemetry || !security.membership) {
    return (
      <main className="grid min-h-screen place-items-center bg-[#06142a] p-4 text-slate-100">
        <section className="w-full max-w-lg rounded-3xl border border-red-300/15 bg-[#091a31]/95 p-6">
          <div className="flex items-start gap-3">
            <AlertTriangle className="mt-1 h-6 w-6 shrink-0 text-red-300" aria-hidden="true" />
            <div>
              <p className="text-xs tracking-[0.2em] text-red-300 uppercase">Permission denied</p>
              <h1 className="mt-1 text-xl font-semibold text-white">Немає доступу до Live Data</h1>
            </div>
          </div>
          <p className="mt-5 text-sm leading-6 text-slate-400">
            Потрібен permission `telemetry.read`. REST telemetry та WebSocket subscriptions не виконувалися.
            Для Saved Dashboards додатково потрібен `dashboard.read`.
          </p>
          <div className="mt-6 flex flex-wrap gap-3">
            <Link
              href="/"
              className="inline-flex items-center gap-2 rounded-xl border border-white/10 px-4 py-2.5 text-sm text-slate-200 hover:border-cyan-300/30"
            >
              До огляду
            </Link>
            <Link
              href="/login"
              className="inline-flex items-center gap-2 rounded-xl bg-blue-500 px-4 py-2.5 text-sm font-medium text-white hover:bg-blue-400"
            >
              <LogIn className="h-4 w-4" aria-hidden="true" />
              Змінити користувача
            </Link>
          </div>
        </section>
      </main>
    );
  }

  return (
    <div className="min-h-screen bg-[#06142a] text-slate-100">
      <Sidebar
        open={sidebarOpen}
        activeItem="Live дані"
        onClose={() => setSidebarOpen(false)}
        onSelect={() => undefined}
      />
      <div className="min-h-screen lg:pl-[264px]">
        <Topbar
          title={effectiveWorkspace === "explorer" ? "Live Data" : "Live Dashboards"}
          onMenuOpen={() => setSidebarOpen(true)}
          showCreateSession={false}
          securitySession={security.session}
          selectedMembership={security.membership}
          onOrganizationChange={security.selectOrganization}
          onSignOut={() => {
            void security.signOut().then(() => router.replace("/login"));
          }}
        />
        <main className="relative min-w-0 overflow-hidden p-3 sm:p-4 xl:p-5 2xl:p-6">
          <div className="pointer-events-none absolute -top-40 -right-24 h-[420px] w-[420px] rounded-full bg-blue-500/[0.07] blur-3xl" />
          <div className="pointer-events-none absolute bottom-0 left-1/4 h-[300px] w-[300px] rounded-full bg-cyan-400/[0.035] blur-3xl" />
          <div className="relative mx-auto max-w-[1800px] min-w-0">
            <nav
              className="mb-4 flex max-w-full flex-wrap gap-2 rounded-2xl border border-white/[0.08] bg-[#091a31]/90 p-2"
              aria-label="Live workspace"
            >
              <button
                type="button"
                aria-current={effectiveWorkspace === "explorer" ? "page" : undefined}
                onClick={() => switchWorkspace("explorer")}
                className={`inline-flex min-h-11 items-center gap-2 rounded-xl px-4 text-sm font-medium transition outline-none focus-visible:ring-2 focus-visible:ring-cyan-300 ${effectiveWorkspace === "explorer" ? "bg-cyan-400/12 text-cyan-100" : "text-slate-400 hover:bg-white/[0.04] hover:text-white"}`}
              >
                <BarChart3 className="h-4 w-4" aria-hidden="true" />
                Live Data
              </button>
              {canReadDashboards ? (
                <button
                  type="button"
                  aria-current={effectiveWorkspace === "dashboards" ? "page" : undefined}
                  onClick={() => switchWorkspace("dashboards")}
                  className={`inline-flex min-h-11 items-center gap-2 rounded-xl px-4 text-sm font-medium transition outline-none focus-visible:ring-2 focus-visible:ring-cyan-300 ${effectiveWorkspace === "dashboards" ? "bg-cyan-400/12 text-cyan-100" : "text-slate-400 hover:bg-white/[0.04] hover:text-white"}`}
                >
                  <LayoutDashboard className="h-4 w-4" aria-hidden="true" />
                  Saved Dashboards
                </button>
              ) : null}
            </nav>

            {effectiveWorkspace === "explorer" ? (
              <LiveDataWorkspace organizationId={security.membership.organizationId} />
            ) : canReadDashboards ? (
              <LiveDashboardWorkspace
                organizationId={security.membership.organizationId}
                canManage={canManage}
              />
            ) : null}
          </div>
        </main>
      </div>
    </div>
  );
}
