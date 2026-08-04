"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState, useSyncExternalStore } from "react";
import { RotateCcw, Settings2 } from "lucide-react";

import { SecurityGate } from "@/components/dashboard/security-gate";
import { Sidebar } from "@/components/dashboard/sidebar";
import { Topbar } from "@/components/dashboard/topbar";
import { SettingsWorkspace } from "@/components/settings/settings-workspace";
import {
  buildSettingsRuntimeDiagnostics,
  readSettingsRuntimeInput,
} from "@/features/settings/runtime-diagnostics";
import { useDashboardSecurity } from "@/hooks/use-dashboard-security";
import { useSettingsPreferences } from "@/hooks/use-settings-preferences";

function subscribeBrowserOrigin(): () => void {
  return () => undefined;
}

function readBrowserOrigin(): string {
  return window.location.origin;
}

function readServerBrowserOrigin(): null {
  return null;
}

function SettingsModeGate({ title, message, retry }: { title: string; message: string; retry?: () => void }) {
  return (
    <main className="grid min-h-screen place-items-center bg-[#06142a] p-4 text-slate-100">
      <section className="w-full max-w-lg rounded-3xl border border-cyan-400/15 bg-[#091a31]/95 p-6 shadow-2xl shadow-black/30">
        <div className="flex items-start gap-3">
          <div className="grid h-12 w-12 shrink-0 place-items-center rounded-2xl border border-cyan-300/20 bg-cyan-400/10">
            <Settings2 className="h-6 w-6 text-cyan-300" />
          </div>
          <div>
            <p className="text-xs tracking-[0.2em] text-cyan-300 uppercase">NEXOLAB Settings Gate</p>
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

export function SettingsScreen() {
  const router = useRouter();
  const security = useDashboardSecurity();
  const localPreferences = useSettingsPreferences();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const browserOrigin = useSyncExternalStore(
    subscribeBrowserOrigin,
    readBrowserOrigin,
    readServerBrowserOrigin,
  );

  const diagnostics = useMemo(
    () => buildSettingsRuntimeDiagnostics(readSettingsRuntimeInput(browserOrigin)),
    [browserOrigin],
  );

  if (security.mode === "demo") {
    return (
      <SettingsModeGate
        title="Налаштування потребують перевіреної live session"
        message="Сторінка навмисно не підміняє identity, organization або runtime configuration демонстраційними значеннями. Увімкніть live mode і локальну операторську автентифікацію."
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
      <SettingsModeGate
        title="Організацію не вибрано"
        message="Для Settings workspace потрібне активне membership із перевіреної backend session. Жодні configuration mutations не виконувалися."
        retry={security.retry}
      />
    );
  }

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
          title="Налаштування"
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
          <div className="pointer-events-none absolute bottom-0 left-1/4 h-[300px] w-[300px] rounded-full bg-cyan-400/[0.035] blur-3xl" />
          <div className="relative mx-auto max-w-[1900px]">
            <SettingsWorkspace
              session={security.session}
              membership={security.membership}
              diagnostics={diagnostics}
              preferences={localPreferences.preferences}
              preferencesLoaded={localPreferences.loaded}
              preferencesRecovered={localPreferences.recovered}
              preferenceRecoveryReason={localPreferences.recoveryReason}
              onPreferenceChange={localPreferences.updatePreference}
              onPreferencesReset={localPreferences.reset}
            />
          </div>
        </main>
      </div>
    </div>
  );
}
