"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { AlertTriangle, Gauge, LogIn, RotateCcw } from "lucide-react";

import { SecurityGate } from "@/components/dashboard/security-gate";
import { Sidebar } from "@/components/dashboard/sidebar";
import { Topbar } from "@/components/dashboard/topbar";
import { clearRetainedEnergyHistory } from "@/features/energy/energy-history-retention";
import { useEnergyConsumption } from "@/features/energy/use-energy-consumption";
import { useDashboardSecurity } from "@/hooks/use-dashboard-security";
import { useEnergyTelemetry } from "@/hooks/use-energy-telemetry";

import { EnergyWorkspace } from "./energy-workspace";

function EnergyModeGate({ title, message, retry }: { title: string; message: string; retry?: () => void }) {
  return (
    <main className="grid min-h-screen place-items-center bg-[#06142a] p-4 text-slate-100">
      <section className="w-full max-w-lg rounded-3xl border border-cyan-400/15 bg-[#091a31]/95 p-6 shadow-2xl shadow-black/30">
        <div className="flex items-start gap-3">
          <div className="grid h-12 w-12 shrink-0 place-items-center rounded-2xl border border-cyan-300/20 bg-cyan-400/10">
            <Gauge className="h-6 w-6 text-cyan-300" />
          </div>
          <div>
            <p className="text-xs tracking-[0.2em] text-cyan-300 uppercase">NEXOLAB Energy Gate</p>
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
              <RotateCcw className="h-4 w-4" />
              Повторити
            </button>
          ) : null}
        </div>
      </section>
    </main>
  );
}

export function EnergyScreen() {
  const router = useRouter();
  const security = useDashboardSecurity();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const securityReady = security.mode === "live" && security.state === "ready";
  const canReadTelemetry =
    securityReady && Boolean(security.membership?.permissions.includes("telemetry.read"));
  const organizationId = security.membership?.organizationId ?? null;
  const telemetry = useEnergyTelemetry({
    enabled: canReadTelemetry,
    organizationId,
    securityScopeId: security.session?.identity.id ?? null,
  });
  const consumption = useEnergyConsumption({
    enabled: canReadTelemetry,
    organizationId,
  });

  if (security.mode === "demo") {
    return (
      <EnergyModeGate
        title="Енергомоніторинг доступний лише в live mode"
        message="Сторінка навмисно не показує демонстраційні значення як реальні покази W1–W4. Налаштуйте локальний Telemetry Service і NEXT_PUBLIC_NEXOLAB_DATA_MODE=live."
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

  if (!security.membership?.permissions.includes("telemetry.read")) {
    return (
      <main className="grid min-h-screen place-items-center bg-[#06142a] p-4 text-slate-100">
        <section className="w-full max-w-lg rounded-3xl border border-red-300/15 bg-[#091a31]/95 p-6">
          <div className="flex items-start gap-3">
            <AlertTriangle className="mt-1 h-6 w-6 shrink-0 text-red-300" />
            <div>
              <p className="text-xs tracking-[0.2em] text-red-300 uppercase">Permission denied</p>
              <h1 className="mt-1 text-xl font-semibold text-white">Немає доступу до телеметрії</h1>
            </div>
          </div>
          <p className="mt-5 text-sm leading-6 text-slate-400">
            Поточне membership не містить permission `telemetry.read`. Енергетичні показники не
            завантажувалися.
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
              <LogIn className="h-4 w-4" />
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
        activeItem="Енергомоніторинг"
        onClose={() => setSidebarOpen(false)}
        onSelect={() => undefined}
      />
      <div className="min-h-screen lg:pl-[264px]">
        <Topbar
          title="Енергомоніторинг"
          onMenuOpen={() => setSidebarOpen(true)}
          showCreateSession={false}
          securitySession={security.session}
          selectedMembership={security.membership}
          onOrganizationChange={security.selectOrganization}
          onSignOut={() => {
            clearRetainedEnergyHistory();
            void security.signOut().then(() => router.replace("/login"));
          }}
        />
        <main className="relative overflow-hidden p-3 sm:p-4 xl:p-5 2xl:p-6">
          <div className="pointer-events-none absolute -top-40 -right-24 h-[420px] w-[420px] rounded-full bg-blue-500/[0.07] blur-3xl" />
          <div className="pointer-events-none absolute bottom-0 left-1/4 h-[300px] w-[300px] rounded-full bg-cyan-400/[0.035] blur-3xl" />
          <div className="relative mx-auto max-w-[1800px]">
            <EnergyWorkspace telemetry={telemetry} consumption={consumption} />
          </div>
        </main>
      </div>
    </div>
  );
}
