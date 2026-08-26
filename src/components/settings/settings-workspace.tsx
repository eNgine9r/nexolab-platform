"use client";

import Link from "next/link";
import { useState, type ReactNode } from "react";
import {
  Activity,
  AlertTriangle,
  CheckCircle2,
  ChevronRight,
  CircleUserRound,
  DatabaseZap,
  Eye,
  Gauge,
  KeyRound,
  MonitorCog,
  PackageCheck,
  Palette,
  RefreshCcw,
  Settings2,
  ShieldCheck,
  SlidersHorizontal,
  TriangleAlert,
  UsersRound,
} from "lucide-react";

import type {
  SecurityMembership,
  SecurityPermission,
  SecuritySession,
} from "@/features/security/security-session";
import type { SettingsPreferences } from "@/features/settings/preferences";
import type {
  SanitizedSettingsEndpoint,
  SettingsConfigurationState,
  SettingsRuntimeDiagnostics,
} from "@/features/settings/runtime-diagnostics";

type EditablePreference = keyof Omit<SettingsPreferences, "schemaVersion">;
type SettingsSectionId = "general" | "appearance" | "data-collection" | "monitoring" | "system";

type SettingsWorkspaceProps = {
  session: SecuritySession;
  membership: SecurityMembership;
  diagnostics: SettingsRuntimeDiagnostics;
  preferences: SettingsPreferences;
  preferencesLoaded: boolean;
  preferencesRecovered: boolean;
  preferenceRecoveryReason: string | null;
  onPreferenceChange: (key: EditablePreference, value: SettingsPreferences[EditablePreference]) => void;
  onPreferencesReset: () => void;
  acquisitionCadenceContent?: ReactNode;
  canManageSensorMonitoring?: boolean;
  sensorMonitoringReady?: boolean;
  sensorMonitoringError?: string | null;
  sensorMonitoringLoading?: boolean;
  onRetrySensorMonitoring?: () => void;
  onOpenSensorMonitoring?: () => void;
};

type SectionItem = {
  id: SettingsSectionId;
  title: string;
  description: string;
  icon: typeof Settings2;
};

type PermissionGroup = {
  title: string;
  description: string;
  permissions: readonly SecurityPermission[];
};

const coreSections: readonly SectionItem[] = [
  {
    id: "general",
    title: "Загальні",
    description: "Оператор, організація та основні параметри.",
    icon: Settings2,
  },
  {
    id: "appearance",
    title: "Вигляд",
    description: "Щільність інтерфейсу та анімація.",
    icon: Palette,
  },
  {
    id: "data-collection",
    title: "Збір даних",
    description: "Фізичний інтервал read-only опитування.",
    icon: SlidersHorizontal,
  },
  {
    id: "system",
    title: "Система",
    description: "LOCAL_LAN runtime, діагностика та safety boundary.",
    icon: MonitorCog,
  },
];

const monitoringSection: SectionItem = {
  id: "monitoring",
  title: "Моніторинг",
  description: "Канали XJP60D для постійного read-only збору.",
  icon: Eye,
};

const permissionGroups: readonly PermissionGroup[] = [
  {
    title: "Моніторинг",
    description: "Перегляд dashboard, телеметрії, вузлів і тривог.",
    permissions: ["dashboard.read", "telemetry.read", "nodes.read", "alerts.read"],
  },
  {
    title: "Звіти й аудит",
    description: "Перегляд, формування та погодження доказів.",
    permissions: ["reports.read", "audit.read", "reports.generate", "reports.approve"],
  },
  {
    title: "Операційні дії",
    description: "Керовані дії в канонічних робочих процесах.",
    permissions: [
      "live_dashboards.manage",
      "sessions.manage",
      "sessions.operate",
      "alerts.rules.manage",
      "alerts.acknowledge",
      "equipment.manage",
      "nodes.manage",
      "layout.draft.edit",
      "layout.publish",
      "layout.restore",
      "memberships.manage",
      "project_versions.manage",
    ],
  },
];

const roleLabels: Record<string, string> = {
  administrator: "Адміністратор",
  laboratory_manager: "Керівник лабораторії",
  engineer: "Інженер",
  laboratory_technician: "Технік-лаборант",
  operator: "Оператор",
  viewer: "Спостерігач",
  auditor: "Аудитор",
};

