from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


write(
    "src/hooks/use-dashboard-security.ts",
    '''"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import {
  createAuthenticatedFetch,
  getSecurityCredentials,
  HttpSecuritySessionClient,
  setSecurityCredentials,
  type SecurityMembership,
  type SecuritySession,
} from "@/features/security/security-session";
import {
  createSupabaseCredentialProvider,
  signOut as signOutSupabase,
} from "@/features/security/supabase-auth";
import { getTelemetryRuntimeConfig } from "@/lib/telemetry/runtime-config";

const STORAGE_KEY = "nexolab.selectedOrganizationId";

export type DashboardSecurityState =
  | "demo"
  | "loading"
  | "ready"
  | "unauthenticated"
  | "forbidden"
  | "error";

export type DashboardSecurityModel = {
  mode: "demo" | "live";
  state: DashboardSecurityState;
  session: SecuritySession | null;
  membership: SecurityMembership | null;
  error: string | null;
  selectOrganization: (organizationId: string) => void;
  retry: () => void;
  signOut: () => Promise<void>;
};

type Runtime =
  | { mode: "demo"; apiBaseUrl: null; configuredOrganizationId: null; error: null }
  | {
      mode: "live";
      apiBaseUrl: string | null;
      configuredOrganizationId: string | null;
      error: string | null;
    };

function loadRuntime(): Runtime {
  try {
    const config = getTelemetryRuntimeConfig();
    if (config.mode === "demo") {
      return { mode: "demo", apiBaseUrl: null, configuredOrganizationId: null, error: null };
    }
    return {
      mode: "live",
      apiBaseUrl: config.apiBaseUrl,
      configuredOrganizationId: process.env.NEXT_PUBLIC_NEXOLAB_ORGANIZATION_ID?.trim() || null,
      error: config.apiBaseUrl ? null : "NEXOLAB API URL is required for authenticated dashboard mode.",
    };
  } catch (error) {
    return {
      mode: "live",
      apiBaseUrl: null,
      configuredOrganizationId: null,
      error: error instanceof Error ? error.message : "Invalid dashboard security configuration.",
    };
  }
}

function storedOrganizationId(): string | null {
  try {
    return window.localStorage.getItem(STORAGE_KEY)?.trim() || null;
  } catch {
    return null;
  }
}

function persistOrganizationId(organizationId: string): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, organizationId);
  } catch {
    // Storage is an optimization only; authorization remains server-side.
  }
}

function chooseMembership(
  session: SecuritySession,
  configuredOrganizationId: string | null,
): SecurityMembership | null {
  const candidates = [
    storedOrganizationId(),
    getSecurityCredentials().organizationId,
    configuredOrganizationId,
  ];
  for (const organizationId of candidates) {
    if (!organizationId) continue;
    const membership = session.memberships.find((item) => item.organizationId === organizationId);
    if (membership) return membership;
  }
  return session.memberships[0] ?? null;
}

export function useDashboardSecurity(): DashboardSecurityModel {
  const [runtime] = useState<Runtime>(loadRuntime);
  const [state, setState] = useState<DashboardSecurityState>(
    runtime.mode === "demo" ? "demo" : "loading",
  );
  const [session, setSession] = useState<SecuritySession | null>(null);
  const [membership, setMembership] = useState<SecurityMembership | null>(null);
  const [error, setError] = useState<string | null>(runtime.error);
  const [generation, setGeneration] = useState(0);

  const retry = useCallback(() => {
    if (runtime.mode === "demo") return;
    setState("loading");
    setError(null);
    setGeneration((value) => value + 1);
  }, [runtime.mode]);

  useEffect(() => {
    if (runtime.mode === "demo") return;
    if (!runtime.apiBaseUrl) {
      setState("error");
      setError(runtime.error ?? "Authenticated dashboard API is unavailable.");
      return;
    }

    let cancelled = false;
    const credentialProvider = createSupabaseCredentialProvider(runtime.configuredOrganizationId);
    const authenticatedFetch = createAuthenticatedFetch(fetch.bind(globalThis), credentialProvider);
    const client = new HttpSecuritySessionClient({
      apiBaseUrl: runtime.apiBaseUrl,
      fetchImpl: authenticatedFetch,
    });

    void client.getSession().then(async (result) => {
      if (cancelled) return;
      if (!result.ok) {
        setSession(null);
        setMembership(null);
        setError(result.error.message);
        setState(
          result.error.code === "AUTHENTICATION_REQUIRED"
            ? "unauthenticated"
            : result.error.code === "ACCESS_DENIED"
              ? "forbidden"
              : "error",
        );
        return;
      }

      const selected = chooseMembership(result.value, runtime.configuredOrganizationId);
      if (!selected) {
        setSession(result.value);
        setMembership(null);
        setError("Користувач не має активного членства в жодній організації NEXOLAB.");
        setState("forbidden");
        return;
      }

      const credentials = await credentialProvider();
      if (cancelled) return;
      setSecurityCredentials({
        accessToken: credentials.accessToken,
        organizationId: selected.organizationId,
      });
      persistOrganizationId(selected.organizationId);
      setSession(result.value);
      setMembership(selected);
      setError(null);
      setState("ready");
    });

    return () => {
      cancelled = true;
    };
  }, [generation, runtime]);

  const selectOrganization = useCallback(
    (organizationId: string) => {
      if (!session) return;
      const selected = session.memberships.find((item) => item.organizationId === organizationId);
      if (!selected) {
        setError("Вибрана організація відсутня у перевіреній сесії користувача.");
        setState("forbidden");
        return;
      }
      const credentials = getSecurityCredentials();
      setSecurityCredentials({
        accessToken: credentials.accessToken,
        organizationId: selected.organizationId,
      });
      persistOrganizationId(selected.organizationId);
      setMembership(selected);
      setError(null);
      setState("ready");
    },
    [session],
  );

  const signOut = useCallback(async () => {
    await signOutSupabase();
    setSecurityCredentials({ accessToken: null, organizationId: null });
    setSession(null);
    setMembership(null);
    setError(null);
    setState(runtime.mode === "demo" ? "demo" : "unauthenticated");
  }, [runtime.mode]);

  return useMemo(
    () => ({
      mode: runtime.mode,
      state,
      session,
      membership,
      error,
      selectOrganization,
      retry,
      signOut,
    }),
    [error, membership, retry, runtime.mode, selectOrganization, session, signOut, state],
  );
}
''',
)

