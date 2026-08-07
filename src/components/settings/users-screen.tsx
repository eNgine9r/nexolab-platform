"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import {
  AlertTriangle,
  KeyRound,
  LogOut,
  RefreshCcw,
  Save,
  Search,
  ShieldCheck,
  UserCheck,
  UserPlus,
  UsersRound,
  UserX,
} from "lucide-react";

import { SecurityGate } from "@/components/dashboard/security-gate";
import { Sidebar } from "@/components/dashboard/sidebar";
import { Topbar } from "@/components/dashboard/topbar";
import { createRuntimeCredentialProvider } from "@/features/security/auth-runtime";
import {
  LocalUserAdminApiError,
  LocalUserAdminClient,
  type LocalUserAdminUser,
  type LocalUserPermissionOption,
  type LocalUserRoleOption,
} from "@/features/security/local-user-admin";
import {
  createAuthenticatedFetch,
  type SecurityEffectivePermission,
  type SecurityProductRole,
} from "@/features/security/security-session";
import { useDashboardSecurity } from "@/hooks/use-dashboard-security";
import { getTelemetryRuntimeConfig } from "@/lib/telemetry/runtime-config";

const roleFallbackLabels: Record<SecurityProductRole, string> = {
  administrator: "Адміністратор",
  laboratory_manager: "Керівник лабораторії",
  engineer: "Інженер",
  laboratory_technician: "Технік-лаборант",
};

const permissionLabels: Partial<Record<SecurityEffectivePermission, string>> = {
  "dashboard.read": "Огляд",
  "live_dashboards.manage": "Керування Live Dashboard",
  "telemetry.read": "Перегляд телеметрії",
  "alerts.read": "Перегляд тривог",
  "audit.read": "Перегляд аудиту",
  "reports.read": "Перегляд звітів",
  "nodes.read": "Перегляд вузлів",
  "reports.generate": "Формування звітів",
  "reports.approve": "Погодження звітів",
  "equipment.manage": "Керування обладнанням",
  "nodes.manage": "Керування вузлами",
  "layout.draft.edit": "Редагування схем",
  "layout.publish": "Публікація схем",
  "layout.restore": "Відновлення схем",
  "sessions.manage": "Керування випробуваннями",
  "sessions.operate": "Виконання випробувань",
  "alerts.rules.manage": "Керування правилами тривог",
  "alerts.acknowledge": "Підтвердження тривог",
  "memberships.manage": "Керування користувачами",
  "project_versions.manage": "Керування версіями NEXOLAB",
};

type CreateDraft = {
  username: string;
  displayName: string;
  email: string;
  password: string;
  role: SecurityProductRole;
  permissions: SecurityEffectivePermission[];
};

const emptyCreateDraft: CreateDraft = {
  username: "",
  displayName: "",
  email: "",
  password: "",
  role: "laboratory_technician",
  permissions: [],
};