const permissionLabels: Record<SecurityPermission, string> = {
  "dashboard.read": "Огляд dashboard",
  "live_dashboards.manage": "Керування Live Dashboard",
  "telemetry.read": "Перегляд телеметрії",
  "alerts.read": "Перегляд тривог",
  "audit.read": "Перегляд аудиту",
  "reports.read": "Перегляд звітів",
  "nodes.read": "Перегляд вузлів",
  "reports.generate": "Формування звітів",
  "reports.approve": "Погодження звітів",
  "memberships.manage": "Керування користувачами",
  "project_versions.manage": "Керування версіями NEXOLAB",
  "equipment.manage": "Керування обладнанням",
  "nodes.manage": "Керування вузлами",
  "layout.draft.edit": "Редагування чернеток схем",
  "layout.publish": "Публікація схем",
  "layout.restore": "Відновлення схем",
  "sessions.manage": "Керування сесіями",
  "sessions.operate": "Операції тестових сесій",
  "alerts.rules.manage": "Керування правилами тривог",
  "alerts.acknowledge": "Підтвердження тривог",
};

const statusCopy: Record<
  SettingsConfigurationState,
  { title: string; description: string; icon: typeof CheckCircle2; className: string }
> = {
  ready: {
    title: "Конфігурація готова",
    description: "LOCAL_LAN runtime contract узгоджений і готовий до роботи.",
    icon: CheckCircle2,
    className: "border-emerald-400/20 bg-emerald-400/[0.08] text-emerald-200",
  },
  incomplete: {
    title: "Конфігурація неповна",
    description: "Для повноцінної роботи потрібно усунути наведені configuration gaps.",
    icon: AlertTriangle,
    className: "border-amber-400/20 bg-amber-400/[0.08] text-amber-200",
  },
  unsafe: {
    title: "Небезпечна конфігурація",
    description: "Виявлено transport або public-configuration risk, який не можна приховувати.",
    icon: TriangleAlert,
    className: "border-rose-400/20 bg-rose-400/[0.08] text-rose-200",
  },
};

