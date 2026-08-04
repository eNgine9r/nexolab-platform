"use client";

import Link from "next/link";
import {
  Activity,
  AlertTriangle,
  BellRing,
  Boxes,
  CheckCircle2,
  ChevronRight,
  CircleUserRound,
  Clock3,
  DatabaseZap,
  FileText,
  Gauge,
  KeyRound,
  LayoutDashboard,
  MonitorCog,
  Network,
  RefreshCcw,
  Refrigerator,
  Settings2,
  ShieldCheck,
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
};

type PermissionGroup = {
  title: string;
  description: string;
  permissions: readonly SecurityPermission[];
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
    ],
  },
];

const roleLabels: Record<string, string> = {
  administrator: "Адміністратор",
  laboratory_manager: "Керівник лабораторії",
  engineer: "Інженер",
  operator: "Оператор",
  viewer: "Спостерігач",
  auditor: "Аудитор",
};

const permissionLabels: Record<SecurityPermission, string> = {
  "dashboard.read": "Огляд dashboard",
  "telemetry.read": "Перегляд телеметрії",
  "alerts.read": "Перегляд тривог",
  "audit.read": "Перегляд аудиту",
  "reports.read": "Перегляд звітів",
  "nodes.read": "Перегляд вузлів",
  "reports.generate": "Формування звітів",
  "reports.approve": "Погодження звітів",
  "memberships.manage": "Керування членством",
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
    description: "Client-visible runtime contract узгоджений із LOCAL_LAN профілем.",
    icon: CheckCircle2,
    className: "border-emerald-400/20 bg-emerald-400/[0.08] text-emerald-200",
  },
  incomplete: {
    title: "Конфігурація неповна",
    description: "Робота можлива лише після усунення наведених configuration gaps.",
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

const navigationItems = [
  {
    href: "/nodes",
    title: "Вузли",
    description: "Інвентар, стан і канонічні node workflows.",
    icon: Network,
  },
  {
    href: "/equipment",
    title: "Обладнання",
    description: "Read-only asset та metrology registry.",
    icon: Boxes,
  },
  {
    href: "/refrigeration",
    title: "Холодильне обладнання",
    description: "Підтримувані passport і layout mutations.",
    icon: Refrigerator,
  },
  {
    href: "/alerts",
    title: "Тривоги",
    description: "Перегляд і дозволені alarm operations.",
    icon: BellRing,
  },
  {
    href: "/reports",
    title: "Звіти",
    description: "Формування, погодження та експорт доказів.",
    icon: FileText,
  },
] as const;

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
}: SettingsWorkspaceProps) {
  const status = statusCopy[diagnostics.status];
  const StatusIcon = status.icon;
  const identityName = session.identity.displayName ?? session.identity.email ?? "Автентифікований оператор";

  return (
    <div className="space-y-5 pb-8">
      <section className="overflow-hidden rounded-3xl border border-cyan-300/10 bg-[#091a31]/90 shadow-2xl shadow-black/20">
        <div className="relative p-5 sm:p-6 xl:p-8">
          <div className="pointer-events-none absolute -top-32 right-0 h-72 w-72 rounded-full bg-blue-500/10 blur-3xl" />
          <div className="relative flex flex-col gap-5 xl:flex-row xl:items-end xl:justify-between">
            <div className="max-w-3xl">
              <div className="flex items-center gap-3">
                <div className="grid h-12 w-12 place-items-center rounded-2xl border border-cyan-300/20 bg-cyan-400/10">
                  <Settings2 className="h-6 w-6 text-cyan-200" />
                </div>
                <div>
                  <p className="text-xs tracking-[0.22em] text-cyan-300 uppercase">
                    Operator-safe configuration
                  </p>
                  <h1 className="mt-1 text-2xl font-semibold text-white sm:text-3xl">Налаштування</h1>
                </div>
              </div>
              <p className="mt-5 text-sm leading-6 text-slate-400 sm:text-base">
                Перевірений контекст організації, очищена runtime-діагностика та локальні presentation
                preferences. Ця сторінка не є прихованим administration backend і не виконує device або
                deployment writes.
              </p>
            </div>

            <div className={`rounded-2xl border px-4 py-3 ${status.className}`}>
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

      <section aria-labelledby="runtime-summary-heading" className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <h2 id="runtime-summary-heading" className="sr-only">
          Підсумок runtime configuration
        </h2>
        <SummaryCard icon={LayoutDashboard} label="Профіль" value={diagnostics.profile} />
        <SummaryCard
          icon={Activity}
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
        <SummaryCard
          icon={ShieldCheck}
          label="Стан"
          value={status.title}
          valueClassName={
            diagnostics.status === "ready"
              ? "text-emerald-200"
              : diagnostics.status === "unsafe"
                ? "text-rose-200"
                : "text-amber-200"
          }
        />
      </section>

      <div className="grid gap-5 2xl:grid-cols-[minmax(0,1.05fr)_minmax(0,0.95fr)]">
        <section
          aria-labelledby="operator-context-heading"
          className="rounded-3xl border border-white/[0.08] bg-[#091a31]/80 p-5 sm:p-6"
        >
          <SectionHeading
            id="operator-context-heading"
            icon={CircleUserRound}
            title="Організація та оператор"
            description="Дані отримано з перевіреного security-session contract."
          />

          <div className="mt-5 grid gap-3 sm:grid-cols-2">
            <Fact label="Оператор" value={identityName} />
            <Fact label="Email" value={session.identity.email ?? "Не вказано"} />
            <Fact label="Identity provider" value={session.identity.provider} />
            <Fact label="Організація" value={membership.organizationName} />
            <Fact label="Slug" value={membership.organizationSlug} mono />
            <Fact label="Membership" value="Перевірено backend" />
          </div>

          <div className="mt-6">
            <p className="text-xs font-medium tracking-[0.16em] text-slate-500 uppercase">Ролі</p>
            <div className="mt-3 flex flex-wrap gap-2">
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
          </div>

          <div className="mt-6 space-y-3">
            <div>
              <p className="text-xs font-medium tracking-[0.16em] text-slate-500 uppercase">
                Ефективні дозволи
              </p>
              <p className="mt-1 text-xs text-slate-500">
                Дозволи показуються для розуміння доступу, а не як editable controls.
              </p>
            </div>
            {permissionGroups.map((group) => {
              const granted = group.permissions.filter((permission) =>
                membership.permissions.includes(permission),
              );
              return (
                <div key={group.title} className="rounded-2xl border border-white/[0.06] bg-black/10 p-4">
                  <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
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
        </section>

        <section
          aria-labelledby="runtime-diagnostics-heading"
          className="rounded-3xl border border-white/[0.08] bg-[#091a31]/80 p-5 sm:p-6"
        >
          <SectionHeading
            id="runtime-diagnostics-heading"
            icon={MonitorCog}
            title="Runtime diagnostics"
            description="Відображаються лише sanitized client-safe values."
          />

          <div className="mt-5 space-y-3">
            <EndpointRow label="Dashboard origin" endpoint={diagnostics.browser} />
            <EndpointRow label="NEXOLAB API" endpoint={diagnostics.api} />
            <EndpointRow label="Telemetry WebSocket" endpoint={diagnostics.websocket} />
          </div>

          <div className="mt-5 rounded-2xl border border-blue-300/10 bg-blue-400/[0.04] p-4">
            <div className="flex gap-3">
              <DatabaseZap className="mt-0.5 h-5 w-5 shrink-0 text-blue-200" />
              <div>
                <h3 className="text-sm font-medium text-slate-100">Offline-first boundary</h3>
                <p className="mt-1 text-xs leading-5 text-slate-400">
                  Основний runtime працює в LOCAL_LAN без mandatory cloud, CDN, remote fonts або paid
                  services. Ця сторінка не змінює delivery, database чи hardware configuration.
                </p>
              </div>
            </div>
          </div>

          {diagnostics.issues.length > 0 ? (
            <div className="mt-5 space-y-2" aria-label="Діагностичні повідомлення">
              {diagnostics.issues.map((issue) => (
                <div
                  key={issue.code}
                  className={`rounded-2xl border p-4 ${
                    issue.severity === "critical"
                      ? "border-rose-400/15 bg-rose-400/[0.05]"
                      : issue.severity === "warning"
                        ? "border-amber-400/15 bg-amber-400/[0.05]"
                        : "border-white/[0.07] bg-white/[0.025]"
                  }`}
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
        </section>
      </div>

      <section
        aria-labelledby="local-preferences-heading"
        className="rounded-3xl border border-white/[0.08] bg-[#091a31]/80 p-5 sm:p-6"
      >
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <SectionHeading
            id="local-preferences-heading"
            icon={Clock3}
            title="Локальні presentation preferences"
            description="Зберігаються лише в цьому браузері та не впливають на acquisition, alarms, retention, auth або devices."
          />
          <button
            type="button"
            onClick={onPreferencesReset}
            disabled={!preferencesLoaded}
            className="inline-flex items-center justify-center gap-2 rounded-xl border border-white/10 px-3.5 py-2.5 text-sm text-slate-300 transition hover:border-cyan-300/25 hover:text-white disabled:cursor-not-allowed disabled:opacity-50"
          >
            <RefreshCcw className="h-4 w-4" />
            Скинути локальні налаштування
          </button>
        </div>

        {preferencesRecovered ? (
          <div className="mt-5 rounded-2xl border border-amber-400/15 bg-amber-400/[0.05] p-4" role="status">
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

        <div className="mt-5 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
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
      </section>

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1.15fr)_minmax(0,0.85fr)]">
        <section
          aria-labelledby="operational-navigation-heading"
          className="rounded-3xl border border-white/[0.08] bg-[#091a31]/80 p-5 sm:p-6"
        >
          <SectionHeading
            id="operational-navigation-heading"
            icon={Activity}
            title="Канонічні робочі процеси"
            description="Settings не дублює вже реалізовані редактори та operations."
          />
          <div className="mt-5 grid gap-3 sm:grid-cols-2">
            {navigationItems.map((item) => {
              const Icon = item.icon;
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className="group rounded-2xl border border-white/[0.07] bg-black/10 p-4 transition hover:border-cyan-300/20 hover:bg-cyan-400/[0.035]"
                >
                  <div className="flex items-start gap-3">
                    <div className="grid h-10 w-10 shrink-0 place-items-center rounded-xl border border-white/[0.07] bg-white/[0.035]">
                      <Icon className="h-5 w-5 text-slate-300" />
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center justify-between gap-3">
                        <h3 className="text-sm font-medium text-slate-100">{item.title}</h3>
                        <ChevronRight className="h-4 w-4 text-slate-600 transition group-hover:translate-x-0.5 group-hover:text-cyan-300" />
                      </div>
                      <p className="mt-1 text-xs leading-5 text-slate-500">{item.description}</p>
                    </div>
                  </div>
                </Link>
              );
            })}
          </div>
        </section>

        <section
          aria-labelledby="unsupported-settings-heading"
          className="rounded-3xl border border-amber-300/10 bg-[#091a31]/80 p-5 sm:p-6"
        >
          <SectionHeading
            id="unsupported-settings-heading"
            icon={UsersRound}
            title="Непідтримувана конфігурація"
            description="Не показуємо disabled controls, які створювали б хибне враження готового admin workflow."
          />
          <ul className="mt-5 space-y-3 text-sm text-slate-400">
            {[
              "Організації, memberships і ролі не редагуються на цій сторінці.",
              "Node credentials, Modbus/RS-485 parameters і device writes відсутні.",
              "Retention, backup, restore, CORS, TLS, DNS і VPN не змінюються з browser UI.",
              "Secret rotation і production/site cutover потребують окремого контрольованого Work Package.",
            ].map((item) => (
              <li key={item} className="flex gap-3">
                <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-amber-300/80" />
                <span className="leading-6">{item}</span>
              </li>
            ))}
          </ul>
        </section>
      </div>
    </div>
  );
}

function SummaryCard({
  icon: Icon,
  label,
  value,
  valueClassName = "text-white",
}: {
  icon: typeof Activity;
  label: string;
  value: string;
  valueClassName?: string;
}) {
  return (
    <div className="rounded-2xl border border-white/[0.07] bg-[#091a31]/75 p-4">
      <div className="flex items-center gap-3">
        <div className="grid h-9 w-9 place-items-center rounded-xl border border-white/[0.07] bg-white/[0.035]">
          <Icon className="h-4 w-4 text-cyan-200" />
        </div>
        <div className="min-w-0">
          <p className="text-xs text-slate-500">{label}</p>
          <p className={`mt-1 truncate text-sm font-medium ${valueClassName}`}>{value}</p>
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

function Fact({ label, value, mono = false }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="rounded-2xl border border-white/[0.06] bg-black/10 p-4">
      <p className="text-xs text-slate-500">{label}</p>
      <p className={`mt-1 text-sm break-words text-slate-200 ${mono ? "font-mono" : ""}`}>{value}</p>
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
          className={`w-fit rounded-full border px-2.5 py-1 text-[11px] ${
            endpoint.valid
              ? "border-emerald-400/15 bg-emerald-400/[0.06] text-emerald-200"
              : "border-amber-400/15 bg-amber-400/[0.06] text-amber-200"
          }`}
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
        className="mt-3 w-full rounded-xl border border-white/10 bg-[#06142a] px-3 py-2.5 text-sm text-slate-200 transition outline-none focus:border-cyan-300/30 disabled:cursor-not-allowed disabled:opacity-50"
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