write(
    "src/components/dashboard/topbar.tsx",
    '''import Link from "next/link";
import {
  Bell,
  CalendarDays,
  ChevronDown,
  LogOut,
  Menu,
  Plus,
  Search,
} from "lucide-react";

import type {
  SecurityMembership,
  SecuritySession,
} from "@/features/security/security-session";

interface TopbarProps {
  title: string;
  onMenuOpen: () => void;
  onCreateSession?: () => void;
  createSessionHref?: string;
  showCreateSession?: boolean;
  securitySession?: SecuritySession | null;
  selectedMembership?: SecurityMembership | null;
  onOrganizationChange?: (organizationId: string) => void;
  onSignOut?: () => void;
}

function initials(label: string): string {
  const parts = label
    .trim()
    .split(/\s+/)
    .filter(Boolean);
  if (parts.length === 0) return "NX";
  return parts
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? "")
    .join("");
}

export function Topbar({
  title,
  onMenuOpen,
  onCreateSession,
  createSessionHref = "/sessions/new",
  showCreateSession = true,
  securitySession = null,
  selectedMembership = null,
  onOrganizationChange,
  onSignOut,
}: TopbarProps) {
  const createClasses =
    "ml-1 inline-flex h-10 items-center gap-2 rounded-xl bg-blue-600 px-3.5 text-[11px] font-semibold text-white shadow-[0_8px_28px_rgba(0,119,255,.22)] transition hover:bg-blue-500 sm:px-4";
  const createContent = (
    <>
      <Plus className="h-4 w-4" />
      <span className="hidden sm:inline">Нова сесія</span>
    </>
  );
  const identityLabel =
    securitySession?.identity.displayName ??
    securitySession?.identity.email ??
    securitySession?.identity.subject ??
    "Інженер";
  const roleLabel = selectedMembership?.roles.join(", ") ?? "Administrator";

  return (
    <header className="sticky top-0 z-30 flex min-h-[78px] items-center gap-3 border-b border-white/[0.055] bg-[#07172e]/90 px-4 backdrop-blur-xl sm:px-5 xl:px-6">
      <button className="icon-button inline-grid lg:hidden" onClick={onMenuOpen} aria-label="Відкрити меню">
        <Menu className="h-5 w-5" />
      </button>
      <div className="min-w-0 lg:hidden">
        <p className="truncate text-sm font-semibold text-white">{title}</p>
        <p className="truncate text-[10px] text-slate-500">
          {selectedMembership?.organizationName ?? "Лабораторія 1"}
        </p>
      </div>

      <label className="relative hidden max-w-[390px] min-w-0 flex-1 lg:block">
        <Search className="pointer-events-none absolute top-1/2 left-4 h-4 w-4 -translate-y-1/2 text-slate-500" />
        <input
          type="search"
          placeholder="Пошук пристроїв, сесій, датчиків…"
          className="h-10 w-full rounded-xl border border-white/[0.07] bg-white/[0.025] pr-14 pl-11 text-[12px] text-slate-100 transition outline-none placeholder:text-slate-600 focus:border-blue-400/45 focus:bg-blue-500/[0.035]"
        />
        <span className="absolute top-1/2 right-3 -translate-y-1/2 rounded-md border border-white/[0.06] bg-white/[0.035] px-1.5 py-0.5 text-[9px] text-slate-600">
          ⌘ K
        </span>
      </label>

      <div className="ml-auto flex items-center gap-2">
        <button className="topbar-control hidden sm:flex">
          <CalendarDays className="h-4 w-4 text-slate-500" />
          <span>24 липня 2026</span>
          <ChevronDown className="h-3.5 w-3.5 text-slate-600" />
        </button>
        {securitySession && selectedMembership && onOrganizationChange ? (
          <label className="topbar-control hidden md:flex">
            <span className="sr-only">Організація</span>
            <select
              value={selectedMembership.organizationId}
              onChange={(event) => onOrganizationChange(event.target.value)}
              className="max-w-48 bg-transparent text-[10px] text-slate-300 outline-none"
            >
              {securitySession.memberships.map((membership) => (
                <option
                  key={membership.organizationId}
                  value={membership.organizationId}
                  className="bg-[#07172e] text-slate-100"
                >
                  {membership.organizationName}
                </option>
              ))}
            </select>
            <ChevronDown className="h-3.5 w-3.5 text-slate-600" />
          </label>
        ) : (
          <button className="topbar-control hidden md:flex">
            <span>Лабораторія 1</span>
            <ChevronDown className="h-3.5 w-3.5 text-slate-600" />
          </button>
        )}
        <button className="icon-button relative inline-grid" aria-label="Сповіщення">
          <Bell className="h-[18px] w-[18px]" />
          <span className="absolute -top-1 -right-1 grid h-4 min-w-4 place-items-center rounded-full bg-red-500 px-1 text-[8px] font-semibold text-white">
            12
          </span>
        </button>
        {showCreateSession ? (
          onCreateSession ? (
            <button onClick={onCreateSession} className={createClasses}>
              {createContent}
            </button>
          ) : (
            <Link href={createSessionHref} className={createClasses}>
              {createContent}
            </Link>
          )
        ) : null}
        <div className="ml-1 hidden items-center gap-2 rounded-xl p-1.5 xl:flex">
          <span className="grid h-8 w-8 place-items-center rounded-full border border-blue-400/45 bg-blue-500/10 text-[11px] font-semibold text-cyan-200">
            {initials(identityLabel)}
          </span>
          <span className="max-w-36 text-left">
            <span className="block truncate text-[10px] font-medium text-slate-100">{identityLabel}</span>
            <span className="block truncate text-[8px] text-slate-600">{roleLabel}</span>
          </span>
          {onSignOut ? (
            <button
              type="button"
              onClick={onSignOut}
              className="icon-button ml-1 inline-grid h-8 w-8"
              aria-label="Вийти з NEXOLAB"
            >
              <LogOut className="h-3.5 w-3.5" />
            </button>
          ) : (
            <ChevronDown className="h-3.5 w-3.5 text-slate-600" />
          )}
        </div>
      </div>
    </header>
  );
}
''',
)