export function SettingsWorkspace({
  session,
  membership,
  diagnostics,
  preferences,
  preferencesLoaded,
  preferencesRecovered,
  preferenceRecoveryReason,
  onPreferenceChange,
  onPreferencesReset,
  acquisitionCadenceContent = null,
  canManageSensorMonitoring = false,
  sensorMonitoringReady = false,
  sensorMonitoringError = null,
  sensorMonitoringLoading = false,
  onRetrySensorMonitoring = () => undefined,
  onOpenSensorMonitoring = () => undefined,
}: SettingsWorkspaceProps) {
  const [activeSection, setActiveSection] = useState<SettingsSectionId>("general");
  const sections = canManageSensorMonitoring
    ? [...coreSections.slice(0, 3), monitoringSection, coreSections[3]]
    : [...coreSections];
  const effectiveSection = sections.some((item) => item.id === activeSection) ? activeSection : "general";
  const selectedSection = sections.find((item) => item.id === effectiveSection) ?? sections[0];
  const status = statusCopy[diagnostics.status];
  const StatusIcon = status.icon;
  const identityName = session.identity.displayName ?? session.identity.email ?? "Автентифікований оператор";
  const canManageUsers = membership.permissions.includes("memberships.manage");
  const canManageVersions = membership.permissions.includes("project_versions.manage");

  return (
    <div className="space-y-5 pb-8">
      <section className="overflow-hidden rounded-3xl border border-cyan-300/10 bg-[#091a31]/90 shadow-2xl shadow-black/20">
        <div className="relative p-5 sm:p-6 xl:p-7">
          <div className="pointer-events-none absolute -top-32 right-0 h-72 w-72 rounded-full bg-blue-500/10 blur-3xl" />
          <div className="relative flex flex-col gap-5 xl:flex-row xl:items-end xl:justify-between">
            <div className="max-w-3xl">
              <div className="flex items-center gap-3">
                <div className="grid h-12 w-12 place-items-center rounded-2xl border border-cyan-300/20 bg-cyan-400/10">
                  <Settings2 className="h-6 w-6 text-cyan-200" />
                </div>
                <div>
                  <p className="text-xs tracking-[0.22em] text-cyan-300 uppercase">NEXOLAB configuration</p>
                  <h1 className="mt-1 text-2xl font-semibold text-white sm:text-3xl">Налаштування</h1>
                </div>
              </div>
              <p className="mt-4 text-sm leading-6 text-slate-400 sm:text-base">
                Оберіть задачу, яку потрібно налаштувати. Presentation preferences не змінюють фізичне
                опитування, а операційні дії залишаються в межах чинних дозволів і LOCAL_LAN safety rules.
              </p>
            </div>
            <div className={`rounded-2xl border px-4 py-3 ${status.className}`} role="status">
              <div className="flex items-start gap-3">
                <StatusIcon className="mt-0.5 h-5 w-5 shrink-0" />
                <div>
                  <p className="font-medium">{status.title}</p>
                  <p className="mt-1 max-w-md text-xs leading-5 opacity-80">{status.description}</p>
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      <div className="lg:grid lg:grid-cols-[240px_minmax(0,1fr)] lg:items-start lg:gap-5">
        <aside className="mb-4 lg:sticky lg:top-4 lg:mb-0" aria-label="Навігація налаштувань">
          <div className="rounded-2xl border border-white/[0.08] bg-[#091a31]/80 p-3">
            <label
              htmlFor="settings-section"
              className="mb-2 block text-xs font-medium text-slate-400 lg:hidden"
            >
              Розділ налаштувань
            </label>
            <select
              id="settings-section"
              aria-label="Розділ налаштувань"
              value={effectiveSection}
              onChange={(event) => setActiveSection(event.target.value as SettingsSectionId)}
              className="w-full rounded-xl border border-white/10 bg-[#06142a] px-3 py-2.5 text-sm text-white outline-none focus-visible:border-cyan-300/50 focus-visible:ring-2 focus-visible:ring-cyan-300/20 lg:hidden"
            >
              {sections.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.title}
                </option>
              ))}
            </select>

            <nav aria-label="Розділи налаштувань" className="hidden space-y-1 lg:block">
              {sections.map((item) => {
                const Icon = item.icon;
                const active = item.id === effectiveSection;
                return (
                  <button
                    key={item.id}
                    type="button"
                    aria-current={active ? "page" : undefined}
                    onClick={() => setActiveSection(item.id)}
                    className={`group flex w-full items-start gap-3 rounded-xl border px-3 py-3 text-left transition outline-none focus-visible:ring-2 focus-visible:ring-cyan-300/30 ${
                      active
                        ? "border-cyan-300/25 bg-cyan-400/[0.09] text-white"
                        : "border-transparent text-slate-300 hover:border-white/[0.08] hover:bg-white/[0.035]"
                    }`}
                  >
                    <Icon
                      className={`mt-0.5 h-4 w-4 shrink-0 ${active ? "text-cyan-200" : "text-slate-500"}`}
                    />
                    <span className="min-w-0">
                      <span className="block text-sm font-medium">{item.title}</span>
                      <span className="mt-1 block text-[11px] leading-4 text-slate-500">
                        {item.description}
                      </span>
                      {active ? (
                        <span className="mt-1.5 block text-[10px] font-medium text-cyan-200">
                          Поточний розділ
                        </span>
                      ) : null}
                    </span>
                  </button>
                );
              })}
            </nav>

            {canManageUsers || canManageVersions ? (
              <div className="mt-3 border-t border-white/[0.07] pt-3">
                <p className="mb-2 px-2 text-[10px] font-medium tracking-[0.16em] text-slate-600 uppercase">
                  Адміністрування
                </p>
                <div className="space-y-1">
                  {canManageUsers ? (
                    <AdminLink href="/settings/users" icon={UsersRound} title="Користувачі та доступ" />
                  ) : null}
                  {canManageVersions ? (
                    <AdminLink
                      href="/settings/system/version"
                      icon={PackageCheck}
                      title="Версія та оновлення"
                    />
                  ) : null}
                </div>
              </div>
            ) : null}
          </div>
        </aside>

        <section className="min-w-0" aria-label="Вміст налаштувань" aria-live="polite">
          <section className="mb-4 rounded-2xl border border-white/[0.08] bg-[#091a31]/70 px-5 py-4 sm:px-6">
            <p className="text-xs tracking-[0.16em] text-cyan-300 uppercase">Поточний розділ</p>
            <h2 className="mt-1 text-xl font-semibold text-white">{selectedSection.title}</h2>
            <p className="mt-1 text-sm text-slate-500">{selectedSection.description}</p>
          </section>

          {effectiveSection === "general" ? (
            <GeneralSection
              identityName={identityName}
              session={session}
              membership={membership}
              preferences={preferences}
              preferencesLoaded={preferencesLoaded}
              preferencesRecovered={preferencesRecovered}
              preferenceRecoveryReason={preferenceRecoveryReason}
              onPreferenceChange={onPreferenceChange}
              onPreferencesReset={onPreferencesReset}
            />
          ) : null}

          {effectiveSection === "appearance" ? (
            <AppearanceSection
              preferences={preferences}
              preferencesLoaded={preferencesLoaded}
              onPreferenceChange={onPreferenceChange}
            />
          ) : null}

          {effectiveSection === "data-collection" ? acquisitionCadenceContent : null}

          {effectiveSection === "monitoring" && canManageSensorMonitoring ? (
            <MonitoringSection
              ready={sensorMonitoringReady}
              error={sensorMonitoringError}
              loading={sensorMonitoringLoading}
              onRetry={onRetrySensorMonitoring}
              onOpen={onOpenSensorMonitoring}
            />
          ) : null}

          {effectiveSection === "system" ? (
            <SystemSection diagnostics={diagnostics} membership={membership} status={status} />
          ) : null}
        </section>
      </div>
    </div>
  );
}

