"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import {
  AlertTriangle,
  ArrowLeftRight,
  CheckCircle2,
  Download,
  History,
  PackageCheck,
  RefreshCw,
  RotateCcw,
  ShieldCheck,
} from "lucide-react";

import { SecurityGate } from "@/components/dashboard/security-gate";
import { Sidebar } from "@/components/dashboard/sidebar";
import { Topbar } from "@/components/dashboard/topbar";
import { VersionOperationProgress } from "@/components/settings/version-operation-progress";
import { createRuntimeCredentialProvider } from "@/features/security/auth-runtime";
import { createAuthenticatedFetch } from "@/features/security/security-session";
import { versionConfirmationPhrase } from "@/features/settings/version-confirmation";
import {
  VersionManagementClient,
  type UpdateCheck,
  type VersionAction,
  type VersionCatalogItem,
  type VersionOperation,
  type VersionSnapshot,
} from "@/features/settings/version-management";
import { useDashboardSecurity } from "@/hooks/use-dashboard-security";
import { getTelemetryRuntimeConfig } from "@/lib/telemetry/runtime-config";

const POLL_INTERVAL_MS = 3000;

export function VersionScreen() {
  const router = useRouter();
  const security = useDashboardSecurity();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [snapshot, setSnapshot] = useState<VersionSnapshot | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [policyBusy, setPolicyBusy] = useState(false);
  const [checkBusy, setCheckBusy] = useState(false);
  const [checkQueued, setCheckQueued] = useState(false);
  const [selectedBundleId, setSelectedBundleId] = useState<string | null>(null);
  const [action, setAction] = useState<VersionAction>("update");
  const [confirmation, setConfirmation] = useState("");
  const [reason, setReason] = useState("");
  const [showConfirm, setShowConfirm] = useState(false);

  const runtime = useMemo(() => {
    try {
      const value = getTelemetryRuntimeConfig();
      return value.mode === "live" ? value : null;
    } catch {
      return null;
    }
  }, []);
  const allowed = security.membership?.permissions.includes("project_versions.manage") ?? false;
  const client = useMemo(() => {
    if (!runtime?.apiBaseUrl || !security.membership || !allowed) return null;
    const credentials = createRuntimeCredentialProvider(
      runtime.apiBaseUrl,
      security.membership.organizationId,
    );
    return new VersionManagementClient(
      runtime.apiBaseUrl,
      createAuthenticatedFetch(fetch.bind(globalThis), credentials),
    );
  }, [allowed, runtime, security.membership]);

  const refresh = useCallback(async () => {
    if (!client || !allowed) return;
    setLoading(true);
    setError(null);
    try {
      const next = await client.read();
      setSnapshot(next);
      if (next.updateCheck && next.updateCheck.status !== "checking") {
        setCheckQueued(false);
      }
    } catch (cause) {
      setError(describeError(cause));
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
    if (!snapshot?.activeOperation && !checkQueued && snapshot?.updateCheck?.status !== "checking") return;
    const id = window.setInterval(() => void refresh(), POLL_INTERVAL_MS);
    return () => window.clearInterval(id);
  }, [checkQueued, refresh, snapshot?.activeOperation, snapshot?.updateCheck?.status]);

  const current = snapshot?.current ?? null;
  const selected = snapshot?.catalog.find((item) => item.bundleId === selectedBundleId) ?? null;
  const availableTargets = useMemo(
    () => snapshot?.catalog.filter((item) => !current || item.bundleId !== current.bundleId) ?? [],
    [current, snapshot?.catalog],
  );
  const updateCheck = snapshot?.updateCheck ?? null;
  const automaticUpdatesEnabled = snapshot?.updatePolicy.automaticUpdatesEnabled ?? false;
  const updateCandidate = useMemo(
    () =>
      updateCheck?.candidateBundleId
        ? (snapshot?.catalog.find((item) => item.bundleId === updateCheck.candidateBundleId) ?? null)
        : null,
    [snapshot?.catalog, updateCheck?.candidateBundleId],
  );

  useEffect(() => {
    if (updateCandidate && updateCheck?.activationEligible) {
      setSelectedBundleId(updateCandidate.bundleId);
      setAction("update");
    }
  }, [updateCandidate, updateCheck?.activationEligible]);

  if (security.mode === "demo") {
    return (
      <VersionGate
        title="Version management недоступний у demo mode"
        message="Цей workspace читає лише локальне deployment evidence."
      />
    );
  }
  if (["loading", "unauthenticated", "forbidden", "error"].includes(security.state)) {
    return (
      <SecurityGate
        state={security.state as "loading" | "unauthenticated" | "forbidden" | "error"}
        error={security.error}
        errorCode={security.errorCode}
        diagnostics={security.diagnostics}
        onRetry={security.retry}
      />
    );
  }
  if (!security.session || !security.membership) {
    return (
      <VersionGate title="Організацію не вибрано" message="Потрібне активне administrator membership." />
    );
  }
  if (!allowed) {
    return (
      <VersionGate
        title="Доступ заборонено"
        message="Лише адміністратор має project_versions.manage; backend також повертає 403."
      />
    );
  }
  if (!client) {
    return (
      <VersionGate
        title="Local API недоступний"
        message="Version management потребує LOCAL_LAN Telemetry Service."
      />
    );
  }

  async function changeAutomaticUpdates(enabled: boolean) {
    if (policyBusy) return;
    setPolicyBusy(true);
    setError(null);
    try {
      const persisted = await client.setAutomaticUpdates(enabled);
      setSnapshot((previous) =>
        previous
          ? {
              ...previous,
              updatePolicy: persisted,
            }
          : previous,
      );
    } catch (cause) {
      setError(describeError(cause));
      await refresh();
    } finally {
      setPolicyBusy(false);
    }
  }

  async function checkForUpdates() {
    if (checkBusy || snapshot?.activeOperation) return;
    setCheckBusy(true);
    setError(null);
    try {
      await client.requestUpdateCheck("operator requested GitHub update discovery");
      setCheckQueued(true);
    } catch (cause) {
      setError(describeError(cause));
    } finally {
      setCheckBusy(false);
    }
  }

  async function submitAction() {
    if (!selected || busy) return;
    setBusy(true);
    setError(null);
    try {
      await client.requestAction({
        action,
        targetBundleId: selected.bundleId,
        confirmation,
        reason,
      });
      setShowConfirm(false);
      setConfirmation("");
      setReason("");
      await refresh();
    } catch (cause) {
      setError(describeError(cause));
    } finally {
      setBusy(false);
    }
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
                  <p className="text-xs tracking-[.22em] text-cyan-300 uppercase">
                    Local version control / optional GitHub update plane
                  </p>
                  <h1 className="mt-1 text-2xl font-semibold">Системна версія</h1>
                  <p className="mt-2 max-w-4xl text-sm leading-6 text-slate-400">
                    LOCAL_LAN monitoring не залежить від GitHub. Remote revision може стати кандидатом лише
                    після GREEN main CI та відповідності validated local package; браузер не виконує shell і
                    не отримує GitHub credentials.
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => void refresh()}
                  disabled={loading}
                  className="inline-flex items-center gap-2 rounded-xl border border-white/10 px-4 py-2.5 text-sm disabled:opacity-50"
                >
                  <RefreshCw
                    className={`h-4 w-4 ${loading ? "animate-spin motion-reduce:animate-none" : ""}`}
                  />
                  Оновити стан
                </button>
              </div>
            </section>

            {error ? <Notice>{error}</Notice> : null}
            {!snapshot && loading ? (
              <p className="text-sm text-slate-400">Завантаження локального version evidence…</p>
            ) : null}

            {snapshot ? (
              <>
                <section className="grid gap-4 xl:grid-cols-[1.15fr_.85fr]">
                  <div className="rounded-2xl border border-white/10 bg-[#091a31] p-5">
                    <div className="flex items-center gap-3">
                      <PackageCheck className="h-5 w-5 text-cyan-200" />
                      <h2 className="text-lg font-semibold">Поточна версія</h2>
                    </div>
                    {current ? (
                      <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
                        <Fact label="Release" value={current.release} />
                        <Fact label="Bundle" value={current.bundleId} mono />
                        <Fact label="Commit" value={shortCommit(current.sourceCommit)} mono title={current.sourceCommit} />
                        <Fact label="Schema" value={current.schemaHead} mono />
                        <Fact label="Platform" value={current.platform} />
                        <Fact label="Runtime / health" value={`${current.runtimeMode} / ${current.health}`} />
                        <Fact label="Deployed" value={formatTime(current.deployedAt)} />
                        <Fact label="Packaged evidence" value={current.knownPackagedRelease ? "Так" : "Ні"} />
                        <Fact label="Runtime state" value={current.runtimeStateKnown ? "known" : "unknown"} />
                      </div>
                    ) : (
                      <Notice>
                        Runtime не має canonical packaged version evidence. Mutation заблокована до bootstrap
                        або import останньої відомої версії.
                      </Notice>
                    )}
                  </div>

                  <div className="rounded-2xl border border-white/10 bg-[#091a31] p-5">
                    <div className="flex items-center gap-3">
                      <ShieldCheck className="h-5 w-5 text-emerald-200" />
                      <h2 className="text-lg font-semibold">Safety gates</h2>
                    </div>
                    <ul className="mt-4 grid gap-2 text-sm text-slate-300">
                      {[
                        "validated local package identity",
                        "platform and schema compatibility",
                        "capacity preflight before mutation",
                        "PostgreSQL backup before runtime mutation",
                        "exact post-update API / Dashboard / Device Agent readiness",
                        "worker health and advancing telemetry evidence",
                        "no Modbus or controller write path",
                      ].map((item) => (
                        <li key={item} className="flex gap-2">
                          <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-300" />
                          <span>{item}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                </section>

                <section className="rounded-2xl border border-white/10 bg-[#091a31] p-5">
                  <div className="flex flex-wrap items-start justify-between gap-4">
                    <div>
                      <p className="text-xs tracking-[.18em] text-slate-500 uppercase">GitHub update plane</p>
                      <h2 className="mt-1 text-lg font-semibold">Автоматичні оновлення</h2>
                      <p className="mt-1 max-w-3xl text-sm leading-6 text-slate-400">
                        Політика зберігається на host. Вимкнений режим не забороняє manual check, local offline
                        update або rollback.
                      </p>
                    </div>
                    <label className="flex items-center gap-3 rounded-xl border border-white/10 bg-black/10 px-4 py-3">
                      <span className="text-sm text-slate-300">
                        {automaticUpdatesEnabled ? "Увімкнено" : "Вимкнено"}
                      </span>
                      <button
                        type="button"
                        role="switch"
                        aria-checked={automaticUpdatesEnabled}
                        aria-label="Автоматичні оновлення"
                        disabled={policyBusy || Boolean(snapshot.activeOperation)}
                        onClick={() => void changeAutomaticUpdates(!automaticUpdatesEnabled)}
                        className={`relative h-6 w-11 rounded-full border transition focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cyan-300 disabled:cursor-not-allowed disabled:opacity-60 ${
                          automaticUpdatesEnabled
                            ? "border-emerald-300/60 bg-emerald-400/30"
                            : "border-white/20 bg-white/5"
                        }`}
                      >
                        <span
                          className={`absolute top-0.5 h-[18px] w-[18px] rounded-full bg-slate-100 transition-all ${
                            automaticUpdatesEnabled ? "left-[21px]" : "left-0.5"
                          }`}
                        />
                      </button>
                    </label>
                  </div>

                  <div className="mt-4 grid gap-3 md:grid-cols-3">
                    <Fact label="Schedule" value="Щодня о 02:00" />
                    <Fact
                      label="Automatic activation"
                      value={automaticUpdatesEnabled ? "Дозволена в 02:00" : "Вимкнена"}
                    />
                    <Fact
                      label="Last policy change"
                      value={snapshot.updatePolicy.updatedAt ? formatTime(snapshot.updatePolicy.updatedAt) : "—"}
                    />
                  </div>

                  <div className="mt-4 flex flex-wrap items-center gap-3">
                    <button
                      type="button"
                      disabled={checkBusy || Boolean(snapshot.activeOperation)}
                      onClick={() => void checkForUpdates()}
                      className="inline-flex items-center gap-2 rounded-xl border border-cyan-300/25 bg-cyan-300/8 px-4 py-2.5 text-sm text-cyan-100 disabled:opacity-50"
                    >
                      <RefreshCw
                        className={`h-4 w-4 ${checkBusy ? "animate-spin motion-reduce:animate-none" : ""}`}
                      />
                      {checkBusy ? "Запит передано…" : "Перевірити оновлення зараз"}
                    </button>
                    <span className="text-xs text-slate-500">Manual check працює при ON і OFF.</span>
                  </div>

                  <div className="mt-4 rounded-xl border border-white/10 bg-black/10 px-4 py-4">
                    {checkQueued ? (
                      <div role="status" className="flex items-center gap-2 text-sm text-cyan-100">
                        <RefreshCw className="h-4 w-4 animate-spin motion-reduce:animate-none" />
                        Перевіряємо…
                      </div>
                    ) : updateCheck ? (
                      <UpdateCheckSummary check={updateCheck} current={current} candidate={updateCandidate} />
                    ) : (
                      <p className="text-sm text-slate-500">
                        Ще не було update-plane перевірки. Monitoring runtime від цього не залежить.
                      </p>
                    )}
                  </div>
                </section>

                {snapshot.activeOperation ? (
                  <VersionOperationProgress operation={snapshot.activeOperation} />
                ) : null}

                <section className="grid gap-4 xl:grid-cols-[.9fr_1.1fr]">
                  <div className="rounded-2xl border border-white/10 bg-[#091a31] p-5">
                    <div className="flex items-center gap-3">
                      <ArrowLeftRight className="h-5 w-5 text-cyan-300" />
                      <h2 className="text-lg font-semibold">Локальні release packages</h2>
                    </div>
                    <p className="mt-2 text-sm leading-6 text-slate-400">
                      Remote commit сам по собі не є installation authority. Активація можлива лише для
                      validated package з локального catalog.
                    </p>
                    <div className="mt-4 grid gap-2">
                      {availableTargets.length ? (
                        availableTargets.map((item) => (
                          <PackageRow
                            key={item.bundleId}
                            item={item}
                            selected={selectedBundleId === item.bundleId}
                            onSelect={() => {
                              setSelectedBundleId(item.bundleId);
                              setAction(
                                item.bundleId === current?.previousBundleId ? "rollback" : "update",
                              );
                            }}
                          />
                        ))
                      ) : (
                        <p className="text-sm text-slate-500">
                          Інших validated packages у локальному catalog немає.
                        </p>
                      )}
                    </div>
                  </div>

                  <div className="rounded-2xl border border-white/10 bg-[#091a31] p-5">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <div>
                        <p className="text-xs tracking-[.18em] text-slate-500 uppercase">Controlled action</p>
                        <h2 className="mt-1 text-lg font-semibold">Update / rollback</h2>
                      </div>
                      <div className="flex rounded-lg border border-white/10 bg-black/10 p-1">
                        {(["update", "rollback"] as const).map((value) => (
                          <button
                            key={value}
                            type="button"
                            onClick={() => setAction(value)}
                            className={`rounded-md px-3 py-1.5 text-xs font-medium transition ${
                              action === value
                                ? "bg-cyan-300/15 text-cyan-100"
                                : "text-slate-500 hover:text-slate-300"
                            }`}
                          >
                            {value === "update" ? "Update" : "Rollback"}
                          </button>
                        ))}
                      </div>
                    </div>

                    {selected ? (
                      <div className="mt-4 grid gap-3">
                        <div className="grid gap-3 sm:grid-cols-2">
                          <Fact label="Target release" value={selected.release} />
                          <Fact
                            label="Target commit"
                            value={shortCommit(selected.sourceCommit)}
                            mono
                            title={selected.sourceCommit}
                          />
                          <Fact label="Target schema" value={selected.schemaHead} mono />
                          <Fact label="Platform" value={selected.platform} />
                        </div>
                        <label className="grid gap-1.5 text-sm">
                          <span className="text-slate-400">Reason / operator note</span>
                          <input
                            value={reason}
                            onChange={(event) => setReason(event.target.value)}
                            placeholder="Optional local audit note"
                            className="rounded-xl border border-white/10 bg-black/20 px-3 py-2 text-sm text-slate-100 outline-none focus:border-cyan-300/50"
                          />
                        </label>
                        <button
                          type="button"
                          disabled={!current?.runtimeStateKnown || Boolean(snapshot.activeOperation)}
                          onClick={() => setShowConfirm(true)}
                          className="inline-flex w-fit items-center gap-2 rounded-xl border border-amber-300/30 bg-amber-300/8 px-4 py-2.5 text-sm text-amber-100 disabled:opacity-50"
                        >
                          {action === "update" ? (
                            <Download className="h-4 w-4" />
                          ) : (
                            <RotateCcw className="h-4 w-4" />
                          )}
                          {action === "update" && updateCandidate?.bundleId === selected.bundleId
                            ? "Оновити зараз"
                            : action === "update"
                              ? "Підготувати update"
                              : "Підготувати rollback"}
                        </button>
                        {!current?.runtimeStateKnown ? (
                          <Notice>
                            Runtime state позначений як unknown; нова активація заблокована до operator
                            recovery.
                          </Notice>
                        ) : null}
                      </div>
                    ) : (
                      <p className="mt-4 text-sm text-slate-500">Оберіть validated package з локального catalog.</p>
                    )}
                  </div>
                </section>

                <section className="rounded-2xl border border-white/10 bg-[#091a31] p-5">
                  <div className="flex items-center gap-3">
                    <History className="h-5 w-5 text-cyan-300" />
                    <h2 className="text-lg font-semibold">Version history</h2>
                  </div>
                  <div className="mt-4 overflow-x-auto">
                    <table className="w-full min-w-[860px] text-left text-sm">
                      <thead className="text-xs tracking-[.12em] text-slate-500 uppercase">
                        <tr className="border-b border-white/10">
                          <th className="px-3 py-3 font-medium">Start</th>
                          <th className="px-3 py-3 font-medium">Action</th>
                          <th className="px-3 py-3 font-medium">From → To</th>
                          <th className="px-3 py-3 font-medium">Status</th>
                          <th className="px-3 py-3 font-medium">Actor</th>
                          <th className="px-3 py-3 font-medium">Evidence</th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-white/5">
                        {snapshot.history.length ? (
                          snapshot.history.map((operation) => (
                            <tr key={operation.id} className="text-slate-300">
                              <td className="px-3 py-3 text-slate-400">{formatTime(operation.startedAt)}</td>
                              <td className="px-3 py-3">{operation.action}</td>
                              <td className="px-3 py-3">
                                {operation.sourceRelease} → {operation.targetRelease}
                              </td>
                              <td className="px-3 py-3">
                                <OperationBadge operation={operation} />
                              </td>
                              <td className="px-3 py-3 text-slate-400">{operation.actorSubject}</td>
                              <td className="px-3 py-3 font-mono text-xs text-slate-500">
                                {operation.resultCode ?? "—"}
                                {operation.capacityEvidenceId ? ` · ${operation.capacityEvidenceId}` : ""}
                                {operation.backupEvidenceId ? ` · ${operation.backupEvidenceId}` : ""}
                              </td>
                            </tr>
                          ))
                        ) : (
                          <tr>
                            <td colSpan={6} className="px-3 py-5 text-center text-slate-500">
                              Історія update/rollback операцій порожня.
                            </td>
                          </tr>
                        )}
                      </tbody>
                    </table>
                  </div>
                </section>

                {snapshot.rejectedPackages.length ? (
                  <section className="rounded-2xl border border-amber-300/20 bg-amber-300/5 p-5">
                    <div className="flex items-center gap-2 text-amber-100">
                      <AlertTriangle className="h-5 w-5" />
                      <h2 className="font-semibold">Rejected packages</h2>
                    </div>
                    <div className="mt-3 grid gap-2 text-sm">
                      {snapshot.rejectedPackages.map((item) => (
                        <div key={item.directory} className="rounded-xl border border-amber-300/10 px-3 py-2">
                          <span className="font-mono text-xs text-amber-200">{item.directory}</span>
                          <span className="mx-2 text-amber-500">·</span>
                          <span className="text-amber-100">{item.code}</span>
                          <p className="mt-1 text-xs text-amber-100/70">{item.message}</p>
                        </div>
                      ))}
                    </div>
                  </section>
                ) : null}
              </>
            ) : null}
          </div>
        </main>
      </div>

      {showConfirm && selected ? (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm">
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="version-confirm-title"
            className="w-full max-w-lg rounded-2xl border border-amber-300/25 bg-[#091a31] p-5 shadow-2xl"
          >
            <div className="flex items-center gap-3">
              <AlertTriangle className="h-5 w-5 text-amber-200" />
              <div>
                <p className="text-xs tracking-[.16em] text-amber-300 uppercase">Explicit confirmation</p>
                <h2 id="version-confirm-title" className="text-lg font-semibold">
                  Підтвердити {action === "update" ? "update" : "rollback"}
                </h2>
              </div>
            </div>
            <p className="mt-4 text-sm leading-6 text-slate-300">
              Target: <strong>{selected.release}</strong> / {shortCommit(selected.sourceCommit)}. Перед runtime
              mutation host повторно перевірить package, schema, capacity та PostgreSQL backup.
            </p>
            <label className="mt-4 grid gap-1.5 text-sm">
              <span className="text-slate-400">
                Введіть{" "}
                <code className="text-cyan-200">{versionConfirmationPhrase(action, selected.bundleId)}</code>
              </span>
              <input
                autoFocus
                value={confirmation}
                onChange={(event) => setConfirmation(event.target.value)}
                className="rounded-xl border border-white/10 bg-black/20 px-3 py-2 font-mono text-sm text-slate-100 outline-none focus:border-amber-300/50"
              />
            </label>
            <div className="mt-5 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => {
                  setShowConfirm(false);
                  setConfirmation("");
                }}
                className="rounded-xl border border-white/10 px-3 py-2 text-sm text-slate-300"
              >
                Скасувати
              </button>
              <button
                type="button"
                disabled={busy || confirmation !== versionConfirmationPhrase(action, selected.bundleId)}
                onClick={() => void submitAction()}
                className="inline-flex items-center gap-2 rounded-xl border border-amber-300/30 bg-amber-300/10 px-3 py-2 text-sm text-amber-100 disabled:opacity-50"
              >
                {busy ? <RefreshCw className="h-4 w-4 animate-spin motion-reduce:animate-none" /> : null}
                {busy ? "Запит…" : "Підтвердити"}
              </button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function UpdateCheckSummary({
  check,
  current,
  candidate,
}: {
  check: UpdateCheck;
  current: VersionSnapshot["current"];
  candidate: VersionCatalogItem | null;
}) {
  return (
    <div className="grid gap-2 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium text-slate-100">{updateCheckLabel(check.resultCode)}</span>
        <span className="rounded-full border border-white/10 px-2 py-0.5 text-[11px] text-slate-400">
          {check.source === "scheduled" ? "02:00 scheduler" : check.source}
        </span>
        {check.greenRevisionVerified ? (
          <span className="rounded-full border border-emerald-300/20 bg-emerald-300/5 px-2 py-0.5 text-[11px] text-emerald-200">
            GREEN main verified
          </span>
        ) : null}
      </div>
      {check.message ? <p className="text-slate-400">{check.message}</p> : null}
      <div className="flex flex-wrap gap-x-5 gap-y-1 text-xs text-slate-500">
        {check.completedAt ? <span>{formatTime(check.completedAt)}</span> : null}
        {check.currentCommit ? <span>current {shortCommit(check.currentCommit)}</span> : null}
        {check.targetCommit ? <span>target {shortCommit(check.targetCommit)}</span> : null}
        {check.candidateBundleId ? <span>package {check.candidateBundleId}</span> : null}
      </div>
      {check.candidateAvailable && !check.activationEligible ? (
        <div className="mt-1 rounded-xl border border-amber-300/20 bg-amber-300/5 px-3 py-2 text-xs text-amber-100">
          Оновлення виявлено, але активація заблокована: {updateBlockReason(check.blockedReason)}
        </div>
      ) : null}
      {check.activationEligible && candidate ? (
        <div className="mt-1 rounded-xl border border-emerald-300/20 bg-emerald-300/5 px-3 py-2 text-xs text-emerald-100">
          Eligible update: {current?.release ?? "current"} → {candidate.release}. Validated package обрано для
          existing version-management confirmation flow.
        </div>
      ) : null}
      {check.automaticActivationOperationId ? (
        <div className="mt-1 rounded-xl border border-cyan-300/20 bg-cyan-300/5 px-3 py-2 text-xs text-cyan-100">
          02:00 scheduler передав validated package у version manager. Operation ID:{" "}
          {check.automaticActivationOperationId}
        </div>
      ) : null}
    </div>
  );
}

function PackageRow({
  item,
  selected,
  onSelect,
}: {
  item: VersionCatalogItem;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className={`w-full rounded-xl border px-4 py-3 text-left transition ${
        selected
          ? "border-cyan-300/40 bg-cyan-300/8"
          : "border-white/10 bg-black/10 hover:border-white/20"
      }`}
    >
      <div className="flex items-center justify-between gap-3">
        <div>
          <div className="font-medium text-slate-100">{item.release}</div>
          <div className="mt-1 font-mono text-xs text-slate-500">{item.bundleId}</div>
        </div>
        <div className="text-right text-xs text-slate-500">
          <div>{shortCommit(item.sourceCommit)}</div>
          <div className="mt-1">schema {item.schemaHead}</div>
        </div>
      </div>
    </button>
  );
}

function Fact({
  label,
  value,
  mono = false,
  title,
}: {
  label: string;
  value: string;
  mono?: boolean;
  title?: string;
}) {
  return (
    <div className="rounded-xl border border-white/10 bg-black/10 px-3 py-3">
      <div className="text-[11px] tracking-[.12em] text-slate-500 uppercase">{label}</div>
      <div className={`mt-1 truncate text-sm text-slate-200 ${mono ? "font-mono" : ""}`} title={title ?? value}>
        {value}
      </div>
    </div>
  );
}

function OperationBadge({ operation }: { operation: VersionOperation }) {
  const style =
    operation.status === "succeeded"
      ? "border-emerald-300/25 bg-emerald-300/8 text-emerald-200"
      : operation.status === "failed"
        ? "border-rose-300/25 bg-rose-300/8 text-rose-200"
        : operation.status === "running"
          ? "border-cyan-300/25 bg-cyan-300/8 text-cyan-200"
          : "border-amber-300/25 bg-amber-300/8 text-amber-200";
  return <span className={`rounded-full border px-2 py-1 text-xs ${style}`}>{operation.status}</span>;
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

function updateCheckLabel(resultCode: string | null): string {
  switch (resultCode) {
    case "up_to_date":
      return "Встановлено актуальну версію";
    case "candidate_found":
    case "candidate_discovered":
      return "Знайдено новішу ревізію";
    case "github_unavailable":
    case "github_ci_unavailable":
      return "GitHub/update-plane недоступний";
    case "automatic_updates_disabled":
      return "Автоматичні оновлення вимкнено";
    case null:
      return "Перевірка оновлення";
    default:
      return resultCode;
  }
}

function updateBlockReason(reason: string | null): string {
  switch (reason) {
    case "validated_package_required":
      return "для remote revision ще немає validated local package";
    case "current_release_unverified":
      return "поточний runtime не має повного validated package evidence";
    case "target_release_unverified":
      return "target package не пройшов local validation";
    case "platform_incompatible":
      return "target package не відповідає platform поточного runtime";
    case "schema_compatibility_unknown":
      return "schema compatibility з поточним runtime не підтверджена";
    case "ci_not_green":
      return "main-branch CI для target revision завершився неуспішно";
    case "ci_pending_or_missing":
      return "успішний main-branch CI для target revision ще не зафіксовано";
    case "github_ci_unavailable":
      return "не вдалося перевірити GitHub CI evidence";
    case "github_unavailable":
      return "GitHub/origin недоступний; runtime не змінено";
    case "repository_mismatch":
      return "configured origin не є canonical NEXOLAB repository";
    case "branch_mismatch":
      return "update discovery дозволений лише з main";
    case "tracked_worktree_dirty":
      return "tracked local changes блокують update";
    case "current_revision_unknown":
      return "поточна deployed revision невідома";
    case "non_fast_forward":
      return "target не є fast-forward продовженням deployed lineage";
    case "operation_in_progress":
      return "інша update/rollback operation уже виконується або очікує";
    case "candidate_not_eligible":
    case "candidate_revalidation_failed":
      return "candidate втратив eligibility під час повторної host-side перевірки";
    case null:
      return "host eligibility gate";
    default:
      return reason;
  }
}

function shortCommit(value: string): string {
  return value.slice(0, 12);
}

function formatTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : new Intl.DateTimeFormat("uk-UA", {
        dateStyle: "short",
        timeStyle: "medium",
      }).format(date);
}

function describeError(error: unknown): string {
  return error instanceof Error ? error.message : "Version Management недоступний.";
}