path = "src/hooks/use-dashboard-telemetry.ts"
content = read(path)
content = content.replace(
    "export interface DashboardTelemetryModel {\n",
    "export interface DashboardTelemetryOptions {\n  enabled?: boolean;\n  organizationId?: string | null;\n}\n\nexport interface DashboardTelemetryModel {\n",
    1,
)
content = content.replace(
    "export function useDashboardTelemetry(): DashboardTelemetryModel {\n  const [runtime] = useState<RuntimeConfigResult>(loadRuntimeConfig);\n",
    "export function useDashboardTelemetry(\n  options: DashboardTelemetryOptions = {},\n): DashboardTelemetryModel {\n  const enabled = options.enabled ?? true;\n  const selectedOrganizationId = options.organizationId?.trim() || null;\n  const [runtime] = useState<RuntimeConfigResult>(loadRuntimeConfig);\n",
    1,
)
content = content.replace(
    "    if (!config || config.mode === \"demo\") {\n      return;\n    }\n\n    const controller = new AbortController();\n    const organizationId = process.env.NEXT_PUBLIC_NEXOLAB_ORGANIZATION_ID?.trim() || null;\n",
    "    if (!config || config.mode === \"demo\") {\n      return;\n    }\n    if (!enabled) {\n      setConnectionState(\"disconnected\");\n      setHasLoadedSnapshot(false);\n      setStore(createDashboardTelemetryStore());\n      return;\n    }\n\n    setConnectionState(\"connecting\");\n    setHasLoadedSnapshot(false);\n    setStore(createDashboardTelemetryStore());\n    const controller = new AbortController();\n    const organizationId =\n      selectedOrganizationId ?? process.env.NEXT_PUBLIC_NEXOLAB_ORGANIZATION_ID?.trim() ?? null;\n",
    1,
)
content = content.replace(
    "  }, [generation, runtime.config]);\n",
    "  }, [enabled, generation, runtime.config, selectedOrganizationId]);\n",
    1,
)
write(path, content)