function GeneralSection({
  identityName,
  session,
  membership,
  preferences,
  preferencesLoaded,
  preferencesRecovered,
  preferenceRecoveryReason,
  onPreferenceChange,
  onPreferencesReset,
}: {
  identityName: string;
  session: SecuritySession;
  membership: SecurityMembership;
  preferences: SettingsPreferences;
  preferencesLoaded: boolean;
  preferencesRecovered: boolean;
  preferenceRecoveryReason: string | null;
  onPreferenceChange: SettingsWorkspaceProps["onPreferenceChange"];
  onPreferencesReset: () => void;
}) {
  return (
    <section
      aria-labelledby="operator-context-heading"
      className="rounded-3xl border border-white/[0.08] bg-[#091a31]/80 p-5 sm:p-6"
    >
      <SectionHeading
        id="operator-context-heading"
        icon={CircleUserRound}
        title="Організація та оператор"
        description="Перевірений контекст поточної live session."
      />
      <div className="mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        <Fact label="Оператор" value={identityName} />
        <Fact label="Email" value={session.identity.email ?? "Не вказано"} />
        <Fact label="Організація" value={membership.organizationName} />
      </div>
      <div className="mt-5 flex flex-wrap gap-2" aria-label="Ролі оператора">
        {membership.roles.length > 0 ? (
          membership.roles.map((role) => (
            <span
              key={role}
              className="rounded-full border border-cyan-300/15 bg-cyan-400/[0.07] px-3 py-1.5 text-xs text-cyan-100"
            >
              {roleLabels[role] ?? role}
            </span>
          ))
        ) : (
          <span className="text-sm text-slate-500">Ролі відсутні.</span>
        )}
      </div>

      <div className="mt-7 border-t border-white/[0.07] pt-6">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <h3 className="text-base font-semibold text-white">Основні параметри</h3>
            <p className="mt-1 text-xs leading-5 text-slate-500">
              Зберігаються лише в цьому браузері та не змінюють acquisition.
            </p>
          </div>
          <button
            type="button"
            onClick={onPreferencesReset}
            disabled={!preferencesLoaded}
            className="inline-flex items-center justify-center gap-2 rounded-xl border border-white/10 px-3.5 py-2.5 text-sm text-slate-300 transition hover:border-cyan-300/25 hover:text-white focus-visible:ring-2 focus-visible:ring-cyan-300/30 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <RefreshCcw className="h-4 w-4" />
            Скинути локальні налаштування
          </button>
        </div>
        {preferencesRecovered ? (
          <div className="mt-4 rounded-2xl border border-amber-400/15 bg-amber-400/[0.05] p-4" role="status">
            <div className="flex items-start gap-3">
              <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-amber-300" />
              <div>
                <p className="text-sm font-medium text-amber-100">
                  Пошкоджені локальні налаштування відновлено
                </p>
                <p className="mt-1 text-xs leading-5 text-amber-100/60">
                  {preferenceRecoveryReason ?? "Використано детерміновані defaults версії 1."}
                </p>
              </div>
            </div>
          </div>
        ) : null}
        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          <PreferenceSelect
            id="settings-time-display"
            label="Часові позначки"
            description="Лише спосіб відображення часу."
            value={preferences.timeDisplay}
            disabled={!preferencesLoaded}
            onChange={(value) =>
              onPreferenceChange("timeDisplay", value as SettingsPreferences["timeDisplay"])
            }
            options={[
              { value: "local", label: "Локальний час" },
              { value: "utc", label: "UTC" },
            ]}
          />
          <PreferenceSelect
            id="settings-telemetry-window"
            label="Стандартне вікно телеметрії"
            description="Лише початковий presentation window."
            value={preferences.telemetryWindow}
            disabled={!preferencesLoaded}
            onChange={(value) =>
              onPreferenceChange("telemetryWindow", value as SettingsPreferences["telemetryWindow"])
            }
            options={[
              { value: "1h", label: "1 година" },
              { value: "6h", label: "6 годин" },
              { value: "24h", label: "24 години" },
            ]}
          />
        </div>
      </div>
    </section>
  );
}