export function UsersScreen() {
  const router = useRouter();
  const security = useDashboardSecurity();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [users, setUsers] = useState<LocalUserAdminUser[]>([]);
  const [roles, setRoles] = useState<LocalUserRoleOption[]>([]);
  const [permissions, setPermissions] = useState<LocalUserPermissionOption[]>([]);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [roleFilter, setRoleFilter] = useState<"all" | SecurityProductRole | "legacy">("all");
  const [activeFilter, setActiveFilter] = useState<"all" | "active" | "inactive">("all");
  const [createOpen, setCreateOpen] = useState(false);
  const [createDraft, setCreateDraft] = useState<CreateDraft>(emptyCreateDraft);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedRole, setSelectedRole] = useState<SecurityProductRole>("laboratory_technician");
  const [selectedPermissions, setSelectedPermissions] = useState<SecurityEffectivePermission[]>([]);
  const [resetPassword, setResetPassword] = useState("");

  const runtime = useMemo(() => {
    try {
      const config = getTelemetryRuntimeConfig();
      return config.mode === "live" ? config : null;
    } catch {
      return null;
    }
  }, []);

  const client = useMemo(() => {
    if (!runtime?.apiBaseUrl || !security.membership) return null;
    const credentialProvider = createRuntimeCredentialProvider(
      runtime.apiBaseUrl,
      security.membership.organizationId,
    );
    return new LocalUserAdminClient({
      apiBaseUrl: runtime.apiBaseUrl,
      fetchImpl: createAuthenticatedFetch(fetch.bind(globalThis), credentialProvider),
    });
  }, [runtime, security.membership]);

  const canManageUsers = security.membership?.permissions.includes("memberships.manage") ?? false;

  const refresh = async () => {
    if (!client || !canManageUsers) return;
    setLoading(true);
    setError(null);
    try {
      const [nextUsers, nextRoles, nextPermissions] = await Promise.all([
        client.listUsers(),
        client.roles(),
        client.permissions(),
      ]);
      setUsers(nextUsers);
      setRoles(nextRoles);
      setPermissions(nextPermissions);
      setSelectedId((current) =>
        current && nextUsers.some((user) => user.id === current)
          ? current
          : nextUsers[0]?.id ?? null,
      );
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (security.state === "ready" && canManageUsers && client) {
      void refresh();
    }
    // refresh intentionally depends on the resolved security/client boundary only.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [security.state, canManageUsers, client]);

  const selectedUser = users.find((user) => user.id === selectedId) ?? null;

  useEffect(() => {
    if (!selectedUser) return;
    setSelectedRole(selectedUser.role ?? "laboratory_technician");
    setSelectedPermissions(selectedUser.grantedPermissions);
    setResetPassword("");
    setNotice(null);
    setError(null);
  }, [selectedUser]);

  const filteredUsers = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase("uk");
    return users.filter((user) => {
      const searchMatch =
        !normalized ||
        [user.username, user.displayName ?? "", user.email ?? ""]
          .join(" ")
          .toLocaleLowerCase("uk")
          .includes(normalized);
      const roleMatch =
        roleFilter === "all" ||
        (roleFilter === "legacy" ? user.migrationRequired : user.role === roleFilter);
      const activeMatch =
        activeFilter === "all" ||
        (activeFilter === "active" ? user.isActive : !user.isActive);
      return searchMatch && roleMatch && activeMatch;
    });
  }, [activeFilter, query, roleFilter, users]);

  const grantablePermissions = permissions.filter((permission) => permission.grantable);

  if (security.mode === "demo") {
    return <UsersGate title="Користувачі доступні лише в local live mode" message="Users & Access працює з локальною PostgreSQL identity authority і не використовує demo accounts." />;
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
    return <UsersGate title="Організацію не вибрано" message="Для керування користувачами потрібне активне локальне membership." />;
  }

  if (!canManageUsers) {
    return (
      <UsersGate
        title="Доступ заборонено"
        message="Керування користувачами доступне лише адміністратору. Перевірка виконується також на backend через memberships.manage."
      />
    );
  }

  if (!client) {
    return <UsersGate title="Local API недоступний" message="Не вдалося визначити локальний Telemetry Service для Users & Access." />;
  }

  const runMutation = async (action: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await action();
      await refresh();
    } catch (cause) {
      setError(errorMessage(cause));
    } finally {
      setBusy(false);
    }
  };

  const createUser = async () => {
    const password = createDraft.password;
    setCreateDraft((draft) => ({ ...draft, password: "" }));
    await runMutation(async () => {
      const created = await client.createUser({
        username: createDraft.username,
        displayName: createDraft.displayName || null,
        email: createDraft.email || null,
        password,
        role: createDraft.role,
        permissions: createDraft.role === "administrator" ? [] : createDraft.permissions,
        reason: "Created from Users & Access",
      });
      setCreateDraft(emptyCreateDraft);
      setCreateOpen(false);
      setSelectedId(created.id);
      setNotice(`Користувача ${created.username} створено.`);
    });
  };

  const saveAccess = async () => {
    if (!selectedUser) return;
    await runMutation(async () => {
      if (selectedUser.role !== selectedRole) {
        await client.updateUser(selectedUser.id, {
          role: selectedRole,
          reason: "Role changed from Users & Access",
        });
      }
      if (selectedRole !== "administrator") {
        await client.setPermissions(
          selectedUser.id,
          selectedPermissions,
          "Permissions changed from Users & Access",
        );
      }
      setNotice(`Права ${selectedUser.username} оновлено; активні сесії відкликано при зміні доступу.`);
    });
  };

  return (
    <div className="min-h-screen bg-[#06142a] text-slate-100">
      <Sidebar open={sidebarOpen} activeItem="Налаштування" onClose={() => setSidebarOpen(false)} onSelect={() => undefined} />
      <div className="min-h-screen lg:pl-[264px]">
        <Topbar
          title="Користувачі та права"
          onMenuOpen={() => setSidebarOpen(true)}
          showCreateSession={false}
          securitySession={security.session}
          selectedMembership={security.membership}
          onOrganizationChange={security.selectOrganization}
          onSignOut={() => void security.signOut().then(() => router.replace("/login"))}
        />

        <main className="p-3 sm:p-4 xl:p-5 2xl:p-6">
          <div className="mx-auto max-w-[1900px] space-y-5">
            <section className="rounded-3xl border border-cyan-300/10 bg-[#091a31]/90 p-5 shadow-2xl shadow-black/20 sm:p-6">
              <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
                <div className="flex items-start gap-3">
                  <div className="grid h-12 w-12 shrink-0 place-items-center rounded-2xl border border-cyan-300/20 bg-cyan-400/10">
                    <UsersRound className="h-6 w-6 text-cyan-200" />
                  </div>
                  <div>
                    <p className="text-xs tracking-[0.22em] text-cyan-300 uppercase">Local access control</p>
                    <h1 className="mt-1 text-2xl font-semibold text-white">Користувачі та права</h1>
                    <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-400">
                      Чотири продуктові ролі. Адміністратор має повний доступ; для керівника лабораторії, інженера та техніка-лаборанта права задаються явно й перевіряються сервером.
                    </p>
                  </div>
                </div>
                <div className="flex flex-wrap gap-2">
                  <button type="button" onClick={() => void refresh()} disabled={loading || busy} className="inline-flex items-center gap-2 rounded-xl border border-white/10 px-4 py-2.5 text-sm hover:border-cyan-300/30 disabled:opacity-50">
                    <RefreshCcw className="h-4 w-4" /> Оновити
                  </button>
                  <button type="button" onClick={() => setCreateOpen((value) => !value)} className="inline-flex items-center gap-2 rounded-xl bg-blue-500 px-4 py-2.5 text-sm font-medium text-white hover:bg-blue-400">
                    <UserPlus className="h-4 w-4" /> Новий користувач
                  </button>
                </div>
              </div>
            </section>

            {error ? <Notice tone="error" text={error} /> : null}
            {notice ? <Notice tone="success" text={notice} /> : null}

            {createOpen ? (
              <section className="rounded-3xl border border-blue-400/20 bg-[#091a31] p-5">
                <h2 className="text-lg font-semibold">Створити локального користувача</h2>
                <div className="mt-4 grid gap-3 md:grid-cols-2 xl:grid-cols-4">
                  <Field label="Логін"><input value={createDraft.username} onChange={(event) => setCreateDraft((draft) => ({ ...draft, username: event.target.value }))} autoComplete="off" className={inputClass} /></Field>
                  <Field label="Ім’я"><input value={createDraft.displayName} onChange={(event) => setCreateDraft((draft) => ({ ...draft, displayName: event.target.value }))} className={inputClass} /></Field>
                  <Field label="Email"><input type="email" value={createDraft.email} onChange={(event) => setCreateDraft((draft) => ({ ...draft, email: event.target.value }))} className={inputClass} /></Field>
                  <Field label="Початковий пароль"><input type="password" value={createDraft.password} onChange={(event) => setCreateDraft((draft) => ({ ...draft, password: event.target.value }))} autoComplete="new-password" className={inputClass} /></Field>
                  <Field label="Роль">
                    <select value={createDraft.role} onChange={(event) => setCreateDraft((draft) => ({ ...draft, role: event.target.value as SecurityProductRole, permissions: event.target.value === "administrator" ? [] : draft.permissions }))} className={inputClass}>
                      {(roles.length ? roles : fallbackRoles()).map((role) => <option key={role.value} value={role.value}>{role.label}</option>)}
                    </select>
                  </Field>
                </div>
                {createDraft.role !== "administrator" ? (
                  <PermissionGrid options={grantablePermissions} selected={createDraft.permissions} onToggle={(permission) => setCreateDraft((draft) => ({ ...draft, permissions: togglePermission(draft.permissions, permission) }))} />
                ) : <p className="mt-4 text-sm text-emerald-300">Адміністратор автоматично отримує повний каталог дозволів.</p>}
                <div className="mt-4 flex justify-end">
                  <button type="button" disabled={busy || !createDraft.username.trim() || createDraft.password.length < 12} onClick={() => void createUser()} className="rounded-xl bg-blue-500 px-4 py-2.5 text-sm font-medium disabled:opacity-50">Створити</button>
                </div>
              </section>
            ) : null}

            <section className="grid gap-5 2xl:grid-cols-[minmax(420px,0.8fr)_minmax(0,1.2fr)]">
              <div className="rounded-3xl border border-white/10 bg-[#091a31]/90 p-4">
                <div className="grid gap-2 sm:grid-cols-3">
                  <label className="relative sm:col-span-1"><Search className="absolute top-3 left-3 h-4 w-4 text-slate-500" /><input aria-label="Пошук користувачів" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Пошук" className={`${inputClass} pl-9`} /></label>
                  <select aria-label="Фільтр ролі" value={roleFilter} onChange={(event) => setRoleFilter(event.target.value as typeof roleFilter)} className={inputClass}><option value="all">Усі ролі</option>{(roles.length ? roles : fallbackRoles()).map((role) => <option key={role.value} value={role.value}>{role.label}</option>)}<option value="legacy">Потребує міграції</option></select>
                  <select aria-label="Фільтр стану" value={activeFilter} onChange={(event) => setActiveFilter(event.target.value as typeof activeFilter)} className={inputClass}><option value="all">Усі стани</option><option value="active">Активні</option><option value="inactive">Неактивні</option></select>
                </div>
                <div className="mt-4 space-y-2">
                  {loading ? <p className="p-4 text-sm text-slate-400">Завантаження локальних користувачів…</p> : null}
                  {!loading && filteredUsers.length === 0 ? <p className="p-4 text-sm text-slate-400">Користувачів за цими умовами не знайдено.</p> : null}
                  {filteredUsers.map((user) => (
                    <button key={user.id} type="button" onClick={() => setSelectedId(user.id)} className={`w-full rounded-2xl border p-4 text-left transition ${selectedId === user.id ? "border-cyan-300/30 bg-cyan-400/[0.08]" : "border-white/8 bg-white/[0.025] hover:border-white/15"}`}>
                      <div className="flex items-start justify-between gap-3"><div><p className="font-medium text-white">{user.displayName || user.username}</p><p className="mt-1 text-xs text-slate-500">{user.username}{user.email ? ` · ${user.email}` : ""}</p></div><span className={`rounded-full px-2 py-1 text-[11px] ${user.isActive ? "bg-emerald-400/10 text-emerald-300" : "bg-slate-500/10 text-slate-400"}`}>{user.isActive ? "Активний" : "Неактивний"}</span></div>
                      <div className="mt-3 flex flex-wrap gap-2"><span className="rounded-full border border-white/10 px-2 py-1 text-xs text-slate-300">{user.role ? roleLabel(user.role, roles) : `Legacy: ${user.legacyRoles.join(", ")}`}</span>{user.migrationRequired ? <span className="rounded-full bg-amber-400/10 px-2 py-1 text-xs text-amber-300">Потрібна міграція ролі</span> : null}</div>
                    </button>
                  ))}
                </div>
              </div>

              <div className="rounded-3xl border border-white/10 bg-[#091a31]/90 p-5">
                {!selectedUser ? <div className="grid min-h-72 place-items-center text-sm text-slate-500">Виберіть користувача.</div> : (
                  <div className="space-y-5">
                    <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                      <div><p className="text-xs tracking-[0.18em] text-cyan-300 uppercase">Access profile</p><h2 className="mt-1 text-xl font-semibold">{selectedUser.displayName || selectedUser.username}</h2><p className="mt-1 text-sm text-slate-500">{selectedUser.username}</p></div>
                      {selectedUser.migrationRequired ? <div className="max-w-sm rounded-xl border border-amber-400/20 bg-amber-400/[0.06] p-3 text-xs leading-5 text-amber-200"><AlertTriangle className="mr-2 inline h-4 w-4" />Старий role value збережено. Виберіть одну з чотирьох продуктових ролей, щоб завершити контрольовану міграцію.</div> : null}
                    </div>

                    <Field label="Роль"><select value={selectedRole} onChange={(event) => { const role = event.target.value as SecurityProductRole; setSelectedRole(role); if (role === "administrator") setSelectedPermissions([]); }} className={inputClass}>{(roles.length ? roles : fallbackRoles()).map((role) => <option key={role.value} value={role.value}>{role.label}</option>)}</select></Field>

                    {selectedRole === "administrator" ? (
                      <div className="rounded-2xl border border-emerald-400/20 bg-emerald-400/[0.06] p-4 text-sm text-emerald-200"><ShieldCheck className="mr-2 inline h-4 w-4" />Повний доступ, включно з керуванням користувачами та permission boundary для керування версіями NEXOLAB.</div>
                    ) : (
                      <PermissionGrid options={grantablePermissions} selected={selectedPermissions} onToggle={(permission) => setSelectedPermissions((current) => togglePermission(current, permission))} />
                    )}

                    <div className="flex flex-wrap gap-2 border-t border-white/8 pt-4">
                      <button type="button" disabled={busy} onClick={() => void saveAccess()} className="inline-flex items-center gap-2 rounded-xl bg-blue-500 px-4 py-2.5 text-sm font-medium disabled:opacity-50"><Save className="h-4 w-4" />Зберегти права</button>
                      <button type="button" disabled={busy} onClick={() => { if (!window.confirm(selectedUser.isActive ? "Деактивувати користувача та відкликати його сесії?" : "Активувати користувача?")) return; void runMutation(async () => { await client.updateUser(selectedUser.id, { isActive: !selectedUser.isActive, reason: selectedUser.isActive ? "Deactivated from Users & Access" : "Activated from Users & Access" }); setNotice(selectedUser.isActive ? "Користувача деактивовано." : "Користувача активовано."); }); }} className="inline-flex items-center gap-2 rounded-xl border border-white/10 px-4 py-2.5 text-sm disabled:opacity-50">{selectedUser.isActive ? <UserX className="h-4 w-4" /> : <UserCheck className="h-4 w-4" />}{selectedUser.isActive ? "Деактивувати" : "Активувати"}</button>
                      <button type="button" disabled={busy} onClick={() => { if (!window.confirm("Відкликати всі активні сесії цього користувача?")) return; void runMutation(async () => { const count = await client.revokeSessions(selectedUser.id, "Revoked from Users & Access"); setNotice(`Відкликано сесій: ${count}.`); }); }} className="inline-flex items-center gap-2 rounded-xl border border-white/10 px-4 py-2.5 text-sm disabled:opacity-50"><LogOut className="h-4 w-4" />Відкликати сесії</button>
                    </div>

                    <div className="rounded-2xl border border-white/8 bg-white/[0.025] p-4">
                      <h3 className="font-medium">Скидання пароля</h3>
                      <p className="mt-1 text-xs leading-5 text-slate-500">Новий пароль одразу хешується на backend. Після операції всі активні сесії користувача відкликаються.</p>
                      <div className="mt-3 flex flex-col gap-2 sm:flex-row"><input type="password" autoComplete="new-password" value={resetPassword} onChange={(event) => setResetPassword(event.target.value)} placeholder="Новий пароль (мін. 12 символів)" className={`${inputClass} flex-1`} /><button type="button" disabled={busy || resetPassword.length < 12} onClick={() => { const password = resetPassword; setResetPassword(""); if (!window.confirm("Скинути пароль і відкликати всі сесії?")) return; void runMutation(async () => { await client.resetPassword(selectedUser.id, password, "Password reset from Users & Access"); setNotice("Пароль змінено; активні сесії відкликано."); }); }} className="inline-flex items-center justify-center gap-2 rounded-xl border border-cyan-300/20 px-4 py-2.5 text-sm disabled:opacity-50"><KeyRound className="h-4 w-4" />Скинути пароль</button></div>
                    </div>

                    <div className="grid gap-2 text-xs text-slate-500 sm:grid-cols-3"><span>Створено: {formatDate(selectedUser.createdAt)}</span><span>Пароль змінено: {formatDate(selectedUser.passwordChangedAt)}</span><span>Останній вхід: {formatDate(selectedUser.lastAuthenticatedAt)}</span></div>
                  </div>
                )}
              </div>
            </section>
          </div>
        </main>
      </div>
    </div>
  );
}

