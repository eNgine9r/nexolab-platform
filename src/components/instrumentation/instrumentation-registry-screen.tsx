"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { Gauge, RotateCcw } from "lucide-react";
import { useMemo, useState } from "react";

import { SecurityGate } from "@/components/dashboard/security-gate";
import { Sidebar } from "@/components/dashboard/sidebar";
import { Topbar } from "@/components/dashboard/topbar";
import { InstrumentationRegistryWorkspace } from "@/components/instrumentation/instrumentation-registry-workspace";
import { createRuntimeCredentialProvider } from "@/features/security/auth-runtime";
import {
  createAuthenticatedFetch,
} from "@/features/security/security-session";
import {
  HttpInstrumentationRegistryRepository,
} from "@/features/instrumentation/instrumentation-repository";
import { useDashboardSecurity } from "@/hooks/use-dashboard-security";
import { getTelemetryRuntimeConfig } from "@/lib/telemetry/runtime-config";

function RegistryGate({
  title,
  message,
  retry,
}: {
  title: string;
  message: string;
  retry?: () => void;
}) {
  return (
    <main className="grid min-h-screen place-items-center bg-[#06142a] p-4 text-slate-100">
      <section className="w-full max-w-lg rounded-3xl border border-cyan-400/15 bg-[#091a31]/95 p-6 shadow-2xl shadow-black/30">
        <div className="flex items-start gap-3">
          <div className="grid h-12 w-12 shrink-0 place-items-center rounded-2xl border border-cyan-300/20 bg-cyan-400/10">
            <Gauge className="h-6 w-6 text-cyan-300" />
          </div>
          <div>
            <p className="text-xs tracking-[0.2em] text-cyan-300 uppercase">
              NEXOLAB Instrumentation Registry
            </p>
            <h1 className="mt-1 text-xl font-semibold text-white">{title}</h1>
          </div>
        </div>
        <p className="mt-5 text-sm leading-6 text-slate-400">{message}</p>
        <div className="mt-6 flex flex-wrap gap-3">
          <Link
            href="/settings"
            className="inline-flex items-center gap-2 rounded-xl border border-white/10 px-4 py-2.5 text-sm text-slate-200 hover:border-cyan-300/30"
          >
            Повернутися до налаштувань
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

export function InstrumentationRegistryScreen() {
  const router = useRouter();
  const security = useDashboardSecurity();
  const [sidebarOpen, setSidebarOpen] = useState(false);

  const runtime = useMemo(() => {
    try {
      const config = getTelemetryRuntimeConfig();
      return config.mode === "live" ? config : null;
    } catch {
      return null;
    }
  }, []);

  const repository = useMemo(() => {
    if (!runtime?.apiBaseUrl || !security.membership) return null;
    const credentials = createRuntimeCredentialProvider(
      runtime.apiBaseUrl,
      security.membership.organizationId,
    );
    return new HttpInstrumentationRegistryRepository(
      runtime.apiBaseUrl,
      createAuthenticatedFetch(fetch.bind(globalThis), credentials),
    );
  }, [runtime, security.membership]);

  if (security.mode === "demo") {
    return (
      <RegistryGate
        title="Реєстр потребує перевіреної live session"
        message="Instrumentation Registry навмисно не підміняє Instrument, Signal або acceptance демонстраційними значеннями. Увімкніть LOCAL_LAN live mode і локальну операторську автентифікацію."
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

  if (!security.session || !security.membership) {
    return (
      <RegistryGate
        title="Організацію не вибрано"
        message="Для Instrumentation Registry потрібне активне membership із перевіреної backend session."
        retry={security.retry}
      />
    );
  }

  if (!repository) {
    return (
      <RegistryGate
        title="Local API недоступний"
        message="Не вдалося визначити локальний Telemetry Service для canonical Instrumentation Registry."
        retry={security.retry}
      />
    );
  }

  const canManage = security.membership.permissions.includes("equipment.manage");

  return (
    <div className="min-h-screen bg-[#06142a] text-slate-100">
      <Sidebar
        open={sidebarOpen}
        activeItem="Налаштування"
        onClose={() => setSidebarOpen(false)}
        onSelect={() => undefined}
      />
      <div className="min-h-screen lg:pl-[264px]">
        <Topbar
          title="Прилади та сигнали"
          onMenuOpen={() => setSidebarOpen(true)}
          showCreateSession={false}
          securitySession={security.session}
          selectedMembership={security.membership}
          onOrganizationChange={security.selectOrganization}
          onSignOut={() => {
            void security.signOut().then(() => router.replace("/login"));
          }}
        />
        <main className="relative overflow-hidden p-3 sm:p-4 xl:p-5 2xl:p-6">
          <div className="pointer-events-none absolute -top-40 -right-24 h-[420px] w-[420px] rounded-full bg-blue-500/[0.07] blur-3xl" />
          <div className="relative mx-auto max-w-[1900px]">
            <InstrumentationRegistryWorkspace repository={repository} canManage={canManage} />
          </div>
        </main>
      </div>
    </div>
  );
}