function AppearanceSection({
  preferences,
  preferencesLoaded,
  onPreferenceChange,
}: {
  preferences: SettingsPreferences;
  preferencesLoaded: boolean;
  onPreferenceChange: SettingsWorkspaceProps["onPreferenceChange"];
}) {
  return (
    <section
      aria-labelledby="appearance-heading"
      className="rounded-3xl border border-white/[0.08] bg-[#091a31]/80 p-5 sm:p-6"
    >
      <SectionHeading
        id="appearance-heading"
        icon={Palette}
        title="Вигляд інтерфейсу"
        description="Presentation-only параметри без впливу на дані, alarms або physical polling."
      />
      <div className="mt-5 grid gap-4 sm:grid-cols-2">
        <PreferenceSelect
          id="settings-table-density"
          label="Щільність таблиць"
          description="Візуальна щільність операторських списків."
          value={preferences.tableDensity}
          disabled={!preferencesLoaded}
          onChange={(value) =>
            onPreferenceChange("tableDensity", value as SettingsPreferences["tableDensity"])
          }
          options={[
            { value: "comfortable", label: "Комфортна" },
            { value: "compact", label: "Компактна" },
          ]}
        />
        <PreferenceSelect
          id="settings-motion"
          label="Анімація"
          description="Не перевизначає safety-critical state signals."
          value={preferences.motion}
          disabled={!preferencesLoaded}
          onChange={(value) => onPreferenceChange("motion", value as SettingsPreferences["motion"])}
          options={[
            { value: "system", label: "За системою" },
            { value: "reduced", label: "Зменшена" },
          ]}
        />
      </div>
    </section>
  );
}