write(
    "src/components/dashboard/dashboard-shell.tsx",
    '''"use client";

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
            : error ?? "Поточна сесія не має доступу до вибраної організації."}
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
''',
)

write(
    "src/hooks/use-dashboard-security.test.ts",
    '''import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  getSecurityCredentials,
  setSecurityCredentials,
} from "@/features/security/security-session";

const authState = vi.hoisted(() => ({
  signOut: vi.fn(),
  credentials: vi.fn(),
}));

vi.mock("@/lib/telemetry/runtime-config", () => ({
  getTelemetryRuntimeConfig: () => ({
    mode: "live",
    apiBaseUrl: "https://api.example.test",
    websocketUrl: "wss://api.example.test/api/v1/telemetry/live",
  }),
}));

vi.mock("@/features/security/supabase-auth", () => ({
  createSupabaseCredentialProvider: () => authState.credentials,
  signOut: authState.signOut,
}));

import { useDashboardSecurity } from "./use-dashboard-security";

const sessionPayload = {
  authenticated: true,
  identity: {
    id: "identity-1",
    provider: "test-oidc",
    subject: "engineer-user",
    email: "engineer@example.test",
    display_name: "Engineer User",
  },
  memberships: [
    {
      organization_id: "org-1",
      organization_slug: "lab-one",
      organization_name: "Laboratory One",
      roles: ["engineer"],
      permissions: ["dashboard.read", "telemetry.read", "sessions.manage"],
    },
    {
      organization_id: "org-2",
      organization_slug: "lab-two",
      organization_name: "Laboratory Two",
      roles: ["viewer"],
      permissions: ["dashboard.read", "telemetry.read"],
    },
  ],
};

describe("useDashboardSecurity", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();
    setSecurityCredentials({ accessToken: null, organizationId: null });
    authState.credentials.mockResolvedValue({
      accessToken: "access-token",
      organizationId: null,
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(JSON.stringify(sessionPayload), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("loads the verified session and switches only between returned memberships", async () => {
    window.localStorage.setItem("nexolab.selectedOrganizationId", "org-2");
    const { result } = renderHook(() => useDashboardSecurity());

    await waitFor(() => {
      expect(result.current.state).toBe("ready");
    });
    expect(result.current.membership?.organizationId).toBe("org-2");
    expect(getSecurityCredentials()).toEqual({
      accessToken: "access-token",
      organizationId: "org-2",
    });

    act(() => {
      result.current.selectOrganization("org-1");
    });
    expect(result.current.membership?.organizationId).toBe("org-1");
    expect(getSecurityCredentials().organizationId).toBe("org-1");

    act(() => {
      result.current.selectOrganization("foreign-org");
    });
    expect(result.current.state).toBe("forbidden");
    expect(result.current.error).toContain("відсутня");
  });

  it("clears credentials on logout", async () => {
    const { result } = renderHook(() => useDashboardSecurity());
    await waitFor(() => expect(result.current.state).toBe("ready"));

    await act(async () => {
      await result.current.signOut();
    });

    expect(authState.signOut).toHaveBeenCalledOnce();
    expect(result.current.state).toBe("unauthenticated");
    expect(getSecurityCredentials()).toEqual({
      accessToken: null,
      organizationId: null,
    });
  });
});
''',
)
