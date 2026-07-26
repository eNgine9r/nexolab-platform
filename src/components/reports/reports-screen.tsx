"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { AlertTriangle, FileCheck2, LoaderCircle, LogIn, RotateCcw } from "lucide-react";

import { Sidebar } from "@/components/dashboard/sidebar";
import { Topbar } from "@/components/dashboard/topbar";
import { useDashboardSecurity } from "@/hooks/use-dashboard-security";

import { ReportsWorkspace } from "./reports-workspace";

function ReportsSecurityGate({
  state,
  error,
  onRetry,
}: {
  state: "loading" | "unauthenticated" | "forbidden" | "error" | "configuration";
  error: string | null;
  onRetry: () => void;
}) {
  const loading = state === "loading";
  const unauthenticated = state === "unauthenticated";
  const configuration = state === "configuration";

  return (
    <main className="grid min-h-screen place-items-center bg-[#06142a] p-4 text-slate-100">
      <section className="w-full max-w-lg rounded-3xl border border-cyan-400/15 bg-[#091a31]/95 p-6 shadow-2xl shadow-black/30">
        <div className="flex items-start gap-3">
          <div className="grid h-12 w-12 shrink-0 place-items-center rounded-2xl border border-cyan-300/20 bg-cyan-400/10">
            {loading ? (
              <LoaderCircle className="h-6 w-6 animate-spin text-cyan-300" />
            ) : configuration ? (
              <FileCheck2 className="h-6 w-6 text-cyan-300" />
            ) : (
              <AlertTriangle className="h-6 w-6 text-amber-300" />
            )}
          </div>
          <div>
            <p className="text-xs tracking-[0.2em] text-cyan-300 uppercase">NEXOLAB Reports Gate</p>
            <h1 className="mt-1 text-xl font-semibold text-white">
              {loading
                ? "Перевірка захищеної сесії"
                : unauthenticated
                  ? "Потрібен вхід до системи"
                  : configuration
                    ? "Reports доступні лише в live mode"
                    : "Доступ до звітів відхилено"}
            </h1>
          </div>
        </div>
        <p className="mt-5 text-sm leading-6 text-slate-400">
          {loading
            ? "Backend перевіряє JWT, членство в організації та reports.read до завантаження evidence metadata."
            : (error ?? "Поточна сесія не має доступу до звітів вибраної організації.")}
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
          {!loading && !configuration ? (
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

export function ReportsScreen() {
  const router = useRouter();
  const security = useDashboardSecurity();
  const [sidebarOpen, setSidebarOpen] = useState(false);

  if (security.mode === "demo") {
    return (
      <ReportsSecurityGate
        state="configuration"
        error="Встановіть NEXT_PUBLIC_NEXOLAB_DATA_MODE=live і production API URL. Demo reports навмисно відсутні."
        onRetry={() => undefined}
      />
    );
  }

  if (
    security.state === "loading" ||
    security.state === "unauthenticated" ||
    security.state === "forbidden" ||
    security.state === "error"
  ) {
    return <ReportsSecurityGate state={security.state} error={security.error} onRetry={security.retry} />;
  }

  return (
    <div className="min-h-screen bg-[#06142a] text-slate-100">
      <Sidebar
        open={sidebarOpen}
        activeItem="Звіти"
        onClose={() => setSidebarOpen(false)}
        onSelect={() => undefined}
      />
      <div className="min-h-screen lg:pl-[264px]">
        <Topbar
          title="Звіти"
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
          <div className="relative mx-auto max-w-[1800px]">
            <ReportsWorkspace key={security.membership?.organizationId ?? "reports"} />
          </div>
        </main>
      </div>
    </div>
  );
}