function MonitoringSection({
  ready,
  error,
  loading,
  onRetry,
  onOpen,
}: {
  ready: boolean;
  error: string | null;
  loading: boolean;
  onRetry: () => void;
  onOpen: () => void;
}) {
  return (
    <section
      aria-labelledby="monitoring-heading"
      className="rounded-3xl border border-white/[0.08] bg-[#091a31]/80 p-5 sm:p-6"
    >
      <SectionHeading
        id="monitoring-heading"
        icon={MonitorCog}
        title="Безперервний моніторинг XJP60D"
        description="Виберіть канали, які NEXOLAB повинен постійно опитувати в read-only режимі."
      />
      <div className="mt-5 rounded-2xl border border-cyan-300/15 bg-cyan-400/[0.035] p-5">
        <h3 className="text-sm font-medium text-white">Канали постійного збору</h3>
        <p className="mt-2 text-sm leading-6 text-slate-400">
          Зміна цього списку керує лише persisted eligibility для read-only polling. Вона не виконує Modbus
          write і не змінює параметри контролера.
        </p>
        {error ? (
          <div
            role="alert"
            className="mt-4 flex flex-col gap-3 rounded-2xl border border-amber-300/15 bg-amber-400/[0.05] p-4 text-amber-100 sm:flex-row sm:items-center sm:justify-between"
          >
            <div>
              <p className="text-sm font-medium">Не вдалося завантажити конфігурацію моніторингу</p>
              <p className="mt-1 text-xs leading-5 text-amber-100/70">{error}</p>
            </div>
            <button
              type="button"
              onClick={onRetry}
              disabled={loading}
              className="inline-flex shrink-0 items-center justify-center gap-2 rounded-xl border border-amber-200/20 px-3.5 py-2.5 text-xs font-medium text-amber-50 transition hover:border-amber-200/35 focus-visible:ring-2 focus-visible:ring-amber-200/30 disabled:cursor-wait disabled:opacity-50"
            >
              <RefreshCcw className={`h-4 w-4 ${loading ? "animate-spin" : ""}`} />
              Повторити завантаження
            </button>
          </div>
        ) : null}
        <button
          type="button"
          onClick={onOpen}
          disabled={!ready}
          className="mt-5 inline-flex items-center gap-2 rounded-xl bg-blue-500 px-4 py-2.5 text-sm font-medium text-white transition hover:bg-blue-400 focus-visible:ring-2 focus-visible:ring-cyan-300/40 disabled:cursor-wait disabled:opacity-50"
        >
          Налаштувати моніторинг XJP60D
          <ChevronRight className="h-4 w-4" />
        </button>
      </div>
    </section>
  );
}

