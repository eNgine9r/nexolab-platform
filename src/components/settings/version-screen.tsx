"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import {
  AlertTriangle,
  ArchiveRestore,
  CalendarClock,
  CircleCheck,
  PackageCheck,
  RefreshCcw,
  Rocket,
  Search,
  ShieldCheck,
  WifiOff,
} from "lucide-react";

import { SecurityGate } from "@/components/dashboard/security-gate";
import { Sidebar } from "@/components/dashboard/sidebar";
import { Topbar } from "@/components/dashboard/topbar";
import { createRuntimeCredentialProvider } from "@/features/security/auth-runtime";
import { createAuthenticatedFetch } from "@/features/security/security-session";
import {
  VersionManagementClient,
  type UpdateCheck,
  type VersionAction,
  type VersionCatalogItem,
  type VersionSnapshot,
} from "@/features/settings/version-management";
import { useDashboardSecurity } from "@/hooks/use-dashboard-security";
import { getTelemetryRuntimeConfig } from "@/lib/telemetry/runtime-config";

const UPDATE_CHECK_POLL_MS = 2000;
const UPDATE_CHECK_TIMEOUT_MS = 30000;

export function VersionScreen() {
  const router = useRouter();
  const security = useDashboardSecurity();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [snapshot, setSnapshot] = useState<VersionSnapshot | null>(null);
  const [loading, setLoading] = useState(false);
  const [policySaving, setPolicySaving] = useState(false);
  const [checkPending, setCheckPending] = useState(false);
  const [checkRequestedAt, setCheckRequestedAt] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<{ item: VersionCatalogItem; action: VersionAction } | null>(null);
  const [confirmation, setConfirmation] = useState("");
  const [reason, setReason] = useState("");

  const runtime = useMemo(() => {
    try {
      const value = getTelemetryRuntimeConfig();
      return value.mode === "live" ? value : null;
    } catch {
      return null;
    }
  }, []);
  const client = useMemo(() => {
    if (!runtime?.apiBaseUrl || !security.membership) return null;
    const credentials = createRuntimeCredentialProvider(
      runtime.apiBaseUrl,
      security.membership.organizationId,
    );
    return new VersionManagementClient(
      runtime.apiBaseUrl,
      createAuthenticatedFetch(fetch.bind(globalThis), credentials),
    );
  }, [runtime, security.membership]);
  const allowed = security.membership?.permissions.includes("project_versions.manage") ?? false;

  const refresh = useCallback(async () => {
    if (!client || !allowed) return;
    setLoading(true);
    setError(null);
    try {
      setSnapshot(await client.read());
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Version API недоступний.");
    } finally {
      setLoading(false);
    }
  }, [allowed, client]);

  useEffect(() => {
    if (security.state !== "ready" || !client || !allowed) return;
    const id = window.setTimeout(() => void refresh(), 0);
    return () => window.clearTimeout(id);
  }, [security.state, client, allowed, refresh]);
  useEffect(() => {
    if (!snapshot?.activeOperation) return;
    const id = window.setInterval(() => void refresh(), 3000);
    return () => window.clearInterval(id);
  }, [refresh, snapshot?.activeOperation]);
  useEffect(() => {
    if (!checkPending && snapshot?.updateCheck?.status !== "checking") return;
    const id = window.setInterval(() => void refresh(), UPDATE_CHECK_POLL_MS);
    return () => window.clearInterval(id);
  }, [checkPending, refresh, snapshot?.updateCheck?.status]);
  useEffect(() => {
    if (!checkPending) return;
    const id = window.setTimeout(() => setCheckPending(false), UPDATE_CHECK_TIMEOUT_MS);
    return () => window.clearTimeout(id);
  }, [checkPending]);
  useEffect(() => {
    const completedAt = snapshot?.updateCheck?.completedAt;
    if (!checkPending || !checkRequestedAt || !completedAt) return;
    if (Date.parse(completedAt) >= Date.parse(checkRequestedAt)) {
      setCheckPending(false);
    }
  }, [checkPending, checkRequestedAt, snapshot?.updateCheck?.completedAt]);

  if (security.mode === "demo")
    return (
      <VersionGate
        title="Version management недоступний у demo mode"
        message="Цей workspace читає лише локальне deployment evidence."
      />
    );
  if (["loading", "unauthenticated", "forbidden", "error"].includes(security.state))
    return (
      <SecurityGate
        state={security.state as "loading" | "unauthenticated" | "forbidden" | "error"}
        error={security.error}
        errorCode={security.errorCode}
        diagnostics={security.diagnostics}
        onRetry={security.retry}
      />
    );
  if (!security.session || !security.membership)
    return (
      <VersionGate title="Організацію не вибрано" message="Потрібне активне administrator membership." />
    );
  if (!allowed)
    return (
      <VersionGate
        title="Доступ заборонено"
        message="Лише адміністратор має project_versions.manage; backend також повертає 403."
      />
    );
  if (!client)
    return (
      <VersionGate
        title="Local API недоступний"
        message="Version management потребує LOCAL_LAN Telemetry Service."
      />
    );

  const openAction = (item: VersionCatalogItem) => {
    const action: VersionAction =
      item.bundleId === snapshot?.current?.previousBundleId ? "rollback" : "update";
    setSelected({ item, action });
    setConfirmation("");
    setReason("");
    setError(null);
  };
  const expected = selected
    ? `${selected.action === "update" ? "APPLY" : "ROLLBACK"} ${selected.item.bundleId}`
    : "";
  const submit = async () => {
    if (!selected) return;
    setLoading(true);
    setError(null);
    try {
      await client.requestAction({
        action: selected.action,
        targetBundleId: selected.item.bundleId,
        confirmation,
        reason,
      });
      setSelected(null);
      await refresh();
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Операцію не створено.");
    } finally {
      setLoading(false);
    }
  };
  const toggleAutomaticUpdates = async () => {
    if (!snapshot) return;
    setPolicySaving(true);
    setError(null);
    try {
      const updatePolicy = await client.setAutomaticUpdates(
        !snapshot.updatePolicy.automaticUpdatesEnabled,
      );
      setSnapshot((current) => (current ? { ...current, updatePolicy } : current));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Політику оновлень не збережено.");
      await refresh();
    } finally {
      setPolicySaving(false);
    }
  };
  const requestUpdateCheck = async () => {
    setError(null);
    setCheckPending(true);
    try {
      const queued = await client.requestUpdateCheck("Manual Settings update check");
      setCheckRequestedAt(queued.requestedAt);
      await refresh();
    } catch (cause) {
      setCheckPending(false);
      setError(cause instanceof Error ? cause.message : "Перевірку оновлень не створено.");
    }
  };
  const candidatePackage = snapshot?.updateCheck?.targetCommit
    ? snapshot.catalog.find((item) => item.sourceCommit === snapshot.updateCheck?.targetCommit) ?? null
    : null;

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
          title="Версія NEXOLAB"
          onMenuOpen={() => setSidebarOpen(true)}
          showCreateSession={false}
          securitySession={security.session}
          selectedMembership={security.membership}
          onOrganizationChange={security.selectOrganization}
          onSignOut={() => void security.signOut().then(() => router.replace("/login"))}
        />
        <main className="p-4 xl:p-6">
          <div className="mx-auto max-w-[1500px] space-y-5">
            <section className="rounded-3xl border border-cyan-300/10 bg-[#091a31]/90 p-6">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div>
                  <p className="text-xs tracking-[.22em] text-cyan-300 uppercase">Offline release control</p>
                  <h1 className="mt-1 text-2xl font-semibold">Системна версія</h1>
                  <p className="mt-2 text-sm text-slate-400">
                    GitHub використовується тільки як optional update-plane. Runtime, validated packages,
                    backup, schema compatibility та readiness залишаються локальними gates.
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => void refresh()}
                  disabled={loading}
                  className="inline-flex items-center gap-2 rounded-xl border border-white/10 px-4 py-2.5 text-sm disabled:opacity-50"
                >
                  <RefreshCcw className="h-4 w-4" />
                  Оновити стан
                </button>
              </div>
            </section>
            {error ? <Notice>{error}</Notice> : null}
            {!snapshot && loading ? (
              <p className="text-sm text-slate-400">Завантаження локального evidence…</p>
            ) : null}
            {snapshot ? (
              <>
                <section
                  aria-label="Поточна версія"
                  className="grid gap-4 rounded-3xl border border-white/10 bg-[#091a31] p-5 md:grid-cols-2 xl:grid-cols-4"
                >
                  <Metric label="Release" value={snapshot.current?.release ?? "Невідомо"} />
                  <Metric label="Commit" value={snapshot.current?.sourceCommit ?? "—"} />
                  <Metric label="Schema" value={snapshot.current?.schemaHead ?? "—"} />
                  <Metric
                    label="Runtime / health"
                    value={
                      snapshot.current ? `${snapshot.current.runtimeMode} / ${snapshot.current.health}` : "—"
                    }
                  />
                  <Metric label="Build" value={snapshot.current?.buildTimestamp ?? "—"} />
                  <Metric label="Deployed" value={snapshot.current?.deployedAt ?? "—"} />
                  <Metric label="Previous" value={snapshot.current?.previousRelease ?? "—"} />
                  <Metric
                    label="Evidence"
                    value={snapshot.current?.runtimeStateKnown ? "known packaged state" : "unknown state"}
                  />
                  {!snapshot.current?.knownPackagedRelease ? (
                    <div className="md:col-span-2 xl:col-span-4">
                      <Notice>
                        Поточний runtime не прив’язаний до validated package. Будь-яка mutation заблокована.
                      </Notice>
                    </div>
                  ) : null}
                </section>

                <section
                  aria-labelledby="automatic-update-heading"
                  className="rounded-3xl border border-white/10 bg-[#091a31] p-5"
                >
                  <div className="flex flex-wrap items-start justify-between gap-4">
                    <div className="max-w-3xl">
                      <div className="flex items-center gap-2">
                        <CalendarClock className="h-5 w-5 text-cyan-300" />
                        <h2 id="automatic-update-heading" className="text-lg font-semibold">
                          Автоматичні оновлення
                        </h2>
                      </div>
                      <p className="mt-2 text-sm text-slate-400">
                        Щодня о 02:00 локального системного часу Raspberry Pi. Якщо політика вимкнена, host
                        timer завершується до GitHub discovery і не перезапускає NEXOLAB.
                      </p>
                    </div>
                    <button
                      type="button"
                      role="switch"
                      aria-label="Автоматичні оновлення"
                      aria-checked={snapshot.updatePolicy.automaticUpdatesEnabled}
                      onClick={() => void toggleAutomaticUpdates()}
                      disabled={policySaving || Boolean(snapshot.activeOperation)}
                      className="inline-flex items-center gap-3 rounded-2xl border border-white/10 px-4 py-3 text-sm disabled:opacity-50"
                    >
                      <span
                        aria-hidden="true"
                        className={`relative h-6 w-11 rounded-full transition-colors ${
                          snapshot.updatePolicy.automaticUpdatesEnabled ? "bg-emerald-500" : "bg-slate-700"
                        }`}
                      >
                        <span
                          className={`absolute top-1 h-4 w-4 rounded-full bg-white transition-transform ${
                            snapshot.updatePolicy.automaticUpdatesEnabled
                              ? "translate-x-6"
                              : "translate-x-1"
                          }`}
                        />
                      </span>
                      {policySaving
                        ? "Збереження…"
                        : snapshot.updatePolicy.automaticUpdatesEnabled
                          ? "Увімкнено"
                          : "Вимкнено"}
                    </button>
                  </div>

                  <div className="mt-5 grid gap-3 md:grid-cols-3">
                    <Metric label="Розклад" value={`Щодня о ${snapshot.updatePolicy.scheduleLocalTime}`} />
                    <Metric
                      label="Host timezone"
                      value="Локальний системний час Raspberry Pi"
                    />
                    <Metric
                      label="Політика змінена"
                      value={snapshot.updatePolicy.updatedAt ?? "Ще не змінювалась"}
                    />
                  </div>

                  <div className="mt-5 flex flex-wrap items-center gap-3 border-t border-white/10 pt-5">
                    <button
                      type="button"
                      onClick={() => void requestUpdateCheck()}
                      disabled={checkPending || loading || Boolean(snapshot.activeOperation)}
                      className="inline-flex items-center gap-2 rounded-xl bg-blue-500 px-4 py-2.5 text-sm font-medium disabled:opacity-40"
                    >
                      {checkPending || snapshot.updateCheck?.status === "checking" ? (
                        <RefreshCcw className="h-4 w-4 animate-spin motion-reduce:animate-none" />
                      ) : (
                        <Search className="h-4 w-4" />
                      )}
                      {checkPending ? "Перевіряємо…" : "Перевірити оновлення зараз"}
                    </button>
                    <p className="text-xs text-slate-500">
                      Manual check доступний незалежно від стану автоматичних оновлень.
                    </p>
                  </div>

                  <UpdateCheckPanel
                    check={snapshot.updateCheck}
                    checkPending={checkPending}
                    candidatePackage={candidatePackage}
                    onActivate={openAction}
                    activeOperation={Boolean(snapshot.activeOperation)}
                  />
                </section>

                {snapshot.activeOperation ? (
                  <section className="rounded-2xl border border-amber-300/20 bg-amber-400/5 p-4 text-sm">
                    <b>Операція {snapshot.activeOperation.status}:</b>{" "}
                    {snapshot.activeOperation.sourceRelease} → {snapshot.activeOperation.targetRelease}. Host
                    worker виконує backup і verification.
                  </section>
                ) : null}
                <section>
                  <h2 className="mb-3 text-lg font-semibold">Локальний каталог</h2>
                  <div className="grid gap-3 lg:grid-cols-2">
                    {snapshot.catalog.length ? (
                      snapshot.catalog.map((item) => (
                        <article
                          key={item.bundleId}
                          className="rounded-2xl border border-white/10 bg-[#091a31] p-5"
                        >
                          <div className="flex items-start justify-between gap-3">
                            <div>
                              <h3 className="font-semibold">{item.release}</h3>
                              <p className="mt-1 font-mono text-xs text-slate-500">
                                {item.sourceCommit} · {item.platform}
                              </p>
                            </div>
                            <PackageCheck className="h-5 w-5 text-emerald-300" />
                          </div>
                          <p className="mt-3 text-xs text-slate-400">
                            Schema {item.schemaHead} · manifest {item.manifestSha256}
                          </p>
                          {item.bundleId !== snapshot.current?.bundleId ? (
                            <button
                              type="button"
                              onClick={() => openAction(item)}
                              disabled={Boolean(snapshot.activeOperation)}
                              className="mt-4 inline-flex items-center gap-2 rounded-xl bg-blue-500 px-4 py-2 text-sm font-medium disabled:opacity-40"
                            >
                              {item.bundleId === snapshot.current?.previousBundleId ? (
                                <ArchiveRestore className="h-4 w-4" />
                              ) : (
                                <Rocket className="h-4 w-4" />
                              )}
                              {item.bundleId === snapshot.current?.previousBundleId
                                ? "Підготувати rollback"
                                : "Підготувати update"}
                            </button>
                          ) : (
                            <p className="mt-4 text-xs text-emerald-300">Встановлено</p>
                          )}
                        </article>
                      ))
                    ) : (
                      <p className="text-sm text-slate-400">
                        Нових validated packages немає. Staging працює локально й не потребує GitHub.
                      </p>
                    )}
                  </div>
                </section>
                {snapshot.rejectedPackages.length ? (
                  <Notice>
                    Відхилено package manifests:{" "}
                    {snapshot.rejectedPackages.map((item) => item.directory).join(", ")}.
                  </Notice>
                ) : null}
                <section>
                  <h2 className="mb-3 text-lg font-semibold">Історія</h2>
                  <div className="overflow-x-auto rounded-2xl border border-white/10">
                    <table className="w-full text-left text-sm">
                      <thead className="bg-white/5 text-slate-400">
                        <tr>
                          <th className="p-3">Час / actor</th>
                          <th className="p-3">Дія</th>
                          <th className="p-3">Версії / commit</th>
                          <th className="p-3">Результат</th>
                          <th className="p-3">Backup</th>
                        </tr>
                      </thead>
                      <tbody>
                        {snapshot.history.map((item) => (
                          <tr key={item.id} className="border-t border-white/5">
                            <td className="p-3">
                              {item.startedAt}
                              <span className="mt-1 block text-xs text-slate-500">{item.actorSubject}</span>
                            </td>
                            <td className="p-3">{item.action}</td>
                            <td className="p-3">
                              {item.sourceRelease} → {item.targetRelease}
                              <span className="mt-1 block font-mono text-xs text-slate-500">
                                {item.targetCommit}
                              </span>
                            </td>
                            <td className="p-3">{item.status}</td>
                            <td className="p-3 font-mono text-xs">{item.backupEvidenceId ?? "—"}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </section>
              </>
            ) : null}
            {selected ? (
              <section
                role="dialog"
                aria-label="Підтвердження зміни версії"
                className="rounded-3xl border border-amber-300/30 bg-[#101b2d] p-5"
              >
                <div className="flex gap-3">
                  <AlertTriangle className="h-6 w-6 shrink-0 text-amber-300" />
                  <div className="flex-1">
                    <h2 className="font-semibold">High-risk confirmation: {selected.action}</h2>
                    <p className="mt-2 text-sm text-slate-400">
                      Введіть точно <code className="text-amber-200">{expected}</code>. Невідома schema
                      compatibility або backup failure зупинять операцію.
                    </p>
                    <input
                      aria-label="Точне підтвердження"
                      value={confirmation}
                      onChange={(event) => setConfirmation(event.target.value)}
                      className="mt-4 w-full rounded-xl border border-white/10 bg-black/20 px-3 py-2 font-mono text-sm"
                    />
                    <textarea
                      aria-label="Причина"
                      value={reason}
                      onChange={(event) => setReason(event.target.value)}
                      placeholder="Причина (необов’язково)"
                      className="mt-3 w-full rounded-xl border border-white/10 bg-black/20 px-3 py-2 text-sm"
                    />
                    <div className="mt-3 flex gap-2">
                      <button
                        type="button"
                        onClick={() => void submit()}
                        disabled={loading || confirmation !== expected}
                        className="rounded-xl bg-amber-500 px-4 py-2 text-sm font-semibold text-slate-950 disabled:opacity-40"
                      >
                        Створити контрольовану операцію
                      </button>
                      <button
                        type="button"
                        onClick={() => setSelected(null)}
                        className="rounded-xl border border-white/10 px-4 py-2 text-sm"
                      >
                        Скасувати
                      </button>
                    </div>
                  </div>
                </div>
              </section>
            ) : null}
          </div>
        </main>
      </div>
    </div>
  );
}

function UpdateCheckPanel({
  check,
  checkPending,
  candidatePackage,
  onActivate,
  activeOperation,
}: {
  check: UpdateCheck | null;
  checkPending: boolean;
  candidatePackage: VersionCatalogItem | null;
  onActivate: (item: VersionCatalogItem) => void;
  activeOperation: boolean;
}) {
  if (checkPending || check?.status === "checking") {
    return (
      <div className="mt-5 rounded-2xl border border-cyan-300/15 bg-cyan-300/5 p-4 text-sm">
        <div className="flex items-center gap-2 text-cyan-100">
          <RefreshCcw className="h-4 w-4 animate-spin motion-reduce:animate-none" />
          Host worker перевіряє GitHub update-plane. Поточний runtime не перезапускається.
        </div>
      </div>
    );
  }
  if (!check) {
    return (
      <div className="mt-5 rounded-2xl border border-white/10 bg-black/10 p-4 text-sm text-slate-400">
        Перевірка GitHub ще не запускалась. LOCAL_LAN monitoring від цього не залежить.
      </div>
    );
  }
  if (check.resultCode === "up_to_date") {
    return (
      <UpdateState icon={<CircleCheck className="h-5 w-5 text-emerald-300" />} title="Встановлено актуальну версію">
        GitHub main не містить новішого fast-forward target для поточного runtime.
      </UpdateState>
    );
  }
  if (check.resultCode === "github_unavailable" || check.status === "failed") {
    return (
      <UpdateState icon={<WifiOff className="h-5 w-5 text-amber-300" />} title="Update-plane недоступний">
        GitHub не використовується для core monitoring. Поточний LOCAL_LAN runtime продовжує працювати без
        змін.
      </UpdateState>
    );
  }
  if (check.candidateAvailable) {
    return (
      <UpdateState icon={<ShieldCheck className="h-5 w-5 text-cyan-300" />} title="Знайдено новішу ревізію">
        <p>
          <span className="font-mono text-xs text-slate-300">{check.currentCommit ?? "unknown"}</span>{" "}
          → <span className="font-mono text-xs text-slate-300">{check.targetCommit ?? "unknown"}</span>
        </p>
        {check.activationEligible && candidatePackage ? (
          <button
            type="button"
            onClick={() => onActivate(candidatePackage)}
            disabled={activeOperation}
            className="mt-3 inline-flex items-center gap-2 rounded-xl bg-blue-500 px-4 py-2 text-sm font-medium disabled:opacity-40"
          >
            <Rocket className="h-4 w-4" />
            Оновити зараз
          </button>
        ) : (
          <p className="mt-2 text-amber-100">
            Активація заблокована: {updateBlockReason(check.blockedReason)}. Remote commit сам по собі не є
            installation authority.
          </p>
        )}
      </UpdateState>
    );
  }
  return (
    <UpdateState icon={<AlertTriangle className="h-5 w-5 text-amber-300" />} title="Перевірку завершено з блокуванням">
      {check.message ?? updateBlockReason(check.blockedReason)}
    </UpdateState>
  );
}

function UpdateState({
  icon,
  title,
  children,
}: {
  icon: React.ReactNode;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="mt-5 rounded-2xl border border-white/10 bg-black/10 p-4 text-sm">
      <div className="flex items-start gap-3">
        <div className="mt-0.5 shrink-0">{icon}</div>
        <div>
          <p className="font-medium text-slate-100">{title}</p>
          <div className="mt-1 text-slate-400">{children}</div>
        </div>
      </div>
    </div>
  );
}

function updateBlockReason(reason: string | null): string {
  switch (reason) {
    case "validated_package_required":
      return "для target commit ще немає validated local package";
    case "dirty_tree":
      return "tracked working tree містить локальні зміни";
    case "non_fast_forward":
      return "target не є fast-forward продовженням поточного lineage";
    case "wrong_repository":
      return "configured origin не відповідає NEXOLAB repository";
    case "wrong_branch":
      return "локальна checkout-гілка не main";
    case "runtime_state_unknown":
      return "поточна deployed identity недостатньо підтверджена";
    case null:
      return "host eligibility gate не пройдено";
    default:
      return reason;
  }
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs tracking-wider text-slate-500 uppercase">{label}</p>
      <p className="mt-1 font-mono text-sm break-all text-slate-100">{value}</p>
    </div>
  );
}
function Notice({ children }: { children: React.ReactNode }) {
  return (
    <div
      role="alert"
      className="rounded-2xl border border-amber-300/20 bg-amber-400/5 p-4 text-sm text-amber-100"
    >
      {children}
    </div>
  );
}
function VersionGate({ title, message }: { title: string; message: string }) {
  return (
    <main className="grid min-h-screen place-items-center bg-[#06142a] p-6 text-slate-100">
      <section className="max-w-xl rounded-3xl border border-white/10 bg-[#091a31] p-6">
        <h1 className="text-xl font-semibold">{title}</h1>
        <p className="mt-2 text-sm text-slate-400">{message}</p>
      </section>
    </main>
  );
}