function PermissionGrid({ options, selected, onToggle }: { options: LocalUserPermissionOption[]; selected: SecurityEffectivePermission[]; onToggle: (permission: SecurityEffectivePermission) => void }) {
  return <div className="mt-4 grid gap-2 sm:grid-cols-2 xl:grid-cols-3">{options.map((option) => <label key={option.value} className="flex cursor-pointer items-start gap-3 rounded-xl border border-white/8 bg-white/[0.025] p-3 text-sm"><input type="checkbox" checked={selected.includes(option.value)} onChange={() => onToggle(option.value)} className="mt-1" /><span><span className="block text-slate-200">{permissionLabels[option.value] ?? option.value}</span><span className="mt-1 block text-[11px] text-slate-500">{option.value}</span></span></label>)}</div>;
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return <label className="block"><span className="mb-1.5 block text-xs font-medium text-slate-400">{label}</span>{children}</label>;
}

function Notice({ tone, text }: { tone: "error" | "success"; text: string }) {
  return <div className={`rounded-2xl border px-4 py-3 text-sm ${tone === "error" ? "border-rose-400/20 bg-rose-400/[0.06] text-rose-200" : "border-emerald-400/20 bg-emerald-400/[0.06] text-emerald-200"}`}>{text}</div>;
}

function UsersGate({ title, message }: { title: string; message: string }) {
  return <main className="grid min-h-screen place-items-center bg-[#06142a] p-4 text-slate-100"><section className="w-full max-w-lg rounded-3xl border border-cyan-400/15 bg-[#091a31]/95 p-6"><div className="flex items-start gap-3"><div className="grid h-12 w-12 place-items-center rounded-2xl border border-cyan-300/20 bg-cyan-400/10"><UsersRound className="h-6 w-6 text-cyan-300" /></div><div><p className="text-xs tracking-[0.2em] text-cyan-300 uppercase">NEXOLAB Users & Access</p><h1 className="mt-1 text-xl font-semibold">{title}</h1></div></div><p className="mt-5 text-sm leading-6 text-slate-400">{message}</p></section></main>;
}

function fallbackRoles(): LocalUserRoleOption[] {
  return (Object.entries(roleFallbackLabels) as [SecurityProductRole, string][]).map(([value, label]) => ({ value, label, fullAccess: value === "administrator", permissionsEditable: value !== "administrator" }));
}

function roleLabel(role: SecurityProductRole, roles: LocalUserRoleOption[]): string {
  return roles.find((item) => item.value === role)?.label ?? roleFallbackLabels[role];
}

function togglePermission(current: SecurityEffectivePermission[], permission: SecurityEffectivePermission): SecurityEffectivePermission[] {
  return current.includes(permission) ? current.filter((item) => item !== permission) : [...current, permission].sort();
}

function errorMessage(cause: unknown): string {
  if (cause instanceof LocalUserAdminApiError) return `${cause.message} (${cause.code})`;
  return cause instanceof Error ? cause.message : "Невідома помилка керування користувачами.";
}

function formatDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("uk-UA");
}

const inputClass = "w-full rounded-xl border border-white/10 bg-[#06142a] px-3 py-2.5 text-sm text-slate-100 outline-none transition focus:border-cyan-300/40";