function SystemSection({
  diagnostics,
  membership,
  status,
}: {
  diagnostics: SettingsRuntimeDiagnostics;
  membership: SecurityMembership;
  status: (typeof statusCopy)[SettingsConfigurationState];
}) {
  const StatusIcon = status.icon;
  return (
    <section aria-labelledby="system-heading" className="space-y-4">
      <div className="rounded-3xl border border-white/[0.08] bg-[#091a31]/80 p-5 sm:p-6">
        <SectionHeading
          id="system-heading"
          icon={MonitorCog}
          title="Стан системи"
          description="Sanitized LOCAL_LAN runtime diagnostics без секретів і внутрішніх credentials."
        />
        <div
          aria-label="Підсумок runtime configuration"
          className="mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4"
        >
          <SummaryCard icon={Activity} label="Профіль" value={diagnostics.profile} />
          <SummaryCard
            icon={Gauge}
            label="Режим даних"
            value={
              diagnostics.dataMode === "live"
                ? "Live mode"
                : diagnostics.dataMode === "demo"
                  ? "Demo mode"
                  : "Некоректний"
            }
          />
          <SummaryCard icon={KeyRound} label="Auth provider" value={diagnostics.authProviderLabel} />
          <SummaryCard icon={StatusIcon} label="Стан" value={status.title} />
        </div>
        {diagnostics.issues.length > 0 ? (
          <div className="mt-5 space-y-2" aria-label="Діагностичні повідомлення">
            {diagnostics.issues.map((issue) => (
              <div
                key={issue.code}
                className={`rounded-2xl border p-4 ${issue.severity === "critical" ? "border-rose-400/15 bg-rose-400/[0.05]" : issue.severity === "warning" ? "border-amber-400/15 bg-amber-400/[0.05]" : "border-white/[0.07] bg-white/[0.025]"}`}
              >
                <div className="flex items-start gap-3">
                  {issue.severity === "critical" ? (
                    <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0 text-rose-300" />
                  ) : issue.severity === "warning" ? (
                    <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-300" />
                  ) : (
                    <Gauge className="mt-0.5 h-4 w-4 shrink-0 text-slate-400" />
                  )}
                  <div>
                    <p className="text-sm font-medium text-slate-200">{issue.title}</p>
                    <p className="mt-1 text-xs leading-5 text-slate-500">{issue.message}</p>
                    <p className="mt-2 font-mono text-[11px] text-slate-600">{issue.code}</p>
                  </div>
                </div>
              </div>
            ))}
          </div>
        ) : null}
      </div>

      <details className="rounded-2xl border border-white/[0.08] bg-[#091a31]/70 p-4 sm:p-5">
        <summary className="cursor-pointer text-sm font-medium text-slate-200 outline-none focus-visible:ring-2 focus-visible:ring-cyan-300/30">
          Runtime endpoints і деталі
        </summary>
        <p className="mt-2 text-xs leading-5 text-slate-500">
          Відображаються тільки client-safe sanitized values.
        </p>
        <div className="mt-4 space-y-3">
          <EndpointRow label="Dashboard origin" endpoint={diagnostics.browser} />
          <EndpointRow label="NEXOLAB API" endpoint={diagnostics.api} />
          <EndpointRow label="Telemetry WebSocket" endpoint={diagnostics.websocket} />
        </div>
      </details>

      <details className="rounded-2xl border border-white/[0.08] bg-[#091a31]/70 p-4 sm:p-5">
        <summary className="cursor-pointer text-sm font-medium text-slate-200 outline-none focus-visible:ring-2 focus-visible:ring-cyan-300/30">
          Ефективні дозволи
        </summary>
        <p className="mt-2 text-xs leading-5 text-slate-500">
          Це read-only пояснення фактичного доступу, а не редактор RBAC.
        </p>
        <div className="mt-4 space-y-3">
          {permissionGroups.map((group) => {
            const granted = group.permissions.filter((permission) =>
              membership.permissions.includes(permission),
            );
            return (
              <div key={group.title} className="rounded-2xl border border-white/[0.06] bg-black/10 p-4">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <h3 className="text-sm font-medium text-slate-100">{group.title}</h3>
                    <p className="mt-1 text-xs leading-5 text-slate-500">{group.description}</p>
                  </div>
                  <span className="text-xs text-slate-500">
                    {granted.length}/{group.permissions.length}
                  </span>
                </div>
                <div className="mt-3 flex flex-wrap gap-2">
                  {granted.length > 0 ? (
                    granted.map((permission) => (
                      <span
                        key={permission}
                        className="rounded-lg border border-white/[0.07] bg-white/[0.035] px-2.5 py-1.5 text-xs text-slate-300"
                      >
                        {permissionLabels[permission]}
                      </span>
                    ))
                  ) : (
                    <span className="text-xs text-slate-600">Немає дозволів у цій групі.</span>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </details>

      <details className="rounded-2xl border border-amber-300/10 bg-[#091a31]/70 p-4 sm:p-5">
        <summary className="cursor-pointer text-sm font-medium text-slate-200 outline-none focus-visible:ring-2 focus-visible:ring-amber-300/30">
          Safety та offline-first boundary
        </summary>
        <div className="mt-4 flex gap-3 rounded-2xl border border-blue-300/10 bg-blue-400/[0.04] p-4">
          <DatabaseZap className="mt-0.5 h-5 w-5 shrink-0 text-blue-200" />
          <div>
            <h3 className="text-sm font-medium text-slate-100">LOCAL_LAN offline-first</h3>
            <p className="mt-1 text-xs leading-5 text-slate-400">
              Основний runtime працює без mandatory cloud, CDN, remote fonts або paid services.
            </p>
          </div>
        </div>
        <ul className="mt-4 space-y-2 text-xs leading-5 text-slate-400">
          {[
            "Фізичні Modbus/RS-485 parameters і controller writes не налаштовуються з цієї сторінки.",
            "Retention, backup, restore, CORS, TLS, DNS і VPN не змінюються з browser UI.",
            "Secret rotation і production/site cutover потребують окремого контрольованого Work Package.",
          ].map((item) => (
            <li key={item} className="flex gap-2">
              <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-amber-300/80" />
              <span>{item}</span>
            </li>
          ))}
        </ul>
      </details>
    </section>
  );
}

function AdminLink({ href, icon: Icon, title }: { href: string; icon: typeof UsersRound; title: string }) {
  return (
    <Link
      href={href}
      className="group flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm text-slate-300 transition outline-none hover:bg-white/[0.035] hover:text-white focus-visible:ring-2 focus-visible:ring-cyan-300/30"
    >
      <Icon className="h-4 w-4 text-slate-500 group-hover:text-cyan-200" />
      <span className="flex-1">{title}</span>
      <ChevronRight className="h-4 w-4 text-slate-600" />
    </Link>
  );
}

function SummaryCard({ icon: Icon, label, value }: { icon: typeof Activity; label: string; value: string }) {
  return (
    <div className="rounded-2xl border border-white/[0.07] bg-black/10 p-4">
      <div className="flex items-center gap-3">
        <div className="grid h-9 w-9 place-items-center rounded-xl border border-white/[0.07] bg-white/[0.035]">
          <Icon className="h-4 w-4 text-cyan-200" />
        </div>
        <div className="min-w-0">
          <p className="text-xs text-slate-500">{label}</p>
          <p className="mt-1 truncate text-sm font-medium text-white">{value}</p>
        </div>
      </div>
    </div>
  );
}

function SectionHeading({
  id,
  icon: Icon,
  title,
  description,
}: {
  id: string;
  icon: typeof Activity;
  title: string;
  description: string;
}) {
  return (
    <div className="flex items-start gap-3">
      <div className="grid h-10 w-10 shrink-0 place-items-center rounded-xl border border-cyan-300/10 bg-cyan-400/[0.05]">
        <Icon className="h-5 w-5 text-cyan-200" />
      </div>
      <div>
        <h2 id={id} className="text-lg font-semibold text-white">
          {title}
        </h2>
        <p className="mt-1 text-xs leading-5 text-slate-500">{description}</p>
      </div>
    </div>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-2xl border border-white/[0.06] bg-black/10 p-4">
      <p className="text-xs text-slate-500">{label}</p>
      <p className="mt-1 text-sm break-words text-slate-200">{value}</p>
    </div>
  );
}

function EndpointRow({ label, endpoint }: { label: string; endpoint: SanitizedSettingsEndpoint }) {
  const value = endpoint.valid
    ? endpoint.displayValue
    : endpoint.configured
      ? "Некоректний URL"
      : "Не налаштовано";
  return (
    <div className="rounded-2xl border border-white/[0.06] bg-black/10 p-4">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <p className="text-xs text-slate-500">{label}</p>
          <p className="mt-1 font-mono text-xs leading-5 break-all text-slate-200">{value}</p>
        </div>
        <span
          className={`w-fit rounded-full border px-2.5 py-1 text-[11px] ${endpoint.valid ? "border-emerald-400/15 bg-emerald-400/[0.06] text-emerald-200" : "border-amber-400/15 bg-amber-400/[0.06] text-amber-200"}`}
        >
          {endpoint.valid ? "Sanitized" : endpoint.configured ? "Invalid" : "Missing"}
        </span>
      </div>
      {endpoint.redactions.length > 0 ? (
        <p className="mt-2 text-[11px] text-rose-300/80">
          Очищено небезпечні частини: {endpoint.redactions.join(", ")}.
        </p>
      ) : null}
    </div>
  );
}

function PreferenceSelect({
  id,
  label,
  description,
  value,
  disabled,
  onChange,
  options,
}: {
  id: string;
  label: string;
  description: string;
  value: string;
  disabled: boolean;
  onChange: (value: string) => void;
  options: readonly { value: string; label: string }[];
}) {
  return (
    <div className="rounded-2xl border border-white/[0.07] bg-black/10 p-4">
      <label htmlFor={id} className="text-sm font-medium text-slate-200">
        {label}
      </label>
      <p className="mt-1 min-h-10 text-xs leading-5 text-slate-500">{description}</p>
      <select
        id={id}
        value={value}
        disabled={disabled}
        onChange={(event) => onChange(event.target.value)}
        className="mt-3 w-full rounded-xl border border-white/10 bg-[#06142a] px-3 py-2.5 text-sm text-slate-200 transition outline-none focus-visible:border-cyan-300/50 focus-visible:ring-2 focus-visible:ring-cyan-300/20 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </div>
  );
}
